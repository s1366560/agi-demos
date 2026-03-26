"""Tests for agent role definitions and resolver."""

import pytest

from src.domain.model.agent.agent_role import (
    ROLE_DEFAULTS,
    AgentRole,
    AgentRoleResolver,
    RoleCapabilities,
)


@pytest.mark.unit
class TestAgentRole:
    """AgentRole enum tests."""

    def test_main_role_value(self):
        assert AgentRole.MAIN.value == "main"

    def test_orchestrator_role_value(self):
        assert AgentRole.ORCHESTRATOR.value == "orchestrator"

    def test_leaf_role_value(self):
        assert AgentRole.LEAF.value == "leaf"

    def test_main_role_is_string(self):
        assert isinstance(AgentRole.MAIN, str)

    def test_orchestrator_role_is_string(self):
        assert isinstance(AgentRole.ORCHESTRATOR, str)

    def test_leaf_role_is_string(self):
        assert isinstance(AgentRole.LEAF, str)

    def test_all_roles_are_enum_members(self):
        roles = [AgentRole.MAIN, AgentRole.ORCHESTRATOR, AgentRole.LEAF]
        assert len(roles) == 3

    def test_roles_equality_by_value(self):
        assert AgentRole.MAIN == "main"
        assert AgentRole.ORCHESTRATOR == "orchestrator"
        assert AgentRole.LEAF == "leaf"


@pytest.mark.unit
class TestRoleCapabilities:
    """RoleCapabilities value object tests."""

    def test_role_capabilities_is_frozen(self):
        role_capabilities = RoleCapabilities(
            can_spawn=True,
            can_control_children=True,
            can_control_siblings=False,
            max_concurrent_children=8,
            denied_tools=frozenset(),
        )

        with pytest.raises(AttributeError):
            role_capabilities.can_spawn = False  # type: ignore

    def test_role_capabilities_has_all_fields(self):
        capabilities = RoleCapabilities(
            can_spawn=True,
            can_control_children=False,
            can_control_siblings=True,
            max_concurrent_children=5,
            denied_tools=frozenset({"tool1", "tool2"}),
        )

        assert capabilities.can_spawn is True
        assert capabilities.can_control_children is False
        assert capabilities.can_control_siblings is True
        assert capabilities.max_concurrent_children == 5
        assert capabilities.denied_tools == frozenset({"tool1", "tool2"})

    def test_role_capabilities_with_empty_denied_tools(self):
        capabilities = RoleCapabilities(
            can_spawn=True,
            can_control_children=True,
            can_control_siblings=False,
            max_concurrent_children=8,
            denied_tools=frozenset(),
        )

        assert capabilities.denied_tools == frozenset()
        assert len(capabilities.denied_tools) == 0

    def test_role_capabilities_equality(self):
        cap1 = RoleCapabilities(
            can_spawn=True,
            can_control_children=True,
            can_control_siblings=False,
            max_concurrent_children=8,
            denied_tools=frozenset(),
        )
        cap2 = RoleCapabilities(
            can_spawn=True,
            can_control_children=True,
            can_control_siblings=False,
            max_concurrent_children=8,
            denied_tools=frozenset(),
        )

        assert cap1 == cap2


