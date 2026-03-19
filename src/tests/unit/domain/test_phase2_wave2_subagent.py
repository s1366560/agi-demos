"""Tests for Phase 2 Wave 2: SubAgent entity extension with spawn_policy, tool_policy, identity."""

import pytest

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
from src.domain.model.agent.tool_policy import ToolPolicy, ToolPolicyPrecedence


def _make_subagent(**overrides: object) -> SubAgent:
    defaults: dict[str, object] = {
        "id": "sa-1",
        "tenant_id": "t-1",
        "name": "test-agent",
        "display_name": "Test Agent",
        "system_prompt": "You are a test agent.",
        "trigger": AgentTrigger(description="test trigger"),
    }
    defaults.update(overrides)
    return SubAgent(**defaults)  # type: ignore[arg-type]


@pytest.mark.unit
class TestSerializeSpawnPolicy:
    def test_none_returns_none(self) -> None:
        assert serialize_spawn_policy(None) is None

    def test_round_trip(self) -> None:
        policy = SpawnPolicy(max_depth=5, max_active_runs=10, max_children_per_requester=4)
        data = serialize_spawn_policy(policy)
        assert data is not None
        restored = deserialize_spawn_policy(data)
        assert restored is not None
        assert restored.max_depth == 5
        assert restored.max_active_runs == 10
        assert restored.max_children_per_requester == 4
        assert restored.allowed_subagents is None

    def test_with_allowed_subagents(self) -> None:
        policy = SpawnPolicy(allowed_subagents=frozenset({"a", "b"}))
        data = serialize_spawn_policy(policy)
        assert data is not None
        assert set(data["allowed_subagents"]) == {"a", "b"}
        restored = deserialize_spawn_policy(data)
        assert restored is not None
        assert restored.allowed_subagents == frozenset({"a", "b"})


@pytest.mark.unit
class TestDeserializeSpawnPolicy:
    def test_none_returns_none(self) -> None:
        assert deserialize_spawn_policy(None) is None

    def test_defaults_from_empty_dict(self) -> None:
        result = deserialize_spawn_policy({})
        assert result is not None
        assert result.max_depth == 2
        assert result.max_active_runs == 16
        assert result.max_children_per_requester == 8
        assert result.allowed_subagents is None


@pytest.mark.unit
class TestSerializeToolPolicy:
    def test_none_returns_none(self) -> None:
        assert serialize_tool_policy(None) is None

    def test_round_trip(self) -> None:
        policy = ToolPolicy(
            allow=("search", "read"),
            deny=("shell",),
            precedence=ToolPolicyPrecedence.ALLOW_FIRST,
        )
        data = serialize_tool_policy(policy)
        assert data is not None
        assert data["allow"] == ["search", "read"]
        assert data["deny"] == ["shell"]
        assert data["precedence"] == "allow_first"
        restored = deserialize_tool_policy(data)
        assert restored is not None
        assert restored.allow == ("search", "read")
        assert restored.deny == ("shell",)
        assert restored.precedence == ToolPolicyPrecedence.ALLOW_FIRST

    def test_empty_policy_round_trip(self) -> None:
        policy = ToolPolicy()
        data = serialize_tool_policy(policy)
        restored = deserialize_tool_policy(data)
        assert restored is not None
        assert restored.allow == ()
        assert restored.deny == ()
        assert restored.precedence == ToolPolicyPrecedence.DENY_FIRST


@pytest.mark.unit
class TestDeserializeToolPolicy:
    def test_none_returns_none(self) -> None:
        assert deserialize_tool_policy(None) is None

    def test_defaults_from_empty_dict(self) -> None:
        result = deserialize_tool_policy({})
        assert result is not None
        assert result.allow == ()
        assert result.deny == ()
        assert result.precedence == ToolPolicyPrecedence.DENY_FIRST


@pytest.mark.unit
class TestSerializeIdentity:
    def test_none_returns_none(self) -> None:
        assert serialize_identity(None) is None

    def test_round_trip(self) -> None:
        sp = SpawnPolicy(max_depth=3)
        tp = ToolPolicy(deny=("shell",))
        identity = AgentIdentity(
            agent_id="a1",
            name="coder",
            description="A coding agent",
            system_prompt="You are a coder.",
            model=AgentModel.GPT4O,
            allowed_tools=("search", "read"),
            allowed_skills=("web",),
            spawn_policy=sp,
            tool_policy=tp,
            metadata=(("team", "backend"),),
        )
        data = serialize_identity(identity)
        assert data is not None
        assert data["agent_id"] == "a1"
        assert data["name"] == "coder"
        assert data["model"] == "gpt-4o"
        assert data["allowed_tools"] == ["search", "read"]
        assert data["metadata"] == {"team": "backend"}

        restored = deserialize_identity(data)
        assert restored is not None
        assert restored.agent_id == "a1"
        assert restored.name == "coder"
        assert restored.model == AgentModel.GPT4O
        assert restored.allowed_tools == ("search", "read")
        assert restored.allowed_skills == ("web",)
        assert restored.spawn_policy.max_depth == 3
        assert restored.tool_policy.is_allowed("shell") is False
        assert restored.metadata == (("team", "backend"),)

    def test_minimal_identity_round_trip(self) -> None:
        identity = AgentIdentity(agent_id="a1", name="test")
        data = serialize_identity(identity)
        restored = deserialize_identity(data)
        assert restored is not None
        assert restored.agent_id == "a1"
        assert restored.name == "test"
        assert restored.description == ""
        assert isinstance(restored.spawn_policy, SpawnPolicy)
        assert isinstance(restored.tool_policy, ToolPolicy)


