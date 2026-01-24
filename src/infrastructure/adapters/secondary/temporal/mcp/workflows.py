"""MCP Server Workflows for Temporal.

This module defines long-running Workflows for managing MCP server lifecycle,
including connection management, tool discovery, and tool execution.

The workflow separates MCP subprocess management from the API service,
enabling horizontal scaling and fault tolerance.
"""

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Dict, List, Optional

from temporalio import workflow
from temporalio.common import RetryPolicy

# Import activities using workflow-safe imports
with workflow.unsafe.imports_passed_through():
    from src.infrastructure.adapters.secondary.temporal.mcp.activities import (
        call_mcp_tool_activity,
        start_mcp_server_activity,
        stop_mcp_server_activity,
    )


@dataclass
class MCPServerConfig:
    """Configuration for starting an MCP server."""

    server_name: str
    tenant_id: str
    transport_type: str = "local"  # "local", "http", "sse", "websocket"

    # LOCAL transport config
    command: Optional[List[str]] = None
    environment: Optional[Dict[str, str]] = None

    # Remote transport config (HTTP/SSE/WebSocket)
    url: Optional[str] = None
    headers: Optional[Dict[str, str]] = None

    # WebSocket specific config
    heartbeat_interval: int = 30  # seconds
    reconnect_attempts: int = 3

    # Common config
    timeout: int = 30000  # milliseconds
    enabled: bool = True


@dataclass
class MCPToolCallRequest:
    """Request to call an MCP tool."""

    tool_name: str
    arguments: Dict[str, Any] = field(default_factory=dict)
    timeout: Optional[int] = None  # milliseconds


@dataclass
class MCPToolCallResult:
    """Result from an MCP tool call."""

    content: List[Dict[str, Any]] = field(default_factory=list)
    is_error: bool = False
    error_message: Optional[str] = None


@dataclass
class MCPServerStartResult:
    """Result from starting an MCP server."""

    server_name: str
    status: str
    tools: List[Dict[str, Any]] = field(default_factory=list)
    server_info: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


