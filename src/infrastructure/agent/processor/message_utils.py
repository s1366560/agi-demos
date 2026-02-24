"""
Message utilities for SessionProcessor.

Helper functions for working with conversation messages.
"""

from typing import Any, cast


def extract_user_query(messages: list[dict[str, Any]]) -> str | None:
    """
    Extract the latest user query from messages.

    Handles both simple string content and multimodal content arrays.
    For multimodal content, extracts the text parts.

    Args:
        messages: List of messages in OpenAI format

    Returns:
        The user query text, or None if not found
    """
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            # Handle multimodal content (list of content parts)
            if isinstance(content, list):
                # Extract text from content parts
                text_parts = []
                for part in content:
                    if isinstance(part, dict):
                        if part.get("type") == "text":
                            text_parts.append(part.get("text", ""))
                    elif isinstance(part, str):
                        text_parts.append(part)
                return " ".join(text_parts) if text_parts else ""
            # Simple string content
            return cast(str | None, content)
    return None


# Classification rules: (category, primary_keywords, secondary_keywords_or_None)
# A tool matches a category if any primary keyword is found AND
# (secondary_keywords is None OR any secondary keyword is found).
_TOOL_CATEGORY_RULES: list[tuple[str, list[str], list[str] | None]] = [
    (
        "search",
        ["search", "\u641c\u7d22", "\u67e5\u627e", "find", "query", "\u67e5\u8be2", "bing", "google"],
        ["web"],
    ),
    (
        "scrape",
        ["scrape", "\u6293\u53d6", "extract", "\u63d0\u53d6", "fetch", "\u83b7\u53d6", "crawl", "\u722c\u53d6"],
        ["web", "page", "\u7f51\u9875", "html", "url"],
    ),
    (
        "memory",
        ["memory", "\u8bb0\u5fc6", "knowledge", "\u77e5\u8bc6", "recall", "\u56de\u5fc6", "episodic"],
        None,
    ),
    (
        "entity",
        ["entity", "\u5b9e\u4f53", "lookup", "\u67e5\u627e"],
        None,
    ),
    (
        "graph",
        ["graph", "\u56fe\u8c31", "cypher", "relationship", "\u5173\u7cfb", "node", "\u8282\u70b9"],
        None,
    ),
    (
        "code",
        ["code", "\u4ee3\u7801", "execute", "\u6267\u884c", "run", "\u8fd0\u884c", "python", "script"],
        None,
    ),
    (
        "summary",
        ["summary", "\u603b\u7ed3", "summarize", "\u6982\u62ec", "synthesize", "\u7efc\u5408"],
        None,
    ),
]


def _matches_category_rule(
    desc_lower: str, primary: list[str], secondary: list[str] | None
) -> bool:
    """Check if description matches a category rule."""
    if not any(kw in desc_lower for kw in primary):
        return False
    if secondary is None:
        return True
    return any(kw in desc_lower for kw in secondary)


def classify_tool_by_description(tool_name: str, description: str) -> str:
    """
    Classify tool into a category based on its description.
    supporting dynamic tool addition via MCP or Skills without hardcoded names.
    Args:
        tool_name: Name of the tool
        description: Tool description
        Category string: "search", "scrape", "memory", "entity", "graph", "code", "summary", "other"
    """
    desc_lower = description.lower()
    for category, primary, secondary in _TOOL_CATEGORY_RULES:
        if _matches_category_rule(desc_lower, primary, secondary):
            return category
    return "other"


def build_tool_result_message(call_id: str, tool_name: str, result: str) -> dict[str, Any]:
    """
    Build a tool result message in OpenAI format.

    Args:
        call_id: The tool call ID
        tool_name: Name of the tool
        result: Tool execution result

    Returns:
        Message dict in OpenAI tool result format
    """
    return {
        "role": "tool",
        "tool_call_id": call_id,
        "name": tool_name,
        "content": result,
    }


def build_assistant_message_with_tool_calls(
    tool_calls: list[dict[str, Any]],
    content: str | None = None,
) -> dict[str, Any]:
    """
    Build an assistant message with tool calls.

    Args:
        tool_calls: List of tool call dicts
        content: Optional text content

    Returns:
        Message dict in OpenAI format
    """
    msg: dict[str, Any] = {
        "role": "assistant",
        "tool_calls": tool_calls,
    }
    if content:
        msg["content"] = content
    return msg
