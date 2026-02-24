"""Progress handling for MCP tools.

This module provides utilities for handling progress notifications
from MCP tools during long-running operations.
"""

from collections.abc import Callable

# Type alias for progress callback
ProgressHandler = Callable[
    [str, str, float, float | None, str | None],
    None,
]
"""
Progress callback type.

Args:
    tool_name: Name of the tool reporting progress
    progress_token: Unique token for this progress tracking
    progress: Current progress value
    total: Total value if known, None otherwise
    message: Human-readable progress message

Returns:
    None (can be sync or async)
"""


class ProgressTracker:
    """Tracks progress for multiple concurrent operations."""

    def __init__(self) -> None:
        """Initialize the progress tracker."""
        self._active_progress: dict[str, dict] = {}

    def start_tracking(
        self,
        progress_token: str,
        tool_name: str,
        total: float | None = None,
    ) -> None:
        """
        Start tracking progress for an operation.

        Args:
            progress_token: Unique identifier for this progress
            tool_name: Name of the tool
            total: Expected total value if known
        """
        self._active_progress[progress_token] = {
            "tool_name": tool_name,
            "progress": 0.0,
            "total": total,
            "message": None,
        }

    def update_progress(
        self,
        progress_token: str,
        progress: float,
        message: str | None = None,
    ) -> dict | None:
        """
        Update progress for a tracked operation.

        Args:
            progress_token: Unique identifier for this progress
            progress: Current progress value
            message: Optional status message

        Returns:
            Updated progress dict, or None if not tracked
        """
        if progress_token not in self._active_progress:
            return None

        self._active_progress[progress_token]["progress"] = progress
        if message:
            self._active_progress[progress_token]["message"] = message

        return self._active_progress[progress_token].copy()

    def complete_tracking(self, progress_token: str) -> dict | None:
        """
        Mark a tracked operation as complete.

        Args:
            progress_token: Unique identifier for this progress

        Returns:
            Final progress dict, or None if not tracked
        """
        if progress_token not in self._active_progress:
            return None

        result = self._active_progress[progress_token].copy()
        del self._active_progress[progress_token]
        return result

    def get_progress(self, progress_token: str) -> dict | None:
        """
        Get current progress for a tracked operation.

        Args:
            progress_token: Unique identifier for this progress

        Returns:
            Progress dict, or None if not tracked
        """
        return self._active_progress.get(progress_token, {}).copy()

    def get_all_progress(self) -> dict[str, dict]:
        """
        Get all active progress tracking.

        Returns:
            Dict of progress_token to progress info
        """
        return {k: v.copy() for k, v in self._active_progress.items()}

    def clear_all(self) -> None:
        """Clear all tracked progress."""
        self._active_progress.clear()
