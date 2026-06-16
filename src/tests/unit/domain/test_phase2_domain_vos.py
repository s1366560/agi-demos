import pytest

from src.domain.events.agent_events import ToolPolicyDeniedEvent
from src.domain.events.types import EVENT_CATEGORIES, AgentEventType, EventCategory
from src.domain.model.agent.identity import AgentIdentity
from src.domain.model.agent.spawn_policy import SpawnPolicy
from src.domain.model.agent.subagent import AgentModel
from src.domain.model.agent.tool_policy import (
    ControlMessageType,
    ToolPolicy,
    ToolPolicyPrecedence,
)


@pytest.mark.unit
class TestToolPolicyPrecedence:
    def test_values(self) -> None:
        assert ToolPolicyPrecedence.ALLOW_FIRST.value == "allow_first"
        assert ToolPolicyPrecedence.DENY_FIRST.value == "deny_first"

    def test_is_str_enum(self) -> None:
        assert isinstance(ToolPolicyPrecedence.ALLOW_FIRST, str)


@pytest.mark.unit
class TestControlMessageType:
    def test_values(self) -> None:
        assert ControlMessageType.STEER.value == "steer"
        assert ControlMessageType.KILL.value == "kill"
        assert ControlMessageType.PAUSE.value == "pause"
        assert ControlMessageType.RESUME.value == "resume"

    def test_is_str_enum(self) -> None:
        assert isinstance(ControlMessageType.STEER, str)


@pytest.mark.unit
class TestToolPolicy:
    def test_defaults(self) -> None:
        policy = ToolPolicy()
        assert policy.allow == ()
        assert policy.deny == ()
        assert policy.precedence == ToolPolicyPrecedence.DENY_FIRST

    def test_frozen(self) -> None:
        policy = ToolPolicy()
        with pytest.raises(AttributeError):
            policy.allow = ("x",)  # type: ignore[misc]

    def test_value_equality(self) -> None:
        a = ToolPolicy(allow=("a", "b"), deny=("c",))
        b = ToolPolicy(allow=("a", "b"), deny=("c",))
        assert a == b

    def test_hashable(self) -> None:
        policy = ToolPolicy(allow=("a",))
        assert hash(policy) == hash(ToolPolicy(allow=("a",)))
        s = {policy, ToolPolicy(allow=("a",))}
        assert len(s) == 1

    def test_deny_first_blocks_denied_tool(self) -> None:
        policy = ToolPolicy(deny=("shell",))
        assert policy.is_allowed("shell") is False

    def test_deny_first_allows_unlisted_tool(self) -> None:
        policy = ToolPolicy(deny=("shell",))
        assert policy.is_allowed("search") is True

    def test_deny_first_deny_wins_over_allow(self) -> None:
        policy = ToolPolicy(allow=("shell",), deny=("shell",))
        assert policy.is_allowed("shell") is False

    def test_deny_first_restricts_unlisted_when_allow_present(self) -> None:
        policy = ToolPolicy(allow=("read",), deny=("shell",))
        assert policy.is_allowed("read") is True
        assert policy.is_allowed("search") is False

    def test_deny_first_wildcard_allow_keeps_unlisted_open(self) -> None:
        policy = ToolPolicy(allow=("*",), deny=("shell",))
        assert policy.is_allowed("search") is True
        assert policy.is_allowed("shell") is False

    def test_deny_first_empty_allows_everything(self) -> None:
        policy = ToolPolicy()
        assert policy.is_allowed("anything") is True

    def test_allow_first_permits_allowed_tool(self) -> None:
        policy = ToolPolicy(
            allow=("shell",),
            deny=("shell",),
            precedence=ToolPolicyPrecedence.ALLOW_FIRST,
        )
        assert policy.is_allowed("shell") is True

    def test_allow_first_restricts_unlisted_when_allow_present(self) -> None:
        policy = ToolPolicy(
            allow=("read",),
            deny=("shell",),
            precedence=ToolPolicyPrecedence.ALLOW_FIRST,
        )
        assert policy.is_allowed("read") is True
        assert policy.is_allowed("search") is False

    def test_allow_first_blocks_denied_not_allowed(self) -> None:
        policy = ToolPolicy(
            deny=("shell",),
            precedence=ToolPolicyPrecedence.ALLOW_FIRST,
        )
        assert policy.is_allowed("shell") is False

    def test_allow_first_permits_unlisted(self) -> None:
        policy = ToolPolicy(
            deny=("shell",),
            precedence=ToolPolicyPrecedence.ALLOW_FIRST,
        )
        assert policy.is_allowed("search") is True

    def test_filter_tools_tuple_input(self) -> None:
        policy = ToolPolicy(deny=("shell", "exec"))
        result = policy.filter_tools(("shell", "search", "exec", "read"))
        assert result == ["search", "read"]

    def test_filter_tools_list_input(self) -> None:
        policy = ToolPolicy(deny=("shell",))
        result = policy.filter_tools(["shell", "search"])
        assert result == ["search"]

    def test_filter_tools_empty(self) -> None:
        policy = ToolPolicy(deny=("shell",))
        assert policy.filter_tools(()) == []


