"""
Tool conversion utilities for ReAct Agent.

Converts tool instances to ToolDefinition format used by SessionProcessor.
Supports both legacy class-based tools (AgentToolBase subclasses) and new
@tool_define decorator-based tools (ToolInfo instances).
"""

from __future__ import annotations

from typing import Any, cast

from src.infrastructure.agent.tools.define import ToolInfo

from .processor import ToolDefinition


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
    """
    method_candidates: list[tuple[str, bool]] = [
        ("execute", True),  # may be sync or async; caller checks
        ("ainvoke", True),
        ("_arun", True),
        ("_run", False),
        ("run", False),
    ]
    for attr, is_async in method_candidates:
        method = getattr(tool_instance, attr, None)
        if method is not None:
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
                result = method(**kwargs)
                if hasattr(result, "__await__"):
                    return await result
                return result
            return method(**kwargs)
        except Exception as e:
            return f"Error executing tool {tool_name}: {e!s}"

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
        except Exception as e:
            return f"Error executing tool {tool_info.name}: {e!s}"

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
                    _tool_instance=tool,  # ToolInfo stored for pipeline detection
                )
            )
            continue

        # Handle legacy class-based tools (AgentToolBase subclasses)
        if not _is_tool_visible_to_model(tool):
            continue

        definitions.append(
            ToolDefinition(
                name=name,
                description=getattr(tool, "description", f"Tool: {name}"),
                parameters=_get_tool_parameters(tool),
                execute=_make_execute_wrapper(tool, name),
                permission=getattr(tool, "permission", None),
                _tool_instance=tool,
            )
        )

    return definitions
