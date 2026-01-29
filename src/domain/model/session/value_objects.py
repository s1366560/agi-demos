"""Value objects for Session domain."""

from enum import Enum
from dataclasses import dataclass
from typing import Literal


class SessionKind(str, Enum):
    """Session kind types."""
    MAIN = "main"
    SUB_AGENT = "sub_agent"
    BACKGROUND = "background"
    ONE_SHOT = "one_shot"


class SessionStatus(str, Enum):
    """Session status types."""
    ACTIVE = "active"
    INACTIVE = "inactive"
    TERMINATED = "terminated"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class SessionKey:
    """Unique identifier for a session.

    Format: `agent:{agent_id}:{session_id}` or similar pattern.
    """
    value: str

    def __post_init__(self):
        if not self.value or len(self.value) < 3:
            raise ValueError("Session key must be at least 3 characters")
        if ":" not in self.value:
            raise ValueError("Session key must contain at least one colon")

    @classmethod
    def from_parts(cls, prefix: str, *parts: str) -> "SessionKey":
        """Create SessionKey from parts."""
        return cls(value=":".join([prefix, *parts]))

    @property
    def prefix(self) -> str:
        """Get the prefix part (e.g., 'agent')."""
        return self.value.split(":")[0]

    @property
    def parts(self) -> list[str]:
        """Get all parts as a list."""
        return self.value.split(":")
