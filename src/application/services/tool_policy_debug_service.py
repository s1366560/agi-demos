"""Tool policy debug service for diagnosing tool access control decisions.

Provides diagnostic capabilities to answer "why was this tool denied?" by
building the multi-layer policy chain for a given agent context and reporting
per-tool denial reasons.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.application.services.tool_policy_resolver import ToolPolicy, ToolPolicyResolver
from src.domain.model.agent.agent_role import (
    ROLE_DEFAULTS,
    AgentRole,
    AgentRoleResolver,
    RoleCapabilities,
)
from src.domain.model.agent.sandbox_scope import SandboxScope


@dataclass(frozen=True)
class ToolPolicyReport:
    """Immutable report for a single tool's policy evaluation.

    Attributes:
        tool_name: Name of the tool evaluated.
        allowed: Whether the tool is allowed.
        denial_reason: Human-readable denial reason, None if allowed.
    """

    tool_name: str
    allowed: bool
    denial_reason: str | None


@dataclass(frozen=True)
class PolicyDebugResult:
    """Immutable result of a full policy debug evaluation.

    Attributes:
        role: The resolved agent role.
        role_capabilities: Capabilities for the resolved role.
        sandbox_scope: The sandbox scope used.
        policies: List of policies registered in precedence order.
        tool_reports: Per-tool evaluation reports.
        total_tools: Total number of tools evaluated.
        allowed_count: Number of tools allowed.
        denied_count: Number of tools denied.
    """

    role: AgentRole
    role_capabilities: RoleCapabilities
    sandbox_scope: SandboxScope
    policies: list[PolicySummary]
    tool_reports: list[ToolPolicyReport]
    total_tools: int
    allowed_count: int
    denied_count: int


@dataclass(frozen=True)
class PolicySummary:
    """Summary of a registered policy layer.

    Attributes:
        source: Policy source name (e.g. "sandbox", "agent", "subagent").
        precedence: Policy precedence (higher = evaluated first).
        allowed: Set of allowed tools, or None for unrestricted.
        denied: Set of denied tools.
    """

    source: str
    precedence: int
    allowed: frozenset[str] | None
    denied: frozenset[str]


# Standard precedence values for the 3-layer policy chain.
SANDBOX_PRECEDENCE = 30
AGENT_PRECEDENCE = 20
SUBAGENT_PRECEDENCE = 10


class ToolPolicyDebugService:
    """Service for diagnosing tool access control decisions.

    Builds the 3-layer policy chain (sandbox -> agent -> subagent) based on
    agent context and evaluates each tool to report allow/deny status with
    human-readable reasons.

    This is a stateless service with no infrastructure dependencies.
    """

    @staticmethod
    def build_resolver(
        role: AgentRole,
        sandbox_scope: SandboxScope,
        sandbox_allowed_tools: frozenset[str] | None = None,
        sandbox_denied_tools: frozenset[str] | None = None,
        agent_allowed_tools: frozenset[str] | None = None,
        agent_denied_tools: frozenset[str] | None = None,
    ) -> ToolPolicyResolver:
        """Build a ToolPolicyResolver with the 3-layer policy chain.

        Layer 1 (highest precedence): Sandbox policy — restricts tools based
            on sandbox configuration.
        Layer 2: Agent policy — restricts tools based on agent-level config.
        Layer 3 (lowest precedence): SubAgent/role policy — restricts tools
            based on the agent's role (e.g. LEAF cannot spawn).

        Args:
            role: The resolved agent role.
            sandbox_scope: The sandbox scope in effect.
            sandbox_allowed_tools: Tools allowed by sandbox, None = no restriction.
            sandbox_denied_tools: Tools denied by sandbox.
            agent_allowed_tools: Tools allowed by agent config, None = no restriction.
            agent_denied_tools: Tools denied by agent config.

        Returns:
            Configured ToolPolicyResolver with all layers registered.
        """
        resolver = ToolPolicyResolver()
        capabilities = ROLE_DEFAULTS.get(role, ROLE_DEFAULTS[AgentRole.LEAF])

        # Layer 1: Sandbox policy (highest precedence)
        resolver.register_policy(
            ToolPolicy(
                source=f"sandbox({sandbox_scope.value})",
                precedence=SANDBOX_PRECEDENCE,
                allowed=sandbox_allowed_tools,
                denied=sandbox_denied_tools or frozenset(),
            )
        )

        # Layer 2: Agent policy
        resolver.register_policy(
            ToolPolicy(
                source="agent",
                precedence=AGENT_PRECEDENCE,
                allowed=agent_allowed_tools,
                denied=agent_denied_tools or frozenset(),
            )
        )

        # Layer 3: Role-based policy (lowest precedence)
        resolver.register_policy(
            ToolPolicy(
                source=f"role({role.value})",
                precedence=SUBAGENT_PRECEDENCE,
                allowed=None,  # Role policy only denies, never restricts allowed set
                denied=capabilities.denied_tools,
            )
        )

        return resolver

    @staticmethod
    def evaluate(
        tool_names: list[str],
        depth: int,
        max_depth: int,
        sandbox_scope: SandboxScope = SandboxScope.AGENT,
        sandbox_allowed_tools: frozenset[str] | None = None,
        sandbox_denied_tools: frozenset[str] | None = None,
        agent_allowed_tools: frozenset[str] | None = None,
        agent_denied_tools: frozenset[str] | None = None,
    ) -> PolicyDebugResult:
        """Evaluate tool access for a given agent context.

        Resolves the agent role from depth, builds the 3-layer policy chain,
        and evaluates each tool.

        Args:
            tool_names: List of tool names to evaluate.
            depth: Agent depth in the hierarchy (0 = root).
            max_depth: Maximum allowed depth.
            sandbox_scope: Sandbox scope in effect.
            sandbox_allowed_tools: Tools allowed by sandbox config.
            sandbox_denied_tools: Tools denied by sandbox config.
            agent_allowed_tools: Tools allowed by agent config.
            agent_denied_tools: Tools denied by agent config.

        Returns:
            PolicyDebugResult with per-tool reports and summary.

        Raises:
            ValueError: If depth or max_depth is invalid.
        """
        role = AgentRoleResolver.resolve(depth, max_depth)
        capabilities = ROLE_DEFAULTS.get(role, ROLE_DEFAULTS[AgentRole.LEAF])

        resolver = ToolPolicyDebugService.build_resolver(
            role=role,
            sandbox_scope=sandbox_scope,
            sandbox_allowed_tools=sandbox_allowed_tools,
            sandbox_denied_tools=sandbox_denied_tools,
            agent_allowed_tools=agent_allowed_tools,
            agent_denied_tools=agent_denied_tools,
        )

        tool_reports: list[ToolPolicyReport] = []
        for tool_name in tool_names:
            allowed = resolver.is_allowed(tool_name)
            denial_reason = resolver.get_denial_reason(tool_name) if not allowed else None
            tool_reports.append(
                ToolPolicyReport(
                    tool_name=tool_name,
                    allowed=allowed,
                    denial_reason=denial_reason,
                )
            )

        allowed_count = sum(1 for r in tool_reports if r.allowed)
        denied_count = len(tool_reports) - allowed_count

        policies = [
            PolicySummary(
                source=p.source,
                precedence=p.precedence,
                allowed=p.allowed,
                denied=p.denied,
            )
            for p in resolver.policies
        ]

        return PolicyDebugResult(
            role=role,
            role_capabilities=capabilities,
            sandbox_scope=sandbox_scope,
            policies=policies,
            tool_reports=tool_reports,
            total_tools=len(tool_reports),
            allowed_count=allowed_count,
            denied_count=denied_count,
        )
