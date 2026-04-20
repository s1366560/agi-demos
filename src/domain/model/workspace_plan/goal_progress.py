"""GoalProgress: first-class projection of plan status."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from src.domain.model.workspace_plan.acceptance import EvidenceRef


@dataclass(frozen=True)
class GoalProgress:
    """Aggregate progress snapshot for a single plan.

    Produced by :class:`ProgressProjector` from the current ``Plan`` state.
    Persisted as a ``goal_progress_snapshots`` row and emitted as a
    ``goal_progress_updated`` event so the UI can render a live progress bar.
    """

    workspace_id: str
    plan_id: str
    goal_node_id: str
    total_nodes: int
    todo_nodes: int
    in_progress_nodes: int
    blocked_nodes: int
    done_nodes: int
    percent: float  # 0..100 — done / total
    critical_path_remaining_minutes: int = 0
    evidence: tuple[EvidenceRef, ...] = field(default_factory=tuple)
    last_updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if self.total_nodes < 0:
            raise ValueError("total_nodes must be >= 0")
        counts = self.todo_nodes + self.in_progress_nodes + self.blocked_nodes + self.done_nodes
        if counts != self.total_nodes:
            raise ValueError(f"status counts {counts} do not sum to total_nodes {self.total_nodes}")
        if not 0.0 <= self.percent <= 100.0:
            raise ValueError("percent must be in [0,100]")

    @property
    def is_complete(self) -> bool:
        return self.total_nodes > 0 and self.done_nodes == self.total_nodes

    @property
    def is_stalled(self) -> bool:
        """Heuristic: every remaining node is blocked."""
        remaining = self.total_nodes - self.done_nodes
        return remaining > 0 and self.blocked_nodes == remaining
