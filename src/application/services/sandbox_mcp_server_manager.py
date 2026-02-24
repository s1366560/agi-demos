"""Sandbox MCP Server Manager service.
Orchestrates user-configured MCP servers running inside project sandbox
containers. Handles sandbox auto-creation, server installation, lifecycle
management, tool discovery, and tool call proxying.
"""

from __future__ import annotations

import json
import logging
import os
from typing import TYPE_CHECKING, Any, cast

from src.domain.ports.services.sandbox_mcp_server_port import (
    SandboxMCPServerPort,
    SandboxMCPServerStatus,
    SandboxMCPToolCallResult,
)
from src.domain.ports.services.sandbox_resource_port import SandboxResourcePort

if TYPE_CHECKING:
    from src.application.services.mcp_app_service import MCPAppService

logger = logging.getLogger(__name__)

# Names of sandbox-side management tools
TOOL_INSTALL = "mcp_server_install"
TOOL_START = "mcp_server_start"
TOOL_STOP = "mcp_server_stop"
TOOL_LIST = "mcp_server_list"
TOOL_DISCOVER = "mcp_server_discover_tools"
TOOL_CALL = "mcp_server_call_tool"

# Timeouts (seconds) - override via env MCP_INSTALL_TIMEOUT, etc.
MCP_INSTALL_TIMEOUT = float(os.environ.get("MCP_INSTALL_TIMEOUT", "120"))
MCP_START_TIMEOUT = float(os.environ.get("MCP_START_TIMEOUT", "60"))
MCP_STOP_TIMEOUT = float(os.environ.get("MCP_STOP_TIMEOUT", "30"))
MCP_CALL_TOOL_TIMEOUT = float(os.environ.get("MCP_CALL_TOOL_TIMEOUT", "60"))
MCP_DISCOVER_TIMEOUT = float(os.environ.get("MCP_DISCOVER_TIMEOUT", "20"))


