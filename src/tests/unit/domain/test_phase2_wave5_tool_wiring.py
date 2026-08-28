"""Tests for Phase 2 Wave 5: Tool & DI wiring for ControlChannel."""

from __future__ import annotations

from types import MappingProxyType
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.domain.model.agent.tool_policy import ControlMessageType
from src.domain.ports.agent.control_channel_port import ControlMessage
from src.infrastructure.agent.tools import subagent_sessions as subagent_sessions_module


def _make_tool_context() -> MagicMock:
    ctx = MagicMock()
    ctx.emit = AsyncMock()
    return ctx


def _make_run_registry(*, attach_metadata_return: MagicMock | None = None) -> MagicMock:
    registry = MagicMock()
    run = MagicMock()
    run.run_id = "run-1"
    run.status = MagicMock()
    run.status.value = "running"
    run.to_event_data.return_value = {"run_id": "run-1"}
    registry.attach_metadata.return_value = attach_metadata_return or run
    registry.get_run.return_value = run
    return registry


def _make_subagent_run() -> MagicMock:
    run = MagicMock()
    run.run_id = "run-1"
    run.subagent_name = "test-agent"
    run.task = "original task"
    run.metadata = {}
    run.status = MagicMock()
    run.status.value = "running"
    run.to_event_data.return_value = {"run_id": "run-1"}
    return run


def _configure_control_runtime(
    *,
    registry: MagicMock | None = None,
    channel: AsyncMock | None = None,
    cancel_callback: AsyncMock | None = None,
    restart_callback: AsyncMock | None = None,
    conversation_id: str = "conv-1",
) -> None:
    runtime = subagent_sessions_module.SubAgentSessionToolRuntime(
        control=subagent_sessions_module.SubAgentControlRuntime(
            run_registry=registry or MagicMock(),
            conversation_id=conversation_id,
            subagent_names=("test-agent",),
            subagent_descriptions=MappingProxyType({"test-agent": "Test agent"}),
            cancel_callback=cancel_callback or AsyncMock(return_value=True),
            restart_callback=restart_callback,
            control_channel=channel,
            steer_rate_limit_ms=2000,
            max_active_runs=16,
            max_active_runs_per_lineage=16,
            max_children_per_requester=16,
            requester_session_key=conversation_id,
            delegation_depth=0,
            max_delegation_depth=1,
        )
    )
    _ = subagent_sessions_module._session_tool_runtime.set(  # pyright: ignore[reportPrivateUsage]
        runtime
    )


@pytest.fixture(autouse=True)
def _reset_control_runtime() -> object:
    token = subagent_sessions_module._session_tool_runtime.set(  # pyright: ignore[reportPrivateUsage]
        None
    )
    try:
        yield
    finally:
        subagent_sessions_module._session_tool_runtime.reset(  # pyright: ignore[reportPrivateUsage]
            token
        )


@pytest.mark.unit
class TestCtrlSendControlMessage:
    async def test_noop_when_channel_is_none(self) -> None:
        from src.infrastructure.agent.tools.subagent_sessions import (
            _ctrl_send_control_message,  # pyright: ignore[reportPrivateUsage]
        )

        _configure_control_runtime()
        await _ctrl_send_control_message("run-1", ControlMessageType.KILL)

    async def test_sends_message_when_channel_present(self) -> None:
        from src.infrastructure.agent.tools.subagent_sessions import (
            _ctrl_send_control_message,  # pyright: ignore[reportPrivateUsage]
        )

        channel = AsyncMock()
        channel.send_control = AsyncMock(return_value=True)
        _configure_control_runtime(channel=channel)
        await _ctrl_send_control_message("run-1", ControlMessageType.STEER, "go left")
        channel.send_control.assert_awaited_once()
        sent: ControlMessage = channel.send_control.call_args[0][0]
        assert sent.run_id == "run-1"
        assert sent.message_type == ControlMessageType.STEER
        assert sent.payload == "go left"
        assert sent.sender_id == "conv-1"

    async def test_swallows_exception(self) -> None:
        from src.infrastructure.agent.tools.subagent_sessions import (
            _ctrl_send_control_message,  # pyright: ignore[reportPrivateUsage]
        )

        channel = AsyncMock()
        channel.send_control = AsyncMock(side_effect=RuntimeError("redis down"))
        _configure_control_runtime(channel=channel)
        await _ctrl_send_control_message("run-1", ControlMessageType.KILL)

    async def test_cascade_flag_forwarded(self) -> None:
        from src.infrastructure.agent.tools.subagent_sessions import (
            _ctrl_send_control_message,  # pyright: ignore[reportPrivateUsage]
        )

        channel = AsyncMock()
        channel.send_control = AsyncMock(return_value=True)
        _configure_control_runtime(channel=channel)
        await _ctrl_send_control_message("run-1", ControlMessageType.KILL, cascade=True)
        sent: ControlMessage = channel.send_control.call_args[0][0]
        assert sent.cascade is True