@workflow.defn(name="mcp_server")
class MCPServerWorkflow:
    """
    Long-running Workflow for managing an MCP server lifecycle.

    This workflow:
    1. Starts an MCP server (subprocess or HTTP client)
    2. Maintains the connection while listening for signals
    3. Handles tool calls via the call_tool update
    4. Gracefully shuts down when receiving the stop signal

    Workflow ID pattern: tenant_{tenant_id}_mcp_{server_name}

    Usage:
        # Start workflow
        handle = await client.start_workflow(
            MCPServerWorkflow.run,
            config,
            id=f"tenant_{tenant_id}_mcp_{server_name}",
            task_queue="mcp-tasks",
        )

        # Call a tool
        result = await handle.execute_update(
            MCPServerWorkflow.call_tool,
            MCPToolCallRequest(tool_name="fetch", arguments={"url": "..."}),
        )

        # Get tools list
        tools = await handle.query(MCPServerWorkflow.list_tools)

        # Stop the server
        await handle.signal(MCPServerWorkflow.stop)
    """

    def __init__(self):
        self._config: Optional[MCPServerConfig] = None
        self._tools: List[Dict[str, Any]] = []
        self._server_info: Optional[Dict[str, Any]] = None
        self._stop_requested = False
        self._connected = False
        self._error: Optional[str] = None

    @workflow.run
    async def run(self, config: MCPServerConfig) -> Dict[str, Any]:
        """
        Main workflow execution.

        Args:
            config: MCP server configuration

        Returns:
            Final status of the workflow
        """
        self._config = config

        # Retry policy for activities
        retry_policy = RetryPolicy(
            initial_interval=timedelta(seconds=1),
            maximum_interval=timedelta(seconds=30),
            maximum_attempts=3,
            backoff_coefficient=2.0,
        )

        workflow.logger.info(
            f"Starting MCP server workflow: {config.server_name} "
            f"(tenant: {config.tenant_id}, transport: {config.transport_type})"
        )

        try:
            # 1. Start the MCP server
            start_result: Dict[str, Any] = await workflow.execute_activity(
                start_mcp_server_activity,
                config,
                start_to_close_timeout=timedelta(seconds=60),
                heartbeat_timeout=timedelta(seconds=30),
                retry_policy=retry_policy,
            )

            if start_result.get("status") != "connected":
                self._error = start_result.get("error") or "Failed to start MCP server"
                workflow.logger.error(f"MCP server failed to start: {self._error}")
                return {
                    "server_name": config.server_name,
                    "status": "failed",
                    "error": self._error,
                }

            # Store connection info
            self._connected = True
            self._tools = start_result.get("tools", [])
            self._server_info = start_result.get("server_info")

            workflow.logger.info(
                f"MCP server started: {config.server_name} with {len(self._tools)} tools"
            )

            # 2. Wait for stop signal (long-running)
            await workflow.wait_condition(lambda: self._stop_requested)

            workflow.logger.info(f"Stop requested for MCP server: {config.server_name}")

        except Exception as e:
            self._error = str(e)
            workflow.logger.error(f"MCP server workflow error: {e}")

        finally:
            # 3. Cleanup: Stop the MCP server
            if self._connected:
                try:
                    await workflow.execute_activity(
                        stop_mcp_server_activity,
                        config,
                        start_to_close_timeout=timedelta(seconds=30),
                        retry_policy=RetryPolicy(maximum_attempts=1),
                    )
                    workflow.logger.info(f"MCP server stopped: {config.server_name}")
                except Exception as e:
                    workflow.logger.error(f"Error stopping MCP server: {e}")

        return {
            "server_name": config.server_name,
            "status": "stopped" if not self._error else "error",
            "error": self._error,
        }

    @workflow.update
    async def call_tool(self, request: MCPToolCallRequest) -> MCPToolCallResult:
        """
        Handle a tool call request.

        This update handler executes an MCP tool and returns the result.
        Uses Temporal's update mechanism for synchronous request-response.

        Args:
            request: Tool call request

        Returns:
            Tool call result
        """
        if not self._connected:
            return MCPToolCallResult(
                is_error=True,
                error_message="MCP server not connected",
            )

        if not self._config:
            return MCPToolCallResult(
                is_error=True,
                error_message="MCP server configuration missing",
            )

        workflow.logger.info(f"Calling tool: {request.tool_name}")

        try:
            # Execute tool call activity
            timeout_seconds = (request.timeout or self._config.timeout) / 1000
            retry_policy = RetryPolicy(
                initial_interval=timedelta(seconds=1),
                maximum_attempts=2,
                backoff_coefficient=2.0,
            )

            result = await workflow.execute_activity(
                call_mcp_tool_activity,
                {
                    "config": self._config,
                    "tool_name": request.tool_name,
                    "arguments": request.arguments,
                },
                start_to_close_timeout=timedelta(seconds=timeout_seconds + 10),
                retry_policy=retry_policy,
            )

            return MCPToolCallResult(
                content=result.get("content", []),
                is_error=result.get("is_error", False),
                error_message=result.get("error_message"),
            )

        except Exception as e:
            workflow.logger.error(f"Tool call failed: {e}")
            return MCPToolCallResult(
                is_error=True,
                error_message=str(e),
            )

    @workflow.query
    def list_tools(self) -> List[Dict[str, Any]]:
        """
        Query available tools.

        Returns:
            List of tool schemas
        """
        return self._tools

    @workflow.query
    def get_status(self) -> Dict[str, Any]:
        """
        Query server status.

        Returns:
            Current status information
        """
        return {
            "connected": self._connected,
            "server_info": self._server_info,
            "tool_count": len(self._tools),
            "error": self._error,
        }

    @workflow.signal
    def stop(self):
        """
        Signal to stop the MCP server.

        The workflow will gracefully shutdown after receiving this signal.
        """
        workflow.logger.info("Received stop signal")
        self._stop_requested = True
