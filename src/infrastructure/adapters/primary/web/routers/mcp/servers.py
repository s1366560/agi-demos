"""MCP Server management endpoints (database-backed).

CRUD operations for MCP server configurations stored in database.
MCP servers are project-scoped and run inside project sandbox containers.
"""

import logging
import time
from collections.abc import Collection
from typing import Any, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.mcp_runtime_service import MCPRuntimeService
from src.domain.model.mcp.server import MCPServer
from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user,
    get_current_user_tenant,
)
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import MCPLifecycleEvent, User
from src.infrastructure.adapters.secondary.persistence.sql_mcp_server_repository import (
    SqlMCPServerRepository,
)
from src.infrastructure.i18n import gettext as _

from .schemas import (
    MCPHealthSummary,
    MCPReconcileResultResponse,
    MCPServerCreate,
    MCPServerHealthStatus,
    MCPServerResponse,
    MCPServerTestResult,
    MCPServerUpdate,
)
from .utils import MCP_PROJECT_WRITE_ROLES, ensure_project_access, list_accessible_project_ids

logger = logging.getLogger(__name__)

router = APIRouter()

MCP_LOGGING_LEVELS = {
    "debug",
    "info",
    "notice",
    "warning",
    "error",
    "critical",
    "alert",
    "emergency",
}


def _mcp_server_not_found_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=_("MCP server not found"),
    )


def _mcp_access_denied_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=_("Access denied"),
    )


def _mcp_server_action_failed_error(status_code: int = status.HTTP_400_BAD_REQUEST) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail=_("MCP server operation failed"),
    )


async def _get_runtime_service(request: Request, db: AsyncSession) -> MCPRuntimeService:
    """Get unified MCP runtime service from DI container (H2 fix)."""
    container = request.app.state.container.with_db(db)
    return cast(MCPRuntimeService, container.mcp_runtime_service())


@router.post("/create", response_model=MCPServerResponse, status_code=status.HTTP_201_CREATED)
async def create_mcp_server(
    server_data: MCPServerCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_current_user_tenant),
    current_user: User = Depends(get_current_user),
) -> Any:
    """
    Create a new MCP server configuration.

    The server is bound to the project specified by project_id.
    Auto-discovers tools after creation so they are immediately available.
    """
    await ensure_project_access(
        db,
        server_data.project_id,
        tenant_id,
        current_user.id,
        MCP_PROJECT_WRITE_ROLES,
    )
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

        _cache_generation = invalidate_mcp_tools_cache(tenant_id)
        return MCPServerResponse.model_validate(server)

    except PermissionError as e:
        await db.rollback()
        raise _mcp_access_denied_error() from e
    except Exception as e:
        await db.rollback()
        logger.exception("Failed to create MCP server")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_("Failed to create MCP server"),
        ) from e


@router.get("/list", response_model=list[MCPServerResponse])
async def list_mcp_servers(
    project_id: str | None = Query(None, description="Filter by project ID"),
    enabled_only: bool = Query(False, description="Only return enabled servers"),
    db: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_current_user_tenant),
    current_user: User = Depends(get_current_user),
) -> list[Any]:
    """
    List MCP servers. If project_id is provided, returns servers for that project only.
    Otherwise returns all servers for the current tenant.
    """
    repository = SqlMCPServerRepository(db)

    if project_id:
        await ensure_project_access(db, project_id, tenant_id, current_user.id)
        servers = await repository.list_by_project(
            project_id=project_id,
            enabled_only=enabled_only,
        )
    else:
        accessible_project_ids = await list_accessible_project_ids(db, tenant_id, current_user.id)
        if not accessible_project_ids:
            return []
        servers = await repository.list_by_tenant(
            tenant_id=tenant_id,
            enabled_only=enabled_only,
        )
        servers = [server for server in servers if server.project_id in accessible_project_ids]

    return [MCPServerResponse.model_validate(server) for server in servers]


@router.get("/{server_id}", response_model=MCPServerResponse)
async def get_mcp_server(
    server_id: str,
    db: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_current_user_tenant),
    current_user: User = Depends(get_current_user),
) -> Any:
    """
    Get a specific MCP server by ID.
    """
    server = await _get_mcp_server_for_tenant(db, server_id, tenant_id, current_user.id)

    return MCPServerResponse.model_validate(server)


@router.put("/{server_id}", response_model=MCPServerResponse)
async def update_mcp_server(
    server_id: str,
    server_data: MCPServerUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_current_user_tenant),
    current_user: User = Depends(get_current_user),
) -> Any:
    """
    Update an MCP server configuration.

    When enabled status changes, starts/stops the server in its project sandbox.
    """
    _checked_server = await _get_mcp_server_for_tenant(
        db,
        server_id,
        tenant_id,
        current_user.id,
        MCP_PROJECT_WRITE_ROLES,
    )
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

        _cache_generation = invalidate_mcp_tools_cache(tenant_id)
        return MCPServerResponse.model_validate(server)

    except ValueError as e:
        await db.rollback()
        raise _mcp_server_not_found_error() from e
    except PermissionError as e:
        await db.rollback()
        raise _mcp_access_denied_error() from e
    except Exception as e:
        await db.rollback()
        logger.exception("Failed to update MCP server")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_("Failed to update MCP server"),
        ) from e


