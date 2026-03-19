"""Unit tests for tool policy resolver."""

import pytest

from src.application.services.tool_policy_resolver import ToolPolicy, ToolPolicyResolver


@pytest.mark.unit
class TestToolPolicy:
    """Test suite for ToolPolicy frozen dataclass."""

    def test_frozen_immutability(self):
        """Test that ToolPolicy is frozen and immutable."""
        policy = ToolPolicy(
            source="test_source",
            precedence=10,
            allowed=frozenset({"tool1", "tool2"}),
            denied=frozenset({"tool3"}),
        )

        with pytest.raises(AttributeError):
            policy.source = "new_source"

        with pytest.raises(AttributeError):
            policy.precedence = 20

        with pytest.raises(AttributeError):
            policy.allowed = frozenset({"tool4"})

        with pytest.raises(AttributeError):
            policy.denied = frozenset({"tool5"})

    def test_all_fields_accessible(self):
        """Test that all fields are accessible."""
        policy = ToolPolicy(
            source="my_source",
            precedence=5,
            allowed=frozenset({"a", "b"}),
            denied=frozenset({"c"}),
        )

        assert policy.source == "my_source"
        assert policy.precedence == 5
        assert policy.allowed == frozenset({"a", "b"})
        assert policy.denied == frozenset({"c"})

    def test_allowed_none_means_no_restriction(self):
        """Test that allowed=None means no restriction from this layer."""
        policy = ToolPolicy(
            source="permissive",
            precedence=1,
            allowed=None,
            denied=frozenset(),
        )

        assert policy.allowed is None
        assert policy.denied == frozenset()

    def test_denied_is_frozenset(self):
        """Test that denied field stores as frozenset."""
        policy = ToolPolicy(
            source="test",
            precedence=1,
            allowed=frozenset(),
            denied=frozenset({"bad_tool"}),
        )

        assert isinstance(policy.denied, frozenset)
        assert "bad_tool" in policy.denied

    def test_denied_default_is_empty_frozenset(self):
        """Test that denied defaults to empty frozenset."""
        policy = ToolPolicy(
            source="test",
            precedence=1,
            allowed=frozenset({"tool1"}),
        )

        assert policy.denied == frozenset()
        assert isinstance(policy.denied, frozenset)

    def test_allowed_can_be_wildcard(self):
        """Test that allowed can contain wildcard '*'."""
        policy = ToolPolicy(
            source="all_allowed",
            precedence=1,
            allowed=frozenset({"*"}),
            denied=frozenset(),
        )

        assert "*" in policy.allowed


