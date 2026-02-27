"""Doom Loop Detector - Reference: OpenCode processor.ts:144-168

Detects when the agent makes identical tool calls repeatedly,
indicating it's stuck in a loop.

Also detects consecutive tool errors (e.g. repeated "Unknown tool"
failures) even when tool names or arguments vary between calls.
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


@dataclass
class ToolErrorRecord:
    """Record of a tool error for consecutive-error detection."""

    tool: str
    error: str
    timestamp: float


class DoomLoopDetector:
    """Doom Loop Detector - Reference: OpenCode processor.ts:144-168

    Detects repeated identical tool calls (same tool + same input).
    When threshold is reached, signals that user intervention is needed.

    Also supports **error-pattern detection**: if consecutive tool errors
    accumulate (regardless of which tool or what arguments), the detector
    will trigger intervention.  This catches doom loops where the agent
    varies tool names or arguments on each retry (e.g. repeated
    "Unknown tool" errors after a failed tool refresh).

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

        # Error-pattern detection:
        detector.record_error("tool_a", "Unknown tool: tool_a")
        detector.record_error("tool_b", "Unknown tool: tool_b")
        detector.record_error("tool_c", "Unknown tool: tool_c")
        detector.should_intervene_on_errors()  # True (3 consecutive errors)
    """

    def __init__(
        self,
        threshold: int = 3,
        window_size: int = 10,
        error_threshold: int | None = None,
    ) -> None:
        """
        Initialize the detector.

        Args:
            threshold: Number of identical calls before intervention (default: 3)
            window_size: Maximum number of calls to track (default: 10)
            error_threshold: Number of consecutive errors before intervention.
                Defaults to ``threshold * 2`` to allow a reasonable margin
                for transient failures while still catching doom loops.
        """
        self.threshold = threshold
        self.window: deque[ToolCallRecord] = deque(maxlen=window_size)

        # Error-pattern tracking
        self._error_threshold = error_threshold if error_threshold is not None else threshold * 2
        self._consecutive_errors: list[ToolErrorRecord] = []

    def _hash_input(self, input: Any) -> str:
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

    def record(self, tool: str, input: Any) -> None:
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

    def record_error(self, tool: str, error: str) -> None:
        """
        Record a tool error for consecutive-error tracking.

        Call this whenever a tool invocation fails ("Unknown tool",
        execution error, etc.).  A subsequent successful tool call
        should call :meth:`reset_errors` to reset the counter.

        Args:
            tool: Name of the tool that errored
            error: Error message
        """
        self._consecutive_errors.append(
            ToolErrorRecord(tool=tool, error=error, timestamp=time.time())
        )

    def reset_errors(self) -> None:
        """Reset the consecutive error counter (call after a successful tool execution)."""
        self._consecutive_errors = []

    @property
    def consecutive_error_count(self) -> int:
        """Return the current number of consecutive tool errors."""
        return len(self._consecutive_errors)

    def should_intervene(self, tool: str, input: Any) -> bool:
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

    def should_intervene_on_errors(self) -> bool:
        """
        Check if user intervention is needed due to consecutive errors.

        Returns True if the number of consecutive (unbroken by a success)
        tool errors has reached or exceeded ``error_threshold``.

        Returns:
            True if error-based intervention is needed, False otherwise.
        """
        return len(self._consecutive_errors) >= self._error_threshold

    def get_recent_errors(self, n: int = 5) -> list[ToolErrorRecord]:
        """Return the most recent error records."""
        return self._consecutive_errors[-n:]

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
        """Clear all recorded tool calls and errors."""
        self.window.clear()
        self._consecutive_errors = []

    def reset_for_new_conversation(self) -> None:
        """Reset detector for a new conversation."""
        self.clear()
