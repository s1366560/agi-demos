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

        # Only start retained history at a user turn. A tool result may refer to a
        # parallel call earlier in its turn. Always retain runtime instructions.
        boundary = len(messages) - self._max_messages
        user_indexes = [i for i, message in enumerate(messages) if message.get("role") == "user"]
        start = next(
            (i for i in user_indexes if i >= boundary), user_indexes[-1] if user_indexes else 0
        )
        trimmed = [
            message
            for i, message in enumerate(messages)
            if i >= start or message.get("role") in {"developer", "system"}
        ]
        dropped = len(messages) - len(trimmed)
        return trimmed, {
            "max_messages": self._max_messages,
            "dropped_messages": dropped,
            "modified_messages": dropped,
        }
