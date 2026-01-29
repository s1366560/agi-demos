"""Session domain entities."""

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from dataclasses import dataclass, field

from .value_objects import SessionKey, SessionStatus, SessionKind


class MessageRole(str, Enum):
    """Message role types."""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


@dataclass(slots=True)
class SessionMessage:
    """A message within a session."""

    id: str
    session_id: str
    role: MessageRole
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)

    def __post_init__(self):
        if not self.content:
            raise ValueError("Message content cannot be empty")

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "session_id": self.session_id,
            "role": self.role.value,
            "content": self.content,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
        }


@dataclass(slots=True)
class Session:
    """A session represents an isolated conversation context.

    Sessions can be:
    - Main sessions (direct user interaction)
    - Sub-agent sessions (spawned for specific tasks)
    - Background sessions (long-running tasks)
    - One-shot sessions (single task, then cleanup)
    """

    id: str
    session_key: SessionKey
    agent_id: str
    kind: SessionKind = SessionKind.MAIN
    model: Optional[str] = None  # Model override
    status: SessionStatus = SessionStatus.ACTIVE
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_active_at: datetime = field(default_factory=datetime.utcnow)

    def __post_init__(self):
        if not self.agent_id:
            raise ValueError("agent_id cannot be empty")

    def update_last_active(self) -> None:
        """Update last_active timestamp."""
        self.last_active_at = datetime.utcnow()

    def terminate(self) -> None:
        """Mark session as terminated."""
        self.status = SessionStatus.TERMINATED
        self.update_last_active()

    def activate(self) -> None:
        """Mark session as active."""
        self.status = SessionStatus.ACTIVE
        self.update_last_active()

    def is_active(self) -> bool:
        """Check if session is active."""
        return self.status == SessionStatus.ACTIVE

    def is_terminated(self) -> bool:
        """Check if session is terminated."""
        return self.status == SessionStatus.TERMINATED

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "session_key": self.session_key.value,
            "agent_id": self.agent_id,
            "kind": self.kind.value,
            "model": self.model,
            "status": self.status.value,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
            "last_active_at": self.last_active_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Session":
        """Create Session from dictionary."""
        return cls(
            id=data["id"],
            session_key=SessionKey(data["session_key"]),
            agent_id=data["agent_id"],
            kind=SessionKind(data.get("kind", "main")),
            model=data.get("model"),
            status=SessionStatus(data.get("status", "active")),
            metadata=data.get("metadata", {}),
            created_at=datetime.fromisoformat(data["created_at"]),
            last_active_at=datetime.fromisoformat(data["last_active_at"]),
        )
