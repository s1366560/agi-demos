"""Audio modes and provider transcript facts, independent of agent-run lifetime."""

from dataclasses import dataclass
from enum import StrEnum


class AudioMode(StrEnum):
    DICTATION = "dictation"
    MEETING = "meeting"
    VOICE = "voice"


@dataclass(frozen=True, kw_only=True)
class TranscriptSegment:
    segment_id: str
    text: str
    final: bool
    start_ms: int | None = None
    end_ms: int | None = None
    speaker_id: str | None = None
    source: str = "microphone"
    stream_id: str = ""
    revision: int = 0

    def __post_init__(self) -> None:
        if not self.segment_id or self.revision < 0:
            raise ValueError("invalid transcript identity")
        if (self.start_ms is None) != (self.end_ms is None):
            raise ValueError("transcript timestamps must be supplied together")
        if self.start_ms is not None and (
            self.start_ms < 0 or self.end_ms is None or self.end_ms < self.start_ms
        ):
            raise ValueError("invalid transcript timestamps")


@dataclass(frozen=True, kw_only=True)
class AudioSessionOwner:
    user_id: str
    tenant_id: str
    project_id: str
    device_id: str


MAX_MEETING_DURATION_MS = 8 * 60 * 60 * 1000
MEETING_SEGMENT_MS = 30_000
