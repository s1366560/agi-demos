"""
SubAgent Router - Routes tasks to specialized SubAgents.

SubAgents are specialized agents that handle specific types of tasks with
isolated tool access and custom system prompts.
"""

import logging
from dataclasses import dataclass
from typing import Any

from src.domain.model.agent.subagent import AgentModel, SubAgent

logger = logging.getLogger(__name__)


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
    ) -> None:
        """
        Initialize SubAgent router.

        Args:
            subagents: List of available SubAgents
            default_confidence_threshold: Minimum confidence for routing
        """
        self.subagents = {s.name: s for s in subagents if s.enabled}
        self.default_confidence_threshold = default_confidence_threshold

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

    def match(
        self,
        query: str,
        confidence_threshold: float | None = None,
    ) -> SubAgentMatch:
        """
        Find the best SubAgent for a query.

        Uses keyword matching first, then falls back to description matching.

        Args:
            query: User query or task description
            confidence_threshold: Optional custom threshold

        Returns:
            SubAgentMatch with best match or None
        """
        threshold = confidence_threshold or self.default_confidence_threshold
        query_lower = query.lower()
        query_words = set(query_lower.split())

        # First try keyword matching
        keyword_matches: dict[str, int] = {}  # subagent_name -> match_count

        for word in query_words:
            if word in self._keyword_index:
                for subagent_name in self._keyword_index[word]:
                    keyword_matches[subagent_name] = keyword_matches.get(subagent_name, 0) + 1

        # Calculate confidence based on keyword matches
        if keyword_matches:
            best_match_name = max(keyword_matches.keys(), key=lambda k: keyword_matches[k])
            best_match_count = keyword_matches[best_match_name]

            # Get subagent
            subagent = self.subagents.get(best_match_name)
            if subagent:
                # Calculate confidence (more keywords = higher confidence)
                total_keywords = len(subagent.trigger.keywords)
                if total_keywords > 0:
                    confidence = min(best_match_count / max(total_keywords, 3), 1.0)
                    # Boost confidence if multiple keywords matched
                    confidence = min(confidence + 0.1 * (best_match_count - 1), 0.95)
                else:
                    confidence = 0.6

                if confidence >= threshold:
                    return SubAgentMatch(
                        subagent=subagent,
                        confidence=confidence,
                        match_reason=f"Keyword match: {best_match_count} keywords",
                    )

        # Fallback: simple description matching
        for subagent in self.subagents.values():
            description_lower = subagent.trigger.description.lower()

            # Count word overlaps
            desc_words = set(description_lower.split())
            overlap = query_words & desc_words

            if len(overlap) >= 2:
                confidence = min(len(overlap) / 5, 0.6)  # Cap at 0.6 for description match

                if confidence >= threshold:
                    return SubAgentMatch(
                        subagent=subagent,
                        confidence=confidence,
                        match_reason=f"Description match: {len(overlap)} words",
                    )

        # No match found
        return SubAgentMatch(
            subagent=None,
            confidence=0.0,
            match_reason="No match found",
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
        # If wildcard "*" in allowed_tools, return all tools
        if "*" in subagent.allowed_tools:
            return available_tools

        # Filter to only allowed tools
        return {
            name: tool for name, tool in available_tools.items() if name in subagent.allowed_tools
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

        # Add to router
        self.subagents["explore-agent"] = explore_agent

        # Update keyword index
        for keyword in explore_agent.trigger.keywords:
            keyword_lower = keyword.lower()
            if keyword_lower not in self._keyword_index:
                self._keyword_index[keyword_lower] = []
            if "explore-agent" not in self._keyword_index[keyword_lower]:
                self._keyword_index[keyword_lower].append("explore-agent")

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