class SandboxMCPServerManager(SandboxMCPServerPort):
    """Manages user MCP servers in project sandbox containers.

    Uses the existing SandboxResourcePort to communicate with sandbox
    containers via MCP management tools registered in the sandbox.
    """

    def __init__(
        self,
        sandbox_resource: SandboxResourcePort,
        app_service: MCPAppService | None = None,
    ) -> None:
        """Initialize the manager.

        Args:
            sandbox_resource: Port for sandbox access (ensure/execute tools).
            app_service: Optional MCPAppService for auto-detecting MCP Apps.
        """
        self._sandbox_resource = sandbox_resource
        self._app_service = app_service

    async def install_and_start(
        self,
        project_id: str,
        tenant_id: str,
        server_name: str,
        server_type: str,
        transport_config: dict[str, Any],
    ) -> SandboxMCPServerStatus:
        """Install and start an MCP server in the project's sandbox."""
        # Ensure sandbox exists
        sandbox_id = await self._sandbox_resource.ensure_sandbox_ready(
            project_id=project_id,
            tenant_id=tenant_id,
        )
        logger.info(f"Sandbox ready (id={sandbox_id}) for MCP server '{server_name}'")

        config_json = json.dumps(transport_config)

        # Install the MCP server package
        install_result = await self._sandbox_resource.execute_tool(
            project_id=project_id,
            tool_name=TOOL_INSTALL,
            arguments={
                "name": server_name,
                "server_type": server_type,
                "transport_config": config_json,
            },
            timeout=MCP_INSTALL_TIMEOUT,
        )
        install_data = self._parse_tool_result(install_result)
        if not install_data.get("success", False):
            error = install_data.get("error", "Installation failed")
            logger.error(f"Failed to install MCP server '{server_name}': {error}")
            return SandboxMCPServerStatus(
                name=server_name,
                server_type=server_type,
                status="failed",
                error=error,
            )

        # Start the MCP server
        start_result = await self._sandbox_resource.execute_tool(
            project_id=project_id,
            tool_name=TOOL_START,
            arguments={
                "name": server_name,
                "server_type": server_type,
                "transport_config": config_json,
            },
            timeout=MCP_START_TIMEOUT,
        )
        start_data = self._parse_tool_result(start_result)
        if not start_data.get("success", False):
            error = start_data.get("error", "Start failed")
            logger.error(f"Failed to start MCP server '{server_name}': {error}")
            return SandboxMCPServerStatus(
                name=server_name,
                server_type=server_type,
                status="failed",
                error=error,
            )

        logger.info(f"MCP server '{server_name}' started in sandbox {sandbox_id}")
        return SandboxMCPServerStatus(
            name=server_name,
            server_type=server_type,
            status=start_data.get("status", "running"),
            pid=start_data.get("pid"),
            port=start_data.get("port"),
        )

    async def stop_server(
        self,
        project_id: str,
        server_name: str,
    ) -> bool:
        """Stop an MCP server in the project's sandbox."""
        try:
            result = await self._sandbox_resource.execute_tool(
                project_id=project_id,
                tool_name=TOOL_STOP,
                arguments={"name": server_name},
                timeout=MCP_STOP_TIMEOUT,
            )
            data = self._parse_tool_result(result)
            return cast(bool, data.get("success", False))
        except Exception as e:
            logger.warning(f"Failed to stop MCP server '{server_name}': {e}")
            return False

    async def discover_tools(
        self,
        project_id: str,
        tenant_id: str,
        server_name: str,
        server_type: str,
        transport_config: dict[str, Any],
        ensure_running: bool = True,
    ) -> list[dict[str, Any]]:
        """Discover tools from an MCP server in the sandbox."""
        if ensure_running:
            status = await self.install_and_start(
                project_id=project_id,
                tenant_id=tenant_id,
                server_name=server_name,
                server_type=server_type,
                transport_config=transport_config,
            )
            if status.status == "failed":
                raise RuntimeError(
                    f"Cannot discover tools: server '{server_name}' failed to start: {status.error}"
                )

        # Discover tools
        result = await self._sandbox_resource.execute_tool(
            project_id=project_id,
            tool_name=TOOL_DISCOVER,
            arguments={"name": server_name},
            timeout=MCP_DISCOVER_TIMEOUT,
        )
        tools = self._parse_tool_result(result)
        if isinstance(tools, list):
            # Auto-detect MCP Apps (tools with _meta.ui.resourceUri)
            if self._app_service and tools:
                try:
                    await self._app_service.detect_apps_from_tools(
                        server_id="",  # resolved by service from server_name
                        project_id=project_id,
                        tenant_id=tenant_id,
                        server_name=server_name,
                        tools=tools,
                    )
                except Exception as e:
                    logger.warning(f"MCP App auto-detection failed: {e}")
            return tools
        return []

    async def call_tool(
        self,
        project_id: str,
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> SandboxMCPToolCallResult:
        """Call a tool on an MCP server in the sandbox."""
        try:
            result = await self._sandbox_resource.execute_tool(
                project_id=project_id,
                tool_name=TOOL_CALL,
                arguments={
                    "server_name": server_name,
                    "tool_name": tool_name,
                    "arguments": json.dumps(arguments),
                },
                timeout=MCP_CALL_TOOL_TIMEOUT,
            )

            content = result.get("content", [])
            is_error = result.get("isError", result.get("is_error", False))
            return SandboxMCPToolCallResult(
                content=content,
                is_error=is_error,
            )

        except Exception as e:
            logger.error(f"Error calling tool '{tool_name}' on '{server_name}': {e}")
            return SandboxMCPToolCallResult(
                content=[{"type": "text", "text": f"Error: {e!s}"}],
                is_error=True,
                error_message=str(e),
            )

    async def read_resource(
        self,
        project_id: str,
        uri: str,
        server_name: str | None = None,
        tenant_id: str | None = None,
    ) -> str | None:
        """Read a resource from an MCP server via resources/read.

        Proxies the resources/read call through the sandbox WebSocket client.
        Returns HTML content string or None.
        """
        try:
            # The sandbox resource port wraps the sandbox adapter which can
            # do a direct resources/read on the WebSocket connection.
            adapter = getattr(self._sandbox_resource, "_adapter", None) or getattr(
                self._sandbox_resource, "_sandbox_adapter", None
            )
            if adapter and hasattr(adapter, "read_resource"):
                sandbox_id = await self._sandbox_resource.get_sandbox_id(
                    project_id, tenant_id or ""
                )
                if not sandbox_id:
                    logger.warning("No sandbox for project %s", project_id)
                    return None
                return cast("str | None", await adapter.read_resource(sandbox_id, uri))

            # Fallback: use management tool mcp_server_call_tool with
            # the "resources/read" protocol path (for future compat).
            logger.warning("read_resource: no adapter path, falling back to None")
            return None
        except Exception as e:
            logger.warning(f"read_resource failed for '{uri}': {e}")
            return None

    async def list_resources(
        self,
        project_id: str,
        tenant_id: str | None = None,
    ) -> list[Any]:
        """List resources from MCP servers in the sandbox.

        Proxies the resources/list call through the sandbox WebSocket client.
        Returns list of resource descriptors or empty list.
        """
        try:
            adapter = getattr(self._sandbox_resource, "_adapter", None) or getattr(
                self._sandbox_resource, "_sandbox_adapter", None
            )
            if adapter and hasattr(adapter, "list_resources"):
                sandbox_id = await self._sandbox_resource.get_sandbox_id(
                    project_id, tenant_id or ""
                )
                if not sandbox_id:
                    return []
                return cast("list[Any]", await adapter.list_resources(sandbox_id))
            return []
        except Exception as e:
            logger.warning(f"list_resources failed: {e}")
            return []

    async def test_connection(
        self,
        project_id: str,
        tenant_id: str,
        server_name: str,
        server_type: str,
        transport_config: dict[str, Any],
    ) -> SandboxMCPServerStatus:
        """Test MCP server connection by running it in sandbox."""
        # Install and start
        status = await self.install_and_start(
            project_id=project_id,
            tenant_id=tenant_id,
            server_name=server_name,
            server_type=server_type,
            transport_config=transport_config,
        )

        if status.status == "failed":
            return status

        # Try to discover tools as a connectivity test
        try:
            result = await self._sandbox_resource.execute_tool(
                project_id=project_id,
                tool_name=TOOL_DISCOVER,
                arguments={"name": server_name},
                timeout=MCP_DISCOVER_TIMEOUT,
            )
            tools = self._parse_tool_result(result)
            if isinstance(tools, list):
                tool_count = len(tools)
                status.tool_count = tool_count
            else:
                # If not a list, it might be an error dict or raw text
                error_msg = "Unknown error"
                if isinstance(tools, dict):
                    error_msg = tools.get("error", tools.get("raw_output", str(tools))) or "Unknown error"
                else:
                    error_msg = str(tools)

                status.status = "failed"
                status.error = f"Tool discovery failed: {error_msg}"
                status.tool_count = 0
        except Exception as e:
            status.status = "failed"
            status.error = f"Tool discovery failed: {e!s}"

        return status

    async def list_servers(
        self,
        project_id: str,
    ) -> list[SandboxMCPServerStatus]:
        """List MCP servers running in a project's sandbox."""
        try:
            result = await self._sandbox_resource.execute_tool(
                project_id=project_id,
                tool_name=TOOL_LIST,
                arguments={},
                timeout=15.0,
            )
            servers_data = self._parse_tool_result(result)
            if not isinstance(servers_data, list):
                return []

            return [
                SandboxMCPServerStatus(
                    name=s.get("name", ""),
                    server_type=s.get("server_type", ""),
                    status=s.get("status", "unknown"),
                    pid=s.get("pid"),
                    port=s.get("port"),
                )
                for s in servers_data
            ]
        except Exception as e:
            logger.warning(f"Failed to list MCP servers: {e}")
            return []

    def _parse_tool_result(self, result: dict[str, Any]) -> Any:
        """Parse tool result content, extracting JSON if present."""
        content = result.get("content", [])
        if not content:
            return result

        # Extract text from content items
        text_parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text_parts.append(item.get("text", ""))

        text = "\n".join(text_parts)
        if not text:
            return result

        # Try to parse as JSON
        try:
            return json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return {"success": False, "error": text, "raw_output": text}
