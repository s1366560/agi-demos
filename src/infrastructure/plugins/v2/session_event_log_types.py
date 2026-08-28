"""Storage-neutral types for the protocol-v2 session event log."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True, order=True, kw_only=True)
class SessionEventCursorV2:
    """Exact position in one ordered conversation event stream."""

    event_time_us: int = 0
    event_counter: int = 0

    def __post_init__(self) -> None:
        if self.event_time_us < 0:
            raise ValueError("event_time_us must be non-negative")
        if self.event_counter < 0:
            raise ValueError("event_counter must be non-negative")

    def to_payload(self) -> dict[str, int]:
        return {
            "event_time_us": self.event_time_us,
            "event_counter": self.event_counter,
        }


@dataclass(frozen=True, kw_only=True)
class SessionEventRecordV2:
    """Storage-neutral event record consumed by the v2 materializer."""

    event_id: str
    conversation_id: str
    message_id: str
    event_type: str
    event_data: Mapping[str, Any]
    cursor: SessionEventCursorV2


@dataclass(frozen=True, kw_only=True)
class SessionMessageRecoveryStateV2:
    """Durable recovery state for one exact conversation message."""

    has_events: bool
    is_terminal: bool
    cursor: SessionEventCursorV2 = field(default_factory=SessionEventCursorV2)


class SessionEventLogStoreV2(Protocol):
    """Driven store port owned exclusively by the v2 session-log service."""

    async def append_stream_events(
        self,
        *,
        conversation_id: str,
        message_id: str,
        events: list[dict[str, Any]],
        correlation_id: str | None,
    ) -> None: ...

    async def read_events(
        self,
        *,
        conversation_id: str,
        after: SessionEventCursorV2 | None,
        limit: int,
    ) -> Sequence[SessionEventRecordV2]: ...

    async def read_message_events(
        self,
        *,
        conversation_id: str,
        message_id: str,
    ) -> Sequence[SessionEventRecordV2]: ...

    async def last_cursor(self, *, conversation_id: str) -> SessionEventCursorV2: ...


__all__ = [
    "SessionEventCursorV2",
    "SessionEventLogStoreV2",
    "SessionEventRecordV2",
    "SessionMessageRecoveryStateV2",
]
