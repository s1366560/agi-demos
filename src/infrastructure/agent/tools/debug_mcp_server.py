"""DebugMCPServerTool - Provides debugging information for MCP servers.

This tool helps agents diagnose issues with MCP servers running inside
sandboxes by collecting logs, process info, and error details.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from src.domain.ports.services.sandbox_port import SandboxPort


from src.infrastructure.agent.tools.base import AgentTool
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.define import tool_define
from src.infrastructure.agent.tools.result import ToolResult

logger = logging.getLogger(__name__)


class DebugMCPServerTool(AgentTool):
    """Tool for debugging MCP servers running inside sandboxes.

    Collects and aggregates debugging information including:
    - Server status and process info
    - Recent logs
    - Last error details
    - Configuration summary

    This is useful when developing or troubleshooting MCP servers
    that are failing to start or behave unexpectedly.
    """

    def __init__(
        self,
        sandbox_adapter: SandboxPort,
        sandbox_id: str,
    ) -> None:
        """Initialize the debug tool.

        Args:
            sandbox_adapter: MCPSandboxAdapter instance.
            sandbox_id: Sandbox container ID.
        """
        self._sandbox_adapter = sandbox_adapter
        self._sandbox_id = sandbox_id

    @property
    def name(self) -> str:
        return "debug_mcp_server"

    @property
    def description(self) -> str:
        return (
            "Get debugging information for an MCP server running in the sandbox. "
            "Returns logs, process status, and error details. "
            "Use this tool to diagnose why a server is not working correctly."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "server_name": {
                    "type": "string",
                    "description": "Name of the MCP server to debug",
                },
                "include_logs": {
                    "type": "boolean",
                    "description": "Whether to include server logs (default: true)",
                    "default": True,
                },
                "log_lines": {
                    "type": "integer",
                    "description": "Number of log lines to include (default: 50)",
                    "default": 50,
                },
            },
            "required": ["server_name"],
        }

    def get_parameters_schema(self) -> dict[str, Any]:
        return self.parameters

    async def execute(  # type: ignore[override]
        self,
        server_name: str,
        include_logs: bool = True,
        log_lines: int = 50,
    ) -> dict[str, Any]:
        """Execute the debug tool to collect server information.

        Args:
            server_name: Name of the MCP server to debug.
            include_logs: Whether to include server logs.
            log_lines: Number of log lines to include.

        Returns:
            Dict with debug information including status, logs, and errors.
        """
        result: dict[str, Any] = {
            "server_name": server_name,
            "status": None,
            "logs": None,
            "process_info": None,
            "last_error": None,
            "error_count": 0,
        }

        try:
            # Get server status
            status_result = await self._sandbox_adapter.call_tool(
                sandbox_id=self._sandbox_id,
                tool_name="mcp_server_status",
                arguments={"name": server_name},
            )
            status_data = self._parse_response(status_result)
            if status_data:
                result["status"] = status_data.get("status")
                result["process_info"] = {
                    "pid": status_data.get("pid"),
                    "memory_mb": status_data.get("memory_mb"),
                    "cpu_percent": status_data.get("cpu_percent"),
                    "uptime_seconds": status_data.get("uptime_seconds"),
                }
                result["last_error"] = status_data.get("last_error")
                result["error_count"] = status_data.get("error_count", 0)

        except Exception as e:
            logger.warning("Failed to get server status: %s", e)
            result["status"] = "unknown"
            result["last_error"] = str(e)

        # Get logs if requested
        if include_logs:
            try:
                logs_result = await self._sandbox_adapter.call_tool(
                    sandbox_id=self._sandbox_id,
                    tool_name="mcp_server_logs",
                    arguments={
                        "name": server_name,
                        "lines": log_lines,
                    },
                )
                logs_data = self._parse_response(logs_result)
                if logs_data:
                    result["logs"] = logs_data.get("logs", logs_data.get("content", ""))
            except Exception as e:
                logger.warning("Failed to get server logs: %s", e)
                result["logs"] = f"Error fetching logs: {e}"

        # Get list info for additional context
        try:
            list_result = await self._sandbox_adapter.call_tool(
                sandbox_id=self._sandbox_id,
                tool_name="mcp_server_list",
                arguments={},
            )
            list_data = self._parse_response(list_result)
            if list_data:
                servers = list_data if isinstance(list_data, list) else list_data.get("servers", [])  # type: ignore[unreachable]
                for server in servers:
                    if isinstance(server, dict) and server.get("name") == server_name:
                        result["registered"] = True
                        if not result["status"]:
                            result["status"] = server.get("status")
                        break
                else:
                    result["registered"] = False
        except Exception as e:
            logger.debug("Failed to get server list: %s", e)

        return result

    def _parse_response(self, response: dict[str, Any]) -> dict[str, Any] | None:
        """Parse MCP tool response to extract data."""
        if not response:
            return None

        content = response.get("content", [])
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text = item.get("text", "")
                try:
                    return cast(dict[str, Any] | None, json.loads(text))
                except (json.JSONDecodeError, TypeError):
                    # Return raw text if not JSON
                    return {"content": text}

        return None


# === New @tool_define based implementation ===

# ---------------------------------------------------------------------------
# Module-level state for dependency injection
# ---------------------------------------------------------------------------

_debug_mcp_sandbox_adapter: Any = None
_debug_mcp_sandbox_id: str = ""


def configure_debug_mcp_server(
    sandbox_adapter: Any,
    sandbox_id: str = "",
) -> None:
    """Configure dependencies for the debug_mcp_server tool."""
    global _debug_mcp_sandbox_adapter, _debug_mcp_sandbox_id
    _debug_mcp_sandbox_adapter = sandbox_adapter
    _debug_mcp_sandbox_id = sandbox_id


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _parse_mcp_response(
    response: dict[str, Any],
) -> dict[str, Any] | None:
    """Parse MCP tool response to extract data."""
    if not response:
        return None
    content = response.get("content", [])
    for item in content:
        if isinstance(item, dict) and item.get("type") == "text":
            text = item.get("text", "")
            try:
                return cast(dict[str, Any] | None, json.loads(text))
            except (json.JSONDecodeError, TypeError):
                return {"content": text}
    return None


# ---------------------------------------------------------------------------
# Tool definition
# ---------------------------------------------------------------------------


@tool_define(
    name="debug_mcp_server",
    description=(
        "Get debugging information for an MCP server running "
        "in the sandbox. Returns logs, process status, and "
        "error details. Use this tool to diagnose why a server "
        "is not working correctly."
    ),
    parameters={
        "type": "object",
        "properties": {
            "server_name": {
                "type": "string",
                "description": ("Name of the MCP server to debug"),
            },
            "include_logs": {
                "type": "boolean",
                "description": ("Whether to include server logs (default: true)"),
                "default": True,
            },
            "log_lines": {
                "type": "integer",
                "description": ("Number of log lines to include (default: 50)"),
                "default": 50,
            },
        },
        "required": ["server_name"],
    },
    permission=None,
    category="mcp",
    tags=frozenset({"mcp", "debug"}),
)
async def debug_mcp_server_tool(
    ctx: ToolContext,
    *,
    server_name: str,
    include_logs: bool = True,
    log_lines: int = 50,
) -> ToolResult:
    """Get debugging information for an MCP server."""
    adapter: SandboxPort | None = _debug_mcp_sandbox_adapter
    sandbox_id = _debug_mcp_sandbox_id

    if adapter is None:
        return ToolResult(
            output="Error: No sandbox adapter configured.",
            is_error=True,
        )

    result: dict[str, Any] = {
        "server_name": server_name,
        "status": None,
        "logs": None,
        "process_info": None,
        "last_error": None,
        "error_count": 0,
    }

    # Get server status
    try:
        status_result = await adapter.call_tool(
            sandbox_id=sandbox_id,
            tool_name="mcp_server_status",
            arguments={"name": server_name},
        )
        status_data = _parse_mcp_response(status_result)
        if status_data:
            result["status"] = status_data.get("status")
            result["process_info"] = {
                "pid": status_data.get("pid"),
                "memory_mb": status_data.get("memory_mb"),
                "cpu_percent": status_data.get("cpu_percent"),
                "uptime_seconds": status_data.get("uptime_seconds"),
            }
            result["last_error"] = status_data.get("last_error")
            result["error_count"] = status_data.get("error_count", 0)
    except Exception as exc:
        logger.warning("Failed to get server status: %s", exc)
        result["status"] = "unknown"
        result["last_error"] = str(exc)

    # Get logs if requested
    if include_logs:
        try:
            logs_result = await adapter.call_tool(
                sandbox_id=sandbox_id,
                tool_name="mcp_server_logs",
                arguments={
                    "name": server_name,
                    "lines": log_lines,
                },
            )
            logs_data = _parse_mcp_response(logs_result)
            if logs_data:
                result["logs"] = logs_data.get("logs", logs_data.get("content", ""))
        except Exception as exc:
            logger.warning("Failed to get server logs: %s", exc)
            result["logs"] = f"Error fetching logs: {exc}"

    # Get list info for additional context
    try:
        list_result = await adapter.call_tool(
            sandbox_id=sandbox_id,
            tool_name="mcp_server_list",
            arguments={},
        )
        list_data = _parse_mcp_response(list_result)
        if list_data:
            servers = list_data if isinstance(list_data, list) else list_data.get("servers", [])
            for server in servers:
                if isinstance(server, dict) and server.get("name") == server_name:
                    result["registered"] = True
                    if not result["status"]:
                        result["status"] = server.get("status")
                    break
            else:
                result["registered"] = False
    except Exception as exc:
        logger.debug("Failed to get server list: %s", exc)

    return ToolResult(
        output=json.dumps(result, indent=2, default=str),
        title=f"Debug: {server_name}",
        metadata={"server_name": server_name},
    )
