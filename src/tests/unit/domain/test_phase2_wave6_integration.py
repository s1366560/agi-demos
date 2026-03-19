"""Cross-component integration tests for Phase 2 Control & Isolation."""

from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.domain.events.agent_events import AgentErrorEvent, ToolPolicyDeniedEvent
from src.domain.events.types import AgentEventType
from src.domain.model.agent.identity import AgentIdentity
from src.domain.model.agent.spawn_policy import SpawnPolicy
from src.domain.model.agent.subagent import (
    AgentModel,
    AgentTrigger,
    SubAgent,
    deserialize_identity,
    deserialize_spawn_policy,
    deserialize_tool_policy,
    serialize_identity,
    serialize_spawn_policy,
    serialize_tool_policy,
)
from src.domain.model.agent.tool_policy import (
    ControlMessageType,
    ToolPolicy,
    ToolPolicyPrecedence,
)
from src.domain.ports.agent.control_channel_port import ControlMessage
from src.infrastructure.agent.processor.processor import (
    ProcessorConfig,
    SessionProcessor,
    ToolDefinition,
)


def _make_processor(
    *,
    control_channel: AsyncMock | None = None,
    run_id: str | None = None,
) -> SessionProcessor:
    config = ProcessorConfig(
        model="test-model",
        control_channel=control_channel,
        run_id=run_id,
    )
    dummy_tool = ToolDefinition(
        name="test_tool",
        description="noop",
        parameters={"type": "object", "properties": {}},
        execute=AsyncMock(return_value="ok"),
    )
    return SessionProcessor(config=config, tools=[dummy_tool])


def _make_control_channel() -> AsyncMock:
    channel = AsyncMock()
    channel.consume_control = AsyncMock(return_value=[])
    channel.check_control = AsyncMock(return_value=None)
    channel.send_control = AsyncMock(return_value=True)
    channel.cleanup = AsyncMock()
    return channel


@pytest.mark.unit
class TestE2ESteerFlow:
    async def test_steer_message_reaches_processor_and_injects(self) -> None:
        steer_msg = ControlMessage(
            run_id="run-1",
            message_type=ControlMessageType.STEER,
            payload="focus on security analysis",
            sender_id="parent-conv",
        )

        channel = _make_control_channel()
        channel.consume_control.return_value = [steer_msg]

        proc = _make_processor(control_channel=channel, run_id="run-1")
        messages: list[dict[str, str]] = []
        events = await proc._check_control_channel(messages)  # pyright: ignore[reportPrivateUsage]

        assert len(messages) == 1
        assert messages[0]["role"] == "system"
        assert "focus on security analysis" in messages[0]["content"]
        assert events == []

    async def test_multiple_steer_messages_all_injected(self) -> None:
        steer1 = ControlMessage(
            run_id="run-1",
            message_type=ControlMessageType.STEER,
            payload="first direction",
            sender_id="parent",
        )
        steer2 = ControlMessage(
            run_id="run-1",
            message_type=ControlMessageType.STEER,
            payload="second direction",
            sender_id="parent",
        )

        channel = _make_control_channel()
        channel.consume_control.return_value = [steer1, steer2]

        proc = _make_processor(control_channel=channel, run_id="run-1")
        messages: list[dict[str, str]] = []
        await proc._check_control_channel(messages)  # pyright: ignore[reportPrivateUsage]

        assert len(messages) == 2
        assert "first direction" in messages[0]["content"]
        assert "second direction" in messages[1]["content"]


@pytest.mark.unit
class TestE2EKillFlow:
    async def test_kill_message_sets_abort_event(self) -> None:
        kill_msg = ControlMessage(
            run_id="run-1",
            message_type=ControlMessageType.KILL,
            payload="resource limit exceeded",
            sender_id="parent-conv",
        )

        channel = _make_control_channel()
        channel.consume_control.return_value = [kill_msg]

        proc = _make_processor(control_channel=channel, run_id="run-1")
        abort = asyncio.Event()
        proc._abort_event = abort  # pyright: ignore[reportPrivateUsage]

        events = await proc._check_control_channel([])  # pyright: ignore[reportPrivateUsage]

        assert abort.is_set()
        assert len(events) == 1
        assert isinstance(events[0], AgentErrorEvent)
        assert events[0].code == "KILLED"

    async def test_kill_preempts_steer_in_same_batch(self) -> None:
        steer_msg = ControlMessage(
            run_id="run-1",
            message_type=ControlMessageType.STEER,
            payload="do something",
            sender_id="parent",
        )
        kill_msg = ControlMessage(
            run_id="run-1",
            message_type=ControlMessageType.KILL,
            payload="terminate",
            sender_id="parent",
        )

        channel = _make_control_channel()
        channel.consume_control.return_value = [steer_msg, kill_msg]

        proc = _make_processor(control_channel=channel, run_id="run-1")
        abort = asyncio.Event()
        proc._abort_event = abort  # pyright: ignore[reportPrivateUsage]

        messages: list[dict[str, str]] = []
        events = await proc._check_control_channel(messages)  # pyright: ignore[reportPrivateUsage]

        assert abort.is_set()
        assert len(events) == 1
        assert isinstance(events[0], AgentErrorEvent)
        assert events[0].code == "KILLED"
        assert len(messages) == 1


