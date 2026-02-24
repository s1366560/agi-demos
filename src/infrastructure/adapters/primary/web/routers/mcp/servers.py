"""MCP Server management endpoints (database-backed).

CRUD operations for MCP server configurations stored in database.
MCP servers are project-scoped and run inside project sandbox containers.
"""

import logging
import time
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.mcp_runtime_service import MCPRuntimeService
from src.domain.model.mcp.server import MCPServer
from src.infrastructure.adapters.primary.web.dependencies import get_current_user_tenant
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.sql_mcp_app_repository import (
    SqlMCPAppRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_mcp_server_repository import (
    SqlMCPServerRepository,
)

from .schemas import (
    MCPHealthSummary,
    MCPReconcileResultResponse,
    MCPServerCreate,
    MCPServerHealthStatus,
    MCPServerResponse,
    MCPServerTestResult,
    MCPServerUpdate,
)
from .utils import ensure_project_access, get_sandbox_mcp_server_manager

logger = logging.getLogger(__name__)

router = APIRouter()


async def _get_runtime_service(request: Request, db: AsyncSession) -> MCPRuntimeService:
    """Build unified MCP runtime service for request scope."""
    container = request.app.state.container.with_db(db)
    manager = await get_sandbox_mcp_server_manager(request, db)
    return MCPRuntimeService(
        db=db,
        server_repo=SqlMCPServerRepository(db),
        app_repo=SqlMCPAppRepository(db),
        app_service=container.mcp_app_service(),
        sandbox_manager=manager,
        redis_client=container.redis(),
    )


@router.post("/create", response_model=MCPServerResponse, status_code=status.HTTP_201_CREATED)
async def create_mcp_server(
    server_data: MCPServerCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_current_user_tenant),
) -> Any:
    """
    Create a new MCP server configuration.

    The server is bound to the project specified by project_id.
    Auto-discovers tools after creation so they are immediately available.
    """
    try:
        runtime = await _get_runtime_service(request, db)
        server = await runtime.create_server(
            tenant_id=tenant_id,
            project_id=server_data.project_id,
            name=server_data.name,
            description=server_data.description,
            server_type=server_data.server_type,
            transport_config=server_data.transport_config,
            enabled=server_data.enabled,
        )
        await db.commit()

        from src.infrastructure.agent.state.agent_session_pool import (
            invalidate_mcp_tools_cache,
        )

        invalidate_mcp_tools_cache(tenant_id)
        return MCPServerResponse.model_validate(server)

    except PermissionError as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e),
        ) from e
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to create MCP server: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to create MCP server: {e!s}",
        ) from e


@router.get("/list", response_model=list[MCPServerResponse])
async def list_mcp_servers(
    project_id: str | None = Query(None, description="Filter by project ID"),
    enabled_only: bool = Query(False, description="Only return enabled servers"),
    db: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_current_user_tenant),
) -> list[Any]:
    """
    List MCP servers. If project_id is provided, returns servers for that project only.
    Otherwise returns all servers for the current tenant.
    """
    repository = SqlMCPServerRepository(db)

    if project_id:
        await ensure_project_access(db, project_id, tenant_id)
        servers = await repository.list_by_project(
            project_id=project_id,
            enabled_only=enabled_only,
        )
    else:
        servers = await repository.list_by_tenant(
            tenant_id=tenant_id,
            enabled_only=enabled_only,
        )

    return [MCPServerResponse.model_validate(server) for server in servers]


@router.get("/{server_id}", response_model=MCPServerResponse)
async def get_mcp_server(
    server_id: str,
    db: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_current_user_tenant),
) -> Any:
    """
    Get a specific MCP server by ID.
    """
    repository = SqlMCPServerRepository(db)

    server = await repository.get_by_id(server_id)

    if not server:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"MCP server not found: {server_id}",
        )

    if server.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    return MCPServerResponse.model_validate(server)


@router.put("/{server_id}", response_model=MCPServerResponse)
async def update_mcp_server(
    server_id: str,
    server_data: MCPServerUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_current_user_tenant),
) -> Any:
    """
    Update an MCP server configuration.

    When enabled status changes, starts/stops the server in its project sandbox.
    """
    try:
        runtime = await _get_runtime_service(request, db)
        server = await runtime.update_server(
            server_id=server_id,
            tenant_id=tenant_id,
            name=server_data.name,
            description=server_data.description,
            server_type=server_data.server_type,
            transport_config=server_data.transport_config,
            enabled=server_data.enabled,
        )
        await db.commit()

        from src.infrastructure.agent.state.agent_session_pool import (
            invalidate_mcp_tools_cache,
        )

        invalidate_mcp_tools_cache(tenant_id)
        return MCPServerResponse.model_validate(server)

    except ValueError as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    except PermissionError as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e),
        ) from e
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to update MCP server: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to update MCP server: {e!s}",
        ) from e


