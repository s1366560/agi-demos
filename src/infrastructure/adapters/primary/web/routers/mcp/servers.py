"""MCP Server management endpoints (database-backed).

CRUD operations for MCP server configurations stored in database.
MCP servers are project-scoped and run inside project sandbox containers.
"""

import logging
import time
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.primary.web.dependencies import get_current_user_tenant
from src.infrastructure.adapters.secondary.persistence.database import get_db

from .schemas import (
    MCPHealthSummary,
    MCPServerCreate,
    MCPServerHealthStatus,
    MCPServerResponse,
    MCPServerTestResult,
    MCPServerUpdate,
)
from .utils import get_sandbox_mcp_server_manager

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/create", response_model=MCPServerResponse, status_code=status.HTTP_201_CREATED)
async def create_mcp_server(
    server_data: MCPServerCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_current_user_tenant),
):
    """
    Create a new MCP server configuration.

    The server is bound to the project specified by project_id.
    Auto-discovers tools after creation so they are immediately available.
    """
    from src.infrastructure.adapters.secondary.persistence.sql_mcp_server_repository import (
        SqlMCPServerRepository,
    )

    repository = SqlMCPServerRepository(db)

    try:
        server_id = await repository.create(
            tenant_id=tenant_id,
            project_id=server_data.project_id,
            name=server_data.name,
            description=server_data.description,
            server_type=server_data.server_type,
            transport_config=server_data.transport_config,
            enabled=server_data.enabled,
        )

        await db.commit()

        # Auto-discover tools (best-effort, does not block creation)
        if server_data.project_id:
            try:
                manager = await get_sandbox_mcp_server_manager(request, db)
                tools = await manager.discover_tools(
                    project_id=server_data.project_id,
                    tenant_id=tenant_id,
                    server_name=server_data.name,
                    server_type=server_data.server_type,
                    transport_config=server_data.transport_config,
                )
                await repository.update_discovered_tools(
                    server_id=server_id,
                    tools=tools,
                    last_sync_at=datetime.now(timezone.utc),
                )
                await db.commit()

                if server_data.enabled:
                    from src.infrastructure.agent.state.agent_session_pool import (
                        invalidate_mcp_tools_cache,
                    )

                    invalidate_mcp_tools_cache(tenant_id)

                logger.info(
                    f"Auto-discovered {len(tools)} tools from MCP server "
                    f"'{server_data.name}' (project={server_data.project_id})"
                )
            except Exception as e:
                sync_err = str(e)
                logger.warning(
                    f"Auto-discovery failed for MCP server '{server_data.name}', "
                    f"manual sync required: {sync_err}"
                )
                try:
                    await repository.update_discovered_tools(
                        server_id=server_id,
                        tools=[],
                        last_sync_at=datetime.now(timezone.utc),
                        sync_error=sync_err,
                    )
                    await db.commit()
                except Exception:
                    pass

        server = await repository.get_by_id(server_id)
        return MCPServerResponse(**server)

    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to create MCP server: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to create MCP server: {e!s}",
        )