@pytest.mark.unit
class TestDeserializeIdentity:
    def test_none_returns_none(self) -> None:
        assert deserialize_identity(None) is None

    def test_defaults_for_missing_optional_fields(self) -> None:
        data = {"agent_id": "a1", "name": "test"}
        restored = deserialize_identity(data)
        assert restored is not None
        assert restored.description == ""
        assert restored.system_prompt == ""
        assert restored.model == AgentModel.INHERIT
        assert restored.allowed_tools == ()
        assert restored.allowed_skills == ()
        assert isinstance(restored.spawn_policy, SpawnPolicy)
        assert isinstance(restored.tool_policy, ToolPolicy)
        assert restored.metadata == ()


@pytest.mark.unit
class TestSubAgentNewFields:
    def test_defaults_none(self) -> None:
        agent = _make_subagent()
        assert agent.spawn_policy is None
        assert agent.tool_policy is None
        assert agent.identity is None

    def test_with_spawn_policy(self) -> None:
        sp = SpawnPolicy(max_depth=5)
        agent = _make_subagent(spawn_policy=sp)
        assert agent.spawn_policy is not None
        assert agent.spawn_policy is sp
        assert agent.spawn_policy.max_depth == 5

    def test_with_tool_policy(self) -> None:
        tp = ToolPolicy(deny=("shell",))
        agent = _make_subagent(tool_policy=tp)
        assert agent.tool_policy is not None
        assert agent.tool_policy is tp
        assert agent.tool_policy.is_allowed("shell") is False
        assert agent.tool_policy.is_allowed("search") is True

    def test_with_identity(self) -> None:
        identity = AgentIdentity(agent_id="a1", name="coder")
        agent = _make_subagent(identity=identity)
        assert agent.identity is not None
        assert agent.identity is identity
        assert agent.identity.agent_id == "a1"

    def test_all_three_fields(self) -> None:
        sp = SpawnPolicy(max_depth=1)
        tp = ToolPolicy(allow=("read",), deny=("exec",))
        ident = AgentIdentity(agent_id="x", name="worker")
        agent = _make_subagent(spawn_policy=sp, tool_policy=tp, identity=ident)
        assert agent.spawn_policy is sp
        assert agent.tool_policy is tp
        assert agent.identity is ident


@pytest.mark.unit
class TestRecordExecutionPreservesFields:
    def test_preserves_spawn_policy(self) -> None:
        sp = SpawnPolicy(max_depth=7)
        agent = _make_subagent(spawn_policy=sp)
        updated = agent.record_execution(100.0, success=True)
        assert updated.spawn_policy is sp

    def test_preserves_tool_policy(self) -> None:
        tp = ToolPolicy(deny=("shell",))
        agent = _make_subagent(tool_policy=tp)
        updated = agent.record_execution(50.0, success=False)
        assert updated.tool_policy is tp

    def test_preserves_identity(self) -> None:
        ident = AgentIdentity(agent_id="a1", name="test")
        agent = _make_subagent(identity=ident)
        updated = agent.record_execution(200.0, success=True)
        assert updated.identity is ident

    def test_preserves_all_three(self) -> None:
        sp = SpawnPolicy(max_depth=1)
        tp = ToolPolicy(allow=("read",))
        ident = AgentIdentity(agent_id="a1", name="bot")
        agent = _make_subagent(spawn_policy=sp, tool_policy=tp, identity=ident)
        updated = agent.record_execution(300.0, success=True)
        assert updated.spawn_policy is sp
        assert updated.tool_policy is tp
        assert updated.identity is ident
        assert updated.total_invocations == 1

    def test_preserves_none_fields(self) -> None:
        agent = _make_subagent()
        updated = agent.record_execution(100.0, success=True)
        assert updated.spawn_policy is None
        assert updated.tool_policy is None
        assert updated.identity is None


