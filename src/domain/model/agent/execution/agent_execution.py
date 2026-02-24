"""AgentExecution entity for tracking agent execution cycles."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from src.domain.shared_kernel import Entity


class ExecutionStatus(str, Enum):
    """Status of an agent execution step."""

    THINKING = "thinking"
    ACTING = "acting"
    OBSERVING = "observing"
    COMPLETED = "completed"
    FAILED = "failed"

    # Multi-level thinking statuses
    WORK_PLANNING = "work_planning"  # Generating work plan
    STEP_EXECUTING = "step_executing"  # Executing a step
    SYNTHESIZING = "synthesizing"  # Combining step results


@dataclass(kw_only=True)
class AgentExecution(Entity):
    """
    A single agent execution cycle (Think-Act-Observe).

    This tracks the agent's reasoning process, actions taken,
    and observations made during each step of the ReAct loop.
    """

    conversation_id: str
    message_id: str
    status: ExecutionStatus

    # Agent's reasoning (Think phase)
    thought: str | None = None

    # Action taken (Act phase)
    action: str | None = None
    tool_name: str | None = None
    tool_input: dict[str, Any] = field(default_factory=dict)

    # Result of action (Observe phase)
    observation: str | None = None
    tool_output: str | None = None

    # Additional metadata
    metadata: dict[str, Any] = field(default_factory=dict)

    # Timestamps
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None

    # Multi-level thinking support
    work_level_thought: str | None = None  # Work-level plan
    task_level_thought: str | None = None  # Task-level reasoning
    plan_steps: list[dict[str, Any]] | None = None  # Planned steps
    current_step_index: int | None = None  # Current step number
    workflow_pattern_id: str | None = None  # Pattern used (if any)

    def mark_completed(self) -> None:
        """Mark this execution as completed."""
        self.status = ExecutionStatus.COMPLETED
        self.completed_at = datetime.now(UTC)

    def mark_failed(self, error: str) -> None:
        """
        Mark this execution as failed.

        Args:
            error: Error message describing the failure
        """
        self.status = ExecutionStatus.FAILED
        self.completed_at = datetime.now(UTC)
        self.metadata["error"] = error

    def set_thinking(self, thought: str) -> None:
        """
        Set the thought phase content.

        Args:
            thought: The agent's reasoning
        """
        self.status = ExecutionStatus.THINKING
        self.thought = thought

    def set_acting(self, tool_name: str, tool_input: dict[str, Any]) -> None:
        """
        Set the acting phase content.

        Args:
            tool_name: Name of the tool being called
            tool_input: Arguments for the tool
        """
        self.status = ExecutionStatus.ACTING
        self.action = f"call_{tool_name}"
        self.tool_name = tool_name
        self.tool_input = tool_input

    def set_observing(self, observation: str, tool_output: str | None = None) -> None:
        """
        Set the observation phase content.

        Args:
            observation: The agent's observation
            tool_output: Raw output from the tool
        """
        self.status = ExecutionStatus.OBSERVING
        self.observation = observation
        self.tool_output = tool_output

    @property
    def duration_ms(self) -> int | None:
        """
        Get the duration of this execution in milliseconds.

        Returns:
            Duration in milliseconds, or None if not completed
        """
        if self.completed_at is None:
            return None
        delta = self.completed_at - self.started_at
        return int(delta.total_seconds() * 1000)
