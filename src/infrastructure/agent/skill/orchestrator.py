"""
Skill Orchestrator - Skill matching and execution coordination.

Encapsulates:
- Skill matching against user queries
- Skill execution mode determination (direct vs inject)
- Skill execution coordination via SkillExecutor
- Event conversion for skill execution progress
- Result summarization

Extracted from react_agent.py to reduce complexity and improve testability.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, AsyncIterator, Dict, List, Optional, Protocol

from src.domain.events.agent_events import (
    AgentDomainEvent,
    AgentEventType,
    AgentSkillExecutionCompleteEvent,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Protocol Definitions
# ============================================================================


class SkillProtocol(Protocol):
    """Protocol for Skill objects."""

    id: str
    name: str
    description: str
    tools: List[str]
    prompt_template: Optional[str]
    status: Any  # SkillStatus

    def is_accessible_by_agent(self, agent_mode: str) -> bool:
        """Check if skill is accessible by agent mode."""
        ...

    def matches_query(self, query: str) -> float:
        """Calculate match score for query."""
        ...

    def record_usage(self, success: bool) -> None:
        """Record skill usage."""
        ...


class SkillExecutorProtocol(Protocol):
    """Protocol for SkillExecutor."""

    async def execute(
        self,
        skill: SkillProtocol,
        query: str,
        context: Dict[str, Any],
        sandbox_id: Optional[str] = None,
    ) -> AsyncIterator[AgentDomainEvent]:
        """Execute skill and yield domain events."""
        ...


class ToolProtocol(Protocol):
    """Protocol for tool definitions."""

    sandbox_id: Optional[str]


# ============================================================================
# Data Classes
# ============================================================================


class SkillExecutionMode(str, Enum):
    """Modes for skill execution."""

    NONE = "none"  # No skill matched
    DIRECT = "direct"  # Execute skill directly without LLM
    INJECT = "inject"  # Inject skill into LLM prompt


@dataclass
class SkillMatchResult:
    """Result of skill matching."""

    skill: Optional[SkillProtocol] = None
    score: float = 0.0
    mode: SkillExecutionMode = SkillExecutionMode.NONE

    @property
    def matched(self) -> bool:
        """Check if a skill was matched."""
        return self.skill is not None and self.mode != SkillExecutionMode.NONE


@dataclass
class SkillExecutionConfig:
    """Configuration for skill execution."""

    match_threshold: float = 0.9  # Threshold for prompt injection
    direct_execute_threshold: float = 0.95  # Threshold for direct execution
    fallback_on_error: bool = True  # Fallback to LLM on skill error
    execution_timeout: int = 300  # Timeout in seconds


@dataclass
class SkillExecutionContext:
    """Context for skill execution."""

    project_id: str
    user_id: str
    tenant_id: str
    query: str
    sandbox_id: Optional[str] = None


@dataclass
class SkillExecutionSummary:
    """Summary of skill execution."""

    skill_id: str
    skill_name: str
    success: bool
    summary: str
    tool_results: List[Dict[str, Any]] = field(default_factory=list)
    execution_time_ms: int = 0
    error: Optional[str] = None


# ============================================================================
# Skill Orchestrator
# ============================================================================


class SkillOrchestrator:
    """
    Orchestrates skill matching and execution.

    Responsibilities:
    - Match queries against available skills
    - Determine execution mode (direct vs inject)
    - Coordinate skill execution via SkillExecutor
    - Convert domain events to SSE format
    - Summarize execution results
    """

    def __init__(
        self,
        skills: Optional[List[SkillProtocol]] = None,
        skill_executor: Optional[SkillExecutorProtocol] = None,
        tools: Optional[Dict[str, ToolProtocol]] = None,
        config: Optional[SkillExecutionConfig] = None,
        agent_mode: str = "default",
        debug_logging: bool = False,
    ):
        """
        Initialize skill orchestrator.

        Args:
            skills: Available skills for matching
            skill_executor: Executor for skill execution
            tools: Available tools (for sandbox_id extraction)
            config: Execution configuration
            agent_mode: Agent mode for skill filtering
            debug_logging: Enable verbose logging
        """
        self._skills = skills or []
        self._skill_executor = skill_executor
        self._tools = tools or {}
        self._config = config or SkillExecutionConfig()
        self._agent_mode = agent_mode
        self._debug_logging = debug_logging

    @property
    def has_skills(self) -> bool:
        """Check if skills are available."""
        return bool(self._skills)

    @property
    def has_executor(self) -> bool:
        """Check if skill executor is available."""
        return self._skill_executor is not None

    def match(self, query: str) -> SkillMatchResult:
        """
        Match query against available skills.

        Args:
            query: User query to match

        Returns:
            SkillMatchResult with matched skill and mode
        """
        if self._debug_logging:
            logger.debug(f"[SkillOrchestrator] Matching query: {query[:100]}...")
            logger.debug(f"[SkillOrchestrator] Available skills: {len(self._skills)}")

        if not self._skills:
            return SkillMatchResult()

        best_skill = None
        best_score = 0.0

        for skill in self._skills:
            # Check agent mode accessibility
            if not skill.is_accessible_by_agent(self._agent_mode):
                if self._debug_logging:
                    logger.debug(
                        f"[SkillOrchestrator] Skill {skill.name} not accessible "
                        f"by agent_mode={self._agent_mode}"
                    )
                continue

            # Check skill status
            if skill.status.value != "active":
                continue

            # Calculate match score
            score = skill.matches_query(query)
            if self._debug_logging:
                logger.debug(f"[SkillOrchestrator] Skill {skill.name} score: {score:.3f}")

            if score > best_score:
                best_score = score
                best_skill = skill

        # Determine execution mode
        mode = self._determine_mode(best_skill, best_score)

        if best_skill and mode != SkillExecutionMode.NONE:
            logger.info(
                f"[SkillOrchestrator] Matched skill: {best_skill.name} "
                f"(score={best_score:.3f}, mode={mode.value})"
            )
        else:
            if self._debug_logging:
                logger.debug("[SkillOrchestrator] No skill matched")

        return SkillMatchResult(
            skill=best_skill if mode != SkillExecutionMode.NONE else None,
            score=best_score,
            mode=mode,
        )

    def find_by_name(self, name: str) -> SkillMatchResult:
        """Find a skill by exact name (case-insensitive) for forced execution.

        Args:
            name: Skill name to look up

        Returns:
            SkillMatchResult with mode=DIRECT and score=1.0 if found
        """
        name_lower = name.strip().lower()
        for skill in self._skills:
            if skill.name.lower() == name_lower and skill.status.value == "active":
                logger.info(f"[SkillOrchestrator] Forced skill found: {skill.name}")
                return SkillMatchResult(
                    skill=skill,
                    score=1.0,
                    mode=SkillExecutionMode.DIRECT,
                )

        logger.warning(f"[SkillOrchestrator] Forced skill not found: {name}")
        return SkillMatchResult()

    def _determine_mode(
        self,
        skill: Optional[SkillProtocol],
        score: float,
    ) -> SkillExecutionMode:
        """
        Determine execution mode based on skill and score.

        Args:
            skill: Matched skill (may be None)
            score: Match score

        Returns:
            SkillExecutionMode
        """
        if not skill:
            return SkillExecutionMode.NONE

        # Check for direct execution threshold
        if score >= self._config.direct_execute_threshold and self._skill_executor:
            return SkillExecutionMode.DIRECT

        # Check for prompt injection threshold
        if score >= self._config.match_threshold:
            return SkillExecutionMode.INJECT

        # Score too low
        return SkillExecutionMode.NONE

    async def execute_directly(
        self,
        skill: SkillProtocol,
        context: SkillExecutionContext,
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        Execute skill directly via SkillExecutor.

        Args:
            skill: Skill to execute
            context: Execution context

        Yields:
            Event dictionaries for execution progress
        """
        if not self._skill_executor:
            raise ValueError("SkillExecutor not initialized")

        logger.info(f"[SkillOrchestrator] Direct executing skill: {skill.name}")

        # Build execution context for SkillExecutor
        exec_context = {
            "project_id": context.project_id,
            "user_id": context.user_id,
            "tenant_id": context.tenant_id,
        }

        # Extract sandbox_id from tools if not provided
        sandbox_id = context.sandbox_id
        if not sandbox_id:
            sandbox_id = self._extract_sandbox_id(skill.tools)

        # Emit skill execution start
        yield {
            "type": "skill_execution_start",
            "data": {
                "skill_id": skill.id,
                "skill_name": skill.name,
                "tools": list(skill.tools),
                "total_steps": len(skill.tools),
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        tool_results = []
        current_step = 0

        # Execute skill and convert events
        async for domain_event in self._skill_executor.execute(
            skill, context.query, exec_context, sandbox_id=sandbox_id
        ):
            # Convert domain event to SSE format
            converted = self._convert_domain_event(domain_event, skill, current_step)
            if converted:
                yield converted

            # Track tool results
            if domain_event.event_type == AgentEventType.OBSERVE:
                tool_results.append(
                    {
                        "tool_name": domain_event.tool_name,
                        "result": domain_event.result,
                        "error": domain_event.error,
                        "duration_ms": domain_event.duration_ms,
                        "status": domain_event.status,
                    }
                )
                current_step += 1

            # Handle completion
            if domain_event.event_type == AgentEventType.SKILL_EXECUTION_COMPLETE:
                if isinstance(domain_event, AgentSkillExecutionCompleteEvent):
                    summary = self._summarize_results(
                        skill, tool_results, domain_event.success, domain_event.error
                    )

                    yield {
                        "type": "skill_execution_complete",
                        "data": {
                            "skill_id": skill.id,
                            "skill_name": skill.name,
                            "success": domain_event.success,
                            "summary": summary,
                            "tool_results": tool_results,
                            "execution_time_ms": domain_event.execution_time_ms,
                            "error": domain_event.error,
                        },
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }

    def _extract_sandbox_id(self, tool_names: List[str]) -> Optional[str]:
        """Extract sandbox_id from tools if available."""
        for tool_name in tool_names:
            tool = self._tools.get(tool_name)
            if tool and hasattr(tool, "sandbox_id") and tool.sandbox_id:
                return tool.sandbox_id
        return None

    def _convert_domain_event(
        self,
        domain_event: AgentDomainEvent,
        skill: SkillProtocol,
        current_step: int,
    ) -> Optional[Dict[str, Any]]:
        """
        Convert domain event to SSE format.

        Args:
            domain_event: Domain event from SkillExecutor
            skill: Skill being executed
            current_step: Current step index

        Returns:
            Converted event dict or None
        """
        timestamp = datetime.now(timezone.utc).isoformat()

        if domain_event.event_type == AgentEventType.THOUGHT:
            thought_level = getattr(domain_event, "thought_level", "reasoning")
            content = getattr(domain_event, "content", "")

            if thought_level == "skill":
                return {
                    "type": "thought",
                    "data": {
                        "content": content,
                        "thought_level": "skill",
                        "skill_id": skill.id,
                    },
                    "timestamp": timestamp,
                }
            elif thought_level == "skill_complete":
                # Handled separately in execute_directly
                return None
            else:
                return {
                    "type": "thought",
                    "data": {"content": content, "thought_level": thought_level},
                    "timestamp": timestamp,
                }

        elif domain_event.event_type == AgentEventType.ACT:
            return {
                "type": "skill_tool_start",
                "data": {
                    "skill_id": skill.id,
                    "skill_name": skill.name,
                    "tool_name": domain_event.tool_name,
                    "tool_input": domain_event.tool_input,
                    "step_index": current_step,
                    "total_steps": len(skill.tools),
                },
                "timestamp": timestamp,
            }

        elif domain_event.event_type == AgentEventType.OBSERVE:
            return {
                "type": "skill_tool_result",
                "data": {
                    "skill_id": skill.id,
                    "skill_name": skill.name,
                    "tool_name": domain_event.tool_name,
                    "result": domain_event.result,
                    "error": domain_event.error,
                    "step_index": current_step,
                    "total_steps": len(skill.tools),
                },
                "timestamp": timestamp,
            }

        # SKILL_EXECUTION_COMPLETE handled separately
        return None

    def _summarize_results(
        self,
        skill: SkillProtocol,
        tool_results: List[Dict[str, Any]],
        success: bool,
        error: Optional[str],
    ) -> str:
        """
        Generate summary from skill execution results.

        Args:
            skill: Executed skill
            tool_results: Results from each tool
            success: Whether execution succeeded
            error: Error message if failed

        Returns:
            Human-readable summary string
        """
        if not success:
            if error:
                return f"Skill '{skill.name}' failed: {error}"

            # Find failed tool
            for result in tool_results:
                if result.get("error"):
                    return f"Skill '{skill.name}' failed at tool '{result.get('tool_name')}'"

            return f"Skill '{skill.name}' execution failed"

        # Build success summary
        summary_parts = [f"Completed skill '{skill.name}':"]

        for result in tool_results:
            tool_name = result.get("tool_name", "unknown")
            output = result.get("result", "")

            # Truncate long outputs
            if isinstance(output, str) and len(output) > 200:
                output = output[:200] + "..."
            elif isinstance(output, dict):
                output = str(output)[:200] + "..."

            summary_parts.append(f"- {tool_name}: {output}")

        if len(summary_parts) > 1:
            return "\n".join(summary_parts)
        else:
            return f"Skill '{skill.name}' completed successfully"

    def to_skill_dict(self, skill: SkillProtocol) -> Dict[str, Any]:
        """
        Convert skill to dict format for prompt context.

        Args:
            skill: Skill to convert

        Returns:
            Dict representation of skill
        """
        return {
            "id": skill.id,
            "name": skill.name,
            "description": skill.description,
            "tools": skill.tools,
            "prompt_template": skill.prompt_template,
        }

    def get_skills_data(self) -> Optional[List[Dict[str, Any]]]:
        """
        Get all skills as dict format for prompt context.

        Returns:
            List of skill dicts or None
        """
        if not self._skills:
            return None

        return [
            {
                "id": s.id,
                "name": s.name,
                "description": s.description,
                "tools": list(s.tools),
                "status": s.status.value,
            }
            for s in self._skills
            if s.is_accessible_by_agent(self._agent_mode)
        ]


# ============================================================================
# Singleton Management
# ============================================================================

_orchestrator: Optional[SkillOrchestrator] = None


def get_skill_orchestrator() -> SkillOrchestrator:
    """
    Get singleton SkillOrchestrator instance.

    Raises:
        RuntimeError if orchestrator not initialized
    """
    global _orchestrator
    if _orchestrator is None:
        raise RuntimeError(
            "SkillOrchestrator not initialized. "
            "Call set_skill_orchestrator() or create_skill_orchestrator() first."
        )
    return _orchestrator


def set_skill_orchestrator(orchestrator: SkillOrchestrator) -> None:
    """Set singleton SkillOrchestrator instance."""
    global _orchestrator
    _orchestrator = orchestrator


def create_skill_orchestrator(
    skills: Optional[List[SkillProtocol]] = None,
    skill_executor: Optional[SkillExecutorProtocol] = None,
    tools: Optional[Dict[str, ToolProtocol]] = None,
    config: Optional[SkillExecutionConfig] = None,
    agent_mode: str = "default",
    debug_logging: bool = False,
) -> SkillOrchestrator:
    """
    Create and set singleton SkillOrchestrator.

    Returns:
        Created SkillOrchestrator instance
    """
    global _orchestrator
    _orchestrator = SkillOrchestrator(
        skills=skills,
        skill_executor=skill_executor,
        tools=tools,
        config=config,
        agent_mode=agent_mode,
        debug_logging=debug_logging,
    )
    return _orchestrator
