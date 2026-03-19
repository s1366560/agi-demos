"""Configuration for child-to-parent result announcement retry policy.

This module defines the retry policy configuration for sub-agent announcements.
It is DISTINCT from AnnouncePayload (which carries the actual result data).
AnnounceConfig defines HOW announcements are retried and when they expire.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from src.domain.shared_kernel import ValueObject


class AnnounceState(str, Enum):
    """Lifecycle state of an announce operation."""

    PENDING = "pending"  # Not yet announced
    ANNOUNCING = "announcing"  # Announce in progress
    ANNOUNCED = "announced"  # Successfully announced
    FAILED = "failed"  # All retries exhausted
    EXPIRED = "expired"  # TTL exceeded before announce


@dataclass(frozen=True)
class AnnounceConfig(ValueObject):
    """Configuration for child-to-parent result announcement retry policy.

    This is DISTINCT from AnnouncePayload (which carries the actual result data).
    AnnounceConfig defines HOW announcements are retried and when they expire.

    Attributes:
        max_retries: Maximum number of retry attempts (>= 0).
        retry_delay_ms: Base delay in milliseconds between retries (>= 0).
        backoff_multiplier: Exponential backoff factor (>= 1.0).
        max_retry_delay_ms: Cap on computed delay (>= retry_delay_ms).
        expire_after_seconds: TTL for the announce operation (> 0).
    """

    max_retries: int = 2
    retry_delay_ms: int = 200
    backoff_multiplier: float = 2.0
    max_retry_delay_ms: int = 5000
    expire_after_seconds: int = 300  # 5 minutes

    def __post_init__(self) -> None:
        if self.max_retries < 0:
            raise ValueError(f"max_retries must be >= 0, got {self.max_retries}")
        if self.retry_delay_ms < 0:
            raise ValueError(f"retry_delay_ms must be >= 0, got {self.retry_delay_ms}")
        if self.backoff_multiplier < 1.0:
            raise ValueError(f"backoff_multiplier must be >= 1.0, got {self.backoff_multiplier}")
        if self.max_retry_delay_ms < self.retry_delay_ms:
            msg = (
                f"max_retry_delay_ms ({self.max_retry_delay_ms})"
                f" must be >= retry_delay_ms ({self.retry_delay_ms})"
            )
            raise ValueError(msg)
        if self.expire_after_seconds <= 0:
            raise ValueError(f"expire_after_seconds must be > 0, got {self.expire_after_seconds}")

    def delay_for_attempt(self, attempt: int) -> int:
        """Calculate delay in ms for a given retry attempt (0-indexed).

        Uses exponential backoff: retry_delay_ms * (backoff_multiplier ** attempt)
        Capped at max_retry_delay_ms.

        Args:
            attempt: Zero-indexed retry attempt number.

        Returns:
            Delay in milliseconds, capped at max_retry_delay_ms.
        """
        raw = self.retry_delay_ms * (self.backoff_multiplier**attempt)
        return min(int(raw), self.max_retry_delay_ms)

    @classmethod
    def from_settings(cls, settings: object) -> AnnounceConfig:
        """Construct from application settings object.

        Reads AGENT_SUBAGENT_ANNOUNCE_MAX_RETRIES and
        AGENT_SUBAGENT_ANNOUNCE_RETRY_DELAY_MS from the settings object.
        Other fields use class defaults.

        Args:
            settings: Application settings with optional announce attributes.

        Returns:
            AnnounceConfig populated from settings with defaults for missing fields.
        """
        max_retries = getattr(settings, "AGENT_SUBAGENT_ANNOUNCE_MAX_RETRIES", 2)
        retry_delay_ms = getattr(settings, "AGENT_SUBAGENT_ANNOUNCE_RETRY_DELAY_MS", 200)
        return cls(
            max_retries=max_retries,
            retry_delay_ms=retry_delay_ms,
        )
