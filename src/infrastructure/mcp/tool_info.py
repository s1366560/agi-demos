"""Unified MCP tool representation for both external and sandbox MCP servers.

Makes MCP tools first-class pipeline citizens by converting them into standard
ToolInfo instances that go through the same ToolPipeline as native tools
(hooks, permissions, truncation, etc.).

The MCPToolExecutorPort protocol decouples tool definitions from transport
details (HTTP, WebSocket, subprocess), while MCPToolInfo carries the metadata
needed to build a ToolInfo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from src.infrastructure.agent.tools.define import ToolInfo


# ---------------------------------------------------------------------------
# MCP call result
# ---------------------------------------------------------------------------


@dataclass
class MCPCallResult:
    """Raw result from an MCP tool call."""

    content: str
    is_error: bool = False
    metadata: dict[str, Any] = field(default_factory=lambda: dict[str, Any]())


# ---------------------------------------------------------------------------
# Executor protocol (transport-agnostic)
# ---------------------------------------------------------------------------


@runtime_checkable
class MCPToolExecutorPort(Protocol):
    """Transport-agnostic MCP tool execution interface.

    Implementations handle the actual communication with the MCP server
    (HTTP, WebSocket, subprocess, etc.).
    """

    async def call_tool(
        self,
        server_id: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> MCPCallResult: ...


# ---------------------------------------------------------------------------
# Unified MCP tool definition
# ---------------------------------------------------------------------------


@dataclass
class MCPToolInfo:
    """Unified MCP tool definition for both external and sandbox MCP servers.

    Attributes:
        server_id: MCP server identifier.
        tool_name: Tool name within the MCP server.
        description: Human-readable description.
        parameters_schema: JSON Schema from MCP server.
        executor: Transport executor.
    """

    server_id: str
    tool_name: str
    description: str
    parameters_schema: dict[str, Any]
    executor: MCPToolExecutorPort

    @property
    def full_name(self) -> str:
        """Consistent MCP tool name with double underscore separator."""
        return f"mcp__{self.server_id}__{self.tool_name}"

    async def execute(self, **kwargs: Any) -> Any:  # noqa: ANN401
        """Execute via the executor abstraction.

        Returns a ToolResult for pipeline compatibility.
        """
        result = await self.executor.call_tool(
            server_id=self.server_id,
            tool_name=self.tool_name,
            arguments=kwargs,
        )
        from src.infrastructure.agent.tools.result import ToolResult

        return ToolResult(
            output=result.content,
            is_error=result.is_error,
            title=f"{self.server_id}.{self.tool_name}",
            metadata={
                "mcp_server": self.server_id,
                "mcp_tool": self.tool_name,
                **result.metadata,
            },
        )


# ---------------------------------------------------------------------------
# Conversion helper
# ---------------------------------------------------------------------------


def mcp_tool_to_info(mcp_tool: MCPToolInfo) -> ToolInfo:
    """Convert an MCPToolInfo into a standard ToolInfo for the pipeline.

    This makes MCP tools first-class citizens that go through the same
    ToolPipeline as native tools (hooks, permissions, truncation, etc.).
    """
    from src.infrastructure.agent.tools.define import ToolInfo

    return ToolInfo(
        name=mcp_tool.full_name,
        description=mcp_tool.description,
        parameters=mcp_tool.parameters_schema,
        execute=mcp_tool.execute,
        permission="mcp",
        category="mcp",
        tags=frozenset({"mcp", mcp_tool.server_id}),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
    "MCPCallResult",
    "MCPToolExecutorPort",
    "MCPToolInfo",
    "mcp_tool_to_info",
]
