"""
Compression State - Per-session state for context compression.

Tracks the current compression level, pending background work, and
cached summaries for non-blocking compression.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class CompressionLevel(str, Enum):
    """Multi-level compression strategy."""

    NONE = "none"  # No compression needed
    L1_PRUNE = "l1_prune"  # Tool output pruning only
    L2_SUMMARIZE = "l2_summarize"  # L1 + incremental chunk summarization
    L3_DEEP_COMPRESS = "l3_deep_compress"  # L1 + L2 + global distillation


@dataclass
class SummaryChunk:
    """A summary of a group of messages."""

    summary_text: str
    message_start_index: int
    message_end_index: int
    original_token_count: int
    summary_token_count: int
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "summary_text": self.summary_text,
            "message_range": [self.message_start_index, self.message_end_index],
            "original_tokens": self.original_token_count,
            "summary_tokens": self.summary_token_count,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class CompressionState:
    """Per-session compression state.

    Maintains state between compression operations, including cached summaries
    and pending background compression results.
    """

    # Current compression level applied
    current_level: CompressionLevel = CompressionLevel.NONE

    # Cached summary chunks from incremental summarization (L2)
    summary_chunks: List[SummaryChunk] = field(default_factory=list)

    # Global summary from deep compression (L3)
    global_summary: Optional[str] = None
    global_summary_tokens: int = 0

    # Tracking
    last_compression_at: Optional[datetime] = None
    messages_summarized_up_to: int = 0  # Index of last message included in summaries
    total_original_tokens_summarized: int = 0

    # Background compression
    pending_compression: bool = False
    pending_level: Optional[CompressionLevel] = None

    def get_combined_summary(self) -> Optional[str]:
        """Get the combined summary from all chunks, or global summary if available."""
        if self.global_summary:
            return self.global_summary

        if not self.summary_chunks:
            return None

        parts = [chunk.summary_text for chunk in self.summary_chunks]
        return "\n\n".join(parts)

    def get_summary_token_count(self) -> int:
        """Get total tokens used by summaries."""
        if self.global_summary:
            return self.global_summary_tokens

        return sum(chunk.summary_token_count for chunk in self.summary_chunks)

    def add_summary_chunk(self, chunk: SummaryChunk) -> None:
        """Add a new summary chunk from incremental summarization."""
        self.summary_chunks.append(chunk)
        self.messages_summarized_up_to = chunk.message_end_index
        self.total_original_tokens_summarized += chunk.original_token_count
        self.last_compression_at = datetime.now(timezone.utc)

        logger.debug(
            f"Added summary chunk: messages [{chunk.message_start_index}:{chunk.message_end_index}], "
            f"original={chunk.original_token_count} tokens, "
            f"summary={chunk.summary_token_count} tokens"
        )

    def set_global_summary(self, summary: str, token_count: int) -> None:
        """Set the global summary from deep compression (replaces chunks)."""
        self.global_summary = summary
        self.global_summary_tokens = token_count
        self.last_compression_at = datetime.now(timezone.utc)

        logger.debug(
            f"Set global summary: {token_count} tokens (replaced {len(self.summary_chunks)} chunks)"
        )

    def mark_pending(self, level: CompressionLevel) -> None:
        """Mark that background compression is pending."""
        self.pending_compression = True
        self.pending_level = level

    def clear_pending(self) -> None:
        """Clear pending compression flag."""
        self.pending_compression = False
        self.pending_level = None

    def has_cached_summary(self) -> bool:
        """Check if there is a pre-computed summary available."""
        return self.global_summary is not None or len(self.summary_chunks) > 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "current_level": self.current_level.value,
            "summary_chunks_count": len(self.summary_chunks),
            "has_global_summary": self.global_summary is not None,
            "messages_summarized_up_to": self.messages_summarized_up_to,
            "total_original_tokens_summarized": self.total_original_tokens_summarized,
            "summary_token_count": self.get_summary_token_count(),
            "pending_compression": self.pending_compression,
            "pending_level": self.pending_level.value if self.pending_level else None,
            "last_compression_at": (
                self.last_compression_at.isoformat() if self.last_compression_at else None
            ),
        }

    def reset(self) -> None:
        """Reset state for a new conversation."""
        self.current_level = CompressionLevel.NONE
        self.summary_chunks.clear()
        self.global_summary = None
        self.global_summary_tokens = 0
        self.last_compression_at = None
        self.messages_summarized_up_to = 0
        self.total_original_tokens_summarized = 0
        self.pending_compression = False
        self.pending_level = None
