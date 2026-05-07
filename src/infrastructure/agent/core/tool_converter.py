"""
Tool conversion utilities for ReAct Agent.

Converts tool instances to ToolDefinition format used by SessionProcessor.
Supports both legacy class-based tools (AgentToolBase subclasses) and new
@tool_define decorator-based tools (ToolInfo instances).
"""

from __future__ import annotations

import inspect
import logging
from typing import Any, cast

from src.infrastructure.agent.tools.define import ToolInfo

from .processor import ToolDefinition

logger = logging.getLogger(__name__)


def _is_tool_visible_to_model(tool: Any) -> bool:
    """Check whether a tool should be included in the LLM tool list.

    SEP-1865: Tools whose _meta.ui.visibility is ["app"] only
    (not including "model") are excluded from the LLM tool list.
    They remain callable by the MCP App UI through the tool call proxy.
    """
    # Check MCPToolSchema.is_model_visible or raw _schema dict for visibility.
    tool_schema = getattr(tool, "_tool_schema", None) or getattr(tool, "tool_info", None)
    if tool_schema is not None and hasattr(tool_schema, "is_model_visible"):
        if not tool_schema.is_model_visible:
            return False

    # Also check raw dict schema (SandboxMCPToolWrapper stores _schema as dict)
    raw_schema = getattr(tool, "_schema", None)
    if isinstance(raw_schema, dict):
        meta = raw_schema.get("_meta")
        if isinstance(meta, dict):
            ui = meta.get("ui")
            if isinstance(ui, dict):
                visibility = ui.get("visibility", ["model", "app"])
                if "model" not in visibility:
                    return False

    return True


def _get_tool_parameters(tool: Any) -> dict[str, Any]:
    """Extract parameters schema from a tool instance."""
    if hasattr(tool, "get_parameters_schema"):
        return cast(dict[str, Any], tool.get_parameters_schema())
    if hasattr(tool, "args_schema"):
        schema = tool.args_schema
        if hasattr(schema, "model_json_schema"):
            return cast(dict[str, Any], schema.model_json_schema())
    return {"type": "object", "properties": {}, "required": []}


def _resolve_execute_method(
    tool_instance: Any,
) -> tuple[Any, bool] | None:
    """Find the best execute method on a tool instance.

    Returns:
        Tuple of (bound method, is_async) or None if no method found.

    Async detection uses :func:`inspect.iscoroutinefunction` so a sync
    ``execute`` that happens to live on a class with that name does not get
    awaited (and a true async ``__call__`` is correctly awaited).
    """
    method_candidates: list[str] = [
        "execute",
        "ainvoke",
        "_arun",
        "_run",
        "run",
        "__call__",
    ]
    for attr in method_candidates:
        method = getattr(tool_instance, attr, None)
        if method is None:
            continue
        is_async = inspect.iscoroutinefunction(method) or inspect.iscoroutinefunction(
            getattr(method, "__func__", method)
        )
        return method, is_async
    return None


def _make_execute_wrapper(tool_instance: Any, tool_name: str) -> Any:
    """Create an async execute wrapper for a tool instance."""

    resolved = _resolve_execute_method(tool_instance)

    async def execute_wrapper(**kwargs: Any) -> Any:
        """Wrapper to execute tool."""
        try:
            if resolved is None:
                raise ValueError(f"Tool {tool_name} has no execute method")
            method, is_async = resolved
            if is_async:
                # Method is a coroutine function -> always returns awaitable.
                return await method(**kwargs)
            result = method(**kwargs)
            # Defensive: a sync-typed callable may still return an awaitable
            # at runtime (e.g. duck-typed wrappers); await it if so.
            if inspect.isawaitable(result):
                return await result
            return result
        except Exception:
            # Do NOT leak the raw exception text to the LLM: it can
            # contain stack traces, file paths, secrets pulled from env
            # vars, or third-party API error bodies. Log fully on the
            # server, return a structured, safe error to the model.
            logger.exception(
                "[tool_converter] tool execution failed",
                extra={"tool": tool_name},
            )
            return {
                "error": "tool_execution_failed",
                "tool": tool_name,
                "message": "Tool raised an exception. See server logs for details.",
            }

    return execute_wrapper


