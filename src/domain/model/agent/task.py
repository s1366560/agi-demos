"""Agent Task domain model.

Represents a task item in a conversation's task list, managed by the agent
via TodoRead/TodoWrite tools. Tasks are persisted to DB for durability.
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class TaskStatus(str, Enum):
    """Status of a task."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskPriority(str, Enum):
    """Priority level of a task."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass(kw_only=True)
class AgentTask:
    """A single task in a conversation's task list.

    Attributes:
        id: Unique identifier.
        conversation_id: Associated conversation.
        content: Task description.
        status: Current status.
        priority: Priority level.
        order_index: Display ordering (0-based).
        created_at: Creation timestamp.
        updated_at: Last update timestamp.
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    conversation_id: str
    content: str
    title: str = ""
    description: str | None = None
    estimated_duration_seconds: int | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    result_summary: str | None = None
    evidence_refs: list[str] = field(default_factory=list)
    status: TaskStatus = TaskStatus.PENDING
    priority: TaskPriority = TaskPriority.MEDIUM
    order_index: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if not self.title.strip():
            self.title = self.content

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "content": self.content,
            "title": self.title,
            "description": self.description,
            "estimated_duration_seconds": self.estimated_duration_seconds,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "result_summary": self.result_summary,
            "evidence_refs": list(self.evidence_refs),
            "status": self.status.value,
            "priority": self.priority.value,
            "order_index": self.order_index,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentTask":
        """Create from dictionary."""
        status = data.get("status", "pending")
        if isinstance(status, str):
            status = TaskStatus(status)
        priority = data.get("priority", "medium")
        if isinstance(priority, str):
            priority = TaskPriority(priority)

        return cls(
            id=data.get("id", str(uuid.uuid4())),
            conversation_id=data["conversation_id"],
            content=data["content"],
            title=data.get("title") or data["content"],
            description=data.get("description"),
            estimated_duration_seconds=data.get("estimated_duration_seconds"),
            started_at=_optional_datetime(data.get("started_at")),
            completed_at=_optional_datetime(data.get("completed_at")),
            result_summary=data.get("result_summary"),
            evidence_refs=[str(value) for value in data.get("evidence_refs", [])],
            status=status,
            priority=priority,
            order_index=data.get("order_index", 0),
        )

    def validate(self) -> bool:
        """Validate task data."""
        if not self.content or not self.content.strip():
            return False
        if self.status not in TaskStatus:
            return False
        return self.priority in TaskPriority


def _optional_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value.strip():
        return datetime.fromisoformat(value)
    return None
