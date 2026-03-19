"""Unit tests for tool policy debug service."""

import pytest

from src.application.services.tool_policy_debug_service import (
    PolicySummary,
    ToolPolicyDebugService,
)
from src.domain.model.agent.agent_role import AgentRole
from src.domain.model.agent.sandbox_scope import SandboxScope


@pytest.mark.unit
class TestToolPolicyDebugService:
    """Test suite for ToolPolicyDebugService."""

    def test_build_resolver_returns_resolver_with_three_policies(self):
        """Test that build_resolver creates a resolver with 3 layers."""
        resolver = ToolPolicyDebugService.build_resolver(
            role=AgentRole.MAIN,
            sandbox_scope=SandboxScope.SESSION,
        )

        assert len(resolver.policies) == 3

    def test_build_resolver_policies_in_precedence_order(self):
        """Test that policies are ordered by precedence (30, 20, 10)."""
        resolver = ToolPolicyDebugService.build_resolver(
            role=AgentRole.MAIN,
            sandbox_scope=SandboxScope.SESSION,
        )

        policies = resolver.policies
        assert policies[0].precedence == 30
        assert policies[1].precedence == 20
        assert policies[2].precedence == 10

    def test_build_resolver_with_sandbox_allowed_tools(self):
        """Test that sandbox_allowed_tools are included in resolver."""
        sandbox_allowed = frozenset({"tool1", "tool2"})
        resolver = ToolPolicyDebugService.build_resolver(
            role=AgentRole.MAIN,
            sandbox_scope=SandboxScope.SESSION,
            sandbox_allowed_tools=sandbox_allowed,
        )

        policies = resolver.policies
        assert policies[0].allowed == sandbox_allowed

    def test_build_resolver_with_sandbox_denied_tools(self):
        """Test that sandbox_denied_tools are included in resolver."""
        sandbox_denied = frozenset({"bad_tool"})
        resolver = ToolPolicyDebugService.build_resolver(
            role=AgentRole.MAIN,
            sandbox_scope=SandboxScope.SESSION,
            sandbox_denied_tools=sandbox_denied,
        )

        policies = resolver.policies
        assert policies[0].denied == sandbox_denied

    def test_build_resolver_with_agent_allowed_tools(self):
        """Test that agent_allowed_tools are included in resolver."""
        agent_allowed = frozenset({"read", "write"})
        resolver = ToolPolicyDebugService.build_resolver(
            role=AgentRole.MAIN,
            sandbox_scope=SandboxScope.SESSION,
            agent_allowed_tools=agent_allowed,
        )

        policies = resolver.policies
        assert policies[1].allowed == agent_allowed

    def test_build_resolver_with_agent_denied_tools(self):
        """Test that agent_denied_tools are included in resolver."""
        agent_denied = frozenset({"delete"})
        resolver = ToolPolicyDebugService.build_resolver(
            role=AgentRole.MAIN,
            sandbox_scope=SandboxScope.SESSION,
            agent_denied_tools=agent_denied,
        )

        policies = resolver.policies
        assert policies[1].denied == agent_denied

    def test_evaluate_main_role_allows_all_tools(self):
        """Test that MAIN role allows all standard tools."""
        result = ToolPolicyDebugService.evaluate(
            tool_names=["tool1", "tool2", "tool3"],
            depth=0,
            max_depth=3,
            sandbox_scope=SandboxScope.SESSION,
        )

        assert result.role == AgentRole.MAIN
        assert all(report.allowed for report in result.tool_reports)
        assert result.denied_count == 0

    def test_evaluate_orchestrator_role_allows_all_tools(self):
        """Test that ORCHESTRATOR role allows all standard tools."""
        result = ToolPolicyDebugService.evaluate(
            tool_names=["tool1", "tool2", "tool3"],
            depth=1,
            max_depth=3,
            sandbox_scope=SandboxScope.SESSION,
        )

        assert result.role == AgentRole.ORCHESTRATOR
        assert all(report.allowed for report in result.tool_reports)
        assert result.denied_count == 0

    def test_evaluate_leaf_role_denies_spawn_tools(self):
        """Test that LEAF role denies spawn_agent and delegate_to_subagent."""
        result = ToolPolicyDebugService.evaluate(
            tool_names=["spawn_agent", "delegate_to_subagent", "normal_tool"],
            depth=3,
            max_depth=3,
            sandbox_scope=SandboxScope.SESSION,
        )

        assert result.role == AgentRole.LEAF

        reports = {r.tool_name: r for r in result.tool_reports}
        assert reports["spawn_agent"].allowed is False
        assert reports["delegate_to_subagent"].allowed is False
        assert reports["normal_tool"].allowed is True

    def test_evaluate_with_sandbox_allowed_restriction(self):
        """Test that sandbox_allowed_tools restricts tool access."""
        result = ToolPolicyDebugService.evaluate(
            tool_names=["tool1", "tool2", "tool3"],
            depth=0,
            max_depth=3,
            sandbox_scope=SandboxScope.SESSION,
            sandbox_allowed_tools=frozenset({"tool1", "tool2"}),
        )

        reports = {r.tool_name: r for r in result.tool_reports}
        assert reports["tool1"].allowed is True
        assert reports["tool2"].allowed is True
        assert reports["tool3"].allowed is False

    def test_evaluate_with_sandbox_denied_restriction(self):
        """Test that sandbox_denied_tools denies specific tools."""
        result = ToolPolicyDebugService.evaluate(
            tool_names=["tool1", "tool2", "tool3"],
            depth=0,
            max_depth=3,
            sandbox_scope=SandboxScope.SESSION,
            sandbox_denied_tools=frozenset({"tool2"}),
        )

        reports = {r.tool_name: r for r in result.tool_reports}
        assert reports["tool1"].allowed is True
        assert reports["tool2"].allowed is False
        assert reports["tool3"].allowed is True

    def test_evaluate_with_agent_denied_restriction(self):
        """Test that agent_denied_tools denies specific tools."""
        result = ToolPolicyDebugService.evaluate(
            tool_names=["read", "write", "delete"],
            depth=0,
            max_depth=3,
            sandbox_scope=SandboxScope.SESSION,
            agent_denied_tools=frozenset({"delete"}),
        )

        reports = {r.tool_name: r for r in result.tool_reports}
        assert reports["read"].allowed is True
        assert reports["write"].allowed is True
        assert reports["delete"].allowed is False

    def test_evaluate_combined_restrictions(self):
        """Test that combined restrictions work correctly."""
        result = ToolPolicyDebugService.evaluate(
            tool_names=["tool1", "tool2", "tool3", "tool4"],
            depth=0,
            max_depth=3,
            sandbox_scope=SandboxScope.SESSION,
            sandbox_allowed_tools=frozenset({"tool1", "tool2", "tool3"}),
            agent_denied_tools=frozenset({"tool2"}),
        )

        reports = {r.tool_name: r for r in result.tool_reports}
        assert reports["tool1"].allowed is True
        assert reports["tool2"].allowed is False
        assert reports["tool3"].allowed is True
        assert reports["tool4"].allowed is False

    def test_evaluate_counts_correctness(self):
        """Test that counts are correct."""
        result = ToolPolicyDebugService.evaluate(
            tool_names=["tool1", "tool2", "tool3", "tool4"],
            depth=0,
            max_depth=3,
            sandbox_scope=SandboxScope.SESSION,
            sandbox_allowed_tools=frozenset({"tool1", "tool2"}),
        )

        assert result.total_tools == 4
        assert result.allowed_count == 2
        assert result.denied_count == 2

    def test_evaluate_result_role_correct(self):
        """Test that result includes correct role."""
        result = ToolPolicyDebugService.evaluate(
            tool_names=["tool1"],
            depth=1,
            max_depth=3,
            sandbox_scope=SandboxScope.SESSION,
        )

        assert result.role == AgentRole.ORCHESTRATOR

    def test_evaluate_result_sandbox_scope_correct(self):
        """Test that result includes correct sandbox scope."""
        result = ToolPolicyDebugService.evaluate(
            tool_names=["tool1"],
            depth=0,
            max_depth=3,
            sandbox_scope=SandboxScope.SHARED,
        )

        assert result.sandbox_scope == SandboxScope.SHARED

    def test_evaluate_result_policies_list_correct(self):
        """Test that result includes all 3 policies as summaries."""
        result = ToolPolicyDebugService.evaluate(
            tool_names=["tool1"],
            depth=0,
            max_depth=3,
            sandbox_scope=SandboxScope.SESSION,
        )

        assert len(result.policies) == 3
        assert all(isinstance(p, PolicySummary) for p in result.policies)

    def test_evaluate_denial_reason_nonempty_for_denied_tools(self):
        """Test that denied tools have non-empty denial_reason."""
        result = ToolPolicyDebugService.evaluate(
            tool_names=["tool1", "tool2"],
            depth=0,
            max_depth=3,
            sandbox_scope=SandboxScope.SESSION,
            sandbox_denied_tools=frozenset({"tool1"}),
        )

        reports = {r.tool_name: r for r in result.tool_reports}
        assert reports["tool1"].denial_reason is not None
        assert len(reports["tool1"].denial_reason) > 0

    def test_evaluate_denial_reason_none_for_allowed_tools(self):
        """Test that allowed tools have None for denial_reason."""
        result = ToolPolicyDebugService.evaluate(
            tool_names=["tool1", "tool2"],
            depth=0,
            max_depth=3,
            sandbox_scope=SandboxScope.SESSION,
        )

        reports = {r.tool_name: r for r in result.tool_reports}
        assert reports["tool1"].denial_reason is None
        assert reports["tool2"].denial_reason is None

    def test_evaluate_empty_tool_names_list(self):
        """Test that empty tool_names list is handled correctly."""
        result = ToolPolicyDebugService.evaluate(
            tool_names=[],
            depth=0,
            max_depth=3,
            sandbox_scope=SandboxScope.SESSION,
        )

        assert result.total_tools == 0
        assert result.allowed_count == 0
        assert result.denied_count == 0
        assert result.tool_reports == []

    def test_evaluate_depth_equals_max_depth_is_leaf(self):
        """Test that depth == max_depth resolves to LEAF role."""
        result = ToolPolicyDebugService.evaluate(
            tool_names=["spawn_agent"],
            depth=5,
            max_depth=5,
            sandbox_scope=SandboxScope.SESSION,
        )

        assert result.role == AgentRole.LEAF
        assert result.tool_reports[0].allowed is False

    def test_evaluate_tool_reports_maintain_order(self):
        """Test that tool_reports maintain input tool order."""
        tool_names = ["zulu", "alpha", "mike", "bravo"]
        result = ToolPolicyDebugService.evaluate(
            tool_names=tool_names,
            depth=0,
            max_depth=3,
            sandbox_scope=SandboxScope.SESSION,
        )

        reported_names = [r.tool_name for r in result.tool_reports]
        assert reported_names == tool_names

    def test_evaluate_role_capabilities_included(self):
        """Test that result includes role capabilities."""
        result = ToolPolicyDebugService.evaluate(
            tool_names=["tool1"],
            depth=0,
            max_depth=3,
            sandbox_scope=SandboxScope.SESSION,
        )

        assert result.role_capabilities is not None
        assert result.role_capabilities.can_spawn is True
        assert result.role_capabilities.denied_tools == frozenset()

    def test_evaluate_leaf_role_capabilities_correct(self):
        """Test that LEAF role capabilities deny spawn tools."""
        result = ToolPolicyDebugService.evaluate(
            tool_names=["tool1"],
            depth=5,
            max_depth=5,
            sandbox_scope=SandboxScope.SESSION,
        )

        assert result.role_capabilities.can_spawn is False
        assert "spawn_agent" in result.role_capabilities.denied_tools
        assert "delegate_to_subagent" in result.role_capabilities.denied_tools

    def test_evaluate_sandbox_scope_session_with_leaf_role(self):
        """Test sandbox scope SESSION works correctly with LEAF role."""
        result = ToolPolicyDebugService.evaluate(
            tool_names=["tool1"],
            depth=10,
            max_depth=5,
            sandbox_scope=SandboxScope.SESSION,
        )

        assert result.sandbox_scope == SandboxScope.SESSION
        assert result.role == AgentRole.LEAF
