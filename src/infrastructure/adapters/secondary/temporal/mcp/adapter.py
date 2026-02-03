"""MCP Temporal Adapter.

This module provides the API-side adapter for MCP operations via Temporal.
It replaces the direct MCPManager with a Temporal-based implementation,
enabling horizontal scaling and fault tolerance.

The adapter communicates with MCP servers through Temporal Workflows,
which run in separate MCP Worker processes.

Domain Models:
- MCPServerStatus is now available in src.domain.model.mcp.server
- MCPTool is now available in src.domain.model.mcp.tool
- Use domain_adapter.py for conversions between Temporal and domain models
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from temporalio.client import Client
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from src.infrastructure.adapters.secondary.temporal.mcp.workflows import (
    MCPServerConfig,
    MCPServerWorkflow,
    MCPToolCallRequest,
    MCPToolCallResult,
)

logger = logging.getLogger(__name__)

# Default task queue for MCP workflows
MCP_TASK_QUEUE = "mcp-tasks"


@dataclass
class MCPServerStatus:
    """Status of an MCP server.

    Note: This is a Temporal-specific dataclass for workflow serialization.
    For domain model, use src.domain.model.mcp.server.MCPServerStatus
    """

    server_name: str
    tenant_id: str
    connected: bool = False
    tool_count: int = 0
    server_info: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    workflow_id: Optional[str] = None


@dataclass
class MCPToolInfo:
    """Information about an MCP tool.

    Note: This is a Temporal-specific dataclass for workflow serialization.
    For domain model, use src.domain.model.mcp.tool.MCPTool
    """

    name: str
    server_name: str
    description: Optional[str] = None
    input_schema: Dict[str, Any] = field(default_factory=dict)


class MCPTemporalAdapter:
    """
    Temporal-based adapter for MCP operations.

    This adapter manages MCP servers through Temporal Workflows,
    providing horizontal scaling, fault tolerance, and tenant isolation.

    Usage:
        adapter = MCPTemporalAdapter(temporal_client)

        # Start an MCP server
        await adapter.start_mcp_server(
            tenant_id="tenant_1",
            server_name="fetch",
            transport_type="local",
            command=["uvx", "mcp-server-fetch"],
        )

        # Call a tool
        result = await adapter.call_mcp_tool(
            tenant_id="tenant_1",
            server_name="fetch",
            tool_name="fetch",
            arguments={"url": "https://example.com"},
        )

        # List tools
        tools = await adapter.list_tools(tenant_id="tenant_1", server_name="fetch")

        # Stop the server
        await adapter.stop_mcp_server(tenant_id="tenant_1", server_name="fetch")
    """

    def __init__(
        self,
        temporal_client: Client,
        task_queue: str = MCP_TASK_QUEUE,
    ):
        """
        Initialize the adapter.

        Args:
            temporal_client: Temporal client instance
            task_queue: Task queue for MCP workflows
        """
        self._client = temporal_client
        self._task_queue = task_queue

    def _get_workflow_id(self, tenant_id: str, server_name: str) -> str:
        """
        Generate a workflow ID for an MCP server.

        Args:
            tenant_id: Tenant identifier
            server_name: Server name

        Returns:
            Workflow ID in format: tenant_{tenant_id}_mcp_{server_name}
        """
        # Sanitize names for workflow ID
        safe_tenant = tenant_id.replace("-", "_").replace(".", "_")
        safe_server = server_name.replace("-", "_").replace(".", "_")
        return f"tenant_{safe_tenant}_mcp_{safe_server}"

    async def start_mcp_server(
        self,
        tenant_id: str,
        server_name: str,
        transport_type: str = "local",
        command: Optional[List[str]] = None,
        environment: Optional[Dict[str, str]] = None,
        url: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: int = 30000,
        heartbeat_interval: int = 30,
        reconnect_attempts: int = 3,
    ) -> MCPServerStatus:
        """
        Start an MCP server workflow.

        Args:
            tenant_id: Tenant identifier
            server_name: Unique name for the server
            transport_type: "local", "http", "sse", or "websocket"
            command: Command for local transport
            environment: Environment variables for local transport
            url: URL for remote transport (HTTP/SSE/WebSocket)
            headers: HTTP headers for remote transport
            timeout: Operation timeout in milliseconds
            heartbeat_interval: WebSocket ping interval in seconds
            reconnect_attempts: Max WebSocket reconnection attempts

        Returns:
            Server status
        """
        workflow_id = self._get_workflow_id(tenant_id, server_name)

        config = MCPServerConfig(
            server_name=server_name,
            tenant_id=tenant_id,
            transport_type=transport_type,
            command=command,
            environment=environment,
            url=url,
            headers=headers,
            timeout=timeout,
            heartbeat_interval=heartbeat_interval,
            reconnect_attempts=reconnect_attempts,
        )

        logger.info(f"Starting MCP server workflow: {workflow_id}")

        try:
            # Start the workflow
            handle = await self._client.start_workflow(
                MCPServerWorkflow.run,
                config,
                id=workflow_id,
                task_queue=self._task_queue,
                id_reuse_policy=WorkflowIDReusePolicy.TERMINATE_IF_RUNNING,
            )

            # Query initial status
            status = await handle.query(MCPServerWorkflow.get_status)

            return MCPServerStatus(
                server_name=server_name,
                tenant_id=tenant_id,
                connected=status.get("connected", False),
                tool_count=status.get("tool_count", 0),
                server_info=status.get("server_info"),
                error=status.get("error"),
                workflow_id=workflow_id,
            )

        except WorkflowAlreadyStartedError:
            logger.warning(f"Workflow already running: {workflow_id}")
            # Get existing workflow status
            return await self.get_server_status(tenant_id, server_name)

        except Exception as e:
            logger.exception(f"Error starting MCP server workflow: {e}")
            return MCPServerStatus(
                server_name=server_name,
                tenant_id=tenant_id,
                connected=False,
                error=str(e),
                workflow_id=workflow_id,
            )

    async def stop_mcp_server(
        self,
        tenant_id: str,
        server_name: str,
    ) -> bool:
        """
        Stop an MCP server workflow.

        Args:
            tenant_id: Tenant identifier
            server_name: Server name

        Returns:
            True if stop signal sent successfully
        """
        workflow_id = self._get_workflow_id(tenant_id, server_name)

        logger.info(f"Stopping MCP server workflow: {workflow_id}")

        try:
            handle = self._client.get_workflow_handle(workflow_id)
            await handle.signal(MCPServerWorkflow.stop)
            return True

        except Exception as e:
            logger.exception(f"Error stopping MCP server workflow: {e}")
            return False

    async def call_mcp_tool(
        self,
        tenant_id: str,
        server_name: str,
        tool_name: str,
        arguments: Optional[Dict[str, Any]] = None,
        timeout: Optional[int] = None,
    ) -> MCPToolCallResult:
        """
        Call a tool on an MCP server.

        Args:
            tenant_id: Tenant identifier
            server_name: Server name
            tool_name: Name of the tool to call
            arguments: Tool arguments
            timeout: Operation timeout in milliseconds

        Returns:
            Tool call result
        """
        from datetime import timedelta

        workflow_id = self._get_workflow_id(tenant_id, server_name)

        logger.info(f"Calling MCP tool: {tool_name} on {workflow_id}")

        try:
            handle = self._client.get_workflow_handle(workflow_id)

            request = MCPToolCallRequest(
                tool_name=tool_name,
                arguments=arguments or {},
                timeout=timeout,
            )

            # Use execute_update for synchronous request-response
            # Set RPC timeout to allow for long-running MCP tools
            # Add extra buffer time (20s) on top of tool timeout for workflow overhead
            timeout_seconds = (timeout or 30000) / 1000.0
            rpc_timeout = timedelta(seconds=timeout_seconds + 20)

            result = await handle.execute_update(
                MCPServerWorkflow.call_tool,
                request,
                rpc_timeout=rpc_timeout,
            )

            return result

        except Exception as e:
            logger.exception(f"Error calling MCP tool: {e}")
            return MCPToolCallResult(
                is_error=True,
                error_message=str(e),
            )

    async def list_tools(
        self,
        tenant_id: str,
        server_name: str,
    ) -> List[MCPToolInfo]:
        """
        List tools available from an MCP server.

        Args:
            tenant_id: Tenant identifier
            server_name: Server name

        Returns:
            List of tool information
        """
        workflow_id = self._get_workflow_id(tenant_id, server_name)

        logger.debug(f"Listing tools from: {workflow_id}")

        try:
            handle = self._client.get_workflow_handle(workflow_id)
            tools = await handle.query(MCPServerWorkflow.list_tools)

            return [
                MCPToolInfo(
                    name=f"mcp__{server_name}__{tool.get('name', '')}",
                    server_name=server_name,
                    description=tool.get("description"),
                    input_schema=tool.get("inputSchema", {}),
                )
                for tool in tools
            ]

        except Exception as e:
            logger.exception(f"Error listing MCP tools: {e}")
            return []

    async def get_server_status(
        self,
        tenant_id: str,
        server_name: str,
    ) -> MCPServerStatus:
        """
        Get the status of an MCP server.

        Args:
            tenant_id: Tenant identifier
            server_name: Server name

        Returns:
            Server status
        """
        workflow_id = self._get_workflow_id(tenant_id, server_name)

        try:
            handle = self._client.get_workflow_handle(workflow_id)
            status = await handle.query(MCPServerWorkflow.get_status)

            return MCPServerStatus(
                server_name=server_name,
                tenant_id=tenant_id,
                connected=status.get("connected", False),
                tool_count=status.get("tool_count", 0),
                server_info=status.get("server_info"),
                error=status.get("error"),
                workflow_id=workflow_id,
            )

        except Exception as e:
            # Check if this is a "workflow not ready" error vs actual error
            error_str = str(e)
            if "no poller seen" in error_str or "workflow not found" in error_str.lower():
                # Workflow not started yet - expected during startup, log at debug level
                logger.debug(f"MCP server '{server_name}' workflow not ready yet: {e}")
            else:
                # Actual error - log at warning level
                logger.warning(f"Error querying MCP server '{server_name}' status: {e}")
            return MCPServerStatus(
                server_name=server_name,
                tenant_id=tenant_id,
                connected=False,
                error=None,  # Don't expose "not ready" as an error to callers
                workflow_id=workflow_id,
            )

    async def is_server_running(
        self,
        tenant_id: str,
        server_name: str,
    ) -> bool:
        """
        Check if an MCP server workflow is running.

        Args:
            tenant_id: Tenant identifier
            server_name: Server name

        Returns:
            True if the workflow is running
        """
        status = await self.get_server_status(tenant_id, server_name)
        return status.connected

    async def list_servers(
        self,
        tenant_id: str,
    ) -> List[MCPServerStatus]:
        """
        List all MCP servers for a tenant.

        Note: This requires querying Temporal's visibility API,
        which may not return real-time results.

        Args:
            tenant_id: Tenant identifier

        Returns:
            List of server statuses
        """
        # Query Temporal for workflows matching the tenant pattern
        # Sanitize tenant_id to match the format used in _get_workflow_id
        safe_tenant = tenant_id.replace("-", "_").replace(".", "_")
        # Only query running workflows to avoid duplicates from historical executions
        query = (
            f'WorkflowId STARTS_WITH "tenant_{safe_tenant}_mcp_" AND ExecutionStatus = "Running"'
        )

        servers = []
        seen_servers = set()  # Track seen servers to avoid duplicates
        try:
            async for workflow in self._client.list_workflows(query=query):
                # Extract server name from workflow ID
                # Format: tenant_{tenant_id}_mcp_{server_name}
                # Use maxsplit=1 to handle server names containing "_mcp_"
                parts = workflow.id.split("_mcp_", 1)
                if len(parts) == 2:
                    # Server name in workflow ID has underscores, convert back to original
                    safe_server_name = parts[1]

                    # Skip if we've already seen this server
                    if safe_server_name in seen_servers:
                        continue
                    seen_servers.add(safe_server_name)

                    status = await self.get_server_status(tenant_id, safe_server_name)
                    servers.append(status)

        except Exception as e:
            logger.exception(f"Error listing MCP servers: {e}")

        return servers

    async def list_all_tools(
        self,
        tenant_id: str,
    ) -> List[MCPToolInfo]:
        """
        List all tools from all running MCP servers for a tenant.

        Args:
            tenant_id: Tenant identifier

        Returns:
            List of all tool information
        """
        servers = await self.list_servers(tenant_id)
        all_tools = []

        for server in servers:
            if server.connected:
                tools = await self.list_tools(tenant_id, server.server_name)
                all_tools.extend(tools)

        return all_tools
