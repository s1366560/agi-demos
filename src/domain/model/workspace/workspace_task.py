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
    priority: int = 0
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
