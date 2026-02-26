"""Pipeline-aware MCP tool execution with abort signals and structured errors."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from src.infrastructure.mcp.tool_info import MCPCallResult, MCPToolExecutorPort

if TYPE_CHECKING:
    from src.infrastructure.agent.tools.context import ToolContext

from src.infrastructure.agent.tools.result import ToolResult


class MCPErrorHandler:
    """Convert MCP errors to structured ToolResult."""

    @staticmethod
    def handle_error(server: str, tool: str, error: Exception) -> ToolResult:
        """Convert exceptions to ToolResult with consistent structure.

        Args:
            server: MCP server identifier.
            tool: Tool name within the server.
            error: The exception to convert.

        Returns:
            ToolResult with error details and metadata.
        """
        from src.infrastructure.agent.tools.context import ToolAbortedError

        error_map: dict[type[Exception], tuple[str, str]] = {
            ConnectionError: ("connection_error", "Failed to connect to MCP server"),
            TimeoutError: ("timeout", "MCP tool execution timed out"),
            ToolAbortedError: ("aborted", "Tool execution was cancelled"),
        }

        error_type, message = error_map.get(type(error), ("unknown", str(error)))

        return ToolResult(
            output=f"[{error_type.upper()}] {message}: {error}",
            title=f"Error: {server}.{tool}",
            metadata={
                "error_type": error_type,
                "server": server,
                "tool": tool,
                "original_error": str(error),
            },
            is_error=True,
        )


class PipelineMCPExecutor:
    """Wraps an MCPToolExecutorPort with abort signal and error handling.

    This decorator adds:
    - Abort signal propagation via abort_aware_timeout
    - Structured error handling via MCPErrorHandler
    - Configurable timeout
    """

    def __init__(
        self,
        inner: MCPToolExecutorPort,
        default_timeout: float = 300.0,
    ) -> None:
        self._inner = inner
        self._default_timeout = default_timeout

    async def call_tool(
        self,
        server_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        ctx: ToolContext | None = None,
        timeout: float | None = None,
    ) -> MCPCallResult:
        """Execute with abort signal and error handling.

        Args:
            server_id: MCP server identifier.
            tool_name: Tool name.
            arguments: Tool arguments.
            ctx: Optional ToolContext for abort signal.
            timeout: Override default timeout.

        Returns:
            MCPCallResult from the inner executor.

        Raises:
            ToolAbortedError: If abort signal fires during execution.
            TimeoutError: If execution exceeds timeout.
            Exception: Any other exception from the inner executor.
        """
        effective_timeout = timeout or self._default_timeout

        coro = self._inner.call_tool(server_id, tool_name, arguments)

        if ctx is not None:
            from src.infrastructure.agent.tools.abort import abort_aware_timeout

            return await abort_aware_timeout(ctx, coro, effective_timeout)

        return await asyncio.wait_for(coro, timeout=effective_timeout)


__all__ = ["MCPErrorHandler", "PipelineMCPExecutor"]
