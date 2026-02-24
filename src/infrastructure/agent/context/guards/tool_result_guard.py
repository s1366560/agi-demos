"""Guard that caps tool-result payload size before compression."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


class ToolResultGuard:
    """Constrain tool output by per-message size and total-context ratio."""

    name = "tool_result_guard"

    def __init__(
        self,
        *,
        max_tool_chars: int = 6000,
        max_tool_output_ratio: float = 0.35,
    ) -> None:
        self._max_tool_chars = max(200, int(max_tool_chars))
        self._max_tool_output_ratio = min(max(float(max_tool_output_ratio), 0.05), 0.95)

    def apply(
        self,
        messages: list[dict[str, Any]],
        *,
        estimate_message_tokens: Callable[[dict[str, Any]], int],
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        if not messages:
            return messages, {
                "tool_messages": 0,
                "char_compacted": 0,
                "ratio_compacted": 0,
                "modified_messages": 0,
            }

        total_tokens = sum(max(0, int(estimate_message_tokens(msg))) for msg in messages)
        max_tool_tokens = max(1, int(total_tokens * self._max_tool_output_ratio))

        tool_entries: list[tuple[int, int]] = []
        for idx, msg in enumerate(messages):
            if msg.get("role") != "tool":
                continue
            if not isinstance(msg.get("content"), str):
                continue
            tool_entries.append((idx, max(1, int(estimate_message_tokens(msg)))))

        if not tool_entries:
            return messages, {
                "tool_messages": 0,
                "char_compacted": 0,
                "ratio_compacted": 0,
                "modified_messages": 0,
            }

        keep_indexes: set[int] = set()
        running_tool_tokens = 0
        for idx, tool_tokens in reversed(tool_entries):
            if running_tool_tokens + tool_tokens <= max_tool_tokens:
                keep_indexes.add(idx)
                running_tool_tokens += tool_tokens

        updated: list[dict[str, Any]] = list(messages)
        char_compacted = 0
        ratio_compacted = 0

        for idx, msg in enumerate(messages):
            if msg.get("role") != "tool":
                continue
            content = msg.get("content")
            if not isinstance(content, str):
                continue

            next_content = content
            compacted = False

            if len(next_content) > self._max_tool_chars:
                next_content = (
                    next_content[: self._max_tool_chars]
                    + "\n[... tool output truncated by context guard]"
                )
                char_compacted += 1
                compacted = True

            if idx not in keep_indexes:
                next_content = "[Tool output compacted by context guard to protect context budget]"
                ratio_compacted += 1
                compacted = True

            if compacted:
                updated[idx] = {**msg, "content": next_content}

        modified_messages = char_compacted + ratio_compacted
        return updated, {
            "tool_messages": len(tool_entries),
            "max_tool_tokens": max_tool_tokens,
            "char_compacted": char_compacted,
            "ratio_compacted": ratio_compacted,
            "modified_messages": modified_messages,
        }
