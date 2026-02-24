"""
SubAgent Orchestrator - Coordinates SubAgent routing and execution.

Encapsulates:
- SubAgent matching and routing
- Tool filtering for SubAgents
- Execution configuration management
- Event emission for routing decisions

Extracted from react_agent.py to reduce complexity and improve testability.
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

logger = logging.getLogger(__name__)


# ============================================================================
# Protocol Definitions
# ============================================================================


class SubAgentProtocol(Protocol):
    """Protocol for SubAgent objects."""

    id: str
    name: str
    display_name: str
    enabled: bool
    model: Any  # AgentModel
    temperature: float
    max_tokens: int
    max_iterations: int
    system_prompt: str
    allowed_tools: list[str]
    allowed_skills: list[str]
    allowed_mcp_servers: list[str]

    def record_execution(self, execution_time_ms: int, success: bool) -> None:
        """Record execution statistics."""
        ...


class SubAgentRouterProtocol(Protocol):
    """Protocol for SubAgentRouter."""

    def match(
        self,
        query: str,
        confidence_threshold: float | None = None,
    ) -> Any:  # SubAgentMatch
        """Find the best SubAgent for a query."""
        ...

    def filter_tools(
        self,
        subagent: SubAgentProtocol,
        available_tools: dict[str, Any],
    ) -> dict[str, Any]:
        """Filter tools based on SubAgent permissions."""
        ...

    def get_subagent_config(self, subagent: SubAgentProtocol) -> dict[str, Any]:
        """Get configuration for running a SubAgent."""
        ...

    def list_subagents(self) -> list[SubAgentProtocol]:
        """List all enabled SubAgents."""
        ...


class SubAgentExecutorProtocol(Protocol):
    """Protocol for SubAgentExecutor."""

    subagent: SubAgentProtocol

    def get_system_prompt(self) -> str:
        """Get the SubAgent's system prompt."""
        ...

    def get_config(self) -> dict[str, Any]:
        """Get execution configuration."""
        ...

    def record_execution(self, execution_time_ms: int, success: bool) -> None:
        """Record execution statistics."""
        ...


# ============================================================================
# Data Classes
# ============================================================================


@dataclass
class SubAgentRoutingResult:
    """Result of SubAgent routing."""

    subagent: SubAgentProtocol | None = None
    confidence: float = 0.0
    match_reason: str = "No match"
    routed: bool = False

    @property
    def matched(self) -> bool:
        """Check if a SubAgent was matched."""
        return self.subagent is not None and self.routed


@dataclass
class SubAgentExecutionConfig:
    """Configuration for SubAgent execution."""

    model: str | None = None
    temperature: float = 0.7
    max_tokens: int = 4096
    max_iterations: int = 20
    system_prompt: str = ""
    allowed_tools: list[str] = field(default_factory=list)
    allowed_skills: list[str] = field(default_factory=list)
    allowed_mcp_servers: list[str] = field(default_factory=list)


@dataclass
class SubAgentOrchestratorConfig:
    """Configuration for SubAgent orchestration."""

    default_confidence_threshold: float = 0.5
    emit_routing_events: bool = True


# ============================================================================
# SubAgent Orchestrator
# ============================================================================


