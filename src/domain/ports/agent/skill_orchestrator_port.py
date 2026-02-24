"""
Skill Orchestrator Port - Domain interface for skill matching and execution.

Skills are declarative tool compositions (L2 layer) that combine multiple
tools into reusable workflows.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable


class SkillExecutionMode(str, Enum):
    """How a skill should be executed."""

    DIRECT = "direct"  # Execute immediately, return result
    DELEGATE = "delegate"  # Delegate to skill executor
    STREAM = "stream"  # Stream execution events


@dataclass
class SkillMatchRequest:
    """Request to match a skill.

    Attributes:
        message: User message to match against
        project_id: Project context
        available_skills: List of available skill definitions
        context: Additional matching context
    """

    message: str
    project_id: str
    available_skills: list[dict[str, Any]] | None = None
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class SkillMatchResult:
    """Result of skill matching.

    Attributes:
        matched: Whether a skill was matched
        skill_name: Name of matched skill
        skill_definition: Full skill definition
        confidence: Match confidence (0-1)
        execution_mode: How skill should be executed
        extracted_params: Parameters extracted from message
    """

    matched: bool
    skill_name: str | None = None
    skill_definition: dict[str, Any] | None = None
    confidence: float = 0.0
    execution_mode: SkillExecutionMode = SkillExecutionMode.DIRECT
    extracted_params: dict[str, Any] = field(default_factory=dict)


@dataclass
class SkillExecutionRequest:
    """Request to execute a skill.

    Attributes:
        skill_name: Name of skill to execute
        skill_definition: Full skill definition
        params: Execution parameters
        project_id: Project context
        user_id: User requesting execution
        session_id: Session context
        sandbox_id: Optional sandbox for execution
        stream: Whether to stream execution events
    """

    skill_name: str
    skill_definition: dict[str, Any]
    params: dict[str, Any]
    project_id: str
    user_id: str | None = None
    session_id: str | None = None
    sandbox_id: str | None = None
    stream: bool = False


@dataclass
class SkillExecutionResult:
    """Result from skill execution.

    Attributes:
        success: Whether execution succeeded
        output: Skill output
        error: Error message if failed
        artifacts: Generated artifacts
        tool_calls: Tools that were called
        duration_ms: Execution duration
        metadata: Additional result metadata
    """

    success: bool
    output: str = ""
    error: str | None = None
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    duration_ms: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class SkillOrchestratorPort(Protocol):
    """
    Protocol for skill orchestration.

    Handles skill matching (finding the right skill for a message)
    and skill execution (running the skill's tool composition).

    Example:
        class SkillOrchestrator(SkillOrchestratorPort):
            async def match(
                self, request: SkillMatchRequest
            ) -> SkillMatchResult:
                for skill in request.available_skills:
                    if self._matches(skill, request.message):
                        return SkillMatchResult(
                            matched=True,
                            skill_name=skill["name"],
                            ...
                        )
                return SkillMatchResult(matched=False)

            async def execute(
                self, request: SkillExecutionRequest
            ) -> SkillExecutionResult:
                # Run skill's tool composition
                ...
    """

    async def match(self, request: SkillMatchRequest) -> SkillMatchResult:
        """
        Match a message to a skill.

        Args:
            request: Match request with message and context

        Returns:
            Match result indicating if/which skill matched
        """
        ...

    async def execute(self, request: SkillExecutionRequest) -> SkillExecutionResult:
        """
        Execute a matched skill.

        Args:
            request: Execution request with skill and params

        Returns:
            Execution result with output or error
        """
        ...

    async def execute_stream(self, request: SkillExecutionRequest) -> AsyncIterator[dict[str, Any]]:
        """
        Execute a skill with streaming output.

        Args:
            request: Execution request with skill and params

        Yields:
            Execution events during skill run
        """
        ...

    def get_available_skills(self, project_id: str) -> list[dict[str, Any]]:
        """
        Get available skills for a project.

        Args:
            project_id: Project to get skills for

        Returns:
            List of skill definitions
        """
        ...
