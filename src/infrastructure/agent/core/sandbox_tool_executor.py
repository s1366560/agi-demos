"""Sandbox-side tool executor for tools that run in Docker containers.

Encapsulates the sandbox execution pattern: dependency installation,
tool dispatch via SandboxPort.call_tool(), and result normalization.
Replaces the split logic across SandboxMCPToolWrapper and
create_sandbox_plugin_tool.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Protocol

from src.infrastructure.agent.core.tool_execution_router import ToolExecutionConfig
from src.infrastructure.agent.tools.define import ToolInfo
from src.infrastructure.agent.tools.file_metadata import build_sandbox_tool_metadata
from src.infrastructure.agent.tools.result import ToolResult

logger = logging.getLogger(__name__)


class SandboxPortProtocol(Protocol):
    """Minimal sandbox execution interface used by sandbox tools."""

    async def call_tool(
        self,
        sandbox_id: str,
        tool_name: str,
        arguments: dict[str, object],
    ) -> dict[str, Any]: ...


class DependencyOrchestratorProtocol(Protocol):
    """Minimal dependency installer interface used by sandbox tools."""

    async def ensure_dependencies(self, sandbox_id: str, dependencies: list[str]) -> None: ...


class SandboxToolExecutor:
    """Unified executor for all sandbox-bound tools.

    Wraps a ToolInfo so that its execute() method runs inside a sandbox
    container via the SandboxPort interface.

    Args:
        sandbox_port: Interface to communicate with sandbox containers.
        sandbox_id: ID of the target sandbox container.
        dependency_orchestrator: Manages runtime dependency installation.
    """

    def __init__(
        self,
        sandbox_port: SandboxPortProtocol,
        sandbox_id: str,
        dependency_orchestrator: DependencyOrchestratorProtocol | None = None,
    ) -> None:
        self._sandbox_port = sandbox_port
        self._sandbox_id = sandbox_id
        self._dep_orchestrator = dependency_orchestrator

    def wrap(self, tool_info: ToolInfo, config: ToolExecutionConfig) -> ToolInfo:
        """Create a ToolInfo that delegates execution to the sandbox.

        Args:
            tool_info: The original tool definition.
            config: Execution configuration with sandbox dependencies.

        Returns:
            A new ToolInfo whose execute() runs in the sandbox.
        """
        sandbox_port = self._sandbox_port
        sandbox_id = self._sandbox_id
        dep_orchestrator = self._dep_orchestrator

        async def sandbox_execute(ctx: object | None = None, **kwargs: object) -> ToolResult:
            # 1. Ensure runtime dependencies
            if config.sandbox_dependencies and dep_orchestrator is not None:
                await dep_orchestrator.ensure_dependencies(sandbox_id, config.sandbox_dependencies)

            # 2. Execute in sandbox via MCP
            tool_name = config.sandbox_tool_name or tool_info.name
            try:
                mcp_result: dict[str, Any] = await sandbox_port.call_tool(
                    sandbox_id, tool_name, kwargs
                )
            except Exception:
                logger.exception(
                    "Sandbox execution failed for tool %s in sandbox %s",
                    tool_name,
                    sandbox_id,
                )
                raise

            # 3. Normalize result to ToolResult
            return _normalize_mcp_result(mcp_result, tool_name)

        return ToolInfo(
            name=tool_info.name,
            description=tool_info.description,
            parameters=tool_info.parameters,
            execute=sandbox_execute,
            permission=tool_info.permission,
            category=tool_info.category,
            tags=tool_info.tags,
            execution_context=tool_info.execution_context,
            dependencies=tool_info.dependencies,
        )


def _normalize_mcp_result(mcp_result: dict[str, Any], tool_name: str) -> ToolResult:
    """Normalize a raw MCP call_tool result dict to a ToolResult.

    Args:
        mcp_result: Raw dict from sandbox_port.call_tool().
        tool_name: Name of the tool (for error messages).

    Returns:
        A structured ToolResult.
    """
    output = mcp_result.get("output", "")
    if isinstance(output, dict):
        output = json.dumps(output, ensure_ascii=False, indent=2)
    elif not isinstance(output, str):
        output = str(output)
    is_error = bool(mcp_result.get("isError", mcp_result.get("is_error", False)))
    metadata = build_sandbox_tool_metadata(
        tool_name=tool_name,
        arguments={},
        raw_result=mcp_result,
        output=output,
    )
    return ToolResult(output=output, metadata=metadata, is_error=is_error)