@pytest.mark.unit
class TestRoleDefaults:
    """ROLE_DEFAULTS tests."""

    def test_main_role_can_spawn(self):
        assert ROLE_DEFAULTS[AgentRole.MAIN].can_spawn is True

    def test_main_role_can_control_children(self):
        assert ROLE_DEFAULTS[AgentRole.MAIN].can_control_children is True

    def test_main_role_cannot_control_siblings(self):
        assert ROLE_DEFAULTS[AgentRole.MAIN].can_control_siblings is False

    def test_main_role_max_concurrent_children(self):
        assert ROLE_DEFAULTS[AgentRole.MAIN].max_concurrent_children == 8

    def test_main_role_denied_tools_empty(self):
        assert ROLE_DEFAULTS[AgentRole.MAIN].denied_tools == frozenset()

    def test_orchestrator_role_can_spawn(self):
        assert ROLE_DEFAULTS[AgentRole.ORCHESTRATOR].can_spawn is True

    def test_orchestrator_role_can_control_children(self):
        assert ROLE_DEFAULTS[AgentRole.ORCHESTRATOR].can_control_children is True

    def test_orchestrator_role_cannot_control_siblings(self):
        assert ROLE_DEFAULTS[AgentRole.ORCHESTRATOR].can_control_siblings is False

    def test_orchestrator_role_max_concurrent_children(self):
        assert ROLE_DEFAULTS[AgentRole.ORCHESTRATOR].max_concurrent_children == 5

    def test_orchestrator_role_denied_tools_empty(self):
        assert ROLE_DEFAULTS[AgentRole.ORCHESTRATOR].denied_tools == frozenset()

    def test_leaf_role_cannot_spawn(self):
        assert ROLE_DEFAULTS[AgentRole.LEAF].can_spawn is False

    def test_leaf_role_cannot_control_children(self):
        assert ROLE_DEFAULTS[AgentRole.LEAF].can_control_children is False

    def test_leaf_role_cannot_control_siblings(self):
        assert ROLE_DEFAULTS[AgentRole.LEAF].can_control_siblings is False

    def test_leaf_role_max_concurrent_children(self):
        assert ROLE_DEFAULTS[AgentRole.LEAF].max_concurrent_children == 0

    def test_leaf_role_denied_tools_contains_spawn_agent(self):
        assert "spawn_agent" in ROLE_DEFAULTS[AgentRole.LEAF].denied_tools

    def test_leaf_role_denied_tools_contains_delegate_to_subagent(self):
        assert "delegate_to_subagent" in ROLE_DEFAULTS[AgentRole.LEAF].denied_tools

    def test_leaf_role_denied_tools_exact(self):
        expected = frozenset({"spawn_agent", "delegate_to_subagent"})
        assert ROLE_DEFAULTS[AgentRole.LEAF].denied_tools == expected

    def test_all_roles_have_defaults(self):
        assert AgentRole.MAIN in ROLE_DEFAULTS
        assert AgentRole.ORCHESTRATOR in ROLE_DEFAULTS
        assert AgentRole.LEAF in ROLE_DEFAULTS


@pytest.mark.unit
class TestAgentRoleResolver:
    """AgentRoleResolver tests."""

    def test_depth_zero_returns_main(self):
        result = AgentRoleResolver.resolve(depth=0, max_depth=5)
        assert result is AgentRole.MAIN

    def test_depth_between_zero_and_max_depth_returns_orchestrator(self):
        result = AgentRoleResolver.resolve(depth=2, max_depth=5)
        assert result is AgentRole.ORCHESTRATOR

    def test_depth_equal_to_max_depth_returns_leaf(self):
        result = AgentRoleResolver.resolve(depth=5, max_depth=5)
        assert result is AgentRole.LEAF

    def test_depth_greater_than_max_depth_returns_leaf(self):
        result = AgentRoleResolver.resolve(depth=10, max_depth=5)
        assert result is AgentRole.LEAF

    def test_negative_depth_raises_value_error(self):
        with pytest.raises(ValueError, match="Agent depth cannot be negative"):
            _ = AgentRoleResolver.resolve(depth=-1, max_depth=5)

    def test_max_depth_less_than_one_raises_value_error(self):
        with pytest.raises(ValueError, match="Max depth must be at least 1"):
            _ = AgentRoleResolver.resolve(depth=0, max_depth=0)

    def test_max_depth_zero_raises_value_error(self):
        with pytest.raises(ValueError, match="Max depth must be at least 1"):
            _ = AgentRoleResolver.resolve(depth=1, max_depth=0)

    def test_boundary_depth_one_less_than_max_returns_orchestrator(self):
        result = AgentRoleResolver.resolve(depth=4, max_depth=5)
        assert result is AgentRole.ORCHESTRATOR

    def test_boundary_depth_equals_max_returns_leaf(self):
        result = AgentRoleResolver.resolve(depth=5, max_depth=5)
        assert result is AgentRole.LEAF

    def test_max_depth_one_with_depth_zero_returns_main(self):
        result = AgentRoleResolver.resolve(depth=0, max_depth=1)
        assert result is AgentRole.MAIN

    def test_max_depth_one_with_depth_one_returns_leaf(self):
        result = AgentRoleResolver.resolve(depth=1, max_depth=1)
        assert result is AgentRole.LEAF

    def test_max_depth_one_with_depth_greater_than_one_returns_leaf(self):
        result = AgentRoleResolver.resolve(depth=2, max_depth=1)
        assert result is AgentRole.LEAF

    def test_large_max_depth(self):
        result = AgentRoleResolver.resolve(depth=50, max_depth=100)
        assert result is AgentRole.ORCHESTRATOR

    def test_depth_one_with_max_depth_ten_returns_orchestrator(self):
        result = AgentRoleResolver.resolve(depth=1, max_depth=10)
        assert result is AgentRole.ORCHESTRATOR
