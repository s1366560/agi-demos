"""Plugin tool adapter: wraps raw plugin objects as ToolInfo.

Plugin tool factories (registered via register_tool_factory or
register_sandbox_tool_factory) return arbitrary Python objects.
This module normalizes them into ToolInfo instances that the agent
pipeline can consume.

Handles:
- Objects with __call__ (e.g. PDFTool subclasses)
- Objects with execute / ainvoke / _arun / _run / run methods
- ToolInfo instances (returned as-is)
- dict-returning tools (normalized to ToolResult)

This fixes Root Causes 2 and 4 from PLUGIN_TOOL_PIPELINE_FIX.md.
"""

from __future__ import annotations

import inspect as _inspect
import logging
from collections.abc import Callable
from typing import Any, cast

from src.infrastructure.agent.tools.define import ToolInfo
from src.infrastructure.agent.tools.result import ToolResult

logger = logging.getLogger(__name__)

# Methods to look for on plugin tool objects, in priority order.
# Matches the order used in tool_converter._resolve_execute_method.
_CALLABLE_CANDIDATES: list[str] = [
    "execute",
    "ainvoke",
    "_arun",
    "_run",
    "run",
    "__call__",
]


def adapt_plugin_tool(
    tool_name: str,
    tool_impl: object,
    plugin_name: str,
) -> ToolInfo | None:
    """Adapt a raw plugin tool object into a ToolInfo.

    Plugin tool factories return arbitrary objects. This function inspects
    the object and wraps it as a ToolInfo that the agent pipeline can
    consume.

    Args:
        tool_name: Name to register the tool under.
        tool_impl: The raw object returned by the plugin factory.
        plugin_name: Name of the originating plugin (for logging/tags).

    Returns:
        A ToolInfo wrapping the plugin tool, or None if the object
        has no usable callable method.
    """
    # Already a ToolInfo -- pass through
    if isinstance(tool_impl, ToolInfo):
        return tool_impl

    # Extract description
    description: str = getattr(tool_impl, "description", None) or f"Plugin tool: {tool_name}"

    # Extract parameters schema
    parameters: dict[str, Any] = {}
    if hasattr(tool_impl, "get_parameters_schema"):
        schema = tool_impl.get_parameters_schema()
        if isinstance(schema, dict):
            parameters = schema
    elif hasattr(tool_impl, "parameters"):
        params = tool_impl.parameters
        if isinstance(params, dict):
            parameters = params
    # If still empty, attempt to introspect callable signature
    if not parameters:
        parameters = _introspect_callable_parameters(tool_impl, tool_name)

    # Find the callable
    callable_fn = _find_callable(tool_impl)
    if callable_fn is None:
        logger.warning(
            "Plugin tool '%s' from '%s' has no callable method, skipping",
            tool_name,
            plugin_name,
        )
        return None

    # Build the async execute wrapper
    async def execute(ctx: object | None = None, **kwargs: object) -> ToolResult:
        """Adapted plugin tool execution."""
        _ = ctx  # Plugin tools don't use ToolContext

        try:
            result = callable_fn(**kwargs)
            if _inspect.isawaitable(result):
                result = await result

            # Normalize return value to ToolResult
            return _normalize_result(result, tool_name)
        except Exception as e:
            logger.warning(
                "Plugin tool '%s' raised an exception: %s",
                tool_name,
                e,
                exc_info=True,
            )
            return ToolResult(output=f"Plugin tool error: {e}", is_error=True)

    return ToolInfo(
        name=tool_name,
        description=description,
        parameters=parameters,
        execute=execute,
        permission=getattr(tool_impl, "permission", None),
        category="plugin",
        tags=frozenset({"plugin", plugin_name}),
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _find_callable(tool_impl: object) -> Callable[..., Any] | None:
    """Locate the best callable method on a plugin tool object.

    Returns the callable, or None if nothing suitable was found.
    """
    for attr_name in _CALLABLE_CANDIDATES:
        fn = getattr(tool_impl, attr_name, None)
        if fn is not None and callable(fn):
            return cast(Callable[..., Any], fn)
    return None


def _normalize_result(result: object, tool_name: str) -> ToolResult:
    """Convert an arbitrary tool return value to ToolResult.

    Handles:
    - ToolResult (returned as-is)
    - dict with status/error keys (convention for plugin tools)
    - str (wrapped directly)
    - other (str-ified)

    Args:
        result: Raw return from the plugin tool callable.
        tool_name: Name of the tool (for diagnostics).

    Returns:
        A structured ToolResult.
    """
    if isinstance(result, ToolResult):
        return result

    if isinstance(result, dict):
        # Convention: {"status": "error", ...} or {"error": "..."}
        status = result.get("status", "success")
        if status == "error":
            error_msg = result.get("error", result.get("message", str(result)))
            return ToolResult(output=str(error_msg), is_error=True)
        # For success dicts, serialize to a readable string
        import json as _json

        try:
            output = _json.dumps(result, ensure_ascii=False, indent=2)
        except (TypeError, ValueError):
            output = str(result)
        return ToolResult(output=output)

    if isinstance(result, str):
        return ToolResult(output=result)

    return ToolResult(output=str(result))


def _introspect_callable_parameters(
    tool_impl: object,
    tool_name: str,
) -> dict[str, Any]:
    """Introspect a callable's signature to generate a JSON Schema parameters dict.

    This enables plugin tools that don't declare explicit schemas to still
    work with the LLM function-calling interface.

    Args:
        tool_impl: The plugin tool object.
        tool_name: Name of the tool (for logging).

    Returns:
        A JSON Schema-compatible dict with type/properties/required.
    """
    callable_fn = _find_callable(tool_impl)
    if callable_fn is None:
        return {"type": "object", "properties": {}, "required": []}

    try:
        sig = _inspect.signature(callable_fn)
    except (ValueError, TypeError):
        logger.debug("Cannot introspect signature for plugin tool '%s'", tool_name)
        return {"type": "object", "properties": {}, "required": []}

    properties: dict[str, Any] = {}
    required: list[str] = []

    # Skip common non-user parameters
    _skip_params = {"self", "cls", "ctx", "context", "kwargs", "args"}

    for param_name, param in sig.parameters.items():
        if param_name in _skip_params:
            continue
        if param.kind in (
            _inspect.Parameter.VAR_POSITIONAL,
            _inspect.Parameter.VAR_KEYWORD,
        ):
            continue

        prop: dict[str, Any] = {}

        # Infer type from annotation
        annotation = param.annotation
        if annotation is not _inspect.Parameter.empty:
            _type_map: dict[type, str] = {
                str: "string",
                int: "integer",
                float: "number",
                bool: "boolean",
                list: "array",
                dict: "object",
            }
            origin = getattr(annotation, "__origin__", annotation)
            prop["type"] = _type_map.get(origin, "string")
        else:
            prop["type"] = "string"

        # Handle default values
        if param.default is _inspect.Parameter.empty:
            required.append(param_name)
        elif param.default is not None:
            prop["default"] = param.default

        properties[param_name] = prop

    return {
        "type": "object",
        "properties": properties,
        "required": required,
    }