@router.delete("/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_mcp_server(
    server_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_current_user_tenant),
    current_user: User = Depends(get_current_user),
) -> None:
    """
    Delete an MCP server.

    Stops the server in its project sandbox if enabled before deletion.
    """
    _checked_server = await _get_mcp_server_for_tenant(
        db,
        server_id,
        tenant_id,
        current_user.id,
        MCP_PROJECT_WRITE_ROLES,
    )

    try:
        runtime = await _get_runtime_service(request, db)
        await runtime.delete_server(server_id, tenant_id)

        from src.infrastructure.agent.state.agent_session_pool import (
            invalidate_mcp_tools_cache,
        )

        _cache_generation = invalidate_mcp_tools_cache(tenant_id)
        # NOTE: MCPToolFactory.remove_adapter() was removed -- it was a bug
        # (calling instance method on class). Cache invalidation above is sufficient.
        await db.commit()

    except ValueError as e:
        await db.rollback()
        raise _mcp_server_not_found_error() from e
    except PermissionError as e:
        await db.rollback()
        raise _mcp_access_denied_error() from e
    except Exception as e:
        await db.rollback()
        logger.exception("Failed to delete MCP server")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_("Failed to delete MCP server"),
        ) from e


@router.post("/{server_id}/sync", response_model=MCPServerResponse)
async def sync_mcp_server_tools(
    server_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_current_user_tenant),
    current_user: User = Depends(get_current_user),
) -> Any:
    """
    Sync tools from an MCP server.

    Uses the server's stored project_id to determine sandbox context.
    """
    _checked_server = await _get_mcp_server_for_tenant(
        db,
        server_id,
        tenant_id,
        current_user.id,
        MCP_PROJECT_WRITE_ROLES,
    )
    try:
        runtime = await _get_runtime_service(request, db)
        server = await runtime.sync_server(server_id, tenant_id)
        await db.commit()

        from src.infrastructure.agent.state.agent_session_pool import (
            invalidate_mcp_tools_cache,
        )

        _cache_generation = invalidate_mcp_tools_cache(tenant_id)
        return MCPServerResponse.model_validate(server)

    except ValueError as e:
        await db.rollback()
        message = str(e)
        if "not found" in message.lower():
            raise _mcp_server_not_found_error() from e
        raise _mcp_server_action_failed_error() from e
    except PermissionError as e:
        await db.rollback()
        raise _mcp_access_denied_error() from e
    except Exception as e:
        await db.rollback()
        logger.exception("Failed to sync MCP server tools")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_("Failed to sync MCP server tools"),
        ) from e


@router.post("/{server_id}/test", response_model=MCPServerTestResult)
async def test_mcp_server_connection(
    server_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_current_user_tenant),
    current_user: User = Depends(get_current_user),
) -> MCPServerTestResult:
    """
    Test connection to an MCP server.

    Uses the server's stored project_id to determine sandbox context.
    """
    _checked_server = await _get_mcp_server_for_tenant(
        db,
        server_id,
        tenant_id,
        current_user.id,
        MCP_PROJECT_WRITE_ROLES,
    )
    try:
        start_time = time.time()
        runtime = await _get_runtime_service(request, db)
        result = await runtime.test_server(server_id, tenant_id)

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
        if "not found" in message.lower():
            raise _mcp_server_not_found_error() from e
        raise _mcp_server_action_failed_error() from e
    except PermissionError as e:
        await db.rollback()
        raise _mcp_access_denied_error() from e
    except Exception:
        await db.rollback()
        logger.exception("Failed to test MCP server connection")
        return MCPServerTestResult(
            success=False,
            message=_("Connection failed"),
            errors=[_("Connection failed")],
        )


@router.post("/reconcile/{project_id}", response_model=MCPReconcileResultResponse)
async def reconcile_mcp_project(
    project_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_current_user_tenant),
    current_user: User = Depends(get_current_user),
) -> MCPReconcileResultResponse:
    """Reconcile enabled MCP servers with current sandbox runtime."""
    await ensure_project_access(
        db,
        project_id,
        tenant_id,
        current_user.id,
        MCP_PROJECT_WRITE_ROLES,
    )
    try:
        runtime = await _get_runtime_service(request, db)
        result = await runtime.reconcile_project(project_id, tenant_id)
        await db.commit()
        if result is None:
            return MCPReconcileResultResponse(
                project_id=project_id,
                total_enabled_servers=0,
                already_running=0,
                restored=0,
                failed=0,
            )
        return MCPReconcileResultResponse(
            project_id=result.project_id,
            total_enabled_servers=result.total_enabled_servers,
            already_running=result.already_running,
            restored=result.restored,
            failed=result.failed,
        )
    except PermissionError as e:
        await db.rollback()
        raise _mcp_access_denied_error() from e
    except Exception as e:
        await db.rollback()
        logger.exception("Failed to reconcile MCP project %s", project_id)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_("Failed to reconcile MCP servers"),
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
    current_user: User = Depends(get_current_user),
) -> MCPHealthSummary:
    """Get aggregated health summary for all MCP servers."""
    from src.infrastructure.adapters.secondary.persistence.sql_mcp_server_repository import (
        SqlMCPServerRepository,
    )

    repository = SqlMCPServerRepository(db)

    if project_id:
        await ensure_project_access(db, project_id, tenant_id, current_user.id)
        servers = await repository.list_by_project(project_id)
    else:
        accessible_project_ids = await list_accessible_project_ids(db, tenant_id, current_user.id)
        if not accessible_project_ids:
            return MCPHealthSummary(
                total=0,
                healthy=0,
                degraded=0,
                error=0,
                disabled=0,
                servers=[],
            )
        servers = await repository.list_by_tenant(tenant_id)
        servers = [server for server in servers if server.project_id in accessible_project_ids]

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
    current_user: User = Depends(get_current_user),
) -> MCPServerHealthStatus:
    """Get health status for a single MCP server (lightweight, no connection test)."""

    server = await _get_mcp_server_for_tenant(db, server_id, tenant_id, current_user.id)

    return _compute_server_health(server)