@router.get("/list", response_model=List[MCPServerResponse])
async def list_mcp_servers(
    project_id: Optional[str] = Query(None, description="Filter by project ID"),
    enabled_only: bool = Query(False, description="Only return enabled servers"),
    db: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_current_user_tenant),
):
    """
    List MCP servers. If project_id is provided, returns servers for that project only.
    Otherwise returns all servers for the current tenant.
    """
    from src.infrastructure.adapters.secondary.persistence.sql_mcp_server_repository import (
        SqlMCPServerRepository,
    )

    repository = SqlMCPServerRepository(db)

    if project_id:
        servers = await repository.list_by_project(
            project_id=project_id,
            enabled_only=enabled_only,
        )
    else:
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

    When enabled status changes, starts/stops the server in its project sandbox.
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

    if server["tenant_id"] != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    old_enabled = server["enabled"]
    new_enabled = server_data.enabled if server_data.enabled is not None else old_enabled
    project_id = server["project_id"]

    try:
        await repository.update(
            server_id=server_id,
            name=server_data.name,
            description=server_data.description,
            server_type=server_data.server_type,
            transport_config=server_data.transport_config,
            enabled=server_data.enabled,
        )

        await db.commit()

        # Handle enabled state change - start/stop in project sandbox
        if old_enabled != new_enabled and project_id:
            try:
                updated_server = await repository.get_by_id(server_id)
                manager = await get_sandbox_mcp_server_manager(request, db)

                if new_enabled:
                    await manager.install_and_start(
                        project_id=project_id,
                        tenant_id=tenant_id,
                        server_name=updated_server["name"],
                        server_type=updated_server["server_type"],
                        transport_config=updated_server["transport_config"],
                    )
                    logger.info(f"Started MCP server {server_id} in sandbox (project={project_id})")

                    # Auto-discover tools on enable (best-effort)
                    try:
                        tools = await manager.discover_tools(
                            project_id=project_id,
                            tenant_id=tenant_id,
                            server_name=updated_server["name"],
                            server_type=updated_server["server_type"],
                            transport_config=updated_server["transport_config"],
                        )
                        await repository.update_discovered_tools(
                            server_id=server_id,
                            tools=tools,
                            last_sync_at=datetime.now(timezone.utc),
                        )
                        await db.commit()
                        logger.info(
                            f"Auto-discovered {len(tools)} tools on enable "
                            f"for MCP server '{updated_server['name']}'"
                        )
                    except Exception as disc_err:
                        sync_err = str(disc_err)
                        logger.warning(
                            f"Auto-discovery failed on enable for MCP server "
                            f"{server_id}, manual sync required: {sync_err}"
                        )
                        try:
                            await repository.update_discovered_tools(
                                server_id=server_id,
                                tools=[],
                                last_sync_at=datetime.now(timezone.utc),
                                sync_error=sync_err,
                            )
                            await db.commit()
                        except Exception:
                            pass
                else:
                    await manager.stop_server(project_id, updated_server["name"])
                    logger.info(f"Stopped MCP server {server_id}")

                    # Clean up tool adapter cache on disable
                    try:
                        from src.infrastructure.mcp.tools.factory import MCPToolFactory

                        MCPToolFactory.remove_adapter(updated_server["name"])
                    except Exception:
                        pass

                from src.infrastructure.agent.state.agent_session_pool import (
                    invalidate_mcp_tools_cache,
                )

                invalidate_mcp_tools_cache(tenant_id)
            except Exception as e:
                logger.warning(f"Failed to update MCP server lifecycle for {server_id}: {e}")

        server = await repository.get_by_id(server_id)
        return MCPServerResponse(**server)

    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to update MCP server: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to update MCP server: {e!s}",
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

    Stops the server in its project sandbox if enabled before deletion.
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

    if server["tenant_id"] != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    try:
        # Stop in project sandbox if enabled
        if server["enabled"] and server.get("project_id"):
            try:
                manager = await get_sandbox_mcp_server_manager(request, db)
                await manager.stop_server(server["project_id"], server["name"])

                from src.infrastructure.agent.state.agent_session_pool import (
                    invalidate_mcp_tools_cache,
                )

                invalidate_mcp_tools_cache(tenant_id)
                logger.info(f"Stopped MCP server for deleted config {server_id}")
            except Exception as e:
                logger.warning(f"Failed to stop MCP server {server_id}: {e}")

        # Clean up tool adapter cache
        try:
            from src.infrastructure.mcp.tools.factory import MCPToolFactory

            MCPToolFactory.remove_adapter(server["name"])
        except Exception:
            pass

        # Clean up associated MCP Apps before deleting server
        try:
            from src.application.services.mcp_app_service import MCPAppService
            from src.infrastructure.adapters.secondary.persistence.sql_mcp_app_repository import (
                SqlMCPAppRepository,
            )

            app_service = MCPAppService(
                app_repo=SqlMCPAppRepository(db),
                resource_resolver=None,
            )
            deleted_count = await app_service.delete_apps_by_server(server_id)
            if deleted_count > 0:
                logger.info(f"Cleaned up {deleted_count} MCP apps for server {server_id}")
        except Exception as e:
            logger.warning(f"Failed to clean up MCP apps for server {server_id}: {e}")

        await repository.delete(server_id)
        await db.commit()

    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to delete MCP server: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to delete MCP server: {e!s}",
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

    Uses the server's stored project_id to determine sandbox context.
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

    if server["tenant_id"] != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    project_id = server.get("project_id")
    if not project_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="MCP server has no associated project",
        )

    try:
        manager = await get_sandbox_mcp_server_manager(request, db)
        tools = await manager.discover_tools(
            project_id=project_id,
            tenant_id=tenant_id,
            server_name=server["name"],
            server_type=server["server_type"],
            transport_config=server["transport_config"],
        )

        await repository.update_discovered_tools(
            server_id=server_id,
            tools=tools,
            last_sync_at=datetime.now(timezone.utc),
            sync_error=None,
        )
        await db.commit()

        if server["enabled"]:
            from src.infrastructure.agent.state.agent_session_pool import (
                invalidate_mcp_tools_cache,
            )

            invalidate_mcp_tools_cache(tenant_id)

        logger.info(
            f"Synced {len(tools)} tools from MCP server '{server['name']}' (project={project_id})"
        )

        server = await repository.get_by_id(server_id)
        return MCPServerResponse(**server)

    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to sync MCP server tools: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to sync MCP server tools: {e!s}",
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

    Uses the server's stored project_id to determine sandbox context.
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

    if server["tenant_id"] != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    project_id = server.get("project_id")
    if not project_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="MCP server has no associated project",
        )

    try:
        start_time = time.time()

        manager = await get_sandbox_mcp_server_manager(request, db)
        result = await manager.test_connection(
            project_id=project_id,
            tenant_id=tenant_id,
            server_name=server["name"],
            server_type=server["server_type"],
            transport_config=server["transport_config"],
        )

        latency_ms = (time.time() - start_time) * 1000

        if result.status == "failed":
            return MCPServerTestResult(
                success=False,
                message=f"Connection failed: {result.error}",
                errors=[result.error] if result.error else [],
            )

        return MCPServerTestResult(
            success=True,
            message="Connection successful",
            tools_discovered=result.tool_count,
            connection_time_ms=latency_ms,
        )

    except Exception as e:
        logger.error(f"Failed to test MCP server connection: {e}")
        return MCPServerTestResult(
            success=False,
            message=f"Connection failed: {e!s}",
            errors=[str(e)],
        )


