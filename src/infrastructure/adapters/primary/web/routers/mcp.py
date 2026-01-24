"""
MCP Server Management API endpoints.

Provides REST API for managing MCP servers in the MCP Ecosystem Integration (Phase 4).
MCP servers provide external tools and capabilities via the Model Context Protocol.

MCP servers are managed via Temporal Workflows for horizontal scaling.
Server configurations are stored in database (tenant-scoped).
Tools are loaded dynamically from running Temporal Workflows.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.configuration.di_container import DIContainer
from src.infrastructure.adapters.primary.web.dependencies import get_current_user_tenant
from src.infrastructure.adapters.secondary.persistence.database import get_db


def get_container_with_db(request: Request, db: AsyncSession) -> DIContainer:
    """
    Get DI container with database session for the current request.
    """
    app_container = request.app.state.container
    return DIContainer(
        db=db,
        graph_service=app_container.graph_service,
        redis_client=app_container._redis_client,
        mcp_temporal_adapter=app_container._mcp_temporal_adapter,
    )


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/mcp", tags=["MCP Servers"])


# === Pydantic Models ===


class MCPServerCreate(BaseModel):
    """Schema for creating a new MCP server."""

    name: str = Field(..., min_length=1, max_length=200, description="Server name")
    description: Optional[str] = Field(None, description="Server description")
    server_type: str = Field(..., description="Transport type: stdio, sse, http, websocket")
    transport_config: Dict[str, Any] = Field(..., description="Transport configuration")
    enabled: bool = Field(True, description="Whether server is enabled")


class MCPServerUpdate(BaseModel):
    """Schema for updating an MCP server."""

    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = Field(None)
    server_type: Optional[str] = Field(None)
    transport_config: Optional[Dict[str, Any]] = Field(None)
    enabled: Optional[bool] = Field(None)


class MCPServerResponse(BaseModel):
    """Schema for MCP server response."""

    id: str
    tenant_id: str
    name: str
    description: Optional[str]
    server_type: str
    transport_config: Dict[str, Any]
    enabled: bool
    discovered_tools: List[Dict[str, Any]]
    last_sync_at: Optional[datetime]
    created_at: datetime
    updated_at: Optional[datetime]


class MCPToolResponse(BaseModel):
    """Schema for MCP tool response."""

    server_id: str
    server_name: str
    name: str
    description: str
    input_schema: Dict[str, Any]


class MCPToolCallRequest(BaseModel):
    """Schema for calling an MCP tool."""

    server_id: str = Field(..., description="MCP server ID")
    tool_name: str = Field(..., description="Tool name")
    arguments: Dict[str, Any] = Field(default_factory=dict, description="Tool arguments")


class MCPToolCallResponse(BaseModel):
    """Schema for MCP tool call response."""

    server_id: str
    tool_name: str
    result: Any
    execution_time_ms: float


# === API Endpoints ===


@router.post("", response_model=MCPServerResponse, status_code=status.HTTP_201_CREATED)
async def create_mcp_server(
    server_data: MCPServerCreate,
    db: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_current_user_tenant),
):
    """
    Create a new MCP server configuration.

    Requires tenant admin role.
    """

    from src.infrastructure.adapters.secondary.persistence.sql_mcp_server_repository import (
        SQLMCPServerRepository,
    )

    repository = SQLMCPServerRepository(db)

    try:
        # Create server
        server_id = await repository.create(
            tenant_id=tenant_id,
            name=server_data.name,
            description=server_data.description,
            server_type=server_data.server_type,
            transport_config=server_data.transport_config,
            enabled=server_data.enabled,
        )

        await db.commit()

        # Fetch created server
        server = await repository.get_by_id(server_id)
        return MCPServerResponse(**server)

    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to create MCP server: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to create MCP server: {str(e)}",
        )


@router.get("", response_model=List[MCPServerResponse])
async def list_mcp_servers(
    enabled_only: bool = Query(False, description="Only return enabled servers"),
    db: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_current_user_tenant),
):
    """
    List all MCP servers for the current tenant.
    """

    from src.infrastructure.adapters.secondary.persistence.sql_mcp_server_repository import (
        SQLMCPServerRepository,
    )

    repository = SQLMCPServerRepository(db)

    servers = await repository.list_by_tenant(
        tenant_id=tenant_id,
        enabled_only=enabled_only,
    )

    return [MCPServerResponse(**server) for server in servers]


@router.get("/{server_id}", response_model=MCPServerResponse)
async def get_mcp_server(
    server_id: str,
    db: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_current_user_tenant),
):
    """
    Get a specific MCP server by ID.
    """

    from src.infrastructure.adapters.secondary.persistence.sql_mcp_server_repository import (
        SQLMCPServerRepository,
    )

    repository = SQLMCPServerRepository(db)

    server = await repository.get_by_id(server_id)

    if not server:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"MCP server not found: {server_id}",
        )

    # Verify tenant ownership
    if server["tenant_id"] != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    return MCPServerResponse(**server)


@router.put("/{server_id}", response_model=MCPServerResponse)
async def update_mcp_server(
    server_id: str,
    server_data: MCPServerUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_current_user_tenant),
):
    """
    Update an MCP server configuration.

    When enabled status changes:
    - false → true: Starts Temporal Workflow
    - true → false: Stops Temporal Workflow

    Requires tenant admin role.
    """

    from src.infrastructure.adapters.secondary.persistence.sql_mcp_server_repository import (
        SQLMCPServerRepository,
    )

    repository = SQLMCPServerRepository(db)

    # Verify server exists and tenant ownership
    server = await repository.get_by_id(server_id)
    if not server:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"MCP server not found: {server_id}",
        )

    if server["tenant_id"] != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    # Detect enabled state change
    old_enabled = server["enabled"]
    new_enabled = server_data.enabled if server_data.enabled is not None else old_enabled

    try:
        # Update server
        await repository.update(
            server_id=server_id,
            name=server_data.name,
            description=server_data.description,
            server_type=server_data.server_type,
            transport_config=server_data.transport_config,
            enabled=server_data.enabled,
        )

        await db.commit()

        # Handle enabled state change - start/stop Temporal Workflow
        if old_enabled != new_enabled:
            try:
                adapter = await get_mcp_temporal_adapter(request)
                updated_server = await repository.get_by_id(server_id)

                if new_enabled:
                    # Start Temporal Workflow
                    transport_config = updated_server["transport_config"]
                    # Build full command from command + args
                    command_str = transport_config.get("command")
                    args = transport_config.get("args", [])
                    full_command = [command_str] + args if command_str else None

                    await adapter.start_mcp_server(
                        tenant_id=tenant_id,
                        server_name=updated_server["name"],
                        transport_type=updated_server["server_type"],
                        command=full_command,
                        environment=transport_config.get("environment")
                        or transport_config.get("env"),
                        url=transport_config.get("url"),
                        headers=transport_config.get("headers"),
                        timeout=transport_config.get("timeout", 30000),
                    )
                    logger.info(f"Started Temporal Workflow for MCP server {server_id}")
                else:
                    # Stop Temporal Workflow
                    await adapter.stop_mcp_server(tenant_id, updated_server["name"])
                    logger.info(f"Stopped Temporal Workflow for MCP server {server_id}")
            except HTTPException:
                # Temporal not available, log and continue
                logger.warning(
                    f"Temporal not available, skipping Workflow management for {server_id}"
                )
            except Exception as e:
                logger.warning(
                    f"Failed to update Temporal Workflow for MCP server {server_id}: {e}"
                )

        # Fetch updated server
        server = await repository.get_by_id(server_id)
        return MCPServerResponse(**server)

    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to update MCP server: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to update MCP server: {str(e)}",
        )


@router.delete("/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_mcp_server(
    server_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_current_user_tenant),
):
    """
    Delete an MCP server.

    Stops Temporal Workflow if server is enabled before deletion.
    Requires tenant admin role.
    """

    from src.infrastructure.adapters.secondary.persistence.sql_mcp_server_repository import (
        SQLMCPServerRepository,
    )

    repository = SQLMCPServerRepository(db)

    # Verify server exists and tenant ownership
    server = await repository.get_by_id(server_id)
    if not server:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"MCP server not found: {server_id}",
        )

    if server["tenant_id"] != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    try:
        # Stop Temporal Workflow if server is enabled
        if server["enabled"]:
            try:
                adapter = await get_mcp_temporal_adapter(request)
                await adapter.stop_mcp_server(tenant_id, server["name"])
                logger.info(f"Stopped Temporal Workflow for deleted MCP server {server_id}")
            except HTTPException:
                # Temporal not available, log and continue
                logger.warning(f"Temporal not available, skipping Workflow stop for {server_id}")
            except Exception as e:
                logger.warning(f"Failed to stop Temporal Workflow for MCP server {server_id}: {e}")

        await repository.delete(server_id)
        await db.commit()

    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to delete MCP server: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to delete MCP server: {str(e)}",
        )


@router.post("/{server_id}/sync", response_model=MCPServerResponse)
async def sync_mcp_server_tools(
    server_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_current_user_tenant),
):
    """
    Sync tools from an MCP server.

    Connects to the server, discovers tools, and updates the database.
    If server.enabled=true, automatically starts or refreshes Temporal Workflow.
    """

    from src.infrastructure.adapters.secondary.persistence.sql_mcp_server_repository import (
        SQLMCPServerRepository,
    )
    from src.infrastructure.agent.mcp.client import MCPClient

    repository = SQLMCPServerRepository(db)

    # Verify server exists and tenant ownership
    server = await repository.get_by_id(server_id)
    if not server:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"MCP server not found: {server_id}",
        )

    if server["tenant_id"] != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    try:
        # Connect to MCP server
        async with MCPClient(
            server_type=server["server_type"],
            transport_config=server["transport_config"],
        ) as client:
            # Discover tools
            tools = await client.list_tools()

            # Update database
            await repository.update_discovered_tools(
                server_id=server_id,
                tools=tools,
                last_sync_at=datetime.utcnow(),
            )

            await db.commit()

            # Start Temporal Workflow if server is enabled
            if server["enabled"]:
                try:
                    adapter = await get_mcp_temporal_adapter(request)
                    transport_config = server["transport_config"]

                    # Build full command from command + args
                    command_str = transport_config.get("command")
                    args = transport_config.get("args", [])
                    full_command = [command_str] + args if command_str else None

                    await adapter.start_mcp_server(
                        tenant_id=tenant_id,
                        server_name=server["name"],
                        transport_type=server["server_type"],
                        command=full_command,
                        environment=transport_config.get("environment")
                        or transport_config.get("env"),
                        url=transport_config.get("url"),
                        headers=transport_config.get("headers"),
                        timeout=transport_config.get("timeout", 30000),
                    )
                    logger.info(
                        f"Started Temporal Workflow for MCP server {server_id} "
                        f"(name={server['name']}, tenant={tenant_id})"
                    )
                except HTTPException:
                    # Temporal not available, log and continue
                    logger.warning(
                        f"Temporal not available, tools synced but Workflow not started for {server_id}"
                    )
                except Exception as e:
                    logger.warning(
                        f"Failed to start Temporal Workflow for MCP server {server_id}: {e}"
                    )

            # Fetch updated server
            server = await repository.get_by_id(server_id)
            return MCPServerResponse(**server)

    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to sync MCP server tools: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to sync MCP server tools: {str(e)}",
        )


class MCPServerTestResult(BaseModel):
    """Schema for MCP server test result."""

    success: bool = Field(..., description="Whether the connection test succeeded")
    message: str = Field(..., description="Test result message")
    latency_ms: Optional[float] = Field(None, description="Connection latency in milliseconds")


@router.post("/{server_id}/test", response_model=MCPServerTestResult)
async def test_mcp_server_connection(
    server_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_current_user_tenant),
):
    """
    Test connection to an MCP server.

    Attempts to connect to the server and returns connection status.
    """
    import time

    from src.infrastructure.adapters.secondary.persistence.sql_mcp_server_repository import (
        SQLMCPServerRepository,
    )
    from src.infrastructure.agent.mcp.client import MCPClient

    repository = SQLMCPServerRepository(db)

    # Verify server exists and tenant ownership
    server = await repository.get_by_id(server_id)
    if not server:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"MCP server not found: {server_id}",
        )

    if server["tenant_id"] != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    try:
        start_time = time.time()

        # Try to connect to MCP server
        async with MCPClient(
            server_type=server["server_type"],
            transport_config=server["transport_config"],
        ) as client:
            # Try to list tools as a connection test
            await client.list_tools()

        latency_ms = (time.time() - start_time) * 1000

        return MCPServerTestResult(
            success=True,
            message="Connection successful",
            latency_ms=latency_ms,
        )

    except Exception as e:
        logger.error(f"Failed to test MCP server connection: {e}")
        return MCPServerTestResult(
            success=False,
            message=f"Connection failed: {str(e)}",
            latency_ms=None,
        )


@router.get("/tools/all", response_model=List[MCPToolResponse])
async def list_all_mcp_tools(
    db: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_current_user_tenant),
):
    """
    List all MCP tools from all enabled servers.
    """

    from src.infrastructure.adapters.secondary.persistence.sql_mcp_server_repository import (
        SQLMCPServerRepository,
    )

    repository = SQLMCPServerRepository(db)

    servers = await repository.get_enabled_servers(tenant_id)

    all_tools = []
    for server in servers:
        for tool in server["discovered_tools"]:
            all_tools.append(
                MCPToolResponse(
                    server_id=server["id"],
                    server_name=server["name"],
                    name=tool.get("name", "unknown"),
                    description=tool.get("description", ""),
                    input_schema=tool.get("inputSchema", {}),
                )
            )

    return all_tools


@router.post("/tools/call", response_model=MCPToolCallResponse)
async def call_mcp_tool(
    request_data: MCPToolCallRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_current_user_tenant),
):
    """
    Call a tool on an MCP server.

    Useful for testing tools before integrating them into agents.
    """

    import time

    from src.infrastructure.adapters.secondary.persistence.sql_mcp_server_repository import (
        SQLMCPServerRepository,
    )
    from src.infrastructure.agent.mcp.client import MCPClient

    repository = SQLMCPServerRepository(db)

    # Verify server exists and tenant ownership
    server = await repository.get_by_id(request_data.server_id)
    if not server:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"MCP server not found: {request_data.server_id}",
        )

    if server["tenant_id"] != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    try:
        # Connect to MCP server and call tool
        start_time = time.time()

        async with MCPClient(
            server_type=server["server_type"],
            transport_config=server["transport_config"],
        ) as client:
            result = await client.call_tool(
                tool_name=request_data.tool_name,
                arguments=request_data.arguments,
            )

        execution_time_ms = (time.time() - start_time) * 1000

        return MCPToolCallResponse(
            server_id=request_data.server_id,
            tool_name=request_data.tool_name,
            result=result,
            execution_time_ms=execution_time_ms,
        )

    except Exception as e:
        logger.error(f"Failed to call MCP tool: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to call MCP tool: {str(e)}",
        )


# === Temporal MCP Management Endpoints ===
# These endpoints manage MCP servers via Temporal Workflows for horizontal scaling


class TemporalMCPConnectRequest(BaseModel):
    """Request schema for starting a Temporal MCP server workflow."""

    server_name: str = Field(..., description="Unique name for this MCP server")
    transport_type: str = Field("local", description="Transport type: 'local', 'http', or 'sse'")

    # Local transport config
    command: Optional[List[str]] = Field(None, description="Command for local MCP server")
    environment: Optional[Dict[str, str]] = Field(None, description="Environment variables")

    # Remote transport config
    url: Optional[str] = Field(None, description="URL for remote MCP server")
    headers: Optional[Dict[str, str]] = Field(None, description="HTTP headers")

    # Common settings
    timeout: int = Field(30000, description="Timeout in milliseconds")


class TemporalMCPStatusResponse(BaseModel):
    """Response schema for Temporal MCP server status."""

    server_name: str
    tenant_id: str
    connected: bool = False
    tool_count: int = 0
    error: Optional[str] = None
    workflow_id: Optional[str] = None


class TemporalMCPToolInfo(BaseModel):
    """Information about an MCP tool from Temporal."""

    name: str
    server_name: str
    description: Optional[str] = None
    input_schema: Dict[str, Any] = Field(default_factory=dict)


class TemporalMCPToolCallRequest(BaseModel):
    """Request schema for calling a Temporal MCP tool."""

    tool_name: str = Field(..., description="Name of the tool to call")
    arguments: Dict[str, Any] = Field(default_factory=dict, description="Tool arguments")
    timeout: Optional[int] = Field(None, description="Timeout in milliseconds")


class TemporalMCPToolCallResponse(BaseModel):
    """Response schema for Temporal MCP tool call."""

    content: List[Dict[str, Any]]
    is_error: bool = False
    error_message: Optional[str] = None
    execution_time_ms: float


async def get_mcp_temporal_adapter(request: Request):
    """Get MCPTemporalAdapter from DI container."""

    container = request.app.state.container
    adapter = await container.mcp_temporal_adapter()
    if adapter is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Temporal service is not available. MCP Temporal features require Temporal server.",
        )
    return adapter


@router.post("/temporal/servers", response_model=TemporalMCPStatusResponse)
async def start_temporal_mcp_server(
    connect_request: TemporalMCPConnectRequest,
    request: Request,
    tenant_id: str = Depends(get_current_user_tenant),
):
    """
    Start an MCP server via Temporal Workflow.

    Creates a long-running workflow that manages the MCP server lifecycle.
    The server runs in a separate MCP Worker process for horizontal scaling.

    Benefits over runtime/connect:
    - Survives API service restarts
    - Runs in separate worker process
    - Supports horizontal scaling
    - Tenant isolation via workflow ID
    """
    try:
        adapter = await get_mcp_temporal_adapter(request)

        status = await adapter.start_mcp_server(
            tenant_id=tenant_id,
            server_name=connect_request.server_name,
            transport_type=connect_request.transport_type,
            command=connect_request.command,
            environment=connect_request.environment,
            url=connect_request.url,
            headers=connect_request.headers,
            timeout=connect_request.timeout,
        )

        return TemporalMCPStatusResponse(
            server_name=status.server_name,
            tenant_id=status.tenant_id,
            connected=status.connected,
            tool_count=status.tool_count,
            error=status.error,
            workflow_id=status.workflow_id,
        )

    except Exception as e:
        logger.error(f"Failed to start Temporal MCP server: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start MCP server: {str(e)}",
        )


@router.delete("/temporal/servers/{server_name}", status_code=status.HTTP_204_NO_CONTENT)
async def stop_temporal_mcp_server(
    server_name: str,
    request: Request,
    tenant_id: str = Depends(get_current_user_tenant),
):
    """
    Stop a Temporal MCP server workflow.
    """
    try:
        adapter = await get_mcp_temporal_adapter(request)
        await adapter.stop_mcp_server(tenant_id, server_name)

    except Exception as e:
        logger.error(f"Failed to stop Temporal MCP server: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to stop MCP server: {str(e)}",
        )


@router.get("/temporal/servers", response_model=List[TemporalMCPStatusResponse])
async def list_temporal_mcp_servers(
    request: Request,
    tenant_id: str = Depends(get_current_user_tenant),
):
    """
    List all Temporal MCP servers for the current tenant.
    """
    try:
        adapter = await get_mcp_temporal_adapter(request)
        servers = await adapter.list_servers(tenant_id)

        return [
            TemporalMCPStatusResponse(
                server_name=s.server_name,
                tenant_id=s.tenant_id,
                connected=s.connected,
                tool_count=s.tool_count,
                error=s.error,
                workflow_id=s.workflow_id,
            )
            for s in servers
        ]

    except Exception as e:
        logger.error(f"Failed to list Temporal MCP servers: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list MCP servers: {str(e)}",
        )


@router.get("/temporal/servers/{server_name}/status", response_model=TemporalMCPStatusResponse)
async def get_temporal_mcp_server_status(
    server_name: str,
    request: Request,
    tenant_id: str = Depends(get_current_user_tenant),
):
    """
    Get status of a specific Temporal MCP server.
    """
    try:
        adapter = await get_mcp_temporal_adapter(request)
        status = await adapter.get_server_status(tenant_id, server_name)

        return TemporalMCPStatusResponse(
            server_name=status.server_name,
            tenant_id=status.tenant_id,
            connected=status.connected,
            tool_count=status.tool_count,
            error=status.error,
            workflow_id=status.workflow_id,
        )

    except Exception as e:
        logger.error(f"Failed to get Temporal MCP server status: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get MCP server status: {str(e)}",
        )


@router.get("/temporal/servers/{server_name}/tools", response_model=List[TemporalMCPToolInfo])
async def list_temporal_mcp_tools(
    server_name: str,
    request: Request,
    tenant_id: str = Depends(get_current_user_tenant),
):
    """
    List tools available from a Temporal MCP server.
    """
    try:
        adapter = await get_mcp_temporal_adapter(request)
        tools = await adapter.list_tools(tenant_id, server_name)

        return [
            TemporalMCPToolInfo(
                name=t.name,
                server_name=t.server_name,
                description=t.description,
                input_schema=t.input_schema,
            )
            for t in tools
        ]

    except Exception as e:
        logger.error(f"Failed to list Temporal MCP tools: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list MCP tools: {str(e)}",
        )


@router.get("/temporal/tools", response_model=List[TemporalMCPToolInfo])
async def list_all_temporal_mcp_tools(
    request: Request,
    tenant_id: str = Depends(get_current_user_tenant),
):
    """
    List all tools from all Temporal MCP servers for the current tenant.
    """
    try:
        adapter = await get_mcp_temporal_adapter(request)
        tools = await adapter.list_all_tools(tenant_id)

        return [
            TemporalMCPToolInfo(
                name=t.name,
                server_name=t.server_name,
                description=t.description,
                input_schema=t.input_schema,
            )
            for t in tools
        ]

    except Exception as e:
        logger.error(f"Failed to list all Temporal MCP tools: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list MCP tools: {str(e)}",
        )


@router.post(
    "/temporal/servers/{server_name}/tools/call",
    response_model=TemporalMCPToolCallResponse,
)
async def call_temporal_mcp_tool(
    server_name: str,
    call_request: TemporalMCPToolCallRequest,
    request: Request,
    tenant_id: str = Depends(get_current_user_tenant),
):
    """
    Call a tool on a Temporal MCP server.

    The tool call is executed via Temporal Workflow update,
    ensuring reliable execution with automatic retries.
    """
    import time

    try:
        adapter = await get_mcp_temporal_adapter(request)

        start_time = time.time()

        result = await adapter.call_mcp_tool(
            tenant_id=tenant_id,
            server_name=server_name,
            tool_name=call_request.tool_name,
            arguments=call_request.arguments,
            timeout=call_request.timeout,
        )

        execution_time_ms = (time.time() - start_time) * 1000

        return TemporalMCPToolCallResponse(
            content=result.content,
            is_error=result.is_error,
            error_message=result.error_message,
            execution_time_ms=execution_time_ms,
        )

    except Exception as e:
        logger.error(f"Failed to call Temporal MCP tool: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to call MCP tool: {str(e)}",
        )