@router.delete("/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_mcp_server(
    server_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_current_user_tenant),
) -> None:
    """
    Delete an MCP server.

    Stops the server in its project sandbox if enabled before deletion.
    """
    repository = SqlMCPServerRepository(db)

    server = await repository.get_by_id(server_id)
    if not server:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"MCP server not found: {server_id}",
        )

    if server.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    try:
        runtime = await _get_runtime_service(request, db)
        await runtime.delete_server(server_id, tenant_id)

        from src.infrastructure.agent.state.agent_session_pool import (
            invalidate_mcp_tools_cache,
        )
        from src.infrastructure.mcp.tools.factory import MCPToolFactory

        invalidate_mcp_tools_cache(tenant_id)
        MCPToolFactory.remove_adapter(server.name)
        await db.commit()

    except ValueError as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    except PermissionError as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e),
        ) from e
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to delete MCP server: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to delete MCP server: {e!s}",
        ) from e


@router.post("/{server_id}/sync", response_model=MCPServerResponse)
async def sync_mcp_server_tools(
    server_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_current_user_tenant),
) -> Any:
    """
    Sync tools from an MCP server.

    Uses the server's stored project_id to determine sandbox context.
    """
    try:
        runtime = await _get_runtime_service(request, db)
        server = await runtime.sync_server(server_id, tenant_id)
        await db.commit()

        from src.infrastructure.agent.state.agent_session_pool import (
            invalidate_mcp_tools_cache,
        )

        invalidate_mcp_tools_cache(tenant_id)
        return MCPServerResponse.model_validate(server)

    except ValueError as e:
        await db.rollback()
        message = str(e)
        raise HTTPException(
            status_code=(
                status.HTTP_404_NOT_FOUND
                if "not found" in message.lower()
                else status.HTTP_400_BAD_REQUEST
            ),
            detail=message,
        ) from e
    except PermissionError as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e),
        ) from e
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to sync MCP server tools: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to sync MCP server tools: {e!s}",
        ) from e


@router.post("/{server_id}/test", response_model=MCPServerTestResult)
async def test_mcp_server_connection(
    server_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_current_user_tenant),
) -> MCPServerTestResult:
    """
    Test connection to an MCP server.

    Uses the server's stored project_id to determine sandbox context.
    """
    try:
        start_time = time.time()
        runtime = await _get_runtime_service(request, db)
        result = await runtime.test_server(server_id, tenant_id)
        await db.commit()

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

    except ValueError as e:
        await db.rollback()
        message = str(e)
        raise HTTPException(
            status_code=(
                status.HTTP_404_NOT_FOUND
                if "not found" in message.lower()
                else status.HTTP_400_BAD_REQUEST
            ),
            detail=message,
        ) from e
    except PermissionError as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e),
        ) from e
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to test MCP server connection: {e}")
        return MCPServerTestResult(
            success=False,
            message=f"Connection failed: {e!s}",
            errors=[str(e)],
        )


@router.post("/reconcile/{project_id}", response_model=MCPReconcileResultResponse)
async def reconcile_mcp_project(
    project_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_current_user_tenant),
) -> MCPReconcileResultResponse:
    """Reconcile enabled MCP servers with current sandbox runtime."""
    try:
        runtime = await _get_runtime_service(request, db)
        result = await runtime.reconcile_project(project_id, tenant_id)
        await db.commit()
        return MCPReconcileResultResponse(
            project_id=result.project_id,
            total_enabled_servers=result.total_enabled_servers,
            already_running=result.already_running,
            restored=result.restored,
            failed=result.failed,
        )
    except PermissionError as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e),
        ) from e
    except Exception as e:
        await db.rollback()
        logger.exception("Failed to reconcile MCP project %s", project_id)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to reconcile MCP servers",
        ) from e


def _compute_server_health(server: MCPServer) -> MCPServerHealthStatus:
    """Compute health status for a single server from its stored state."""
    if not server.enabled:
        health_status: Literal["healthy", "degraded", "error", "disabled", "unknown"] = "disabled"
    elif server.sync_error:
        health_status = "error"
    elif not server.last_sync_at:
        health_status = "unknown"
    elif server.discovered_tools:
        health_status = "healthy"
    else:
        health_status = "degraded"

    return MCPServerHealthStatus(
        id=server.id,
        name=server.name,
        status=health_status,
        enabled=server.enabled,
        last_sync_at=server.last_sync_at,
        sync_error=server.sync_error,
        tools_count=len(server.discovered_tools or []),
    )


@router.get("/health/summary", response_model=MCPHealthSummary)
async def get_mcp_health_summary(
    project_id: str | None = Query(None, description="Filter by project ID"),
    db: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_current_user_tenant),
) -> MCPHealthSummary:
    """Get aggregated health summary for all MCP servers."""
    from src.infrastructure.adapters.secondary.persistence.sql_mcp_server_repository import (
        SqlMCPServerRepository,
    )

    repository = SqlMCPServerRepository(db)

    if project_id:
        await ensure_project_access(db, project_id, tenant_id)
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
) -> MCPServerHealthStatus:
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
    if server.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    return _compute_server_health(server)
