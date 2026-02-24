"""Guard that caps conversation history length before compression."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


class HistoryTurnGuard:
    """Limit history messages while preserving the leading system message."""

    name = "history_turn_guard"

    def __init__(self, *, max_messages: int = 120) -> None:
        self._max_messages = max(4, int(max_messages))

    def apply(
        self,
        messages: list[dict[str, Any]],
        *,
        estimate_message_tokens: Callable[[dict[str, Any]], int],
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        if len(messages) <= self._max_messages:
            return messages, {
                "max_messages": self._max_messages,
                "dropped_messages": 0,
                "modified_messages": 0,
            }

        has_system_prefix = bool(messages) and messages[0].get("role") == "system"
        prefix = messages[:1] if has_system_prefix else []
        body = messages[1:] if has_system_prefix else messages

        if len(body) <= self._max_messages:
            return messages, {
                "max_messages": self._max_messages,
                "dropped_messages": 0,
                "modified_messages": 0,
            }

        dropped = len(body) - self._max_messages
        trimmed = prefix + body[-self._max_messages :]
        return trimmed, {
            "max_messages": self._max_messages,
            "dropped_messages": dropped,
            "modified_messages": dropped,
        }
