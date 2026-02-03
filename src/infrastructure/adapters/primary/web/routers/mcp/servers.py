"""MCP Server management endpoints (database-backed).

CRUD operations for MCP server configurations stored in database.
"""

import logging
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.primary.web.dependencies import get_current_user_tenant
from src.infrastructure.adapters.secondary.persistence.database import get_db

from .schemas import (
    MCPServerCreate,
    MCPServerResponse,
    MCPServerTestResult,
    MCPServerUpdate,
)
from .utils import get_mcp_temporal_adapter

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/create", response_model=MCPServerResponse, status_code=status.HTTP_201_CREATED)
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
        SqlMCPServerRepository,
    )

    repository = SqlMCPServerRepository(db)

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


@router.get("/list", response_model=List[MCPServerResponse])
async def list_mcp_servers(
    enabled_only: bool = Query(False, description="Only return enabled servers"),
    db: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_current_user_tenant),
):
    """
    List all MCP servers for the current tenant.
    """
    from src.infrastructure.adapters.secondary.persistence.sql_mcp_server_repository import (
        SqlMCPServerRepository,
    )

    repository = SqlMCPServerRepository(db)

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
        SqlMCPServerRepository,
    )

    repository = SqlMCPServerRepository(db)

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
        SqlMCPServerRepository,
    )

    repository = SqlMCPServerRepository(db)

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
        SqlMCPServerRepository,
    )

    repository = SqlMCPServerRepository(db)

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
        SqlMCPServerRepository,
    )
    from src.infrastructure.agent.mcp.client import MCPClient

    repository = SqlMCPServerRepository(db)

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
        SqlMCPServerRepository,
    )
    from src.infrastructure.agent.mcp.client import MCPClient

    repository = SqlMCPServerRepository(db)

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
            tools = await client.list_tools()

        latency_ms = (time.time() - start_time) * 1000

        return MCPServerTestResult(
            success=True,
            message="Connection successful",
            tools_discovered=len(tools) if tools else 0,
            connection_time_ms=latency_ms,
        )

    except Exception as e:
        logger.error(f"Failed to test MCP server connection: {e}")
        return MCPServerTestResult(
            success=False,
            message=f"Connection failed: {str(e)}",
            errors=[str(e)],
        )