@pytest.mark.unit
class TestE2EToolKillSteerViaTools:
    async def test_kill_tool_sends_control_message(self) -> None:
        from src.infrastructure.agent.tools.subagent_sessions import (
            _ctrl_exec_cancellations,  # pyright: ignore[reportPrivateUsage]
        )

        ctx = MagicMock()
        ctx.emit = AsyncMock()
        channel = AsyncMock()
        channel.send_control = AsyncMock(return_value=True)

        from src.infrastructure.agent.subagent.run_registry import SubAgentRunStatus

        active_run = MagicMock()
        active_run.run_id = "run-target"
        active_run.status = SubAgentRunStatus.RUNNING
        active_run.to_event_data.return_value = {"run_id": "run-target"}

        registry = MagicMock()
        registry.get_run.return_value = active_run
        cancelled_run = MagicMock()
        cancelled_run.to_event_data.return_value = {"run_id": "run-target"}
        registry.mark_cancelled.return_value = cancelled_run

        cancel_cb = AsyncMock(return_value=True)

        with (
            patch("src.infrastructure.agent.tools.subagent_sessions._ctrl_run_registry", registry),
            patch(
                "src.infrastructure.agent.tools.subagent_sessions._ctrl_cancel_callback", cancel_cb
            ),
            patch(
                "src.infrastructure.agent.tools.subagent_sessions._ctrl_conversation_id",
                "parent-conv",
            ),
            patch(
                "src.infrastructure.agent.tools.subagent_sessions._ctrl_control_channel", channel
            ),
        ):
            count = await _ctrl_exec_cancellations(ctx, {"run-target": "root"}, "target")

        assert count == 1
        channel.send_control.assert_awaited_once()
        sent: ControlMessage = channel.send_control.call_args[0][0]
        assert sent.message_type == ControlMessageType.KILL
        assert sent.run_id == "run-target"

    async def test_steer_tool_sends_control_message(self) -> None:
        from src.infrastructure.agent.tools.subagent_sessions import (
            _ctrl_steer_metadata_only,  # pyright: ignore[reportPrivateUsage]
        )

        ctx = MagicMock()
        ctx.emit = AsyncMock()

        run = MagicMock()
        run.run_id = "run-steer"
        run.status = MagicMock()
        run.status.value = "running"
        run.to_event_data.return_value = {"run_id": "run-steer"}

        registry = MagicMock()
        registry.attach_metadata.return_value = run
        channel = AsyncMock()
        channel.send_control = AsyncMock(return_value=True)

        with (
            patch("src.infrastructure.agent.tools.subagent_sessions._ctrl_run_registry", registry),
            patch(
                "src.infrastructure.agent.tools.subagent_sessions._ctrl_conversation_id",
                "parent-conv",
            ),
            patch(
                "src.infrastructure.agent.tools.subagent_sessions._ctrl_control_channel", channel
            ),
        ):
            result = await _ctrl_steer_metadata_only(ctx, "run-steer", "change focus")

        assert not result.is_error
        channel.send_control.assert_awaited_once()
        sent: ControlMessage = channel.send_control.call_args[0][0]
        assert sent.message_type == ControlMessageType.STEER
        assert sent.payload == "change focus"
        assert sent.run_id == "run-steer"


@pytest.mark.unit
class TestLayeredToolPolicyResolution:
    def test_deny_first_blocks_denied_allows_rest(self) -> None:
        policy = ToolPolicy(
            allow=("search", "read"),
            deny=("terminal", "write"),
            precedence=ToolPolicyPrecedence.DENY_FIRST,
        )

        all_tools = ["search", "read", "terminal", "write", "plan"]
        filtered = policy.filter_tools(all_tools)

        assert "search" in filtered
        assert "read" in filtered
        assert "plan" in filtered
        assert "terminal" not in filtered
        assert "write" not in filtered

    def test_allow_first_permits_allowed_blocks_denied(self) -> None:
        policy = ToolPolicy(
            allow=("search",),
            deny=("terminal", "search"),
            precedence=ToolPolicyPrecedence.ALLOW_FIRST,
        )

        assert policy.is_allowed("search") is True
        assert policy.is_allowed("terminal") is False
        assert policy.is_allowed("unknown") is True

    def test_empty_policy_allows_everything(self) -> None:
        policy = ToolPolicy()
        tools = ["a", "b", "c", "d"]
        assert policy.filter_tools(tools) == tools

    def test_subagent_tool_policy_filters_tools(self) -> None:
        policy = ToolPolicy(
            deny=("terminal", "desktop"),
            precedence=ToolPolicyPrecedence.DENY_FIRST,
        )
        sub = SubAgent(
            id="sa-1",
            name="researcher",
            display_name="Research Agent",
            system_prompt="You research.",
            model=AgentModel.INHERIT,
            temperature=0.7,
            max_tokens=4096,
            max_iterations=10,
            allowed_tools=["search", "read", "terminal"],
            tenant_id="t-1",
            trigger=AgentTrigger(description="research tasks"),
            tool_policy=policy,
        )

        available = ["search", "read", "terminal", "desktop", "write"]
        base_filtered = sub.get_filtered_tools(available)
        policy_filtered = (
            sub.tool_policy.filter_tools(base_filtered) if sub.tool_policy else base_filtered
        )

        assert "terminal" not in policy_filtered
        assert "desktop" not in policy_filtered


