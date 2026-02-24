"""
Compression History Tracker - Records and analyzes compression events.

Tracks each compression operation with metrics for monitoring and
adaptive strategy tuning.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CompressionRecord:
    """Immutable record of a single compression event."""

    timestamp: datetime
    level: str  # "L1_PRUNE", "L2_SUMMARIZE", "L3_DEEP_COMPRESS"
    tokens_before: int
    tokens_after: int
    messages_before: int
    messages_after: int
    summary_generated: bool = False
    summary_tokens: int = 0
    pruned_tool_outputs: int = 0
    duration_ms: float = 0.0

    @property
    def tokens_saved(self) -> int:
        return self.tokens_before - self.tokens_after

    @property
    def compression_ratio(self) -> float:
        if self.tokens_before == 0:
            return 0.0
        return self.tokens_after / self.tokens_before

    @property
    def savings_pct(self) -> float:
        if self.tokens_before == 0:
            return 0.0
        return (self.tokens_saved / self.tokens_before) * 100

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "level": self.level,
            "tokens_before": self.tokens_before,
            "tokens_after": self.tokens_after,
            "tokens_saved": self.tokens_saved,
            "compression_ratio": round(self.compression_ratio, 3),
            "savings_pct": round(self.savings_pct, 1),
            "messages_before": self.messages_before,
            "messages_after": self.messages_after,
            "summary_generated": self.summary_generated,
            "pruned_tool_outputs": self.pruned_tool_outputs,
            "duration_ms": round(self.duration_ms, 1),
        }


class CompressionHistory:
    """Tracks compression events for a conversation session.

    Provides metrics for adaptive strategy tuning and frontend monitoring.
    """

    def __init__(self, max_records: int = 100) -> None:
        self._records: list[CompressionRecord] = []
        self._max_records = max_records
        self._total_tokens_saved: int = 0
        self._total_compressions: int = 0

    def record(self, entry: CompressionRecord) -> None:
        """Record a compression event."""
        self._records.append(entry)
        self._total_tokens_saved += entry.tokens_saved
        self._total_compressions += 1

        # Evict oldest records if over limit
        if len(self._records) > self._max_records:
            self._records = self._records[-self._max_records :]

        logger.info(
            f"Compression recorded: level={entry.level}, "
            f"saved={entry.tokens_saved} tokens ({entry.savings_pct:.1f}%), "
            f"duration={entry.duration_ms:.0f}ms"
        )

    @property
    def records(self) -> list[CompressionRecord]:
        return list(self._records)

    @property
    def total_tokens_saved(self) -> int:
        return self._total_tokens_saved

    @property
    def total_compressions(self) -> int:
        return self._total_compressions

    @property
    def last_compression(self) -> CompressionRecord | None:
        return self._records[-1] if self._records else None

    def average_compression_ratio(self) -> float:
        """Average compression ratio across all recorded events."""
        if not self._records:
            return 0.0
        total = sum(r.compression_ratio for r in self._records)
        return total / len(self._records)

    def average_savings_pct(self) -> float:
        """Average savings percentage across all recorded events."""
        if not self._records:
            return 0.0
        total = sum(r.savings_pct for r in self._records)
        return total / len(self._records)

    def to_summary(self) -> dict[str, Any]:
        """Summary for SSE events and frontend display."""
        return {
            "total_compressions": self._total_compressions,
            "total_tokens_saved": self._total_tokens_saved,
            "average_compression_ratio": round(self.average_compression_ratio(), 3),
            "average_savings_pct": round(self.average_savings_pct(), 1),
            "recent_records": [r.to_dict() for r in self._records[-5:]],
        }

    def reset(self) -> None:
        """Reset history for a new conversation."""
        self._records.clear()
        self._total_tokens_saved = 0
        self._total_compressions = 0
