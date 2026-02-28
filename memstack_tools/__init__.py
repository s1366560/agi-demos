"""MemStack Tools SDK -- public API for custom tool development.

This package provides the public interface for writing custom tools
that live in ``.memstack/tools/``.  Import everything you need from
here instead of reaching into ``src.infrastructure.agent.tools.*``.

Usage::

    from memstack_tools import tool_define, ToolResult

    @tool_define(
        name="my_tool",
        description="One-line description shown to the LLM.",
        parameters={
            "type": "object",
            "properties": {
                "arg1": {"type": "string", "description": "..."},
            },
            "required": ["arg1"],
        },
        permission="read",
        category="custom",
    )
    async def my_tool(ctx, arg1: str) -> ToolResult:
        return ToolResult(output=f"Got {arg1}")
"""

from __future__ import annotations

# Re-export public API from internal modules.
# These are the ONLY symbols custom tools should depend on.
from src.infrastructure.agent.tools.define import ToolInfo, tool_define
from src.infrastructure.agent.tools.result import ToolAttachment, ToolEvent, ToolResult

__all__ = [
    "ToolAttachment",
    "ToolEvent",
    "ToolInfo",
    "ToolResult",
    "tool_define",
]