@pytest.mark.unit
class TestAgentIdentityRoundTrip:
    def test_identity_full_round_trip(self) -> None:
        identity = AgentIdentity(
            agent_id="agent-001",
            name="Security Analyzer",
            description="Specializes in code security review",
            system_prompt="You are a security expert.",
            model=AgentModel.INHERIT,
            allowed_tools=("search", "read"),
            allowed_skills=("code-review",),
            spawn_policy=SpawnPolicy(max_depth=1, max_children_per_requester=2),
            tool_policy=ToolPolicy(deny=("terminal",)),
            metadata=(("team", "security"), ("version", "1.0")),
        )

        sub = SubAgent(
            id="sa-identity",
            name="security-analyzer",
            display_name="Security Analyzer",
            system_prompt="You are a security expert.",
            model=AgentModel.INHERIT,
            temperature=0.3,
            max_tokens=8192,
            max_iterations=15,
            allowed_tools=["search", "read"],
            tenant_id="t-1",
            trigger=AgentTrigger(description="security analysis"),
            identity=identity,
            spawn_policy=SpawnPolicy(max_depth=1, max_children_per_requester=2),
            tool_policy=ToolPolicy(deny=("terminal",)),
        )

        identity_json = serialize_identity(sub.identity)
        assert identity_json is not None
        restored = deserialize_identity(identity_json)
        assert restored is not None
        assert restored.agent_id == identity.agent_id
        assert restored.name == identity.name
        assert restored.description == identity.description
        assert restored.allowed_tools == identity.allowed_tools
        assert restored.allowed_skills == identity.allowed_skills
        assert restored.metadata == identity.metadata

    def test_spawn_policy_round_trip(self) -> None:
        sp = SpawnPolicy(
            max_depth=3,
            max_children_per_requester=5,
            allowed_subagents=frozenset({"helper"}),
        )
        sub = SubAgent(
            id="sa-sp",
            name="delegator",
            display_name="Delegator",
            system_prompt="Delegate work.",
            model=AgentModel.INHERIT,
            temperature=0.5,
            max_tokens=4096,
            max_iterations=10,
            allowed_tools=[],
            tenant_id="t-1",
            trigger=AgentTrigger(description="delegation"),
            spawn_policy=sp,
        )

        sp_json = serialize_spawn_policy(sub.spawn_policy)
        assert sp_json is not None
        restored = deserialize_spawn_policy(sp_json)
        assert restored is not None
        assert restored.max_depth == 3
        assert restored.max_children_per_requester == 5
        assert restored.allowed_subagents == frozenset({"helper"})

    def test_tool_policy_round_trip(self) -> None:
        tp = ToolPolicy(
            allow=("search", "read"),
            deny=("terminal",),
            precedence=ToolPolicyPrecedence.ALLOW_FIRST,
        )
        sub = SubAgent(
            id="sa-tp",
            name="safe-agent",
            display_name="Safe Agent",
            system_prompt="Be safe.",
            model=AgentModel.INHERIT,
            temperature=0.5,
            max_tokens=4096,
            max_iterations=10,
            allowed_tools=["search", "read"],
            tenant_id="t-1",
            trigger=AgentTrigger(description="safe operations"),
            tool_policy=tp,
        )

        tp_json = serialize_tool_policy(sub.tool_policy)
        assert tp_json is not None
        restored = deserialize_tool_policy(tp_json)
        assert restored is not None
        assert restored.allow == ("search", "read")
        assert restored.deny == ("terminal",)
        assert restored.precedence == ToolPolicyPrecedence.ALLOW_FIRST

    def test_all_three_fields_round_trip(self) -> None:
        sub = SubAgent(
            id="sa-all",
            name="full-agent",
            display_name="Full Agent",
            system_prompt="I have everything.",
            model=AgentModel.INHERIT,
            temperature=0.7,
            max_tokens=8192,
            max_iterations=20,
            allowed_tools=["search"],
            tenant_id="t-1",
            trigger=AgentTrigger(description="full featured"),
            identity=AgentIdentity(agent_id="a-1", name="Full"),
            spawn_policy=SpawnPolicy(max_depth=2),
            tool_policy=ToolPolicy(deny=("terminal",)),
        )

        id_json = serialize_identity(sub.identity)
        sp_json = serialize_spawn_policy(sub.spawn_policy)
        tp_json = serialize_tool_policy(sub.tool_policy)

        restored_id = deserialize_identity(id_json)
        restored_sp = deserialize_spawn_policy(sp_json)
        restored_tp = deserialize_tool_policy(tp_json)

        assert restored_id is not None
        assert restored_id.agent_id == "a-1"
        assert restored_sp is not None
        assert restored_sp.max_depth == 2
        assert restored_tp is not None
        assert restored_tp.deny == ("terminal",)


