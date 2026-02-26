"""Convert plugin-provided tools to ToolInfo instances.

Plugin tools are created by PluginToolFactory callables registered in
AgentPluginRegistry. This module bridges the plugin system and the new
ToolInfo-based pipeline by converting plugin tool outputs to first-class
ToolInfo instances.

Plugin factories return ``dict[str, Any]`` where each value can be:
- An ``AgentToolBase`` subclass instance (has ``.execute(**kwargs)``)
- A callable (async function)
- A dict with ``name``, ``description``, ``parameters``, and ``execute`` keys

This module handles all three forms.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, cast

from src.infrastructure.agent.plugins.registry import (
    AgentPluginRegistry,
    PluginToolBuildContext,
)
from src.infrastructure.agent.tools.define import ToolInfo, wrap_legacy_tool

logger = logging.getLogger(__name__)


def _make_plugin_tags(plugin_name: str) -> frozenset[str]:
    """Build the tag set for a plugin tool."""
    if plugin_name:
        return frozenset({"plugin", plugin_name})
    return frozenset({"plugin"})


def plugin_tool_to_info(
    tool_name: str,
    tool_impl: Any,
    *,
    plugin_name: str = "",
) -> ToolInfo | None:
    """Convert a single plugin-provided tool to ToolInfo.

    Handles three plugin tool forms:
    1. AgentToolBase instance -- uses wrap_legacy_tool()
    2. Dict with name/description/parameters/execute -- creates ToolInfo directly
    3. Async callable -- wraps as ToolInfo with minimal metadata

    Args:
        tool_name: The tool name (key from plugin factory output).
        tool_impl: The tool implementation (value from plugin factory output).
        plugin_name: Source plugin name for logging.

    Returns:
        ToolInfo instance, or None if conversion fails.
    """
    try:
        tags = _make_plugin_tags(plugin_name)

        # Form 1: Legacy AgentToolBase instance
        if hasattr(tool_impl, "execute") and hasattr(tool_impl, "name"):
            info = wrap_legacy_tool(tool_impl)
            return ToolInfo(
                name=tool_name,
                description=info.description,
                parameters=info.parameters,
                execute=info.execute,
                permission=info.permission,
                category="plugin",
                tags=tags,
            )

        # Form 2: Dict with tool definition
        if isinstance(tool_impl, dict):
            execute_fn = tool_impl.get("execute")
            if execute_fn is None or not callable(execute_fn):
                logger.warning(
                    "Plugin tool '%s' from '%s' has no callable 'execute'",
                    tool_name,
                    plugin_name,
                )
                return None
            typed_execute = cast(Callable[..., Awaitable[Any]], execute_fn)
            typed_description: str = str(tool_impl.get("description", ""))
            typed_parameters: dict[str, Any] = dict(
                tool_impl.get("parameters", {"type": "object", "properties": {}}),
            )
            typed_permission: str | None = (
                str(tool_impl["permission"])
                if "permission" in tool_impl and tool_impl["permission"] is not None
                else None
            )
            return ToolInfo(
                name=tool_name,
                description=typed_description,
                parameters=typed_parameters,
                execute=typed_execute,
                permission=typed_permission,
                category="plugin",
                tags=tags,
            )

        # Form 3: Bare async callable
        if callable(tool_impl):
            typed_callable = cast(Callable[..., Awaitable[Any]], tool_impl)
            return ToolInfo(
                name=tool_name,
                description=f"Plugin tool: {tool_name}",
                parameters={"type": "object", "properties": {}},
                execute=typed_callable,
                permission=None,
                category="plugin",
                tags=tags,
            )

        logger.warning(
            "Plugin tool '%s' from '%s' has unsupported type: %s",
            tool_name,
            plugin_name,
            type(tool_impl).__name__,
        )
        return None

    except Exception:
        logger.exception(
            "Failed to convert plugin tool '%s' from '%s'",
            tool_name,
            plugin_name,
        )
        return None


async def build_plugin_tool_infos(
    registry: AgentPluginRegistry,
    context: PluginToolBuildContext,
) -> list[ToolInfo]:
    """Build ToolInfo instances from all registered plugin factories.

    Calls ``registry.build_tools()`` and converts the results to ToolInfo.
    Logs diagnostics for any conversion failures.

    Args:
        registry: The plugin registry containing tool factories.
        context: Build context with tenant_id, project_id, base_tools.

    Returns:
        List of successfully converted ToolInfo instances.
    """
    plugin_tools, diagnostics = await registry.build_tools(context)

    for diag in diagnostics:
        log_fn = logger.error if diag.level == "error" else logger.info
        log_fn("Plugin diagnostic [%s/%s]: %s", diag.plugin_name, diag.code, diag.message)

    tool_infos: list[ToolInfo] = []

    for tool_name, tool_impl in plugin_tools.items():
        # Determine source plugin name from diagnostics (best effort)
        source_plugin = ""
        for diag in diagnostics:
            if diag.code == "plugin_loaded":
                source_plugin = diag.plugin_name
                break

        info = plugin_tool_to_info(tool_name, tool_impl, plugin_name=source_plugin)
        if info is not None:
            tool_infos.append(info)
            logger.debug("Converted plugin tool '%s' to ToolInfo", tool_name)

    logger.info(
        "Built %d plugin ToolInfo(s) from %d raw plugin tool(s)",
        len(tool_infos),
        len(plugin_tools),
    )
    return tool_infos
