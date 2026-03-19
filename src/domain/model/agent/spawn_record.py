"""Spawn record for tracking child agent sessions."""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from src.domain.model.agent.spawn_mode import SpawnMode


@dataclass(frozen=True)
class SpawnRecord:
    """Record of a spawned child agent session.

    Attributes:
        id: Unique record identifier
        parent_agent_id: Agent that spawned this child
        child_agent_id: The spawned child agent
        child_session_id: Conversation/session ID for the child
        project_id: Multi-tenant isolation
        mode: SpawnMode (RUN or SESSION)
        task_summary: Brief description of what the child was asked to do
        status: Current lifecycle status
        created_at: When the spawn occurred
    """

    parent_agent_id: str
    child_agent_id: str
    child_session_id: str
    project_id: str
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    mode: SpawnMode = SpawnMode.RUN
    task_summary: str = ""
    status: str = "running"
    trace_id: str = ""
    span_id: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "id": self.id,
            "parent_agent_id": self.parent_agent_id,
            "child_agent_id": self.child_agent_id,
            "child_session_id": self.child_session_id,
            "project_id": self.project_id,
            "mode": str(self.mode),
            "task_summary": self.task_summary,
            "status": self.status,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SpawnRecord":
        """Create from dictionary."""
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            parent_agent_id=data["parent_agent_id"],
            child_agent_id=data["child_agent_id"],
            child_session_id=data["child_session_id"],
            project_id=data["project_id"],
            mode=SpawnMode(data.get("mode", "run")),
            task_summary=data.get("task_summary", ""),
            status=data.get("status", "running"),
            created_at=datetime.fromisoformat(data["created_at"])
            if "created_at" in data
            else datetime.now(UTC),
        )