@pytest.mark.unit
class TestAgentIdentity:
    def test_minimal_creation(self) -> None:
        identity = AgentIdentity(agent_id="a1", name="test")
        assert identity.agent_id == "a1"
        assert identity.name == "test"
        assert identity.model == AgentModel.INHERIT
        assert identity.allowed_tools == ()
        assert identity.allowed_skills == ()
        assert identity.metadata == ()

    def test_frozen(self) -> None:
        identity = AgentIdentity(agent_id="a1", name="test")
        with pytest.raises(AttributeError):
            identity.name = "other"  # type: ignore[misc]

    def test_value_equality(self) -> None:
        a = AgentIdentity(agent_id="a1", name="test", description="desc")
        b = AgentIdentity(agent_id="a1", name="test", description="desc")
        assert a == b

    def test_hashable(self) -> None:
        a = AgentIdentity(agent_id="a1", name="test")
        b = AgentIdentity(agent_id="a1", name="test")
        assert hash(a) == hash(b)
        assert len({a, b}) == 1

    def test_full_creation(self) -> None:
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
        assert identity.model == AgentModel.GPT4O
        assert identity.allowed_tools == ("search", "read")
        assert identity.spawn_policy.max_depth == 3
        assert identity.tool_policy.is_allowed("shell") is False
        assert identity.metadata == (("team", "backend"),)

    def test_default_policies(self) -> None:
        identity = AgentIdentity(agent_id="a1", name="test")
        assert isinstance(identity.spawn_policy, SpawnPolicy)
        assert isinstance(identity.tool_policy, ToolPolicy)


@pytest.mark.unit
class TestToolPolicyDeniedEvent:
    def test_creation(self) -> None:
        event = ToolPolicyDeniedEvent(
            agent_id="a1",
            tool_name="shell",
            policy_layer="identity",
            denial_reason="tool in deny list",
        )
        assert event.event_type == AgentEventType.TOOL_POLICY_DENIED
        assert event.agent_id == "a1"
        assert event.tool_name == "shell"
        assert event.policy_layer == "identity"
        assert event.denial_reason == "tool in deny list"

    def test_frozen(self) -> None:
        event = ToolPolicyDeniedEvent(agent_id="a1", tool_name="shell")
        with pytest.raises(Exception):
            event.tool_name = "other"

    def test_to_event_dict_structure(self) -> None:
        event = ToolPolicyDeniedEvent(
            agent_id="a1",
            tool_name="shell",
            policy_layer="identity",
            denial_reason="denied",
        )
        d = event.to_event_dict()
        assert d["type"] == "tool_policy_denied"
        assert "timestamp" in d
        assert d["data"]["agent_id"] == "a1"
        assert d["data"]["tool_name"] == "shell"
        assert d["data"]["policy_layer"] == "identity"
        assert d["data"]["denial_reason"] == "denied"

    def test_event_type_in_categories(self) -> None:
        assert AgentEventType.TOOL_POLICY_DENIED in EVENT_CATEGORIES
        assert EVENT_CATEGORIES[AgentEventType.TOOL_POLICY_DENIED] == EventCategory.AGENT

    def test_defaults(self) -> None:
        event = ToolPolicyDeniedEvent(agent_id="a1", tool_name="shell")
        assert event.policy_layer == ""
        assert event.denial_reason == ""