# ---------------------------------------------------------------------------
# SEP-1865 P2: Prompts & Logging endpoints
# ---------------------------------------------------------------------------


@router.get("/{server_id}/prompts")
async def list_mcp_server_prompts(
    server_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_current_user_tenant),
    current_user: User = Depends(get_current_user),
) -> dict[str, list[dict[str, Any]]]:
    """List prompts exposed by an MCP server."""
    _checked_server = await _get_mcp_server_for_tenant(
        db,
        server_id,
        tenant_id,
        current_user.id,
    )
    try:
        runtime = await _get_runtime_service(request, db)
        prompts = await runtime.list_server_prompts(server_id, tenant_id)
    except PermissionError as exc:
        raise _mcp_access_denied_error() from exc
    except ValueError as exc:
        raise _mcp_server_not_found_error() from exc
    return {"prompts": prompts}


@router.post("/{server_id}/log-level")
async def set_mcp_server_log_level(
    server_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_current_user_tenant),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Set the logging level for an MCP server."""
    body = await request.json()
    raw_level = body.get("level", "info") if isinstance(body, dict) else "info"
    level = raw_level.strip().lower() if isinstance(raw_level, str) else "info"
    if level not in MCP_LOGGING_LEVELS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_("Invalid MCP logging level"),
        )
    _checked_server = await _get_mcp_server_for_tenant(
        db,
        server_id,
        tenant_id,
        current_user.id,
        MCP_PROJECT_WRITE_ROLES,
    )

    try:
        runtime = await _get_runtime_service(request, db)
        success = await runtime.set_server_log_level(server_id, tenant_id, level)
    except PermissionError as exc:
        raise _mcp_access_denied_error() from exc
    except ValueError as exc:
        raise _mcp_server_not_found_error() from exc

    await db.commit()
    if not success:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=_("Failed to set MCP server log level"),
        )
    return {"status": "ok", "level": level}


@router.get("/{server_id}/logs")
async def list_mcp_server_logs(
    server_id: str,
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_current_user_tenant),
    current_user: User = Depends(get_current_user),
) -> dict[str, list[dict[str, Any]]]:
    """List recent persisted lifecycle log messages for an MCP server."""
    server = await _get_mcp_server_for_tenant(db, server_id, tenant_id, current_user.id)
    result = await db.execute(
        refresh_select_statement(
            select(MCPLifecycleEvent)
            .where(
                MCPLifecycleEvent.server_id == server.id,
                MCPLifecycleEvent.tenant_id == tenant_id,
            )
            .order_by(desc(MCPLifecycleEvent.created_at))
            .limit(limit)
        )
    )
    events = result.scalars().all()
    return {"logs": [_mcp_lifecycle_event_to_log(event) for event in events]}


async def _get_mcp_server_for_tenant(
    db: AsyncSession,
    server_id: str,
    tenant_id: str,
    user_id: str | None = None,
    required_roles: Collection[str] | None = None,
) -> MCPServer:
    repository = SqlMCPServerRepository(db)
    server = await repository.get_by_id(server_id)
    if not server:
        raise _mcp_server_not_found_error()
    if server.tenant_id != tenant_id:
        raise _mcp_access_denied_error()
    if user_id is not None:
        if not server.project_id:
            raise _mcp_access_denied_error()
        await ensure_project_access(
            db,
            server.project_id,
            tenant_id,
            user_id,
            required_roles,
        )
    return server


def _mcp_lifecycle_event_to_log(event: MCPLifecycleEvent) -> dict[str, Any]:
    level_by_status = {
        "success": "info",
        "failed": "error",
        "failure": "error",
        "error": "error",
        "warning": "warning",
    }
    level = level_by_status.get(event.status, "info")
    return {
        "level": level,
        "logger": event.event_type,
        "data": {
            "status": event.status,
            "message": event.error_message,
            "metadata": event.metadata_json or {},
        },
        "timestamp": event.created_at.isoformat() if event.created_at else None,
    }
