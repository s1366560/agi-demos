"""Helpers for normalizing LLM response shapes used by graph services."""

from __future__ import annotations

from typing import cast


def extract_response_content(response: object) -> str:
    """Extract text content from common LLM response containers."""
    if isinstance(response, str):
        return response
    if isinstance(response, dict):
        response_dict = cast(dict[str, object], response)
        content = response_dict.get("content")
        if content is None:
            return ""
        return content if isinstance(content, str) else str(content)
    content = cast(object, getattr(response, "content", None))
    if content is None:
        return "" if response is None else str(response)
    return content if isinstance(content, str) else str(content)