@pytest.mark.unit
class TestToolPolicyResolver:
    """Test suite for ToolPolicyResolver."""

    def test_no_policies_allows_all(self):
        """Test that empty resolver allows any tool."""
        resolver = ToolPolicyResolver()

        assert resolver.is_allowed("any_tool") is True
        assert resolver.is_allowed("another_tool") is True
        assert resolver.is_allowed("random_name") is True

    def test_denied_tool_rejected(self):
        """Test that tool in denied set returns False from is_allowed."""
        resolver = ToolPolicyResolver()
        policy = ToolPolicy(
            source="sandbox",
            precedence=10,
            allowed=None,
            denied=frozenset({"dangerous_tool"}),
        )
        resolver.register_policy(policy)

        assert resolver.is_allowed("dangerous_tool") is False
        assert resolver.is_allowed("safe_tool") is True

    def test_allowed_whitelist_rejects_unlisted(self):
        """Test that tool NOT in allowed set returns False."""
        resolver = ToolPolicyResolver()
        policy = ToolPolicy(
            source="restricted",
            precedence=10,
            allowed=frozenset({"tool1", "tool2"}),
            denied=frozenset(),
        )
        resolver.register_policy(policy)

        assert resolver.is_allowed("tool1") is True
        assert resolver.is_allowed("tool2") is True
        assert resolver.is_allowed("tool3") is False
        assert resolver.is_allowed("unlisted_tool") is False

    def test_allowed_whitelist_allows_listed(self):
        """Test that tool IN allowed set returns True."""
        resolver = ToolPolicyResolver()
        policy = ToolPolicy(
            source="agent",
            precedence=5,
            allowed=frozenset({"read", "write", "execute"}),
            denied=frozenset(),
        )
        resolver.register_policy(policy)

        assert resolver.is_allowed("read") is True
        assert resolver.is_allowed("write") is True
        assert resolver.is_allowed("execute") is True

    def test_allowed_wildcard_allows_all(self):
        """Test that '*' in allowed allows all tools."""
        resolver = ToolPolicyResolver()
        policy = ToolPolicy(
            source="root",
            precedence=100,
            allowed=frozenset({"*"}),
            denied=frozenset(),
        )
        resolver.register_policy(policy)

        assert resolver.is_allowed("any_tool") is True
        assert resolver.is_allowed("another") is True
        assert resolver.is_allowed("xyz") is True

    def test_higher_precedence_deny_overrides_lower_allow(self):
        """Test that higher precedence deny wins over lower allow."""
        resolver = ToolPolicyResolver()

        lower_policy = ToolPolicy(
            source="layer1",
            precedence=1,
            allowed=frozenset({"tool1", "tool2"}),
            denied=frozenset(),
        )

        higher_policy = ToolPolicy(
            source="layer2",
            precedence=10,
            allowed=None,
            denied=frozenset({"tool1"}),
        )

        resolver.register_policy(lower_policy)
        resolver.register_policy(higher_policy)

        assert resolver.is_allowed("tool2") is True
        assert resolver.is_allowed("tool1") is False

    def test_higher_precedence_restriction_overrides_lower_unrestricted(self):
        """Test that higher precedence allowed restriction overrides lower unrestricted."""
        resolver = ToolPolicyResolver()

        lower_policy = ToolPolicy(
            source="permissive",
            precedence=1,
            allowed=None,
            denied=frozenset(),
        )

        higher_policy = ToolPolicy(
            source="restrictive",
            precedence=10,
            allowed=frozenset({"tool1", "tool2"}),
            denied=frozenset(),
        )

        resolver.register_policy(lower_policy)
        resolver.register_policy(higher_policy)

        assert resolver.is_allowed("tool1") is True
        assert resolver.is_allowed("tool2") is True
        assert resolver.is_allowed("tool3") is False

    def test_filter_tools_removes_denied(self):
        """Test that filter_tools returns only allowed tool names."""
        resolver = ToolPolicyResolver()
        policy = ToolPolicy(
            source="security",
            precedence=5,
            allowed=frozenset({"read", "write"}),
            denied=frozenset(),
        )
        resolver.register_policy(policy)

        tools = ["read", "write", "delete", "admin"]
        result = resolver.filter_tools(tools)

        assert result == ["read", "write"]

    def test_filter_tools_preserves_order(self):
        """Test that filter_tools preserves original order."""
        resolver = ToolPolicyResolver()
        policy = ToolPolicy(
            source="allowed",
            precedence=1,
            allowed=frozenset({"d", "c", "b", "a"}),
            denied=frozenset(),
        )
        resolver.register_policy(policy)

        tools = ["d", "b", "c", "a"]
        result = resolver.filter_tools(tools)

        assert result == ["d", "b", "c", "a"]

    def test_filter_tools_empty_input(self):
        """Test that filter_tools handles empty list."""
        resolver = ToolPolicyResolver()
        policy = ToolPolicy(
            source="any",
            precedence=1,
            allowed=frozenset({"a"}),
            denied=frozenset(),
        )
        resolver.register_policy(policy)

        result = resolver.filter_tools([])

        assert result == []

    def test_get_denial_reason_returns_source_for_explicit_denial(self):
        """Test that denial reason includes policy source name for explicit denial."""
        resolver = ToolPolicyResolver()
        policy = ToolPolicy(
            source="firewall",
            precedence=10,
            allowed=None,
            denied=frozenset({"hack_tool"}),
        )
        resolver.register_policy(policy)

        reason = resolver.get_denial_reason("hack_tool")

        assert reason is not None
        assert "firewall" in reason
        assert "Denied by" in reason

    def test_get_denial_reason_returns_source_for_restriction(self):
        """Test that denial reason includes policy source for allowed restriction."""
        resolver = ToolPolicyResolver()
        policy = ToolPolicy(
            source="whitelist_policy",
            precedence=5,
            allowed=frozenset({"tool1"}),
            denied=frozenset(),
        )
        resolver.register_policy(policy)

        reason = resolver.get_denial_reason("tool2")

        assert reason is not None
        assert "whitelist_policy" in reason
        assert "Not allowed by" in reason

    def test_get_denial_reason_returns_none_if_allowed(self):
        """Test that allowed tool returns None for denial reason."""
        resolver = ToolPolicyResolver()
        policy = ToolPolicy(
            source="any",
            precedence=1,
            allowed=frozenset({"safe_tool"}),
            denied=frozenset(),
        )
        resolver.register_policy(policy)

        reason = resolver.get_denial_reason("safe_tool")

        assert reason is None

    def test_get_denial_reason_no_policies(self):
        """Test that no policies means tool is allowed (reason is None)."""
        resolver = ToolPolicyResolver()

        reason = resolver.get_denial_reason("any_tool")

        assert reason is None

    def test_multiple_policies_combined(self):
        """Test register multiple policies, verify combined behavior."""
        resolver = ToolPolicyResolver()

        policy1 = ToolPolicy(
            source="layer1",
            precedence=1,
            allowed=frozenset({"a", "b", "c"}),
            denied=frozenset(),
        )

        policy2 = ToolPolicy(
            source="layer2",
            precedence=5,
            allowed=None,
            denied=frozenset({"b"}),
        )

        policy3 = ToolPolicy(
            source="layer3",
            precedence=3,
            allowed=frozenset({"a", "b", "c", "d"}),
            denied=frozenset(),
        )

        resolver.register_policy(policy1)
        resolver.register_policy(policy2)
        resolver.register_policy(policy3)

        assert resolver.is_allowed("a") is True
        assert resolver.is_allowed("b") is False
        assert resolver.is_allowed("c") is True
        assert resolver.is_allowed("d") is False

    def test_precedence_ordering(self):
        """Test that policies are evaluated highest precedence first."""
        resolver = ToolPolicyResolver()

        policy_low = ToolPolicy(
            source="low",
            precedence=1,
            allowed=None,
            denied=frozenset(),
        )

        policy_high = ToolPolicy(
            source="high",
            precedence=10,
            allowed=frozenset({"some_tool", "other_tool"}),
            denied=frozenset(),
        )

        resolver.register_policy(policy_low)
        resolver.register_policy(policy_high)

        assert resolver.is_allowed("some_tool") is True
        assert resolver.is_allowed("other_tool") is True
        assert resolver.is_allowed("unlisted_tool") is False

    def test_denied_with_allowed_restriction(self):
        """Test that denied takes precedence over allowed restriction."""
        resolver = ToolPolicyResolver()

        policy = ToolPolicy(
            source="security",
            precedence=1,
            allowed=frozenset({"tool1", "tool2"}),
            denied=frozenset({"tool1"}),
        )

        resolver.register_policy(policy)

        assert resolver.is_allowed("tool1") is False
        assert resolver.is_allowed("tool2") is True

    def test_register_policy_maintains_precedence_order(self):
        """Test that policies are sorted by precedence after registration."""
        resolver = ToolPolicyResolver()

        policy_low = ToolPolicy("low", 1, None, frozenset())
        policy_mid = ToolPolicy("mid", 5, None, frozenset())
        policy_high = ToolPolicy("high", 10, None, frozenset())

        resolver.register_policy(policy_low)
        resolver.register_policy(policy_high)
        resolver.register_policy(policy_mid)

        assert resolver._policies[0].source == "high"
        assert resolver._policies[1].source == "mid"
        assert resolver._policies[2].source == "low"

    def test_get_denial_reason_uses_highest_precedence_first(self):
        """Test that denial reason comes from highest precedence policy that denies."""
        resolver = ToolPolicyResolver()

        policy_low = ToolPolicy(
            source="lowest",
            precedence=1,
            allowed=frozenset(),
            denied=frozenset({"tool"}),
        )

        policy_high = ToolPolicy(
            source="highest",
            precedence=10,
            allowed=None,
            denied=frozenset({"tool"}),
        )

        resolver.register_policy(policy_low)
        resolver.register_policy(policy_high)

        reason = resolver.get_denial_reason("tool")

        assert "highest" in reason

    def test_empty_allowed_set(self):
        """Test that empty allowed set denies all tools."""
        resolver = ToolPolicyResolver()

        policy = ToolPolicy(
            source="strict",
            precedence=1,
            allowed=frozenset(),
            denied=frozenset(),
        )

        resolver.register_policy(policy)

        assert resolver.is_allowed("any_tool") is False
        assert resolver.is_allowed("another") is False

    def test_only_allowed_none_permits_everything(self):
        """Test that only allowed=None with no denial permits everything."""
        resolver = ToolPolicyResolver()

        policy = ToolPolicy(
            source="permissive",
            precedence=1,
            allowed=None,
            denied=frozenset(),
        )

        resolver.register_policy(policy)

        assert resolver.is_allowed("tool1") is True
        assert resolver.is_allowed("tool2") is True
        assert resolver.is_allowed("anything") is True

    def test_complex_scenario_multiple_layers(self):
        """Test complex scenario with multiple overlapping policies."""
        resolver = ToolPolicyResolver()

        sandbox_policy = ToolPolicy(
            source="sandbox",
            precedence=10,
            allowed=frozenset({"read", "write", "execute", "network"}),
            denied=frozenset({"delete_database"}),
        )

        agent_policy = ToolPolicy(
            source="agent",
            precedence=20,
            allowed=frozenset({"read", "write", "execute"}),
            denied=frozenset(),
        )

        subagent_policy = ToolPolicy(
            source="subagent",
            precedence=30,
            allowed=frozenset({"read"}),
            denied=frozenset(),
        )

        resolver.register_policy(sandbox_policy)
        resolver.register_policy(agent_policy)
        resolver.register_policy(subagent_policy)

        assert resolver.is_allowed("read") is True
        assert resolver.is_allowed("write") is False
        assert resolver.is_allowed("execute") is False
        assert resolver.is_allowed("network") is False
        assert resolver.is_allowed("delete_database") is False
