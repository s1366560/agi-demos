"""
SubAgent Router - Routes tasks to specialized SubAgents.

SubAgents are specialized agents that handle specific types of tasks with
isolated tool access and custom system prompts.

Internally uses a ResolverChain (keyword -> description -> ...) so that
resolution strategies are modular and extensible.
"""

import logging
from dataclasses import dataclass
from typing import Any

from src.domain.model.agent.subagent import AgentModel, SubAgent
from src.domain.model.agent.tool_policy import ToolPolicy, ToolPolicyPrecedence

from .resolver import (
    DescriptionResolver,
    KeywordResolver,
    Resolver,
    ResolverChain,
    ResolverResult,
)
from .tool_name_policy import canonical_tool_policy_name, canonical_tool_policy_names

logger = logging.getLogger(__name__)


def _tool_policy_allows(
    policy: ToolPolicy | None,
    tool_name: str,
    known_tool_names: set[str],
) -> bool:
    if policy is None:
        return True

    canonical_name = canonical_tool_policy_name(tool_name, known_tool_names)
    allow = set(canonical_tool_policy_names(policy.allow, known_tool_names))
    deny = set(canonical_tool_policy_names(policy.deny, known_tool_names))
    explicitly_allowed = canonical_name in allow or "*" in allow
    has_allow_restriction = bool(allow) and "*" not in allow

    if policy.precedence == ToolPolicyPrecedence.ALLOW_FIRST:
        if explicitly_allowed:
            return True
        if canonical_name in deny:
            return False
        return not has_allow_restriction

    if canonical_name in deny:
        return False
    return explicitly_allowed or not has_allow_restriction


def subagent_allows_tool(
    subagent: SubAgent,
    tool_name: str,
    known_tool_names: set[str],
) -> bool:
    """Return whether a tool is available under SubAgent legacy and structured policies."""
    if "*" not in subagent.allowed_tools:
        allowed_tools = set(canonical_tool_policy_names(subagent.allowed_tools, known_tool_names))
        if canonical_tool_policy_name(tool_name, known_tool_names) not in allowed_tools:
            return False
    return _tool_policy_allows(subagent.tool_policy, tool_name, known_tool_names)


@dataclass
class SubAgentMatch:
    """Result of SubAgent matching."""

    subagent: SubAgent | None
    confidence: float
    match_reason: str


