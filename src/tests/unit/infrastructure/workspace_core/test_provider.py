"""Avernet Provider protocol adapter contracts."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from typing import Any

import httpx
import pytest

from src.infrastructure.workspace_core.client import WorkspaceRuntimeCallbackAckRequest
from src.infrastructure.workspace_core.provider import (
    AvernetBotEventHttpSink,
    AvernetProviderAdapter,
    ProviderAbortResult,
    ProviderHistoryResult,
    ProviderRuntimeEvent,
    ProviderWebhookRequest,
)


def _request(method: str = "chat.send") -> ProviderWebhookRequest:
    return ProviderWebhookRequest.model_validate(
        {
            "type": "req",
            "id": "run-1",
            "method": method,
            "session_id": "conversation-1",
            "bcn_group_id": "group-1",
            "to_bot": {
                "provider_id": "provider-1",
                "provider_bot_ref": "agent-1",
            },
            "message": {"content": [{"type": "text", "text": "hello"}]},
            "timeout_ms": 30_000,
            "extensions": {
                "tenant_id": "tenant-1",
                "project_id": "project-1",
                "workspace_id": "workspace-1",
                "task_id": "task-1",
                "plan_node_id": "node-1",
                "conversation_id": "conversation-1",
                "ignored": "not-a-correlation-field",
            },
        }
    )


class FakeRuntime:
    def __init__(self) -> None:
        self.injected: list[str] = []
        self.aborted: list[str] = []
        self.history_requests: list[str] = []

    async def stream_send(
        self,
        request: ProviderWebhookRequest,
    ) -> AsyncIterator[ProviderRuntimeEvent]:
        yield ProviderRuntimeEvent(
            state="delta",
            sequence=1,
            message={"content": "partial"},
        )
        yield ProviderRuntimeEvent(
            state="final",
            sequence=2,
            message={"content": "complete"},
            stop_reason="end_turn",
            persisted=True,
            correlation_id="correlation-1",
        )

    async def inject(self, request: ProviderWebhookRequest) -> None:
        self.injected.append(request.session_id)

    async def abort(self, request: ProviderWebhookRequest) -> ProviderAbortResult:
        self.aborted.append(request.session_id)
        return ProviderAbortResult(ray_cancelled=True, local_worker_cancelled=True)

    async def history(self, request: ProviderWebhookRequest) -> ProviderHistoryResult:
        self.history_requests.append(request.session_id)
        return ProviderHistoryResult(messages=[{"role": "assistant", "content": "history"}])


class RecordingSink:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, str], ProviderRuntimeEvent]] = []

    async def publish(
        self,
        request: ProviderWebhookRequest,
        event: ProviderRuntimeEvent,
    ) -> None:
        self.events.append((request.id, request.correlation, event))


class FlakyTerminalSink(RecordingSink):
    def __init__(self, *, failures: int) -> None:
        super().__init__()
        self.failures = failures
        self.attempted_states: list[str] = []

    async def publish(
        self,
        request: ProviderWebhookRequest,
        event: ProviderRuntimeEvent,
    ) -> None:
        self.attempted_states.append(event.state)
        if event.state in {"final", "aborted", "error"} and self.failures > 0:
            self.failures -= 1
            raise RuntimeError("callback unavailable")
        await super().publish(request, event)


class RecordingAcknowledger:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, str]] = []

    async def acknowledge_runtime_terminal_callback(
        self,
        correlation_id: str,
        request: WorkspaceRuntimeCallbackAckRequest,
    ) -> None:
        self.calls.append(
            (
                correlation_id,
                request.tenant_id,
                request.project_id,
                request.workspace_id,
            )
        )


class ImmediateGenerationReservation:
    @asynccontextmanager
    async def admit(self) -> AsyncIterator[object]:
        yield object()

    async def release(self) -> None:
        return None


async def _reserve_immediate_generation() -> ImmediateGenerationReservation:
    return ImmediateGenerationReservation()


def _adapter(
    runtime: FakeRuntime,
    sink: RecordingSink,
    acknowledger: RecordingAcknowledger,
    **kwargs: Any,
) -> AvernetProviderAdapter:
    return AvernetProviderAdapter(
        runtime,
        sink,
        acknowledger,
        generation_reserver=_reserve_immediate_generation,
        **kwargs,
    )


@pytest.mark.unit
async def test_send_acks_then_publishes_ordered_terminal_events() -> None:
    runtime = FakeRuntime()
    sink = RecordingSink()
    acknowledger = RecordingAcknowledger()
    adapter = _adapter(runtime, sink, acknowledger)

    response = await adapter.handle(_request())
    await adapter.wait_until_idle()

    assert response == {"ok": True}
    assert [event.state for _, _, event in sink.events] == ["delta", "final"]
    assert [event.sequence for _, _, event in sink.events] == [1, 2]
    assert sink.events[-1][1] == {
        "workspace_id": "workspace-1",
        "task_id": "task-1",
        "plan_node_id": "node-1",
        "conversation_id": "conversation-1",
    }
    assert acknowledger.calls == [("correlation-1", "tenant-1", "project-1", "workspace-1")]


@pytest.mark.unit
async def test_send_retries_only_the_same_persisted_terminal_callback() -> None:
    sink = FlakyTerminalSink(failures=2)
    adapter = _adapter(
        FakeRuntime(),
        sink,
        RecordingAcknowledger(),
        terminal_callback_attempts=3,
        terminal_callback_retry_delay_seconds=0,
    )

    _ = await adapter.handle(_request())
    await adapter.wait_until_idle()

    assert sink.attempted_states == ["delta", "final", "final", "final"]
    assert [event.state for _, _, event in sink.events] == ["delta", "final"]
    assert [event.sequence for _, _, event in sink.events] == [1, 2]


@pytest.mark.unit
async def test_inject_history_and_abort_use_runtime_port() -> None:
    runtime = FakeRuntime()
    adapter = _adapter(runtime, RecordingSink(), RecordingAcknowledger())

    inject = await adapter.handle(_request("chat.inject"))
    history = await adapter.handle(_request("chat.history"))
    abort = await adapter.handle(_request("chat.abort"))

    assert inject == {"ok": True}
    assert runtime.injected == ["conversation-1"]
    assert history == {
        "ok": True,
        "session_id": "conversation-1",
        "messages": [{"role": "assistant", "content": "history"}],
        "has_more": False,
        "next_before": None,
        "next_after": None,
    }
    assert abort == {
        "ok": True,
        "aborted": True,
        "ray_cancelled": True,
        "local_worker_cancelled": True,
    }
    assert runtime.aborted == ["conversation-1"]


@pytest.mark.unit
async def test_abort_publishes_and_acknowledges_target_run_terminal() -> None:
    class TerminalAbortRuntime(FakeRuntime):
        async def abort(self, request: ProviderWebhookRequest) -> ProviderAbortResult:
            self.aborted.append(request.session_id)
            return ProviderAbortResult(
                ray_cancelled=True,
                local_worker_cancelled=False,
                terminal_event=ProviderRuntimeEvent(
                    state="aborted",
                    sequence=0,
                    message={"content": "Agent Runtime cancelled"},
                    stop_reason="cancelled",
                    persisted=True,
                    correlation_id="target-correlation-1",
                ),
            )

    sink = RecordingSink()
    acknowledger = RecordingAcknowledger()
    adapter = _adapter(TerminalAbortRuntime(), sink, acknowledger)
    request = _request("chat.abort").model_copy(update={"run_id": "target-run-1"})

    result = await adapter.handle(request)

    assert result["aborted"] is True
    assert [(request_id, event.state) for request_id, _, event in sink.events] == [
        ("target-run-1", "aborted")
    ]
    assert acknowledger.calls == [("target-correlation-1", "tenant-1", "project-1", "workspace-1")]


@pytest.mark.unit
async def test_send_without_persisted_terminal_suppresses_error_callback() -> None:
    class NoTerminalRuntime(FakeRuntime):
        async def stream_send(
            self,
            request: ProviderWebhookRequest,
        ) -> AsyncIterator[ProviderRuntimeEvent]:
            yield ProviderRuntimeEvent(
                state="delta",
                sequence=4,
                message={"content": "partial"},
            )

    sink = RecordingSink()
    adapter = _adapter(NoTerminalRuntime(), sink, RecordingAcknowledger())

    _ = await adapter.handle(_request())
    await adapter.wait_until_idle()

    assert [event.state for _, _, event in sink.events] == ["delta"]


@pytest.mark.unit
async def test_send_closes_runtime_stream_before_releasing_generation() -> None:
    order: list[str] = []

    class ClosingRuntime(FakeRuntime):
        async def stream_send(
            self,
            request: ProviderWebhookRequest,
        ) -> AsyncIterator[ProviderRuntimeEvent]:
            try:
                yield ProviderRuntimeEvent(
                    state="final",
                    sequence=1,
                    message={"content": "complete"},
                    persisted=True,
                    correlation_id="correlation-1",
                )
            finally:
                order.append("stream-closed")

    class RecordingReservation(ImmediateGenerationReservation):
        @asynccontextmanager
        async def admit(self) -> AsyncIterator[object]:
            order.append("generation-entered")
            try:
                yield object()
            finally:
                order.append("generation-released")

    async def reserve() -> RecordingReservation:
        return RecordingReservation()

    adapter = AvernetProviderAdapter(
        ClosingRuntime(),
        RecordingSink(),
        RecordingAcknowledger(),
        generation_reserver=reserve,
    )

    _ = await adapter.handle(_request())
    await adapter.wait_until_idle()

    assert order == ["generation-entered", "stream-closed", "generation-released"]


@pytest.mark.unit
async def test_cancelled_unstarted_send_releases_reserved_generation() -> None:
    release_calls = 0

    class CancellableReservation(ImmediateGenerationReservation):
        async def release(self) -> None:
            nonlocal release_calls
            release_calls += 1

    async def reserve() -> CancellableReservation:
        return CancellableReservation()

    adapter = AvernetProviderAdapter(
        FakeRuntime(),
        RecordingSink(),
        RecordingAcknowledger(),
        generation_reserver=reserve,
    )

    _ = await adapter.handle(_request())
    send_task = next(iter(adapter._tasks))
    send_task.cancel()
    with suppress(asyncio.CancelledError):
        await send_task
    await adapter.wait_until_idle()

    assert release_calls == 1


@pytest.mark.unit
async def test_http_event_sink_posts_protocol_two_callback_with_correlation() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/bot/events"
        assert request.headers["authorization"] == "Bearer bot-event-token"
        assert request.headers["x-bcn-provider-id"] == "provider-1"
        assert request.headers["x-bcn-provider-bot-ref"] == "agent-1"
        payload = json.loads(request.content)
        assert payload["run_id"] == "run-1"
        assert payload["state"] == "final"
        assert payload["event"] == "chat"
        assert payload["payload"]["state"] == "final"
        assert payload["payload"]["message"]["content"][0]["text"] == "complete"
        assert payload["payload"]["extensions"] == _request().correlation
        return httpx.Response(200, json={"ok": True})

    sink = AvernetBotEventHttpSink(
        base_url="http://workspace-core.test",
        event_token="bot-event-token",
        transport=httpx.MockTransport(handler),
    )

    await sink.publish(
        _request(),
        ProviderRuntimeEvent(
            state="final",
            sequence=9,
            message={"content": "complete"},
            stop_reason="end_turn",
            persisted=True,
        ),
    )


@pytest.mark.unit
async def test_http_event_sink_rejects_unpersisted_terminal() -> None:
    sink = AvernetBotEventHttpSink(
        base_url="http://workspace-core.test",
        event_token="bot-event-token",
        transport=httpx.MockTransport(lambda _request: httpx.Response(200)),
    )

    with pytest.raises(RuntimeError, match="persisted history"):
        await sink.publish(
            _request(),
            ProviderRuntimeEvent(state="error", sequence=1, error_message="failed"),
        )


@pytest.mark.unit
async def test_http_event_sink_accepts_terminal_retry_after_upstream_completion() -> None:
    sink = AvernetBotEventHttpSink(
        base_url="http://workspace-core.test",
        event_token="bot-event-token",
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(410, json={"error": "run_terminated"})
        ),
    )

    await sink.publish(
        _request(),
        ProviderRuntimeEvent(
            state="final",
            sequence=9,
            message={"content": "complete"},
            persisted=True,
            correlation_id="correlation-1",
        ),
    )