class SubAgentOrchestrator:
    """
    Orchestrates SubAgent routing and execution.

    Responsibilities:
    - Match queries against available SubAgents
    - Filter tools based on SubAgent permissions
    - Build execution configuration
    - Emit routing events
    - Track execution statistics
    """

    def __init__(
        self,
        router: SubAgentRouterProtocol | None = None,
        config: SubAgentOrchestratorConfig | None = None,
        base_model: str = "gpt-4",
        base_api_key: str | None = None,
        base_url: str | None = None,
        debug_logging: bool = False,
    ) -> None:
        """
        Initialize SubAgent orchestrator.

        Args:
            router: SubAgentRouter instance
            config: Orchestration configuration
            base_model: Base model for inheritance
            base_api_key: Base API key
            base_url: Base API URL
            debug_logging: Enable verbose logging
        """
        self._router = router
        self._config = config or SubAgentOrchestratorConfig()
        self._base_model = base_model
        self._base_api_key = base_api_key
        self._base_url = base_url
        self._debug_logging = debug_logging

    @property
    def has_router(self) -> bool:
        """Check if router is available."""
        return self._router is not None

    @property
    def available_subagents(self) -> list[SubAgentProtocol]:
        """Get list of available SubAgents."""
        if not self._router:
            return []
        return self._router.list_subagents()

    def match(
        self,
        query: str,
        confidence_threshold: float | None = None,
    ) -> SubAgentRoutingResult:
        """
        Match query against available SubAgents.

        Args:
            query: User query to match
            confidence_threshold: Optional custom threshold

        Returns:
            SubAgentRoutingResult with matched SubAgent and confidence
        """
        if self._debug_logging:
            logger.debug(f"[SubAgentOrchestrator] Matching query: {query[:100]}...")

        if not self._router:
            return SubAgentRoutingResult(match_reason="No router configured")

        threshold = confidence_threshold or self._config.default_confidence_threshold

        # Delegate to router
        match = self._router.match(query, threshold)

        if match.subagent:
            logger.info(
                f"[SubAgentOrchestrator] Matched SubAgent: {match.subagent.name} "
                f"(confidence={match.confidence:.3f})"
            )
            return SubAgentRoutingResult(
                subagent=match.subagent,
                confidence=match.confidence,
                match_reason=match.match_reason,
                routed=True,
            )
        else:
            if self._debug_logging:
                logger.debug(
                    f"[SubAgentOrchestrator] No SubAgent matched: {match.match_reason}"
                )
            return SubAgentRoutingResult(
                confidence=match.confidence,
                match_reason=match.match_reason,
                routed=False,
            )

    async def match_async(
        self,
        query: str,
        confidence_threshold: float | None = None,
        conversation_context: str | None = None,
    ) -> SubAgentRoutingResult:
        """Async match with hybrid routing support (keyword + LLM).

        If the router supports async matching (e.g. HybridRouter),
        uses the full hybrid flow. Otherwise falls back to sync match.

        Args:
            query: User query to match.
            confidence_threshold: Optional custom threshold.
            conversation_context: Recent conversation for LLM context.

        Returns:
            SubAgentRoutingResult with matched SubAgent and confidence.
        """
        if not self._router:
            return SubAgentRoutingResult(match_reason="No router configured")

        threshold = confidence_threshold or self._config.default_confidence_threshold

        # Check if router supports async matching (HybridRouter)
        if hasattr(self._router, "match_async"):
            match = await self._router.match_async(
                query, threshold, conversation_context
            )
        else:
            match = self._router.match(query, threshold)

        if match.subagent:
            logger.info(
                f"[SubAgentOrchestrator] Matched SubAgent (async): {match.subagent.name} "
                f"(confidence={match.confidence:.3f})"
            )
            return SubAgentRoutingResult(
                subagent=match.subagent,
                confidence=match.confidence,
                match_reason=match.match_reason,
                routed=True,
            )
        else:
            return SubAgentRoutingResult(
                confidence=match.confidence,
                match_reason=match.match_reason,
                routed=False,
            )

    def filter_tools(
        self,
        subagent: SubAgentProtocol,
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
        if not self._router:
            # If no router, check subagent directly
            if "*" in subagent.allowed_tools:
                return available_tools
            return {
                name: tool
                for name, tool in available_tools.items()
                if name in subagent.allowed_tools
            }

        return self._router.filter_tools(subagent, available_tools)

    def get_execution_config(
        self,
        subagent: SubAgentProtocol,
        override_model: str | None = None,
    ) -> SubAgentExecutionConfig:
        """
        Build execution configuration for a SubAgent.

        Args:
            subagent: SubAgent to configure
            override_model: Optional model override

        Returns:
            SubAgentExecutionConfig with all settings
        """
        # Determine model
        from src.domain.model.agent.subagent import AgentModel

        if hasattr(subagent.model, "value"):
            if subagent.model == AgentModel.INHERIT:
                model = override_model or self._base_model
            else:
                model = subagent.model.value
        else:
            model = str(subagent.model) if subagent.model else self._base_model

        return SubAgentExecutionConfig(
            model=model,
            temperature=subagent.temperature,
            max_tokens=subagent.max_tokens,
            max_iterations=subagent.max_iterations,
            system_prompt=subagent.system_prompt,
            allowed_tools=list(subagent.allowed_tools),
            allowed_skills=list(subagent.allowed_skills),
            allowed_mcp_servers=list(subagent.allowed_mcp_servers),
        )

    def create_routing_event(
        self,
        result: SubAgentRoutingResult,
    ) -> dict[str, Any] | None:
        """
        Create routing event for SSE emission.

        Args:
            result: Routing result

        Returns:
            Event dict or None if routing disabled or no match
        """
        if not self._config.emit_routing_events:
            return None

        if not result.matched:
            return None

        return {
            "type": "subagent_routed",
            "data": {
                "subagent_id": result.subagent.id,
                "subagent_name": result.subagent.display_name,
                "confidence": result.confidence,
                "reason": result.match_reason,
            },
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def record_execution(
        self,
        subagent: SubAgentProtocol,
        execution_time_ms: int,
        success: bool,
    ) -> None:
        """
        Record SubAgent execution statistics.

        Args:
            subagent: Executed SubAgent
            execution_time_ms: Execution time in milliseconds
            success: Whether execution was successful
        """
        try:
            subagent.record_execution(execution_time_ms, success)
            if self._debug_logging:
                logger.debug(
                    f"[SubAgentOrchestrator] Recorded execution for {subagent.name}: "
                    f"time={execution_time_ms}ms, success={success}"
                )
        except Exception as e:
            logger.warning(
                f"[SubAgentOrchestrator] Failed to record execution: {e}"
            )

    def get_subagents_data(self) -> list[dict[str, Any]] | None:
        """
        Get all SubAgents as dict format for prompt context.

        Returns:
            List of SubAgent dicts or None
        """
        subagents = self.available_subagents
        if not subagents:
            return None

        return [
            {
                "id": s.id,
                "name": s.name,
                "display_name": s.display_name,
                "system_prompt_preview": s.system_prompt[:200] + "..."
                if len(s.system_prompt) > 200
                else s.system_prompt,
                "allowed_tools": list(s.allowed_tools)[:10],  # Limit for prompt
            }
            for s in subagents
        ]


# ============================================================================
# Singleton Management
# ============================================================================

_orchestrator: SubAgentOrchestrator | None = None


def get_subagent_orchestrator() -> SubAgentOrchestrator:
    """
    Get singleton SubAgentOrchestrator instance.

    Raises:
        RuntimeError if orchestrator not initialized
    """
    global _orchestrator
    if _orchestrator is None:
        raise RuntimeError(
            "SubAgentOrchestrator not initialized. "
            "Call set_subagent_orchestrator() or create_subagent_orchestrator() first."
        )
    return _orchestrator


def set_subagent_orchestrator(orchestrator: SubAgentOrchestrator) -> None:
    """Set singleton SubAgentOrchestrator instance."""
    global _orchestrator
    _orchestrator = orchestrator


def create_subagent_orchestrator(
    router: SubAgentRouterProtocol | None = None,
    config: SubAgentOrchestratorConfig | None = None,
    base_model: str = "gpt-4",
    base_api_key: str | None = None,
    base_url: str | None = None,
    debug_logging: bool = False,
) -> SubAgentOrchestrator:
    """
    Create and set singleton SubAgentOrchestrator.

    Returns:
        Created SubAgentOrchestrator instance
    """
    global _orchestrator
    _orchestrator = SubAgentOrchestrator(
        router=router,
        config=config,
        base_model=base_model,
        base_api_key=base_api_key,
        base_url=base_url,
        debug_logging=debug_logging,
    )
    return _orchestrator
