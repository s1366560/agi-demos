"""
Token Delta Sampling and Batch Logging utilities for LLM streaming.

Extracted from llm_stream.py to reduce file size.

P0-2 Optimization: Reduces I/O overhead during streaming by:
- Sampling token deltas instead of logging all
- Batching log entries before writing
"""

import logging
import random
import time
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class TokenDeltaSampler:
    """
    Samples token deltas for logging to reduce I/O overhead.

    Instead of logging every single token delta (which can be thousands),
    this sampler intelligently selects which deltas to log based on:
    - Sample rate: Probability of sampling each delta
    - Minimum interval: Minimum time between samples
    - First delta: Always logged for debugging

    Usage:
        sampler = TokenDeltaSampler(sample_rate=0.1, min_sample_interval=0.5)
        sampler.reset()
        for delta in deltas:
            if sampler.should_sample(delta):
                logger.info(f"Sampled delta: {delta}")
    """

    def __init__(
        self,
        sample_rate: float = 0.1,
        min_sample_interval: float = 0.5,
    ):
        """
        Initialize the token delta sampler.

        Args:
            sample_rate: Probability of sampling each delta (0.0 to 1.0).
                        0.0 = only interval-based sampling, 1.0 = sample all.
            min_sample_interval: Minimum seconds between samples.
        """
        self.sample_rate = max(0.0, min(1.0, sample_rate))
        self.min_sample_interval = max(0.0, min_sample_interval)
        self._last_sample_time = 0.0
        self._count = 0

    def reset(self) -> None:
        """Reset the sampler state for a new stream."""
        self._last_sample_time = 0.0
        self._count = 0

    def should_sample(self, delta: str) -> bool:
        """
        Determine if a delta should be sampled.

        Args:
            delta: The token delta content.

        Returns:
            True if the delta should be logged, False otherwise.
        """
        self._count += 1
        now = time.time()

        # Always sample the first delta
        if self._count == 1:
            self._last_sample_time = now
            return True

        # Check minimum interval
        if now - self._last_sample_time < self.min_sample_interval:
            return False

        # Apply sample rate (if not 0 or 1)
        if 0.0 < self.sample_rate < 1.0:
            should_sample = random.random() < self.sample_rate
            if should_sample:
                self._last_sample_time = now
            return should_sample

        # Edge cases: sample_rate == 0.0 or 1.0
        if self.sample_rate == 0.0:
            # Only interval-based sampling
            if now - self._last_sample_time >= self.min_sample_interval:
                self._last_sample_time = now
                return True
            return False

        # sample_rate == 1.0: sample all (subject to interval)
        if now - self._last_sample_time >= self.min_sample_interval:
            self._last_sample_time = now
        return True


class BatchLogBuffer:
    """
    Buffers log entries and flushes them in batches to reduce I/O.

    Instead of writing each log entry immediately, this buffer:
    - Accumulates entries up to max_size
    - Flushes periodically based on flush_interval
    - Provides manual flush capability

    Usage:
        buffer = BatchLogBuffer(max_size=100, flush_interval=1.0)
        buffer.add("info", "Processing chunk")
        buffer.add("debug", "Token count: 42")
        # Auto-flush when full or after interval
    """

    def __init__(
        self,
        max_size: int = 100,
        flush_interval: float = 1.0,
        flush_callback: Optional[Callable[[List[Dict[str, Any]]], None]] = None,
    ):
        """
        Initialize the batch log buffer.

        Args:
            max_size: Maximum number of entries before auto-flush.
            flush_interval: Seconds between auto-flushes (0 = disable).
            flush_callback: Optional callback for flushed entries.
        """
        self.max_size = max_size
        self.flush_interval = flush_interval
        self.flush_callback = flush_callback or self._default_flush
        self.entries: List[Dict[str, Any]] = []
        self._last_flush_time = time.time()

    def _default_flush(self, entries: List[Dict[str, Any]]) -> None:
        """Default flush callback - logs to standard logger."""
        for entry in entries:
            level = entry.get("level", "info").lower()
            message = entry.get("message", "")
            if level == "debug":
                logger.debug(message)
            elif level == "info":
                logger.info(message)
            elif level == "warning":
                logger.warning(message)
            elif level == "error":
                logger.error(message)

    def add(self, level: str, message: str, **kwargs) -> None:
        """
        Add a log entry to the buffer.

        Args:
            level: Log level (debug, info, warning, error).
            message: Log message.
            **kwargs: Additional metadata to include with the entry.
        """
        entry = {
            "level": level,
            "message": message,
            "timestamp": time.time(),
            **kwargs,
        }
        self.entries.append(entry)

        # Auto-flush if at max size
        if len(self.entries) >= self.max_size:
            self.flush()

    def flush(self) -> None:
        """Flush all buffered entries via the callback."""
        if not self.entries:
            return

        try:
            self.flush_callback(self.entries)
        except Exception as e:
            # Don't let logging errors break the stream
            logger.warning(f"[BatchLogBuffer] Flush failed: {e}")
        finally:
            self.entries.clear()
            self._last_flush_time = time.time()

    def should_flush(self) -> bool:
        """
        Check if buffer should flush based on time interval.

        Returns:
            True if flush_interval has passed since last flush.
        """
        if self.flush_interval <= 0:
            return False
        return (time.time() - self._last_flush_time) >= self.flush_interval
