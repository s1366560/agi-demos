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
            return messages, self._empty_stats()
        total_tokens = sum(max(0, int(estimate_message_tokens(msg))) for msg in messages)
        max_tool_tokens = max(1, int(total_tokens * self._max_tool_output_ratio))
        tool_entries = self._collect_tool_entries(messages, estimate_message_tokens)
        if not tool_entries:
            return messages, self._empty_stats()

        keep_indexes = self._compute_keep_indexes(tool_entries, max_tool_tokens)
        updated, char_compacted, ratio_compacted = self._compact_tool_messages(
            messages, keep_indexes
        )
        modified_messages = char_compacted + ratio_compacted
        return updated, {
            "tool_messages": len(tool_entries),
            "max_tool_tokens": max_tool_tokens,
            "char_compacted": char_compacted,
            "ratio_compacted": ratio_compacted,
            "modified_messages": modified_messages,
        }

    @staticmethod
    def _empty_stats() -> dict[str, int]:
        return {
            "tool_messages": 0,
            "char_compacted": 0,
            "ratio_compacted": 0,
            "modified_messages": 0,
        }

    @staticmethod
    def _collect_tool_entries(
        messages: list[dict[str, Any]],
        estimate_message_tokens: Callable[[dict[str, Any]], int],
    ) -> list[tuple[int, int]]:
        """Collect (index, token_count) for tool messages with string content."""
        entries: list[tuple[int, int]] = []
        for idx, msg in enumerate(messages):
            if msg.get("role") != "tool":
                continue
            if not isinstance(msg.get("content"), str):
                continue
            entries.append((idx, max(1, int(estimate_message_tokens(msg)))))
        return entries

    @staticmethod
    def _compute_keep_indexes(
        tool_entries: list[tuple[int, int]], max_tool_tokens: int
    ) -> set[int]:
        """Determine which tool messages to keep based on token budget."""
        keep_indexes: set[int] = set()
        running = 0
        for idx, tool_tokens in reversed(tool_entries):
            if running + tool_tokens <= max_tool_tokens:
                keep_indexes.add(idx)
                running += tool_tokens
        return keep_indexes

    def _compact_tool_messages(
        self,
        messages: list[dict[str, Any]],
        keep_indexes: set[int],
    ) -> tuple[list[dict[str, Any]], int, int]:
        """Apply char and ratio compaction to tool messages."""
        updated: list[dict[str, Any]] = list(messages)
        char_compacted = 0
        ratio_compacted = 0
        for idx, msg in enumerate(messages):
            if msg.get("role") != "tool":
                continue
            content = msg.get("content")
            if not isinstance(content, str):
                continue

            next_content, was_char, was_ratio = self._compact_single_tool(
                content, idx in keep_indexes
            )
            if was_char:
                char_compacted += 1
            if was_ratio:
                ratio_compacted += 1
            if was_char or was_ratio:
                updated[idx] = {**msg, "content": next_content}
        return updated, char_compacted, ratio_compacted

    def _compact_single_tool(
        self, content: str, is_kept: bool
    ) -> tuple[str, bool, bool]:
        """Compact a single tool message. Returns (content, char_compacted, ratio_compacted)."""
        was_char = False
        was_ratio = False
        result = content

        if len(result) > self._max_tool_chars:
            result = (
                result[: self._max_tool_chars]
                + "\n[... tool output truncated by context guard]"
            )
            was_char = True

        if not is_kept:
            result = "[Tool output compacted by context guard to protect context budget]"
            was_ratio = True

        return result, was_char, was_ratio
