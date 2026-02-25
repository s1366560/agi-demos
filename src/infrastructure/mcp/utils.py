"""Shared MCP utility functions."""

from __future__ import annotations

import json
from typing import Any


def parse_tool_result(result: dict[str, Any]) -> dict[str, Any] | list[Any] | str:
    """Parse MCP tool result content, extracting JSON if present.

    Handles the standard MCP content format where tool results are
    returned as a list of content items with type/text fields.

    Args:
        result: Raw tool result dict with optional ``content`` key.

    Returns:
        Parsed JSON object if text is valid JSON, otherwise the raw text string.
        Returns the original *result* dict when content is empty.
    """
    content = result.get("content", [])
    if not content:
        return result

    # Extract text from content items
    text_parts: list[str] = []
    for item in content:
        if isinstance(item, dict) and item.get("type") == "text":
            text_parts.append(item.get("text", ""))

    text = "\n".join(text_parts)
    if not text:
        return result

    # Try to parse as JSON
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return text
