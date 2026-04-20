from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from src.domain.shared_kernel import Entity


class WorkspaceTaskStatus(str, Enum):
    """Task lifecycle status."""

    TODO = "todo"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    DONE = "done"

    # --- Orchestration lifecycle (fine-grained) ---
    DISPATCHED = "dispatched"
    EXECUTING = "executing"
    REPORTED = "reported"
    ADJUDICATING = "adjudicating"


class WorkspaceTaskPriority(str, Enum):
    """Canonical public priority contract for workspace tasks."""

    NONE = ""
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"

    @property
    def rank(self) -> int:
        return {
            WorkspaceTaskPriority.NONE: 0,
            WorkspaceTaskPriority.P1: 1,
            WorkspaceTaskPriority.P2: 2,
            WorkspaceTaskPriority.P3: 3,
            WorkspaceTaskPriority.P4: 4,
        }[self]

    @classmethod
    def from_rank(cls, rank: int | None) -> "WorkspaceTaskPriority":
        return {
            None: cls.NONE,
            0: cls.NONE,
            1: cls.P1,
            2: cls.P2,
            3: cls.P3,
            4: cls.P4,
        }.get(rank, cls.NONE)


@dataclass(kw_only=True)
class WorkspaceTask(Entity):
    """Task tracked in a collaboration workspace."""

    workspace_id: str
    title: str
    description: str | None = None
    created_by: str = ""
    assignee_user_id: str | None = None
    assignee_agent_id: str | None = None
    status: WorkspaceTaskStatus = WorkspaceTaskStatus.TODO
    priority: WorkspaceTaskPriority = WorkspaceTaskPriority.NONE
    estimated_effort: str | None = None
    blocker_reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime | None = None
    completed_at: datetime | None = None
    archived_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.workspace_id:
            raise ValueError("workspace_id cannot be empty")
        if not self.title.strip():
            raise ValueError("title cannot be empty")
        if not self.created_by:
            raise ValueError("created_by cannot be empty")
        if isinstance(self.priority, int):
            self.priority = WorkspaceTaskPriority.from_rank(self.priority)
        elif isinstance(self.priority, str):
            self.priority = WorkspaceTaskPriority(self.priority)
