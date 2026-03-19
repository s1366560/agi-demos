"""Announce payload for child-to-parent result announcements."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AnnouncePayload:
    """Result announced by a child agent back to its parent.

    Attributes:
        agent_id: The child agent that produced this result
        session_id: The child's session/conversation ID
        result: Summary of work done
        artifacts: File paths or artifact IDs produced
        success: Whether the task completed successfully
        metadata: Additional context (tool calls count, tokens used, etc.)
    """

    agent_id: str
    session_id: str
    result: str
    artifacts: list[str] = field(default_factory=list)
    success: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "agent_id": self.agent_id,
            "session_id": self.session_id,
            "result": self.result,
            "artifacts": list(self.artifacts),
            "success": self.success,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AnnouncePayload":
        """Create from dictionary."""
        return cls(
            agent_id=data["agent_id"],
            session_id=data["session_id"],
            result=data.get("result", ""),
            artifacts=data.get("artifacts", []),
            success=data.get("success", True),
            metadata=data.get("metadata", {}),
        )
