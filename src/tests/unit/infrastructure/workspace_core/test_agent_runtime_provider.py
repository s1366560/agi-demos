"""Production MemStack Agent Runtime Provider contracts."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, Literal, cast

import httpx
import pytest

from src.domain.events.types import AgentEventType
from src.domain.model.agent import AgentExecutionEvent
from src.domain.model.agent.conversation.conversation import Conversation
from src.infrastructure.workspace_core.agent_runtime_provider import (
    MemStackAgentRuntimeProvider,
)
from src.infrastructure.workspace_core.client import (
    WorkspaceRuntimeCallbackAckRequest,
    WorkspaceRuntimeCorrelationRequest,
    WorkspaceRuntimeCorrelationResponse,
    WorkspaceRuntimeTerminalReadResponse,
    WorkspaceRuntimeTerminalRequest,
    WorkspaceRuntimeTerminalResponse,
)
from src.infrastructure.workspace_core.provider import (
    AvernetBotEventHttpSink,
    AvernetProviderAdapter,
    ProviderWebhookRequest,
)

pytestmark = pytest.mark.unit


def _request(
    method: str = "chat.send",
    *,
    request_id: str = "provider-run-1",
    message: str = "hello",
    before: int | None = None,
    after: int | None = None,
    limit: int | None = None,
    run_id: str | None = None,
) -> ProviderWebhookRequest:
    return ProviderWebhookRequest.model_validate(
        {
            "type": "req",
            "id": request_id,
            "method": method,
            "run_id": run_id,
            "session_id": "bcs-session-1",
            "bcn_group_id": "group-1",
            "to_bot": {
                "provider_id": "provider-1",
                "provider_bot_ref": "agent-1",
            },
            "message": {"content": [{"type": "text", "text": message}]},
            "before": before,
            "after": after,
            "limit": limit,
            "timeout_ms": 30_000,
            "extensions": {
                "tenant_id": "tenant-1",
                "project_id": "project-1",
                "workspace_id": "workspace-1",
                "user_id": "user-1",
                "conversation_id": "conversation-1",
                "task_id": "task-1",
                "plan_id": "plan-1",
                "plan_node_id": "node-1",
            },
        }
    )


class FakeDb:
    def __init__(self) -> None:
        self.rollback_count = 0
        self.commit_count = 0

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        self.rollback_count += 1


class FakeSessionContext:
    def __init__(self, db: FakeDb) -> None:
        self.db = db

    async def __aenter__(self) -> FakeDb:
        return self.db

    async def __aexit__(self, *_args: object) -> None:
        return None


class FakeConversationRepository:
    def __init__(self) -> None:
        self.conversation: Conversation | None = Conversation(
            id="conversation-1",
            tenant_id="tenant-1",
            project_id="project-1",
            user_id="user-1",
            title="Provider conversation",
            workspace_id="workspace-1",
            linked_workspace_task_id="task-1",
        )

    async def find_by_id(self, conversation_id: str) -> Conversation | None:
        if self.conversation is None or conversation_id != self.conversation.id:
            return None
        return self.conversation

    async def save(self, conversation: Conversation) -> Conversation:
        self.conversation = conversation
        return conversation


class FakeEventRepository:
    def __init__(self) -> None:
        self.events: list[AgentExecutionEvent] = []

    async def save_and_commit(self, event: AgentExecutionEvent) -> None:
        self.events.append(event)

    async def get_events(
        self,
        conversation_id: str,
        from_time_us: int = 0,
        from_counter: int = 0,
        limit: int = 1000,
        event_types: set[str] | None = None,
        before_time_us: int | None = None,
        before_counter: int | None = None,
    ) -> list[AgentExecutionEvent]:
        del from_counter, before_counter
        events = [event for event in self.events if event.conversation_id == conversation_id]
        if event_types is not None:
            events = [event for event in events if str(event.event_type) in event_types]
        if before_time_us is not None:
            events = [event for event in events if event.event_time_us < before_time_us]
            return events[-limit:]
        events = [event for event in events if event.event_time_us > from_time_us]
        return events[:limit]

    async def get_last_event_time(self, conversation_id: str) -> tuple[int, int]:
        events = [event for event in self.events if event.conversation_id == conversation_id]
        if not events:
            return 0, 0
        event = max(events, key=lambda item: (item.event_time_us, item.event_counter))
        return event.event_time_us, event.event_counter

    async def get_events_by_message(
        self,
        conversation_id: str,
        message_id: str,
    ) -> list[AgentExecutionEvent]:
        return [
            event
            for event in self.events
            if event.conversation_id == conversation_id and event.message_id == message_id
        ]


class FakeAgentService:
    def __init__(self, event_repo: FakeEventRepository) -> None:
        self.event_repo = event_repo
        self.stream_kwargs: dict[str, Any] | None = None
        self.execution_count = 0

    async def stream_chat_v2(self, **kwargs: Any) -> AsyncIterator[dict[str, Any]]:
        self.execution_count += 1
        self.stream_kwargs = kwargs
        message_id = str(kwargs["execution_message_id"])
        yield {"type": "text_delta", "data": {"delta": "partial"}}
        self.event_repo.events.extend(
            [
                _event(
                    event_type=AgentEventType.USER_MESSAGE.value,
                    content=str(kwargs["user_message"]),
                    message_id=message_id,
                    event_time_us=2,
                    role="user",
                    conversation_id=str(kwargs["conversation_id"]),
                ),
                _event(
                    event_type=AgentEventType.ASSISTANT_MESSAGE.value,
                    content="complete",
                    message_id=message_id,
                    event_time_us=3,
                    conversation_id=str(kwargs["conversation_id"]),
                ),
            ]
        )
        self.event_repo.events.append(
            _event(
                event_type=AgentEventType.COMPLETE,
                content="complete",
                message_id=message_id,
                event_time_us=4,
                conversation_id=str(kwargs["conversation_id"]),
            )
        )
        yield {
            "type": "complete",
            "data": {"content": "complete", "usage": {"total_tokens": 12}},
        }


class FakeWorkspaceCoreClient:
    def __init__(self) -> None:
        self.correlations: list[WorkspaceRuntimeCorrelationRequest] = []
        self.terminals: list[tuple[str, WorkspaceRuntimeTerminalRequest]] = []
        self.terminal_reads: list[tuple[str, str, str, str]] = []
        self.correlation_created = True
        self.correlation_status: Literal["pending", "running", "completed", "failed", "aborted"] = (
            "running"
        )
        self.terminal_error: Exception | None = None
        self.execution_status: dict[str, str] = {}
        self.timeline_history: list[dict[str, Any]] = []
        self.outbox: list[dict[str, Any]] = []
        self.pipeline_progression: dict[str, str] = {}
        self.acknowledged_correlations: set[str] = set()
        self._known_correlations: set[str] = set()
        self._terminal_reads: dict[str, WorkspaceRuntimeTerminalReadResponse] = {}

    async def record_runtime_correlation(
        self,
        request: WorkspaceRuntimeCorrelationRequest,
    ) -> WorkspaceRuntimeCorrelationResponse:
        self.correlations.append(request)
        created = (
            self.correlation_created and request.correlation_id not in self._known_correlations
        )
        self._known_correlations.add(request.correlation_id)
        return WorkspaceRuntimeCorrelationResponse(
            correlation_id=request.correlation_id,
            status=self.correlation_status,
            created=created,
        )

    async def record_runtime_terminal(
        self,
        correlation_id: str,
        request: WorkspaceRuntimeTerminalRequest,
    ) -> WorkspaceRuntimeTerminalResponse:
        self.terminals.append((correlation_id, request))
        if self.terminal_error is not None:
            raise self.terminal_error
        status = {
            "complete": "completed",
            "error": "failed",
            "aborted": "aborted",
        }[request.execution_status]
        outbox_id = f"outbox-{correlation_id}"
        terminal_id = f"terminal-{correlation_id}"
        response = WorkspaceRuntimeTerminalResponse(
            correlation_id=correlation_id,
            status=status,
            outbox_id=outbox_id,
            terminal_id=terminal_id,
            report_hash="a" * 64,
            created=True,
        )
        self.execution_status[correlation_id] = status
        self.timeline_history.append(cast(dict[str, Any], request.report["legacy_event"]))
        self.outbox.append(
            {
                "outbox_id": outbox_id,
                "correlation_id": correlation_id,
                "event_type": f"workspace.execution.{status}",
            }
        )
        self.pipeline_progression[correlation_id] = status
        self.correlation_status = cast(
            Literal["pending", "running", "completed", "failed", "aborted"], status
        )
        self._terminal_reads[correlation_id] = WorkspaceRuntimeTerminalReadResponse.model_validate(
            {
                "correlation_id": correlation_id,
                "status": status,
                "outbox_id": outbox_id,
                "terminal_id": terminal_id,
                "terminal_message_id": request.terminal_message_id,
                "terminal_event_id": request.terminal_event_id,
                "report": request.report,
                "report_hash": "a" * 64,
                "persisted": True,
            }
        )
        return response

    async def read_runtime_terminal(
        self,
        correlation_id: str,
        *,
        tenant_id: str,
        project_id: str,
        workspace_id: str,
    ) -> WorkspaceRuntimeTerminalReadResponse:
        self.terminal_reads.append((correlation_id, tenant_id, project_id, workspace_id))
        persisted = self._terminal_reads.get(correlation_id)
        if persisted is not None:
            return persisted
        return WorkspaceRuntimeTerminalReadResponse.model_validate(
            {
                "correlation_id": correlation_id,
                "status": self.correlation_status,
                "outbox_id": f"outbox-{correlation_id}",
                "terminal_id": f"terminal-{correlation_id}",
                "terminal_message_id": "message-provider-run-1",
                "terminal_event_id": "event-4-complete",
                "report": {
                    "content": "complete",
                    "provider_state": "final",
                    "sequence": 1,
                    "usage": {"total_tokens": 12},
                    "stop_reason": "end_turn",
                    "error_message": None,
                    "legacy_event": {"event_id": "event-4-complete"},
                },
                "report_hash": "a" * 64,
                "persisted": True,
            }
        )

    async def acknowledge_runtime_terminal_callback(
        self,
        correlation_id: str,
        request: WorkspaceRuntimeCallbackAckRequest,
    ) -> None:
        assert (request.tenant_id, request.project_id, request.workspace_id) == (
            "tenant-1",
            "project-1",
            "workspace-1",
        )
        self.acknowledged_correlations.add(correlation_id)


class FakeScopedContainer:
    def __init__(self) -> None:
        self.conversation_repo = FakeConversationRepository()
        self.event_repo = FakeEventRepository()
        self.service = FakeAgentService(self.event_repo)

    def conversation_repository(self) -> FakeConversationRepository:
        return self.conversation_repo

    def agent_execution_event_repository(self) -> FakeEventRepository:
        return self.event_repo

    def agent_service(self, _llm: object) -> FakeAgentService:
        return self.service


class FakeContainer:
    def __init__(self, scoped: FakeScopedContainer) -> None:
        self.scoped = scoped

    def with_db(self, _db: object) -> FakeScopedContainer:
        return self.scoped


def _event(
    *,
    event_type: AgentEventType | str,
    content: str,
    message_id: str,
    event_time_us: int,
    role: str = "assistant",
    conversation_id: str = "conversation-1",
) -> AgentExecutionEvent:
    return AgentExecutionEvent(
        id=f"event-{event_time_us}-{event_type.value if isinstance(event_type, AgentEventType) else event_type}",
        conversation_id=conversation_id,
        message_id=message_id,
        event_type=event_type,
        event_data={"role": role, "content": content},
        event_time_us=event_time_us,
        event_counter=0,
        created_at=datetime(2026, 8, 10, tzinfo=UTC),
    )


def _provider(
    scoped: FakeScopedContainer,
    db: FakeDb | None = None,
    core_client: FakeWorkspaceCoreClient | None = None,
) -> MemStackAgentRuntimeProvider:
    active_db = db or FakeDb()
    active_core_client = core_client or FakeWorkspaceCoreClient()

    async def llm_factory(_tenant_id: str) -> object:
        return object()

    def session_factory() -> AbstractAsyncContextManager[Any]:
        return FakeSessionContext(active_db)

    return MemStackAgentRuntimeProvider(
        workspace_core_client=cast(Any, active_core_client),
        session_factory=cast(Any, session_factory),
        container_provider=cast(Any, lambda: FakeContainer(scoped)),
        llm_factory=llm_factory,
        terminal_persist_wait_seconds=0.2,
    )


async def test_send_uses_real_runtime_contract_and_marks_persisted_terminal() -> None:
    scoped = FakeScopedContainer()
    core_client = FakeWorkspaceCoreClient()
    provider = _provider(scoped, core_client=core_client)

    events = [event async for event in provider.stream_send(_request())]

    assert [event.state for event in events] == ["delta", "final"]
    assert events[-1].persisted is True
    assert events[-1].usage == {"total_tokens": 12}
    assert scoped.service.stream_kwargs is not None
    assert scoped.service.stream_kwargs["canonical_run_id"] == "provider-run-1"
    assert scoped.service.stream_kwargs["agent_id"] == "agent-1"
    context = scoped.service.stream_kwargs["app_model_context"]
    assert context["context_type"] == "workspace_worker_runtime"
    assert context["workspace_session_role"] == "worker"
    assert context["workspace_binding"]["workspace_id"] == "workspace-1"
    assert len(core_client.correlations) == 1
    correlation = core_client.correlations[0]
    assert correlation.tenant_id == "tenant-1"
    assert correlation.project_id == "project-1"
    assert correlation.workspace_id == "workspace-1"
    assert correlation.user_id == "user-1"
    assert correlation.task_id == "task-1"
    assert correlation.plan_id == "plan-1"
    assert correlation.plan_node_id == "node-1"
    assert correlation.conversation_id == "conversation-1"
    assert correlation.bcs_session_id == "bcs-session-1"
    assert correlation.bcs_group_id == "group-1"
    assert correlation.delivery_request_id == "provider-run-1"
    assert correlation.provider_run_id == "provider-run-1"
    assert correlation.provider_id == "provider-1"
    assert correlation.provider_bot_ref == "agent-1"
    assert len(core_client.terminals) == 1
    terminal_correlation_id, terminal = core_client.terminals[0]
    assert terminal_correlation_id == correlation.correlation_id
    assert terminal.execution_status == "complete"
    assert terminal.terminal_message_id == scoped.event_repo.events[-1].message_id
    assert terminal.terminal_event_id == scoped.event_repo.events[-1].id
    assert terminal.report["content"] == "complete"
    assert terminal.report["usage"] == {"total_tokens": 12}
    assert terminal.report["legacy_event"]["event_type"] == "complete"
    assert events[-1].correlation_id == correlation.correlation_id


async def test_send_suppresses_terminal_when_core_transaction_fails() -> None:
    scoped = FakeScopedContainer()
    core_client = FakeWorkspaceCoreClient()
    core_client.terminal_error = RuntimeError("core transaction failed")

    events = [
        event async for event in _provider(scoped, core_client=core_client).stream_send(_request())
    ]

    assert [event.state for event in events] == ["delta"]
    assert len(core_client.terminals) == 1


async def test_send_without_task_is_a_workspace_leader_turn() -> None:
    scoped = FakeScopedContainer()
    request = _request().model_copy(
        update={
            "extensions": {
                key: value for key, value in _request().extensions.items() if key != "task_id"
            }
        }
    )

    events = [event async for event in _provider(scoped).stream_send(request)]

    assert [event.state for event in events] == ["delta", "final"]
    assert scoped.service.stream_kwargs is not None
    context = scoped.service.stream_kwargs["app_model_context"]
    assert context["context_type"] == "workspace_collaboration_runtime"
    assert context["workspace_session_role"] == "leader"
    assert "workspace_binding" not in context
    assert "task_id" not in context["workspace_scope"]


async def test_duplicate_delivery_does_not_execute_runtime_twice() -> None:
    scoped = FakeScopedContainer()
    core_client = FakeWorkspaceCoreClient()
    core_client.correlation_created = False

    events = [
        event async for event in _provider(scoped, core_client=core_client).stream_send(_request())
    ]

    assert events == []
    assert scoped.service.stream_kwargs is None
    assert len(core_client.correlations) == 1
    assert core_client.terminals == []
    assert core_client.terminal_reads == []


async def test_duplicate_terminal_delivery_replays_core_proof_without_runtime_side_effect() -> None:
    scoped = FakeScopedContainer()
    core_client = FakeWorkspaceCoreClient()
    core_client.correlation_created = False
    core_client.correlation_status = "completed"

    events = [
        event async for event in _provider(scoped, core_client=core_client).stream_send(_request())
    ]

    assert len(events) == 1
    assert events[0].state == "final"
    assert events[0].sequence == 1
    assert events[0].message == {"content": "complete"}
    assert events[0].persisted is True
    assert events[0].correlation_id == core_client.correlations[0].correlation_id
    assert scoped.service.stream_kwargs is None
    assert core_client.terminals == []
    assert core_client.terminal_reads == [
        (
            core_client.correlations[0].correlation_id,
            "tenant-1",
            "project-1",
            "workspace-1",
        )
    ]


async def test_inject_is_idempotent_and_loaded_into_next_send_context() -> None:
    scoped = FakeScopedContainer()
    provider = _provider(scoped)
    inject_request = _request(
        "chat.inject",
        request_id="inject-1",
        message="silent collaboration context",
    )

    await provider.inject(inject_request)
    await provider.inject(inject_request)
    _ = [event async for event in provider.stream_send(_request(request_id="send-2"))]

    injection_events = [
        event
        for event in scoped.event_repo.events
        if str(event.event_type) == "avernet_context_injection"
    ]
    assert len(injection_events) == 1
    assert scoped.service.stream_kwargs is not None
    injections = scoped.service.stream_kwargs["app_model_context"]["avernet"][
        "collaboration_injections"
    ]
    assert injections[0]["content"] == "silent collaboration context"


async def test_history_is_scope_checked_and_uses_persistent_messages() -> None:
    scoped = FakeScopedContainer()
    scoped.event_repo.events.extend(
        [
            _event(
                event_type="user_message",
                content="question",
                message_id="message-1",
                event_time_us=1,
                role="user",
            ),
            _event(
                event_type="assistant_message",
                content="answer",
                message_id="message-1",
                event_time_us=2,
            ),
        ]
    )

    history = await _provider(scoped).history(_request("chat.history", limit=10))

    assert [item["role"] for item in history.messages] == ["user", "assistant"]
    assert history.messages[-1]["content"][0]["text"] == "answer"
    assert history.has_more is False


async def test_abort_cancels_ray_and_local_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    scoped = FakeScopedContainer()

    async def fake_cancel(_conversation: Conversation) -> Any:
        return SimpleNamespace(ray_cancelled=True, local_worker_cancelled=True)

    monkeypatch.setattr(
        "src.application.services.agent.runtime_cancellation.cancel_conversation_runtime",
        fake_cancel,
    )

    core = FakeWorkspaceCoreClient()
    result = await _provider(scoped, core_client=core).abort(
        _request("chat.abort", request_id="abort-request-1", run_id="provider-run-1")
    )

    assert result.ray_cancelled is True
    assert result.local_worker_cancelled is True
    assert result.terminal_event is not None
    assert result.terminal_event.state == "aborted"
    assert result.terminal_event.persisted is True
    assert core.terminals[0][1].execution_status == "aborted"
    assert core.timeline_history[-1]["event_type"] == "cancelled"
    assert core.outbox[-1]["event_type"] == "workspace.execution.aborted"


async def test_send_rejects_cross_workspace_conversation() -> None:
    scoped = FakeScopedContainer()
    assert scoped.conversation_repo.conversation is not None
    scoped.conversation_repo.conversation.workspace_id = "other-workspace"

    with pytest.raises(PermissionError, match="scope does not match"):
        _ = [event async for event in _provider(scoped).stream_send(_request())]


async def test_send_creates_missing_deterministic_workspace_conversation() -> None:
    scoped = FakeScopedContainer()
    scoped.conversation_repo.conversation = None
    db = FakeDb()
    request = _request().model_copy(
        update={
            "extensions": {
                **_request().extensions,
                "conversation_id": "38de6521-f86f-5c70-87f4-55005dc2aa30",
            }
        }
    )

    events = [event async for event in _provider(scoped, db=db).stream_send(request)]

    assert [event.state for event in events] == ["delta", "final"]
    conversation = scoped.conversation_repo.conversation
    assert conversation is not None
    assert conversation.id == request.extensions["conversation_id"]
    assert conversation.tenant_id == "tenant-1"
    assert conversation.project_id == "project-1"
    assert conversation.user_id == "user-1"
    assert conversation.workspace_id == "workspace-1"
    assert conversation.linked_workspace_task_id == "task-1"
    assert conversation.agent_config == {"selected_agent_id": "agent-1"}
    assert conversation.metadata["source"] == "avernet_workspace_message"
    assert db.commit_count == 1


async def test_provider_e2e_preserves_terminal_four_way_authority_and_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scoped = FakeScopedContainer()
    core = FakeWorkspaceCoreClient()
    runtime = _provider(scoped, core_client=core)
    accepted_callbacks: list[dict[str, Any]] = []

    async def bot_events(request: httpx.Request) -> httpx.Response:
        payload = cast(dict[str, Any], json.loads(request.content))
        state = payload["payload"]["state"]
        if state in {"final", "error", "aborted"}:
            correlation_id = next(iter(core.execution_status))
            assert core.execution_status[correlation_id] == "completed"
            assert core.timeline_history[-1]["event_type"] == "complete"
            assert core.outbox[-1]["event_type"] == "workspace.execution.completed"
            assert core.pipeline_progression[correlation_id] == "completed"
            if any(item["payload"]["state"] == state for item in accepted_callbacks):
                return httpx.Response(410, json={"error": "run_terminated"})
        accepted_callbacks.append(payload)
        return httpx.Response(200, json={"ok": True})

    sink = AvernetBotEventHttpSink(
        base_url="http://workspace-core.test",
        event_token="local-contract-token",
        transport=httpx.MockTransport(bot_events),
    )
    adapter = AvernetProviderAdapter(
        runtime,
        sink,
        core,
        terminal_callback_retry_delay_seconds=0,
    )

    await adapter.handle(
        _request(
            "chat.inject",
            request_id="provider-inject-1",
            message="durable collaboration context",
        )
    )
    assert await adapter.handle(_request()) == {"ok": True}
    await adapter.wait_until_idle()

    history = await adapter.handle(_request("chat.history", request_id="history-1", limit=10))

    async def fake_cancel(_conversation: Conversation) -> Any:
        return SimpleNamespace(ray_cancelled=True, local_worker_cancelled=True)

    monkeypatch.setattr(
        "src.application.services.agent.runtime_cancellation.cancel_conversation_runtime",
        fake_cancel,
    )
    abort = await adapter.handle(_request("chat.abort", request_id="abort-1"))

    assert [item["payload"]["state"] for item in accepted_callbacks] == ["delta", "final"]
    assert scoped.service.execution_count == 1
    assert scoped.service.stream_kwargs is not None
    injections = scoped.service.stream_kwargs["app_model_context"]["avernet"][
        "collaboration_injections"
    ]
    assert [item["content"] for item in injections] == ["durable collaboration context"]
    assert [item["role"] for item in history["messages"]] == ["user", "assistant"]
    assert abort == {
        "ok": True,
        "aborted": True,
        "ray_cancelled": True,
        "local_worker_cancelled": True,
    }
    assert len(core.execution_status) == 1
    assert len(core.timeline_history) == 1
    assert len(core.outbox) == 1
    assert len(core.pipeline_progression) == 1
    correlation_id = next(iter(core.execution_status))
    assert core.acknowledged_correlations == {correlation_id}

    # A duplicate BCS delivery replays the persisted terminal proof. It does
    # not execute the Agent, append history/outbox, or progress the pipeline a
    # second time. `/bot/events` may answer 410 and is still acknowledged.
    assert await adapter.handle(_request()) == {"ok": True}
    await adapter.wait_until_idle()

    assert scoped.service.execution_count == 1
    assert len(core.timeline_history) == 1
    assert len(core.outbox) == 1
    assert len(core.pipeline_progression) == 1
    assert core.acknowledged_correlations == {correlation_id}