class SubAgentRouter:
    """
    Routes incoming tasks to appropriate SubAgents.

    Uses keyword matching and semantic similarity to find the best SubAgent
    for a given task.
    """

    def __init__(
        self,
        subagents: list[SubAgent],
        default_confidence_threshold: float = 0.5,
        extra_resolvers: list[Resolver] | None = None,
    ) -> None:
        """
        Initialize SubAgent router.

        Args:
            subagents: List of available SubAgents
            default_confidence_threshold: Minimum confidence for routing
            extra_resolvers: Optional additional resolvers appended after
                the built-in keyword and description resolvers.
        """
        self.subagents = {s.name: s for s in subagents if s.enabled}
        self.default_confidence_threshold = default_confidence_threshold
        self._extra_resolvers = list(extra_resolvers) if extra_resolvers else []

        # Build keyword index for fast matching
        self._keyword_index: dict[str, list[str]] = {}  # keyword -> [subagent_names]
        for subagent in subagents:
            if not subagent.enabled:
                continue
            for keyword in subagent.trigger.keywords:
                keyword_lower = keyword.lower()
                if keyword_lower not in self._keyword_index:
                    self._keyword_index[keyword_lower] = []
                self._keyword_index[keyword_lower].append(subagent.name)

        # Build the resolver chain
        self._resolver_chain = self._build_chain()

    def _build_chain(self) -> ResolverChain:
        """Build the resolver chain from built-in + extra resolvers."""
        resolvers: list[Resolver] = [
            KeywordResolver(self._keyword_index, self.subagents),
            DescriptionResolver(self.subagents),
        ]
        resolvers.extend(self._extra_resolvers)
        return ResolverChain(resolvers)

    @property
    def resolver_chain(self) -> ResolverChain:
        """Access the underlying resolver chain (for plugin extensions)."""
        return self._resolver_chain

    def match(
        self,
        query: str,
        confidence_threshold: float | None = None,
    ) -> SubAgentMatch:
        """
        Find the best SubAgent for a query.

        Delegates to the internal ResolverChain (keyword -> description -> ...).

        Args:
            query: User query or task description
            confidence_threshold: Optional custom threshold

        Returns:
            SubAgentMatch with best match or None
        """
        threshold = confidence_threshold or self.default_confidence_threshold
        result: ResolverResult = self._resolver_chain.resolve(query, threshold)
        return SubAgentMatch(
            subagent=result.subagent,
            confidence=result.confidence,
            match_reason=result.match_reason,
        )

    def get_subagent(self, name: str) -> SubAgent | None:
        """Get SubAgent by name."""
        return self.subagents.get(name)

    def list_subagents(self) -> list[SubAgent]:
        """List all enabled SubAgents."""
        return list(self.subagents.values())

    def get_subagent_config(self, subagent: SubAgent) -> dict[str, Any]:
        """
        Get configuration for running a SubAgent.

        Returns model settings and allowed tools for the SubAgent.

        Args:
            subagent: SubAgent to get config for

        Returns:
            Configuration dictionary
        """
        return {
            "model": subagent.model.value if subagent.model != AgentModel.INHERIT else None,
            "temperature": subagent.temperature,
            "max_tokens": subagent.max_tokens,
            "max_iterations": subagent.max_iterations,
            "system_prompt": subagent.system_prompt,
            "allowed_tools": list(subagent.allowed_tools),
            "allowed_skills": list(subagent.allowed_skills),
            "allowed_mcp_servers": list(subagent.allowed_mcp_servers),
        }

    def filter_tools(
        self,
        subagent: SubAgent,
        available_tools: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Filter tools based on SubAgent permissions.

        Args:
            subagent: SubAgent with tool permissions
            available_tools: All available tools

        Returns:
            Filtered dictionary of allowed tools
        """
        known_tool_names = set(available_tools)
        return {
            name: tool
            for name, tool in available_tools.items()
            if subagent_allows_tool(subagent, name, known_tool_names)
        }

    def get_or_create_explore_agent(
        self,
        tenant_id: str,
        project_id: str | None = None,
    ) -> SubAgent:
        """
        Get or create an explore-agent for Plan Mode.

        This method provides a specialized SubAgent for code exploration
        during Plan Mode. The explore-agent has read-only access and is
        optimized for gathering information about the codebase.

        Args:
            tenant_id: The tenant ID
            project_id: Optional project ID

        Returns:
            An explore SubAgent
        """
        # Check if explore-agent already exists
        explore_agent = self.subagents.get("explore-agent")
        if explore_agent:
            return explore_agent

        # Create a new explore-agent
        from src.infrastructure.agent.core.explore_subagent import create_explore_subagent

        explore_agent = create_explore_subagent(
            tenant_id=tenant_id,
            project_id=project_id,
        )

        # Add to router and rebuild chain
        self.subagents["explore-agent"] = explore_agent

        # Update keyword index
        for keyword in explore_agent.trigger.keywords:
            keyword_lower = keyword.lower()
            if keyword_lower not in self._keyword_index:
                self._keyword_index[keyword_lower] = []
            if "explore-agent" not in self._keyword_index[keyword_lower]:
                self._keyword_index[keyword_lower].append("explore-agent")

        # Rebuild resolver chain so new subagent is visible to all resolvers
        self._resolver_chain = self._build_chain()

        logger.info(f"Created explore-agent for tenant {tenant_id}")

        return explore_agent


class SubAgentExecutor:
    """
    Executes tasks using a specific SubAgent.

    Creates an isolated execution environment with the SubAgent's
    specific configuration and tool access.
    """

    def __init__(
        self,
        subagent: SubAgent,
        base_model: str,
        base_api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        """
        Initialize SubAgent executor.

        Args:
            subagent: SubAgent to execute
            base_model: Base model to use if SubAgent inherits
            base_api_key: Base API key
            base_url: Base API URL
        """
        self.subagent = subagent

        # Determine actual model
        if subagent.model == AgentModel.INHERIT:
            self.model = base_model
        else:
            self.model = subagent.model.value

        self.api_key = base_api_key
        self.base_url = base_url

    def get_system_prompt(self) -> str:
        """Get the SubAgent's system prompt."""
        return self.subagent.system_prompt

    def get_config(self) -> dict[str, Any]:
        """Get execution configuration."""
        return {
            "model": self.model,
            "temperature": self.subagent.temperature,
            "max_tokens": self.subagent.max_tokens,
            "max_iterations": self.subagent.max_iterations,
        }

    def record_execution(
        self,
        execution_time_ms: int,
        success: bool,
    ) -> None:
        """
        Record execution statistics.

        This should be called after SubAgent execution to update stats.

        Args:
            execution_time_ms: Execution time in milliseconds
            success: Whether execution was successful
        """
        self.subagent.record_execution(execution_time_ms, success)