@pytest.mark.unit
class TestToDictFromDictRoundTrip:
    def test_round_trip_with_none_fields(self) -> None:
        agent = _make_subagent()
        data = agent.to_dict()
        assert data["spawn_policy"] is None
        assert data["tool_policy"] is None
        assert data["identity"] is None
        restored = SubAgent.from_dict(data)
        assert restored.spawn_policy is None
        assert restored.tool_policy is None
        assert restored.identity is None

    def test_round_trip_with_spawn_policy(self) -> None:
        sp = SpawnPolicy(max_depth=4, allowed_subagents=frozenset({"coder"}))
        agent = _make_subagent(spawn_policy=sp)
        data = agent.to_dict()
        assert data["spawn_policy"] is not None
        restored = SubAgent.from_dict(data)
        assert restored.spawn_policy is not None
        assert restored.spawn_policy.max_depth == 4
        assert restored.spawn_policy.allowed_subagents == frozenset({"coder"})

    def test_round_trip_with_tool_policy(self) -> None:
        tp = ToolPolicy(
            allow=("search",),
            deny=("shell", "exec"),
            precedence=ToolPolicyPrecedence.ALLOW_FIRST,
        )
        agent = _make_subagent(tool_policy=tp)
        data = agent.to_dict()
        assert data["tool_policy"] is not None
        restored = SubAgent.from_dict(data)
        assert restored.tool_policy is not None
        assert restored.tool_policy.allow == ("search",)
        assert restored.tool_policy.deny == ("shell", "exec")
        assert restored.tool_policy.precedence == ToolPolicyPrecedence.ALLOW_FIRST

    def test_round_trip_with_identity(self) -> None:
        sp = SpawnPolicy(max_depth=2)
        tp = ToolPolicy(deny=("danger",))
        ident = AgentIdentity(
            agent_id="a1",
            name="coder",
            description="Writes code",
            model=AgentModel.DEEPSEEK,
            allowed_tools=("terminal",),
            spawn_policy=sp,
            tool_policy=tp,
            metadata=(("role", "dev"),),
        )
        agent = _make_subagent(identity=ident)
        data = agent.to_dict()
        assert data["identity"] is not None
        restored = SubAgent.from_dict(data)
        assert restored.identity is not None
        assert restored.identity.agent_id == "a1"
        assert restored.identity.name == "coder"
        assert restored.identity.model == AgentModel.DEEPSEEK
        assert restored.identity.allowed_tools == ("terminal",)
        assert restored.identity.spawn_policy.max_depth == 2
        assert restored.identity.tool_policy.is_allowed("danger") is False
        assert restored.identity.metadata == (("role", "dev"),)

    def test_round_trip_with_all_three(self) -> None:
        sp = SpawnPolicy(max_depth=3)
        tp = ToolPolicy(deny=("shell",))
        ident = AgentIdentity(agent_id="x", name="worker")
        agent = _make_subagent(spawn_policy=sp, tool_policy=tp, identity=ident)
        data = agent.to_dict()
        restored = SubAgent.from_dict(data)
        assert restored.spawn_policy is not None
        assert restored.spawn_policy.max_depth == 3
        assert restored.tool_policy is not None
        assert restored.tool_policy.deny == ("shell",)
        assert restored.identity is not None
        assert restored.identity.agent_id == "x"


@pytest.mark.unit
class TestCreateFactory:
    def test_create_without_new_params(self) -> None:
        agent = SubAgent.create(
            tenant_id="t1",
            name="basic",
            display_name="Basic",
            system_prompt="prompt",
            trigger_description="basic trigger",
        )
        assert agent.spawn_policy is None
        assert agent.tool_policy is None
        assert agent.identity is None

    def test_create_with_spawn_policy(self) -> None:
        sp = SpawnPolicy(max_depth=10)
        agent = SubAgent.create(
            tenant_id="t1",
            name="sp-agent",
            display_name="SP Agent",
            system_prompt="prompt",
            trigger_description="trigger",
            spawn_policy=sp,
        )
        assert agent.spawn_policy is sp

    def test_create_with_tool_policy(self) -> None:
        tp = ToolPolicy(deny=("rm",))
        agent = SubAgent.create(
            tenant_id="t1",
            name="tp-agent",
            display_name="TP Agent",
            system_prompt="prompt",
            trigger_description="trigger",
            tool_policy=tp,
        )
        assert agent.tool_policy is tp

    def test_create_with_identity(self) -> None:
        ident = AgentIdentity(agent_id="a1", name="ident-agent")
        agent = SubAgent.create(
            tenant_id="t1",
            name="id-agent",
            display_name="ID Agent",
            system_prompt="prompt",
            trigger_description="trigger",
            identity=ident,
        )
        assert agent.identity is ident

    def test_create_with_all_three(self) -> None:
        sp = SpawnPolicy(max_depth=1)
        tp = ToolPolicy(allow=("search",))
        ident = AgentIdentity(agent_id="a1", name="full")
        agent = SubAgent.create(
            tenant_id="t1",
            name="full-agent",
            display_name="Full Agent",
            system_prompt="prompt",
            trigger_description="trigger",
            spawn_policy=sp,
            tool_policy=tp,
            identity=ident,
        )
        assert agent.spawn_policy is sp
        assert agent.tool_policy is tp
        assert agent.identity is ident
        assert agent.id  # UUID was generated
        assert agent.name == "full-agent"
