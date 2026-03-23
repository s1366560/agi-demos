"""Session policy configuration for agent conversations."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from src.domain.shared_kernel import ValueObject


class DmScope(str, Enum):
    """Determines how DM sessions are scoped."""

    PER_USER = "per_user"  # One session per user (default, current behavior)
    PER_CHAT = "per_chat"  # One session per chat/conversation
    GLOBAL = "global"  # Single global session shared by all users


@dataclass(frozen=True)
class SessionPolicy(ValueObject):
    """Policy controlling session lifecycle and scoping.

    Attributes:
        dm_scope: How DM sessions are scoped (per_user, per_chat, global).
        max_messages: Maximum messages before session trim (None = use system default).
        idle_reset_minutes: Minutes of inactivity before session resets (None = never).
        daily_reset_hour: Hour of day (0-23 UTC) to reset session (None = no daily reset).
        session_ttl_hours: Maximum session age in hours (None = use system default).
    """

    dm_scope: DmScope = DmScope.PER_USER
    max_messages: int | None = None
    idle_reset_minutes: int | None = None
    daily_reset_hour: int | None = None
    session_ttl_hours: int | None = None

    def __post_init__(self) -> None:
        if self.max_messages is not None and self.max_messages < 1:
            raise ValueError("max_messages must be positive")
        if self.idle_reset_minutes is not None and self.idle_reset_minutes < 1:
            raise ValueError("idle_reset_minutes must be positive")
        if self.daily_reset_hour is not None and not (0 <= self.daily_reset_hour <= 23):
            raise ValueError("daily_reset_hour must be 0-23")
        if self.session_ttl_hours is not None and self.session_ttl_hours < 1:
            raise ValueError("session_ttl_hours must be positive")

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dictionary."""
        return {
            "dm_scope": self.dm_scope.value,
            "max_messages": self.max_messages,
            "idle_reset_minutes": self.idle_reset_minutes,
            "daily_reset_hour": self.daily_reset_hour,
            "session_ttl_hours": self.session_ttl_hours,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SessionPolicy:
        """Deserialize from a plain dictionary."""
        return cls(
            dm_scope=DmScope(data.get("dm_scope", "per_user")),
            max_messages=data.get("max_messages"),
            idle_reset_minutes=data.get("idle_reset_minutes"),
            daily_reset_hour=data.get("daily_reset_hour"),
            session_ttl_hours=data.get("session_ttl_hours"),
        )
