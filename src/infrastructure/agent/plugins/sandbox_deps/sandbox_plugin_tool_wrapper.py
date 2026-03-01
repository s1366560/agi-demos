"""Sandbox plugin tool wrapper with automatic dependency installation.

Wraps sandbox plugin tools as ToolInfo instances that ensure runtime
dependencies are installed on first invocation, then delegate subsequent
calls directly to the sandbox via SandboxPort.call_tool().

This follows the same closure-based factory pattern used by
``create_sandbox_mcp_tool()`` in ``sandbox_tool_wrapper.py``, but adds
a one-time dependency pre-installation step coordinated through the
DependencyOrchestrator.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.define import ToolInfo
from src.infrastructure.agent.tools.result import ToolResult

if TYPE_CHECKING:
    from src.domain.ports.services.sandbox_port import SandboxPort
    from src.infrastructure.agent.plugins.sandbox_deps.models import (
        RuntimeDependencies,
    )
    from src.infrastructure.agent.plugins.sandbox_deps.orchestrator import (
        DependencyOrchestrator,
    )

logger = logging.getLogger(__name__)


def _extract_error_text(result: dict[str, Any]) -> str:
    """Extract error message from an MCP error result.

    Args:
        result: The MCP result dict with is_error/isError flag set.

    Returns:
        The extracted error message string.
    """
    content_list = result.get("content", [])

    if content_list and len(content_list) > 0:
        first_content = content_list[0]
        if isinstance(first_content, dict):
            error_msg = first_content.get("text", "")
        else:
            error_msg = str(first_content)
    else:
        error_msg = ""

    if not error_msg:
        error_msg = f"Tool execution failed (no details). Raw result: {result}"

    return str(error_msg)


def _extract_success_text(result: dict[str, Any]) -> str:
    """Extract output string from a successful MCP result.

    Args:
        result: The MCP result dict (no error flag set).

    Returns:
        String representation of the result content.
    """
    content_list = result.get("content", [])

    if content_list and len(content_list) > 0:
        first_content = content_list[0]
        if isinstance(first_content, dict):
            return str(first_content.get("text", ""))
        return str(first_content)

    return "Success"


def create_sandbox_plugin_tool(
    *,
    plugin_id: str,
    tool_name: str,
    description: str,
    parameters: dict[str, Any],
    sandbox_id: str,
    project_id: str,
    sandbox_port: SandboxPort,
    orchestrator: DependencyOrchestrator,
    dependencies: RuntimeDependencies,
    permission: str | None = None,
    category: str = "plugin",
) -> ToolInfo:
    """Create a ToolInfo for a sandbox plugin tool with dependency management.

    Builds a closure-based ToolInfo whose ``execute`` function ensures
    that the plugin's declared runtime dependencies are installed in the
    sandbox on first invocation, then delegates every call to
    ``sandbox_port.call_tool()``.

    The dependency installation is guarded by a mutable flag in closure
    scope so it only runs once per tool lifetime.

    Args:
        plugin_id: Unique identifier for the plugin owning this tool.
        tool_name: Name of the tool (used in LLM function calling).
        description: Human-readable description for the LLM.
        parameters: JSON Schema dict describing the tool's parameters.
        sandbox_id: Target sandbox instance ID.
        project_id: Project scope for multi-tenancy.
        sandbox_port: SandboxPort for routing tool calls.
        orchestrator: DependencyOrchestrator for installing deps.
        dependencies: RuntimeDependencies manifest to pre-install.
        permission: Optional permission identifier.
        category: Tool category for grouping (default ``"plugin"``).

    Returns:
        A ToolInfo instance wrapping the sandbox plugin tool.
    """
    # Mutable flag in closure scope -- list for mutation in nested function.
    _deps_installed: list[bool] = [False]

    async def execute(ctx: ToolContext, **kwargs: Any) -> ToolResult:
        """Execute the sandbox plugin tool with dependency pre-install."""
        _ = ctx  # Available but not used by sandbox tool calls

        # -- Ensure dependencies on first call --------------------------
        if not _deps_installed[0]:
            result = await orchestrator.ensure_dependencies(
                plugin_id=plugin_id,
                project_id=project_id,
                sandbox_id=sandbox_id,
                dependencies=dependencies,
            )

            if not result.success:
                error_detail = "; ".join(result.errors)
                return ToolResult(
                    output=(f"Dependency installation failed: {error_detail}"),
                    is_error=True,
                )

            _deps_installed[0] = True
            logger.info(
                "Plugin deps ready plugin=%s tool=%s sandbox=%s",
                plugin_id,
                tool_name,
                sandbox_id,
            )

        # -- Delegate to sandbox ----------------------------------------
        mcp_result = await sandbox_port.call_tool(
            sandbox_id,
            tool_name,
            kwargs,
        )

        if mcp_result.get("isError") or mcp_result.get("is_error"):
            error_text = _extract_error_text(mcp_result)
            return ToolResult(output=error_text, is_error=True)

        text = _extract_success_text(mcp_result)
        return ToolResult(output=text)

    return ToolInfo(
        name=tool_name,
        description=description,
        parameters=parameters,
        execute=execute,
        permission=permission,
        category=category,
        tags=frozenset({"plugin", "sandbox"}),
        dependencies=dependencies,
    )