@pytest.mark.unit
class TestToolPolicyDeniedEventVerification:
    def test_event_structure(self) -> None:
        event = ToolPolicyDeniedEvent(
            agent_id="agent-1",
            tool_name="terminal",
            policy_layer="subagent",
            denial_reason="Tool 'terminal' is denied by SubAgent tool policy",
        )

        assert event.event_type == AgentEventType.TOOL_POLICY_DENIED
        assert event.agent_id == "agent-1"
        assert event.tool_name == "terminal"
        assert event.policy_layer == "subagent"

    def test_event_dict_serialization(self) -> None:
        event = ToolPolicyDeniedEvent(
            agent_id="agent-1",
            tool_name="write",
            policy_layer="identity",
            denial_reason="blocked by identity policy",
        )

        d = event.to_event_dict()
        assert d["type"] == "tool_policy_denied"
        assert "timestamp" in d
        data = d["data"]
        assert data["agent_id"] == "agent-1"
        assert data["tool_name"] == "write"
        assert data["policy_layer"] == "identity"

    def test_event_type_matches_enum(self) -> None:
        assert AgentEventType.TOOL_POLICY_DENIED == "tool_policy_denied"
        assert AgentEventType.TOOL_POLICY_DENIED.value == "tool_policy_denied"


@pytest.mark.unit
class TestDIContainerControlChannel:
    def test_container_creates_redis_control_channel(self) -> None:
        from src.configuration.containers.agent_container import AgentContainer
        from src.infrastructure.agent.subagent.control_channel import RedisControlChannel

        container = AgentContainer(db=None, redis_client=MagicMock())
        ch = container.control_channel()
        assert isinstance(ch, RedisControlChannel)

    def test_container_caches_channel_singleton(self) -> None:
        from src.configuration.containers.agent_container import AgentContainer

        container = AgentContainer(db=None, redis_client=MagicMock())
        first = container.control_channel()
        second = container.control_channel()
        assert first is second

    def test_container_raises_without_redis(self) -> None:
        from src.configuration.containers.agent_container import AgentContainer

        container = AgentContainer(db=None, redis_client=None)
        with pytest.raises(AssertionError):
            container.control_channel()


@pytest.mark.unit
class TestControlMessageProtocol:
    def test_message_types_cover_all_operations(self) -> None:
        expected = {"steer", "kill", "pause", "resume"}
        actual = {m.value for m in ControlMessageType}
        assert actual == expected

    def test_message_fields_complete(self) -> None:
        msg = ControlMessage(
            run_id="r-1",
            message_type=ControlMessageType.STEER,
            payload="do X",
            sender_id="s-1",
            cascade=True,
        )
        assert msg.run_id == "r-1"
        assert msg.message_type == ControlMessageType.STEER
        assert msg.payload == "do X"
        assert msg.sender_id == "s-1"
        assert msg.cascade is True
        assert isinstance(msg.timestamp, datetime)

    def test_message_immutable(self) -> None:
        msg = ControlMessage(
            run_id="r-1",
            message_type=ControlMessageType.KILL,
        )
        with pytest.raises(AttributeError):
            msg.run_id = "r-2"  # pyright: ignore[reportAttributeAccessIssue]


@pytest.mark.unit
class TestProcessorFactoryWiresControlChannel:
    def test_factory_wires_channel_to_subagent_config(self) -> None:
        from src.infrastructure.agent.processor.factory import ProcessorFactory

        channel = AsyncMock()
        factory = ProcessorFactory(
            base_model="test-model",
            control_channel=channel,
        )

        assert factory.control_channel is channel

    def test_factory_defaults_to_no_channel(self) -> None:
        from src.infrastructure.agent.processor.factory import ProcessorFactory

        factory = ProcessorFactory(
            base_model="test-model",
        )

        assert factory.control_channel is None
