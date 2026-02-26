"""Declarative tool definition via the @tool_define decorator.

This module provides a decorator-based approach to defining agent tools,
replacing the class-based AgentToolBase / AgentTool hierarchy for new tools.

Usage::

    @tool_define(
        name="read_file",
        description="Read a file from the local filesystem.",
        parameters={
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Absolute path"},
            },
            "required": ["file_path"],
        },
        permission="read",
        category="filesystem",
    )
    async def read_file(ctx: ToolContext, file_path: str) -> ToolResult:
        content = await _do_read(file_path)
        return ToolResult(output=content, title=file_path)

After decoration, ``read_file`` is a :class:`ToolInfo` instance (not the
original function). The original async callable is stored in
``ToolInfo.execute`` and remains directly invocable.

Migration path
--------------
Existing class-based tools (``AgentToolBase`` subclasses) can be wrapped via
:func:`wrap_legacy_tool` without modification. New tools should prefer the
``@tool_define`` decorator.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# ToolInfo dataclass
# ---------------------------------------------------------------------------


@dataclass
class ToolInfo:
    """Metadata container for a tool definition.

    Attributes:
        name: Unique tool name (used in LLM tool calls).
        description: Human-readable description for the LLM.
        parameters: JSON Schema dict describing the tool's parameters.
        execute: The actual async callable.
        permission: Permission identifier (e.g., "bash", "write").
        category: Tool category for grouping (e.g., "filesystem", "terminal").
        model_filter: Optional callable that decides if tool is available
            for a given model identifier string.
        tags: Freeform tags for filtering.
    """

    name: str
    description: str
    parameters: dict[str, Any]
    execute: Callable[..., Awaitable[Any]]
    permission: str | None = None
    category: str = "general"
    model_filter: Callable[[str], bool] | None = None
    tags: frozenset[str] = field(default_factory=lambda: frozenset[str]())


# ---------------------------------------------------------------------------
# Module-level auto-discovery registry
# ---------------------------------------------------------------------------

_TOOL_REGISTRY: dict[str, ToolInfo] = {}


def get_registered_tools() -> dict[str, ToolInfo]:
    """Return all tools registered via ``@tool_define``."""
    return dict(_TOOL_REGISTRY)


def clear_registry() -> None:
    """Clear the tool registry (for testing)."""
    _TOOL_REGISTRY.clear()


# ---------------------------------------------------------------------------
# @tool_define decorator
# ---------------------------------------------------------------------------


def tool_define(
    name: str,
    description: str,
    parameters: dict[str, Any],
    *,
    permission: str | None = None,
    category: str = "general",
    model_filter: Callable[[str], bool] | None = None,
    tags: frozenset[str] | None = None,
) -> Callable[[Callable[..., Awaitable[Any]]], ToolInfo]:
    """Decorator factory that converts an async function into a :class:`ToolInfo`.

    The returned object is a ``ToolInfo`` instance, **not** the original
    function. The original callable is accessible via ``ToolInfo.execute``.

    The decorator also registers the tool in the module-level
    ``_TOOL_REGISTRY`` for auto-discovery.

    Args:
        name: Unique tool name for LLM function calling.
        description: Human-readable description shown to the LLM.
        parameters: JSON Schema dict for the tool's parameters.
        permission: Optional permission identifier (e.g., "bash", "write").
        category: Grouping category (default ``"general"``).
        model_filter: Optional predicate ``(model_id) -> bool`` that
            controls whether the tool is offered to a specific model.
        tags: Optional freeform tags for filtering.

    Returns:
        A decorator that accepts an async callable and returns a
        :class:`ToolInfo`.
    """

    def decorator(fn: Callable[..., Awaitable[Any]]) -> ToolInfo:
        info = ToolInfo(
            name=name,
            description=description,
            parameters=parameters,
            execute=fn,
            permission=permission,
            category=category,
            model_filter=model_filter,
            tags=tags if tags is not None else frozenset(),
        )
        # Attach metadata to the original function for introspection.
        fn._tool_info = info  # type: ignore[attr-defined]

        # Register for auto-discovery.
        _TOOL_REGISTRY[name] = info

        return info

    return decorator


# ---------------------------------------------------------------------------
# OpenAI function-calling format conversion
# ---------------------------------------------------------------------------


def tool_info_to_openai_format(info: ToolInfo) -> dict[str, Any]:
    """Convert a :class:`ToolInfo` to the OpenAI function-calling schema.

    Returns a dict suitable for inclusion in the ``tools`` array of an
    OpenAI-style chat completion request::

        {
            "type": "function",
            "function": {
                "name": "...",
                "description": "...",
                "parameters": { ... },
            },
        }
    """
    return {
        "type": "function",
        "function": {
            "name": info.name,
            "description": info.description,
            "parameters": info.parameters,
        },
    }


# ---------------------------------------------------------------------------
# Legacy tool compatibility shim
# ---------------------------------------------------------------------------


def wrap_legacy_tool(tool: Any) -> ToolInfo:
    """Wrap a legacy ``AgentToolBase`` instance as a :class:`ToolInfo`.

    This allows existing class-based tools to work with the new
    ToolPipeline without modification. Accepts any object that exposes
    ``name``, ``description`` (or empty string), and one of
    ``get_parameters()`` / ``get_parameters_schema()`` / ``parameters``.

    Args:
        tool: A legacy tool instance (typically an ``AgentToolBase``
            subclass).

    Returns:
        A :class:`ToolInfo` wrapping the legacy tool.
    """
    parameters: dict[str, Any] = {}
    if hasattr(tool, "get_parameters"):
        parameters = tool.get_parameters()
    elif hasattr(tool, "get_parameters_schema"):
        parameters = tool.get_parameters_schema()
    elif hasattr(tool, "parameters"):
        parameters = tool.parameters

    permission: str | None = getattr(tool, "permission", None)

    return ToolInfo(
        name=tool.name,
        description=getattr(tool, "description", ""),
        parameters=parameters,
        execute=tool.execute,
        permission=permission,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
    "ToolInfo",
    "clear_registry",
    "get_registered_tools",
    "tool_define",
    "tool_info_to_openai_format",
    "wrap_legacy_tool",
]
