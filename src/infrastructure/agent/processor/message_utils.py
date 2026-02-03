"""
Message utilities for SessionProcessor.

Helper functions for working with conversation messages.
"""

from typing import Any, Dict, List, Optional


def extract_user_query(messages: List[Dict[str, Any]]) -> Optional[str]:
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
            return content
    return None


def classify_tool_by_description(tool_name: str, description: str) -> str:
    """
    Classify tool into a category based on its description.

    Uses semantic keywords in the tool's description to determine its purpose,
    supporting dynamic tool addition via MCP or Skills without hardcoded names.

    Args:
        tool_name: Name of the tool
        description: Tool description

    Returns:
        Category string: "search", "scrape", "memory", "entity", "graph", "code", "summary", "other"
    """
    desc_lower = description.lower()

    # Search tools: find information from web, databases, etc.
    search_keywords = ["search", "搜索", "查找", "find", "query", "查询", "bing", "google"]
    if any(kw in desc_lower for kw in search_keywords) and "web" in desc_lower:
        return "search"

    # Scrape tools: extract content from web pages
    scrape_keywords = ["scrape", "抓取", "extract", "提取", "fetch", "获取", "crawl", "爬取"]
    if any(kw in desc_lower for kw in scrape_keywords) and any(
        w in desc_lower for w in ["web", "page", "网页", "html", "url"]
    ):
        return "scrape"

    # Memory tools: access knowledge base
    memory_keywords = ["memory", "记忆", "knowledge", "知识", "recall", "回忆", "episodic"]
    if any(kw in desc_lower for kw in memory_keywords):
        return "memory"

    # Entity tools: lookup entities in knowledge graph
    entity_keywords = ["entity", "实体", "lookup", "查找"]
    if any(kw in desc_lower for kw in entity_keywords):
        return "entity"

    # Graph tools: query knowledge graph
    graph_keywords = ["graph", "图谱", "cypher", "relationship", "关系", "node", "节点"]
    if any(kw in desc_lower for kw in graph_keywords):
        return "graph"

    # Code tools: execute code
    code_keywords = ["code", "代码", "execute", "执行", "run", "运行", "python", "script"]
    if any(kw in desc_lower for kw in code_keywords):
        return "code"

    # Summary tools: summarize or synthesize information
    summary_keywords = ["summary", "总结", "summarize", "概括", "synthesize", "综合"]
    if any(kw in desc_lower for kw in summary_keywords):
        return "summary"

    return "other"


def build_tool_result_message(call_id: str, tool_name: str, result: str) -> Dict[str, Any]:
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
    tool_calls: List[Dict[str, Any]],
    content: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Build an assistant message with tool calls.

    Args:
        tool_calls: List of tool call dicts
        content: Optional text content

    Returns:
        Message dict in OpenAI format
    """
    msg: Dict[str, Any] = {
        "role": "assistant",
        "tool_calls": tool_calls,
    }
    if content:
        msg["content"] = content
    return msg