def _compute_server_health(server: dict) -> MCPServerHealthStatus:
    """Compute health status for a single server from its stored state."""
    if not server.get("enabled"):
        health_status = "disabled"
    elif server.get("sync_error"):
        health_status = "error"
    elif not server.get("last_sync_at"):
        health_status = "unknown"
    elif server.get("discovered_tools"):
        health_status = "healthy"
    else:
        health_status = "degraded"

    return MCPServerHealthStatus(
        id=server["id"],
        name=server["name"],
        status=health_status,
        enabled=server.get("enabled", False),
        last_sync_at=server.get("last_sync_at"),
        sync_error=server.get("sync_error"),
        tools_count=len(server.get("discovered_tools") or []),
    )


@router.get("/health/summary", response_model=MCPHealthSummary)
async def get_mcp_health_summary(
    project_id: Optional[str] = Query(None, description="Filter by project ID"),
    db: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_current_user_tenant),
):
    """Get aggregated health summary for all MCP servers."""
    from src.infrastructure.adapters.secondary.persistence.sql_mcp_server_repository import (
        SqlMCPServerRepository,
    )

    repository = SqlMCPServerRepository(db)

    if project_id:
        servers = await repository.list_by_project(project_id)
    else:
        servers = await repository.list_by_tenant(tenant_id)

    statuses = [_compute_server_health(s) for s in servers]

    return MCPHealthSummary(
        total=len(statuses),
        healthy=sum(1 for s in statuses if s.status == "healthy"),
        degraded=sum(1 for s in statuses if s.status == "degraded"),
        error=sum(1 for s in statuses if s.status == "error"),
        disabled=sum(1 for s in statuses if s.status == "disabled"),
        servers=statuses,
    )


@router.get("/{server_id}/health", response_model=MCPServerHealthStatus)
async def get_mcp_server_health(
    server_id: str,
    db: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_current_user_tenant),
):
    """Get health status for a single MCP server (lightweight, no connection test)."""
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
    if server["tenant_id"] != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    return _compute_server_health(server)