def _make_toolinfo_execute_wrapper(tool_info: ToolInfo) -> Any:
    """Create an async execute wrapper for a ToolInfo-based tool.

    When the ToolPipeline is active, the pipeline constructs a ToolContext
    and passes it via _ToolAdapter.  For the legacy (non-pipeline) path,
    the ToolDefinition.execute is called directly with **kwargs from the
    LLM.  ToolInfo functions expect ``ctx: ToolContext`` as the first arg,
    but the legacy processor path never supplies it.  This wrapper creates
    a minimal ToolContext so the function still works in both paths.
    """

    async def execute_wrapper(**kwargs: Any) -> Any:
        """Wrapper that supplies a stub ToolContext when none is provided."""
        import asyncio

        from src.infrastructure.agent.tools.context import ToolContext

        ctx = ToolContext(
            session_id="",
            message_id="",
            call_id="",
            agent_name="",
            conversation_id="",
            abort_signal=asyncio.Event(),
        )
        try:
            return await tool_info.execute(ctx, **kwargs)
        except Exception:
            logger.exception(
                "[tool_converter] ToolInfo execution failed",
                extra={"tool": tool_info.name},
            )
            return {
                "error": "tool_execution_failed",
                "tool": tool_info.name,
                "message": "Tool raised an exception. See server logs for details.",
            }

    return execute_wrapper


def convert_tools(tools: dict[str, Any]) -> list[ToolDefinition]:
    """
    Convert tool instances to ToolDefinition format.

    Supports two input types:
    - Legacy class-based tools (AgentToolBase subclasses): wrapped via
      _make_execute_wrapper with the original instance stored in
      _tool_instance.
    - New decorator-based tools (ToolInfo instances from @tool_define):
      wrapped via _make_toolinfo_execute_wrapper which injects a stub
      ToolContext.  No _tool_instance is stored because ToolInfo-based
      tools emit events through ctx.emit() instead of _pending_events.

    Tools whose _meta.ui.visibility is ["app"] only (not including "model")
    are excluded from the LLM tool list per SEP-1865 spec. They remain
    callable by the MCP App UI through the tool call proxy.

    Args:
        tools: Dictionary of tool name -> tool instance or ToolInfo

    Returns:
        List of ToolDefinition objects
    """
    definitions = []

    for name, tool in tools.items():
        # Handle new @tool_define based tools (ToolInfo instances)
        if isinstance(tool, ToolInfo):
            definitions.append(
                ToolDefinition(
                    name=tool.name,
                    description=tool.description,
                    parameters=tool.parameters,
                    execute=_make_toolinfo_execute_wrapper(tool),
                    permission=tool.permission,
                    aliases=tool.aliases,
                    _tool_instance=tool,  # ToolInfo stored for pipeline detection
                )
            )
            continue

        # Handle legacy class-based tools (AgentToolBase subclasses)
        if not _is_tool_visible_to_model(tool):
            continue

        legacy_aliases_raw = getattr(tool, "aliases", ())
        legacy_aliases: tuple[str, ...] = tuple(legacy_aliases_raw) if legacy_aliases_raw else ()
        definitions.append(
            ToolDefinition(
                name=name,
                description=getattr(tool, "description", f"Tool: {name}"),
                parameters=_get_tool_parameters(tool),
                execute=_make_execute_wrapper(tool, name),
                permission=getattr(tool, "permission", None),
                aliases=legacy_aliases,
                _tool_instance=tool,
            )
        )

    # Lazy import to avoid basedpyright resolution timing issues
    from src.infrastructure.agent.prompts import tool_summaries as _ts

    _ts.apply_tool_summaries(definitions)
    return cast(list[ToolDefinition], _ts.sort_by_tool_order(definitions))
