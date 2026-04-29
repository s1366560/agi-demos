"""Port: structured review for completed workspace plan iterations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

IterationReviewDecision = Literal[
    "complete_goal",
    "continue_next_iteration",
    "needs_human_review",
]


@dataclass(frozen=True)
class IterationNextTask:
    """A bounded task proposed for the next sprint."""

    id: str
    description: str
    target_subagent: str | None = None
    dependencies: tuple[str, ...] = field(default_factory=tuple)
    priority: int = 0
    phase: str | None = None
    expected_artifacts: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class IterationReviewVerdict:
    """Structured agent verdict after a sprint finishes."""

    verdict: IterationReviewDecision
    confidence: float
    summary: str
    next_sprint_goal: str = ""
    feedback_items: tuple[str, ...] = field(default_factory=tuple)
    next_tasks: tuple[IterationNextTask, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class IterationReviewContext:
    """Facts supplied to the review agent."""

    workspace_id: str
    plan_id: str
    iteration_index: int
    goal_title: str
    goal_description: str
    completed_tasks: tuple[dict[str, object], ...] = field(default_factory=tuple)
    deliverables: tuple[str, ...] = field(default_factory=tuple)
    feedback_items: tuple[str, ...] = field(default_factory=tuple)
    max_next_tasks: int = 6


class IterationReviewPort(Protocol):
    """Agent-first subjective review boundary for sprint completion."""

    async def review(self, context: IterationReviewContext) -> IterationReviewVerdict:
        """Return a structured verdict for the just-completed iteration."""
        ...


__all__ = [
    "IterationNextTask",
    "IterationReviewContext",
    "IterationReviewDecision",
    "IterationReviewPort",
    "IterationReviewVerdict",
]
