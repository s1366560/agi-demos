"""Context Summary value object for persisting compressed conversation context.

A ContextSummary is a cache of older conversation history that has been
compressed via the adaptive compression engine. It sits alongside the
original events (which are never modified) and enables efficient context
loading without re-running LLM summarization on every turn.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class ContextSummary:
    """Cached summary of older conversation messages.

    This is a value object (frozen) stored in conversation.metadata["context_summary"].
    The original events remain untouched in agent_execution_events.

    Attributes:
        summary_text: The compressed summary text of older messages.
        summary_tokens: Estimated token count of the summary.
        messages_covered_up_to: event_time_us of the last summarized message.
        messages_covered_count: Number of messages covered by this summary.
        compression_level: Which compression level produced this summary (L1/L2/L3).
        created_at: When this summary was generated.
        model: Which LLM model generated the summary.
    """

    summary_text: str
    summary_tokens: int
    messages_covered_up_to: int  # event_time_us
    messages_covered_count: int
    compression_level: str = "l2_summarize"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    model: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for JSON storage in conversation.metadata."""
        return {
            "summary_text": self.summary_text,
            "summary_tokens": self.summary_tokens,
            "messages_covered_up_to": self.messages_covered_up_to,
            "messages_covered_count": self.messages_covered_count,
            "compression_level": self.compression_level,
            "created_at": self.created_at.isoformat(),
            "model": self.model,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ContextSummary":
        """Deserialize from dictionary."""
        created_at = data.get("created_at")
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        elif created_at is None:
            created_at = datetime.now(UTC)

        return cls(
            summary_text=data["summary_text"],
            summary_tokens=data.get("summary_tokens", 0),
            messages_covered_up_to=data.get("messages_covered_up_to", 0),
            messages_covered_count=data.get("messages_covered_count", 0),
            compression_level=data.get("compression_level", "l2_summarize"),
            created_at=created_at,
            model=data.get("model"),
        )
