"""Unit tests for the WorkspaceSupervisor (WTP Phase 2)."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.domain.model.workspace.wtp_envelope import WtpEnvelope, WtpVerb
from src.infrastructure.agent.workspace import workspace_supervisor as sup_mod
from src.infrastructure.agent.workspace.workspace_supervisor import (
    WORKSPACE_WTP_INBOX_STREAM,
    WorkspaceSupervisor,
    publish_envelope,
)

pytestmark = pytest.mark.unit


def _completed_envelope(**overrides: Any) -> WtpEnvelope:
    fields = {
        "verb": WtpVerb.TASK_COMPLETED,
        "workspace_id": "ws-1",
        "task_id": "task-1",
        "attempt_id": "attempt-1",
        "root_goal_task_id": "root-1",
        "correlation_id": "corr-1",
        "payload": {"summary": "all done", "artifacts": ["a.md"]},
        "extra_metadata": {
            "leader_agent_id": "leader",
            "worker_agent_id": "worker",
            "worker_conversation_id": "conv-1",
            "actor_user_id": "user-1",
        },
    }
    fields.update(overrides)
    return WtpEnvelope(**fields)


def _progress_envelope() -> WtpEnvelope:
    return WtpEnvelope(
        verb=WtpVerb.TASK_PROGRESS,
        workspace_id="ws-1",
        task_id="task-1",
        attempt_id="attempt-1",
        payload={"summary": "halfway"},
    )


class _FakeRedis:
    """Minimal redis.asyncio stand-in for the supervisor tests."""

    def __init__(self) -> None:
        self.entries: list[tuple[str, dict[str, Any]]] = []
        self._delivered = False

    async def xadd(
        self,
        name: str,
        fields: dict[str, Any],
        *,
        maxlen: int | None = None,
        approximate: bool = True,
    ) -> str:
        entry_id = f"{len(self.entries) + 1}-0"
        self.entries.append((entry_id, dict(fields)))
        return entry_id

    async def xread(
        self,
        streams: dict[str, str],
        *,
        count: int | None = None,
        block: int | None = None,
    ) -> Any:
        # Deliver all queued entries once; subsequent calls return nothing.
        if self._delivered or not self.entries:
            await asyncio.sleep(0)
            return None
        self._delivered = True
        stream_name = next(iter(streams.keys()))
        return [(stream_name, list(self.entries))]


class TestPublishEnvelope:
    async def test_publish_writes_json_data_field(self) -> None:
        redis = _FakeRedis()
        env = _completed_envelope()
        entry_id = await publish_envelope(redis, env)
        assert entry_id == "1-0"
        assert len(redis.entries) == 1
        _, fields = redis.entries[0]
        decoded = json.loads(fields["data"])
        assert decoded["verb"] == "task.completed"
        assert decoded["task_id"] == "task-1"
        assert decoded["correlation_id"] == "corr-1"

    async def test_publish_without_redis_returns_none(self) -> None:
        result = await publish_envelope(None, _completed_envelope())
        assert result is None

    async def test_publish_swallows_redis_errors(self) -> None:
        class BrokenRedis:
            async def xadd(self, *args: Any, **kwargs: Any) -> Any:
                raise RuntimeError("boom")

            async def xread(self, *args: Any, **kwargs: Any) -> Any:
                return None

        result = await publish_envelope(BrokenRedis(), _completed_envelope())
        assert result is None


class TestSupervisorDispatch:
    async def test_terminal_completed_invokes_apply_worker_report(self) -> None:
        redis = _FakeRedis()
        env = _completed_envelope()
        await publish_envelope(redis, env)

        supervisor = WorkspaceSupervisor(redis, block_ms=1)
        supervisor._last_id = "0"  # read from beginning

        with patch(
            "src.infrastructure.agent.workspace.workspace_goal_runtime."
            "apply_workspace_worker_report",
            new=AsyncMock(return_value=None),
        ) as apply_mock:
            await supervisor.start()
            # Give the loop one tick to consume the entry.
            for _ in range(20):
                if apply_mock.await_count > 0:
                    break
                await asyncio.sleep(0.02)
            await supervisor.stop()

        apply_mock.assert_awaited_once()
        kwargs = apply_mock.await_args.kwargs
        assert kwargs["workspace_id"] == "ws-1"
        assert kwargs["task_id"] == "task-1"
        assert kwargs["attempt_id"] == "attempt-1"
        assert kwargs["report_type"] == "completed"
        assert kwargs["summary"] == "all done"
        assert kwargs["artifacts"] == ["a.md"]
        assert kwargs["leader_agent_id"] == "leader"
        assert kwargs["worker_agent_id"] == "worker"
        assert kwargs["conversation_id"] == "conv-1"
        assert kwargs["actor_user_id"] == "user-1"
        assert kwargs["report_id"] == "corr-1"
        assert kwargs["root_goal_task_id"] == "root-1"

    async def test_terminal_blocked_includes_evidence(self) -> None:
        redis = _FakeRedis()
        env = WtpEnvelope(
            verb=WtpVerb.TASK_BLOCKED,
            workspace_id="ws-1",
            task_id="task-2",
            attempt_id="attempt-2",
            correlation_id="corr-2",
            payload={"reason": "missing api key", "evidence": "401 from upstream"},
            extra_metadata={"leader_agent_id": "leader", "worker_agent_id": "worker"},
        )
        await publish_envelope(redis, env)

        supervisor = WorkspaceSupervisor(redis, block_ms=1)
        supervisor._last_id = "0"

        with patch(
            "src.infrastructure.agent.workspace.workspace_goal_runtime."
            "apply_workspace_worker_report",
            new=AsyncMock(return_value=None),
        ) as apply_mock:
            await supervisor.start()
            for _ in range(20):
                if apply_mock.await_count > 0:
                    break
                await asyncio.sleep(0.02)
            await supervisor.stop()

        kwargs = apply_mock.await_args.kwargs
        assert kwargs["report_type"] == "blocked"
        assert "missing api key" in kwargs["summary"]
        assert "401 from upstream" in kwargs["summary"]
        assert kwargs["report_id"] == "corr-2"

    async def test_progress_verb_does_not_invoke_apply(self) -> None:
        redis = _FakeRedis()
        await publish_envelope(redis, _progress_envelope())

        supervisor = WorkspaceSupervisor(redis, block_ms=1)
        supervisor._last_id = "0"

        with patch(
            "src.infrastructure.agent.workspace.workspace_goal_runtime."
            "apply_workspace_worker_report",
            new=AsyncMock(return_value=None),
        ) as apply_mock:
            await supervisor.start()
            await asyncio.sleep(0.1)
            await supervisor.stop()

        apply_mock.assert_not_awaited()

    async def test_unparseable_entry_is_skipped(self) -> None:
        redis = _FakeRedis()
        # Inject a garbage entry directly, bypassing publish_envelope.
        redis.entries.append(("99-0", {"data": "not-json"}))

        supervisor = WorkspaceSupervisor(redis, block_ms=1)
        supervisor._last_id = "0"

        with patch(
            "src.infrastructure.agent.workspace.workspace_goal_runtime."
            "apply_workspace_worker_report",
            new=AsyncMock(return_value=None),
        ) as apply_mock:
            await supervisor.start()
            await asyncio.sleep(0.1)
            await supervisor.stop()

        apply_mock.assert_not_awaited()

    async def test_start_without_redis_is_noop(self) -> None:
        supervisor = WorkspaceSupervisor(None)
        await supervisor.start()
        assert not supervisor.is_running
        await supervisor.stop()

    async def test_stop_cancels_running_task_cleanly(self) -> None:
        redis = _FakeRedis()
        supervisor = WorkspaceSupervisor(redis, block_ms=1)
        await supervisor.start()
        assert supervisor.is_running
        await supervisor.stop()
        assert not supervisor.is_running


class TestPublisherInjection:
    async def test_publish_envelope_default_uses_configured_redis(self) -> None:
        redis = _FakeRedis()
        sup_mod.configure_wtp_publisher(redis)
        try:
            entry = await sup_mod.publish_envelope_default(_completed_envelope())
            assert entry == "1-0"
            assert redis.entries[0][1]["data"]
        finally:
            sup_mod.configure_wtp_publisher(None)

    async def test_publish_envelope_default_no_redis(self) -> None:
        sup_mod.configure_wtp_publisher(None)
        result = await sup_mod.publish_envelope_default(_completed_envelope())
        assert result is None


def test_constants_exposed() -> None:
    assert WORKSPACE_WTP_INBOX_STREAM == "workspace:wtp:inbox"


# --- Phase 5 watchdog --------------------------------------------------------


class TestWatchdog:
    async def test_progress_updates_liveness_entry(self) -> None:
        supervisor = WorkspaceSupervisor(None)
        env = _completed_envelope(verb=WtpVerb.TASK_PROGRESS, correlation_id="c-p")
        await supervisor._dispatch_envelope(env)
        snap = supervisor.get_liveness_snapshot()
        assert "attempt-1" in snap
        assert snap["attempt-1"]["last_verb"] == "task.progress"
        assert snap["attempt-1"]["workspace_id"] == "ws-1"

    async def test_terminal_removes_liveness_entry(self) -> None:
        supervisor = WorkspaceSupervisor(None)
        # First, register liveness via a progress envelope.
        await supervisor._dispatch_envelope(
            _completed_envelope(
                verb=WtpVerb.TASK_PROGRESS, correlation_id="c-progress"
            )
        )
        assert "attempt-1" in supervisor.get_liveness_snapshot()
        # Then terminal.
        with patch(
            "src.infrastructure.agent.workspace.workspace_goal_runtime."
            "apply_workspace_worker_report",
            new=AsyncMock(return_value=None),
        ):
            await supervisor._dispatch_envelope(_completed_envelope())
        assert "attempt-1" not in supervisor.get_liveness_snapshot()

    async def test_post_terminal_heartbeat_does_not_resurrect_liveness(self) -> None:
        supervisor = WorkspaceSupervisor(None)
        terminal = _completed_envelope()
        heartbeat = _completed_envelope(
            verb=WtpVerb.TASK_HEARTBEAT,
            payload={},
            correlation_id="c-heartbeat-after-terminal",
        )

        with patch(
            "src.infrastructure.agent.workspace.workspace_goal_runtime."
            "apply_workspace_worker_report",
            new=AsyncMock(return_value=None),
        ):
            await supervisor._dispatch_envelope(terminal)
            await supervisor._dispatch_envelope(heartbeat)

        assert "attempt-1" not in supervisor.get_liveness_snapshot()

    async def test_watchdog_tick_flips_stale_to_blocked(self) -> None:
        supervisor = WorkspaceSupervisor(
            None, stale_seconds=1, watchdog_interval_seconds=1
        )
        # Pre-seed liveness with a stale entry.
        supervisor._liveness["attempt-stale"] = {
            "last_seen_monotonic": 0.0,  # far in the past
            "workspace_id": "ws-1",
            "task_id": "task-stale",
            "root_goal_task_id": "root-1",
            "leader_agent_id": "leader",
            "worker_agent_id": "worker",
            "actor_user_id": "user-1",
            "worker_conversation_id": "conv-1",
            "last_verb": "task.progress",
        }
        with patch(
            "src.infrastructure.agent.workspace.workspace_goal_runtime."
            "apply_workspace_worker_report",
            new=AsyncMock(return_value=None),
        ) as apply_mock:
            await supervisor._watchdog_tick()
        apply_mock.assert_awaited_once()
        kwargs = apply_mock.await_args.kwargs
        assert kwargs["report_type"] == "blocked"
        assert "stale_no_heartbeat" in kwargs["summary"]
        assert kwargs["report_id"] == "watchdog:attempt-stale"
        assert "attempt-stale" not in supervisor.get_liveness_snapshot()

    async def test_watchdog_disabled_when_stale_seconds_zero(self) -> None:
        supervisor = WorkspaceSupervisor(None, stale_seconds=0)
        supervisor._liveness["x"] = {"last_seen_monotonic": 0.0}
        with patch(
            "src.infrastructure.agent.workspace.workspace_goal_runtime."
            "apply_workspace_worker_report",
            new=AsyncMock(),
        ) as apply_mock:
            await supervisor._watchdog_tick()
        apply_mock.assert_not_awaited()
        assert "x" in supervisor.get_liveness_snapshot()

    async def test_clarify_response_delivered_to_registry(self) -> None:
        from src.infrastructure.agent.tools import workspace_clarification as clar

        supervisor = WorkspaceSupervisor(None)
        loop = asyncio.get_event_loop()
        fut: asyncio.Future[str] = loop.create_future()
        clar._pending_clarifications["corr-resp"] = fut
        try:
            env = WtpEnvelope(
                verb=WtpVerb.TASK_CLARIFY_RESPONSE,
                workspace_id="ws-1",
                task_id="task-1",
                attempt_id="attempt-1",
                correlation_id="corr-resp",
                payload={"answer": "use api key ABC"},
            )
            await supervisor._dispatch_envelope(env)
            # Give call_soon_threadsafe a tick to fire.
            for _ in range(5):
                if fut.done():
                    break
                await asyncio.sleep(0.01)
            assert fut.done()
            assert fut.result() == "use api key ABC"
        finally:
            clar._pending_clarifications.pop("corr-resp", None)