@pytest.mark.unit
class TestSteerMetadataOnlySendsControlMessage:
    async def test_steer_sends_control_message(self) -> None:
        from src.infrastructure.agent.tools.subagent_sessions import (
            _ctrl_steer_metadata_only,  # pyright: ignore[reportPrivateUsage]
        )

        ctx = _make_tool_context()
        registry = _make_run_registry()
        channel = AsyncMock()
        channel.send_control = AsyncMock(return_value=True)

        _configure_control_runtime(registry=registry, channel=channel)
        result = await _ctrl_steer_metadata_only(ctx, "run-1", "focus on tests")

        assert not result.is_error
        channel.send_control.assert_awaited_once()
        sent: ControlMessage = channel.send_control.call_args[0][0]
        assert sent.message_type == ControlMessageType.STEER
        assert sent.payload == "focus on tests"
        assert sent.run_id == "run-1"

    async def test_steer_skips_control_when_attach_fails(self) -> None:
        from src.infrastructure.agent.tools.subagent_sessions import (
            _ctrl_steer_metadata_only,  # pyright: ignore[reportPrivateUsage]
        )

        ctx = _make_tool_context()
        registry = MagicMock()
        registry.attach_metadata.return_value = None
        channel = AsyncMock()
        channel.send_control = AsyncMock(return_value=True)

        _configure_control_runtime(registry=registry, channel=channel)
        result = await _ctrl_steer_metadata_only(ctx, "run-1", "focus on tests")

        assert result.is_error
        channel.send_control.assert_not_awaited()


@pytest.mark.unit
class TestSteerWithRestartSendsKill:
    async def test_kill_sent_before_cancel(self) -> None:
        from src.infrastructure.agent.tools.subagent_sessions import (
            _ctrl_steer_with_restart,  # pyright: ignore[reportPrivateUsage]
        )

        ctx = _make_tool_context()
        run = _make_subagent_run()
        channel = AsyncMock()
        channel.send_control = AsyncMock(return_value=True)

        registry = MagicMock()
        cancelled_run = MagicMock()
        cancelled_run.to_event_data.return_value = {"run_id": "run-1"}
        registry.mark_cancelled.return_value = cancelled_run

        replacement_run = MagicMock()
        replacement_run.run_id = "run-2"
        replacement_run.to_event_data.return_value = {"run_id": "run-2"}
        registry.create_run.return_value = replacement_run

        running_run = MagicMock()
        running_run.to_event_data.return_value = {"run_id": "run-2"}
        registry.mark_running.return_value = running_run

        cancel_cb = AsyncMock(return_value=True)
        restart_cb = AsyncMock(return_value="run-2")

        call_order: list[str] = []

        async def track_send(*args: object, **kwargs: object) -> bool:
            call_order.append("send_control")
            return True

        async def track_cancel(*args: object, **kwargs: object) -> bool:
            call_order.append("cancel_callback")
            return True

        channel.send_control = AsyncMock(side_effect=track_send)
        cancel_cb = AsyncMock(side_effect=track_cancel)

        _configure_control_runtime(
            registry=registry,
            channel=channel,
            cancel_callback=cancel_cb,
            restart_callback=restart_cb,
        )
        result = await _ctrl_steer_with_restart(ctx, run, "new direction")

        assert not result.is_error
        assert call_order == ["send_control", "cancel_callback"]
        sent: ControlMessage = channel.send_control.call_args[0][0]
        assert sent.message_type == ControlMessageType.KILL
        assert sent.run_id == "run-1"


@pytest.mark.unit
class TestExecCancellationsSendsKill:
    async def test_kill_sent_for_each_candidate(self) -> None:
        from src.infrastructure.agent.tools.subagent_sessions import (
            _ctrl_exec_cancellations,  # pyright: ignore[reportPrivateUsage]
        )

        ctx = _make_tool_context()
        channel = AsyncMock()
        channel.send_control = AsyncMock(return_value=True)

        active_run = MagicMock()
        active_run.run_id = "run-a"
        active_run.status = MagicMock()
        active_run.status.value = "running"
        active_run.to_event_data.return_value = {"run_id": "run-a"}

        from src.infrastructure.agent.subagent.run_registry import (
            SubAgentRunStatus,
        )

        active_run.status = SubAgentRunStatus.RUNNING

        registry = MagicMock()
        registry.get_run.return_value = active_run
        cancelled_run = MagicMock()
        cancelled_run.to_event_data.return_value = {"run_id": "run-a"}
        registry.mark_cancelled.return_value = cancelled_run
        cancel_cb = AsyncMock(return_value=True)

        _configure_control_runtime(
            registry=registry,
            channel=channel,
            cancel_callback=cancel_cb,
        )
        count = await _ctrl_exec_cancellations(ctx, {"run-a": "run-root"}, "target")

        assert count == 1
        channel.send_control.assert_awaited_once()
        sent: ControlMessage = channel.send_control.call_args[0][0]
        assert sent.message_type == ControlMessageType.KILL
        assert sent.cascade is True


@pytest.mark.unit
class TestAgentContainerControlChannel:
    def test_returns_redis_control_channel(self) -> None:
        from src.configuration.containers.agent_container import AgentContainer

        redis_client = MagicMock()
        container = AgentContainer(
            db=None,
            redis_client=redis_client,
        )
        channel = container.control_channel()
        from src.infrastructure.agent.subagent.control_channel import (
            RedisControlChannel,
        )

        assert isinstance(channel, RedisControlChannel)

    def test_returns_cached_singleton(self) -> None:
        from src.configuration.containers.agent_container import AgentContainer

        redis_client = MagicMock()
        container = AgentContainer(
            db=None,
            redis_client=redis_client,
        )
        first = container.control_channel()
        second = container.control_channel()
        assert first is second

    def test_raises_when_no_redis(self) -> None:
        from src.configuration.containers.agent_container import AgentContainer

        container = AgentContainer(
            db=None,
            redis_client=None,
        )
        with pytest.raises(AssertionError, match="redis_client"):
            container.control_channel()
