"""Doom Loop Detector - Reference: OpenCode processor.ts:144-168

Detects when the agent makes identical tool calls repeatedly,
indicating it's stuck in a loop.
"""

import json
import time
from collections import deque
from dataclasses import dataclass
from typing import Any


@dataclass
class ToolCallRecord:
    """Record of a tool call for loop detection."""

    tool: str
    input: Any
    input_hash: str
    timestamp: float


class DoomLoopDetector:
    """
    Doom Loop Detector - Reference: OpenCode processor.ts:144-168

    Detects repeated identical tool calls (same tool + same input).
    When threshold is reached, signals that user intervention is needed.

    Example:
        detector = DoomLoopDetector(threshold=3)

        # First call
        detector.record("search", {"query": "test"})
        detector.should_intervene("search", {"query": "test"})  # False

        # Second call
        detector.record("search", {"query": "test"})
        detector.should_intervene("search", {"query": "test"})  # False

        # Third call - triggers intervention
        detector.record("search", {"query": "test"})
        detector.should_intervene("search", {"query": "test"})  # True
    """

    def __init__(self, threshold: int = 3, window_size: int = 10):
        """
        Initialize the detector.

        Args:
            threshold: Number of identical calls before intervention (default: 3)
            window_size: Maximum number of calls to track (default: 10)
        """
        self.threshold = threshold
        self.window: deque[ToolCallRecord] = deque(maxlen=window_size)

    def _hash_input(self, input: Any) -> str:  # noqa: ANN401
        """
        Compute a hash of the tool input for comparison.

        Args:
            input: The tool input (dict, list, or primitive)

        Returns:
            JSON string hash of the input
        """
        try:
            return json.dumps(input, sort_keys=True, default=str)
        except (TypeError, ValueError):
            return str(input)

    def record(self, tool: str, input: Any) -> None:  # noqa: ANN401
        """
        Record a tool call.

        Args:
            tool: Name of the tool called
            input: Input arguments passed to the tool
        """
        self.window.append(
            ToolCallRecord(
                tool=tool,
                input=input,
                input_hash=self._hash_input(input),
                timestamp=time.time(),
            )
        )

    def should_intervene(self, tool: str, input: Any) -> bool:  # noqa: ANN401
        """
        Check if user intervention is needed.

        Returns True if the last `threshold` calls were all identical
        to the current proposed call.

        Args:
            tool: Name of the tool about to be called
            input: Input arguments about to be passed

        Returns:
            True if intervention is needed, False otherwise
        """
        if len(self.window) < self.threshold:
            return False

        input_hash = self._hash_input(input)
        recent = list(self.window)[-self.threshold :]

        return all(record.tool == tool and record.input_hash == input_hash for record in recent)

    def get_recent_calls(self, n: int = 5) -> list[ToolCallRecord]:
        """
        Get the most recent tool calls.

        Args:
            n: Number of calls to return

        Returns:
            List of recent ToolCallRecord objects
        """
        return list(self.window)[-n:]

    def clear(self) -> None:
        """Clear all recorded tool calls."""
        self.window.clear()

    def reset_for_new_conversation(self) -> None:
        """Reset detector for a new conversation."""
        self.clear()
