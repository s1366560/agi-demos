"""Project Sandbox API routes for project-dedicated sandbox lifecycle management.

Provides REST API endpoints for managing persistent sandboxes per project:
- Each project has exactly one persistent sandbox
- Lazy creation on first use
- Health monitoring and auto-recovery
"""

import asyncio
import contextlib
import json
import logging
from datetime import UTC, datetime
from typing import Any, cast

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from pydantic import BaseModel, Field
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.project_sandbox_lifecycle_service import (
    ProjectSandboxLifecycleService,
    SandboxInfo,
)
from src.application.services.sandbox_event_service import SandboxEventPublisher
from src.application.services.sandbox_orchestrator import SandboxOrchestrator
from src.application.services.sandbox_profile import (
    SandboxProfileType,
)
from src.domain.model.sandbox.project_sandbox import ProjectSandboxStatus
from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user,
    get_current_user_from_header_or_query,
    get_current_user_tenant,
)
from src.infrastructure.adapters.primary.web.dependencies.auth_dependencies import (
    get_current_user_from_desktop_proxy,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User, UserProject
from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import (
    MCPSandboxAdapter,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/projects", tags=["project-sandbox"])


# ============================================================================
# Authorization Helper
# ============================================================================


async def verify_project_access(
    project_id: str,
    user: User,
    db: AsyncSession,
    required_roles: list[str] | None = None,
) -> None:
    """Verify user has access to the project. Raises 403 if not."""
    query = select(UserProject).where(
        and_(UserProject.user_id == user.id, UserProject.project_id == project_id)
    )
    if required_roles:
        query = query.where(UserProject.role.in_(required_roles))
    result = await db.execute(query)
    if not result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to project",
        )


# ============================================================================
# Request/Response Schemas
# ============================================================================


class ProjectSandboxResponse(BaseModel):
    """Response schema for project sandbox information."""

    sandbox_id: str = Field(..., description="Unique sandbox identifier")
    project_id: str = Field(..., description="Associated project ID")
    tenant_id: str = Field(..., description="Tenant ID")
    status: str = Field(..., description="Sandbox lifecycle status")
    endpoint: str | None = Field(None, description="MCP WebSocket endpoint")
    websocket_url: str | None = Field(None, description="WebSocket URL")
    mcp_port: int | None = Field(None, description="MCP server port")
    desktop_port: int | None = Field(None, description="noVNC desktop port")
    terminal_port: int | None = Field(None, description="ttyd terminal port")
    desktop_url: str | None = Field(None, description="noVNC access URL")
    terminal_url: str | None = Field(None, description="Terminal access URL")
    created_at: str | None = Field(None, description="Creation timestamp")
    last_accessed_at: str | None = Field(None, description="Last access timestamp")
    is_healthy: bool = Field(False, description="Whether sandbox is healthy")
    error_message: str | None = Field(None, description="Error description if any")

    @classmethod
    def from_info(cls, info: SandboxInfo) -> "ProjectSandboxResponse":
        """Create response from SandboxInfo."""
        return cls(
            sandbox_id=info.sandbox_id,
            project_id=info.project_id,
            tenant_id=info.tenant_id,
            status=info.status,
            endpoint=info.endpoint,
            websocket_url=info.websocket_url,
            mcp_port=info.mcp_port,
            desktop_port=info.desktop_port,
            terminal_port=info.terminal_port,
            desktop_url=info.desktop_url,
            terminal_url=info.terminal_url,
            created_at=info.created_at.isoformat() if info.created_at else None,
            last_accessed_at=info.last_accessed_at.isoformat() if info.last_accessed_at else None,
            is_healthy=info.is_healthy,
            error_message=info.error_message,
        )


class EnsureSandboxRequest(BaseModel):
    """Request to ensure a project's sandbox exists and is running."""

    profile: str | None = Field(
        default=None, description="Sandbox profile: lite, standard, or full"
    )
    auto_create: bool = Field(default=True, description="Auto-create sandbox if it doesn't exist")


MAX_TOOL_TIMEOUT_SECONDS = 300.0


class ExecuteToolRequest(BaseModel):
    """Request to execute a tool in the project's sandbox."""

    tool_name: str = Field(..., description="MCP tool name (bash, read, write, etc.)")
    arguments: dict[str, Any] = Field(default_factory=dict, description="Tool arguments")
    timeout: float = Field(
        default=30.0,
        ge=1.0,
        le=MAX_TOOL_TIMEOUT_SECONDS,
        description=f"Execution timeout in seconds (max {MAX_TOOL_TIMEOUT_SECONDS}s)",
    )


class ExecuteToolResponse(BaseModel):
    """Response from tool execution."""

    success: bool = Field(..., description="Whether execution succeeded")
    content: list[dict[str, Any]] = Field(default_factory=list, description="Tool output")
    is_error: bool = Field(default=False, description="Whether tool returned an error")
    execution_time_ms: int | None = Field(None, description="Execution time")


class HealthCheckResponse(BaseModel):
    """Response from health check."""

    project_id: str = Field(..., description="Project ID")
    sandbox_id: str = Field(..., description="Sandbox ID")
    healthy: bool = Field(..., description="Whether sandbox is healthy")
    status: str = Field(..., description="Current status")
    checked_at: str = Field(..., description="Check timestamp")


class SandboxStatsResponse(BaseModel):
    """Response from sandbox stats/metrics query."""

    project_id: str = Field(..., description="Project ID")
    sandbox_id: str = Field(..., description="Sandbox ID")
    status: str = Field(..., description="Current sandbox status")
    cpu_percent: float = Field(default=0.0, description="CPU usage percentage")
    memory_usage: int = Field(default=0, description="Memory usage in bytes")
    memory_limit: int = Field(default=0, description="Memory limit in bytes")
    memory_percent: float = Field(default=0.0, description="Memory usage percentage")
    disk_usage: int | None = Field(None, description="Disk usage in bytes")
    disk_limit: int | None = Field(None, description="Disk limit in bytes")
    disk_percent: float | None = Field(None, description="Disk usage percentage")
    network_rx_bytes: int | None = Field(None, description="Network bytes received")
    network_tx_bytes: int | None = Field(None, description="Network bytes transmitted")
    pids: int = Field(default=0, description="Number of processes")
    uptime_seconds: int | None = Field(None, description="Container uptime in seconds")
    created_at: str | None = Field(None, description="Container creation time")
    collected_at: str = Field(..., description="Timestamp when stats were collected")


class SandboxActionResponse(BaseModel):
    """Response from sandbox actions (restart, terminate)."""

    success: bool = Field(..., description="Whether action succeeded")
    message: str = Field(..., description="Status message")
    sandbox: ProjectSandboxResponse | None = Field(None, description="Updated sandbox info")


class ListProjectSandboxesResponse(BaseModel):
    """Response for listing project sandboxes."""

    sandboxes: list[ProjectSandboxResponse] = Field(default_factory=list)
    total: int = Field(..., description="Total count")


class CleanupStaleRequest(BaseModel):
    """Request to clean up stale sandboxes."""

    max_idle_seconds: int = Field(default=3600, description="Max idle time before cleanup")
    dry_run: bool = Field(default=False, description="If True, only return IDs without terminating")


class CleanupStaleResponse(BaseModel):
    """Response from stale sandbox cleanup."""

    terminated: list[str] = Field(default_factory=list, description="Terminated sandbox IDs")
    dry_run: bool = Field(..., description="Whether this was a dry run")


# ============================================================================
# Dependency Injection
# ============================================================================


def get_sandbox_adapter() -> MCPSandboxAdapter:
    """Get or create the sandbox adapter singleton."""
    from src.configuration.di_container import DIContainer

    container = DIContainer()
    return cast(MCPSandboxAdapter, container.sandbox_adapter())


def get_lifecycle_service(
    request: Request, db: AsyncSession = Depends(get_db)
) -> ProjectSandboxLifecycleService:
    """Get the project sandbox lifecycle service.

    Uses the properly initialized container from app.state which has
    redis_client configured for distributed locking. Falls back to a new
    container if app.state.container is not available.
    """
    try:
        # Get container from app.state which has redis_client properly configured
        # This enables Redis distributed locks instead of PostgreSQL advisory locks
        container = request.app.state.container.with_db(db)
    except (AttributeError, KeyError):
        # Fallback for tests or when app.state.container is not set
        from src.configuration.di_container import DIContainer

        container = DIContainer().with_db(db)

    return cast(ProjectSandboxLifecycleService, container.project_sandbox_lifecycle_service())


def get_lifecycle_service_for_websocket(
    websocket: WebSocket, db: AsyncSession = Depends(get_db)
) -> ProjectSandboxLifecycleService:
    """Get the project sandbox lifecycle service for WebSocket endpoints.

    WebSocket handlers receive WebSocket instead of Request, so we need
    a separate dependency that extracts app.state from the WebSocket.
    """
    try:
        # Get container from app.state which has redis_client properly configured
        container = websocket.app.state.container.with_db(db)
    except (AttributeError, KeyError):
        # Fallback for tests or when app.state.container is not set
        from src.configuration.di_container import DIContainer

        container = DIContainer().with_db(db)

    return cast(ProjectSandboxLifecycleService, container.project_sandbox_lifecycle_service())


def get_event_publisher(request: Request) -> SandboxEventPublisher | None:
    """Get the sandbox event publisher from app container.

    Uses the properly initialized container from app.state which has
    redis_client configured for the event bus.
    """
    try:
        # Get container from app.state which has redis_client properly configured
        container = request.app.state.container
        return cast(SandboxEventPublisher | None, container.sandbox_event_publisher())
    except Exception as e:
        logger.warning(f"Could not create event publisher: {e}")
        return None


def get_orchestrator() -> SandboxOrchestrator:
    """Get the sandbox orchestrator singleton.

    Uses the shared singleton from sandbox/utils.py to ensure
    the orchestrator uses the same sandbox adapter instance that
    has been synced with existing Docker containers.
    """
    from src.infrastructure.adapters.primary.web.routers.sandbox.utils import (
        get_sandbox_orchestrator,
    )

    return get_sandbox_orchestrator()


# ============================================================================
# API Endpoints
# ============================================================================


@router.get("/{project_id}/sandbox", response_model=ProjectSandboxResponse)
async def get_project_sandbox(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: ProjectSandboxLifecycleService = Depends(get_lifecycle_service),
) -> Any:
    """Get the sandbox for a project.

    Returns the current sandbox information if it exists.
    Does not create a new sandbox if one doesn't exist.
    """
    await verify_project_access(project_id, current_user, db)

    info = await service.get_project_sandbox(project_id)

    if not info:
        raise HTTPException(
            status_code=404,
            detail=f"No sandbox found for project {project_id}. Use POST to create one.",
        )

    return ProjectSandboxResponse.from_info(info)


@router.post("/{project_id}/sandbox", response_model=ProjectSandboxResponse)
async def ensure_project_sandbox(
    project_id: str,
    request: EnsureSandboxRequest,
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
    service: ProjectSandboxLifecycleService = Depends(get_lifecycle_service),
    event_publisher: SandboxEventPublisher | None = Depends(get_event_publisher),
) -> Any:
    """Ensure a project's sandbox exists and is running.

    Creates a new sandbox if one doesn't exist, or returns the existing one.
    Performs health checks and auto-recovery if needed.
    """
    await verify_project_access(project_id, current_user, db, ["owner", "admin", "member"])

    # Parse profile
    profile = None
    if request.profile:
        try:
            profile = SandboxProfileType(request.profile.lower())
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid profile: {request.profile}. Use: lite, standard, full",
            ) from None

    try:
        info = await service.get_or_create_sandbox(
            project_id=project_id,
            tenant_id=tenant_id,
            profile=profile,
        )

        # Publish event via Redis Stream (for SSE subscribers)
        if event_publisher:
            try:
                await event_publisher.publish_sandbox_created(
                    project_id=project_id,
                    sandbox_id=info.sandbox_id,
                    status=info.status,
                    endpoint=info.endpoint,
                    websocket_url=info.websocket_url,
                )
            except Exception as e:
                logger.warning(f"Failed to publish sandbox_created event: {e}")

        # Also broadcast via WebSocket for real-time sync
        try:
            from src.infrastructure.adapters.primary.web.websocket.connection_manager import (
                get_connection_manager,
            )

            manager = get_connection_manager()
            await manager.broadcast_sandbox_state(
                tenant_id=tenant_id,
                project_id=project_id,
                state={
                    "event_type": "created",
                    "sandbox_id": info.sandbox_id,
                    "status": info.status,
                    "endpoint": info.endpoint,
                    "websocket_url": info.websocket_url,
                    "mcp_port": info.mcp_port,
                    "desktop_port": info.desktop_port,
                    "terminal_port": info.terminal_port,
                    "is_healthy": info.is_healthy,
                },
            )
        except Exception as e:
            logger.warning(f"Failed to broadcast sandbox state via WebSocket: {e}")

        return ProjectSandboxResponse.from_info(info)

    except Exception as e:
        logger.error(f"Failed to ensure sandbox for project {project_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create sandbox: {e!s}") from e


@router.get("/{project_id}/sandbox/health", response_model=HealthCheckResponse)
async def check_project_sandbox_health(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: ProjectSandboxLifecycleService = Depends(get_lifecycle_service),
) -> HealthCheckResponse:
    """Check the health of a project's sandbox."""
    await verify_project_access(project_id, current_user, db)

    try:
        healthy = await service.health_check(project_id)
        info = await service.get_project_sandbox(project_id)

        if not info:
            raise HTTPException(
                status_code=404,
                detail=f"No sandbox found for project {project_id}",
            )

        return HealthCheckResponse(
            project_id=project_id,
            sandbox_id=info.sandbox_id,
            healthy=healthy,
            status=info.status,
            checked_at=datetime.now(UTC).isoformat(),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Health check failed for project {project_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Health check failed: {e!s}") from e


@router.get("/{project_id}/sandbox/stats", response_model=SandboxStatsResponse)
async def get_project_sandbox_stats(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: ProjectSandboxLifecycleService = Depends(get_lifecycle_service),
    adapter: MCPSandboxAdapter = Depends(get_sandbox_adapter),
) -> SandboxStatsResponse:
    """Get resource usage statistics for a project's sandbox.

    Returns CPU, memory, disk, network, and process metrics.
    """
    await verify_project_access(project_id, current_user, db)

    try:
        info = await service.get_project_sandbox(project_id)

        if not info:
            raise HTTPException(
                status_code=404,
                detail=f"No sandbox found for project {project_id}",
            )

        # Get stats from the adapter (pass project_id as fallback for container lookup)
        stats = await adapter.get_sandbox_stats(info.sandbox_id, project_id=project_id)

        # Calculate uptime if we have creation time
        uptime_seconds = None
        if info.created_at:
            now = datetime.now(UTC)
            created_at = info.created_at
            # Ensure created_at is timezone-aware
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=UTC)
            uptime_seconds = int((now - created_at).total_seconds())

        return SandboxStatsResponse(
            project_id=project_id,
            sandbox_id=info.sandbox_id,
            status=info.status,
            cpu_percent=stats.get("cpu_percent", 0.0),
            memory_usage=stats.get("memory_usage", 0),
            memory_limit=stats.get("memory_limit", 0),
            memory_percent=stats.get("memory_percent", 0.0),
            network_rx_bytes=stats.get("network_rx_bytes"),
            network_tx_bytes=stats.get("network_tx_bytes"),
            disk_usage=stats.get("disk_read_bytes"),  # Use disk read as usage proxy
            disk_limit=None,
            disk_percent=None,
            pids=stats.get("pids", 0),
            uptime_seconds=uptime_seconds,
            created_at=info.created_at.isoformat() if info.created_at else None,
            collected_at=datetime.now(UTC).isoformat(),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get sandbox stats for project {project_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Stats query failed: {e!s}") from e


@router.post("/{project_id}/sandbox/execute", response_model=ExecuteToolResponse)
async def execute_tool_in_project_sandbox(
    project_id: str,
    request: ExecuteToolRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: ProjectSandboxLifecycleService = Depends(get_lifecycle_service),
) -> ExecuteToolResponse:
    """Execute a tool in the project's sandbox.

    Automatically ensures the sandbox is running before execution.
    """
    await verify_project_access(project_id, current_user, db, ["owner", "admin", "member"])

    try:
        result = await service.execute_tool(
            project_id=project_id,
            tool_name=request.tool_name,
            arguments=request.arguments,
            timeout=request.timeout,
        )

        return ExecuteToolResponse(
            success=not result.get("is_error", False),
            content=result.get("content", []),
            is_error=result.get("is_error", False),
            execution_time_ms=None,
        )

    except Exception as e:
        logger.error(f"Tool execution failed for project {project_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Execution failed: {e!s}") from e


@router.post("/{project_id}/sandbox/restart", response_model=SandboxActionResponse)
async def restart_project_sandbox(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: ProjectSandboxLifecycleService = Depends(get_lifecycle_service),
    event_publisher: SandboxEventPublisher | None = Depends(get_event_publisher),
) -> SandboxActionResponse:
    """Restart the sandbox for a project."""
    await verify_project_access(project_id, current_user, db, ["owner", "admin"])

    try:
        info = await service.restart_project_sandbox(project_id)

        # Publish event via Redis Stream (for SSE subscribers)
        if event_publisher:
            try:
                await event_publisher.publish_sandbox_status(
                    project_id=project_id,
                    sandbox_id=info.sandbox_id,
                    status="restarted",
                )
            except Exception as e:
                logger.warning(f"Failed to publish sandbox_restarted event: {e}")

        # Also broadcast via WebSocket for real-time sync
        try:
            from src.infrastructure.adapters.primary.web.websocket.connection_manager import (
                get_connection_manager,
            )

            manager = get_connection_manager()
            # Get tenant_id from current user context
            await manager.broadcast_sandbox_state(
                tenant_id=current_user.current_tenant_id or "",  # type: ignore[attr-defined]
                project_id=project_id,
                state={
                    "event_type": "restarted",
                    "sandbox_id": info.sandbox_id,
                    "status": info.status,
                    "endpoint": info.endpoint,
                    "mcp_port": info.mcp_port,
                    "desktop_port": info.desktop_port,
                    "terminal_port": info.terminal_port,
                    "is_healthy": info.is_healthy,
                },
            )
        except Exception as e:
            logger.warning(f"Failed to broadcast sandbox state via WebSocket: {e}")

        return SandboxActionResponse(
            success=True,
            message=f"Sandbox {info.sandbox_id} restarted successfully",
            sandbox=ProjectSandboxResponse.from_info(info),
        )

    except Exception as e:
        logger.error(f"Failed to restart sandbox for project {project_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Restart failed: {e!s}") from e


@router.delete("/{project_id}/sandbox", response_model=SandboxActionResponse)
async def terminate_project_sandbox(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: ProjectSandboxLifecycleService = Depends(get_lifecycle_service),
    event_publisher: SandboxEventPublisher | None = Depends(get_event_publisher),
) -> SandboxActionResponse:
    """Terminate the sandbox for a project."""
    await verify_project_access(project_id, current_user, db, ["owner", "admin"])

    try:
        success = await service.terminate_project_sandbox(project_id)

        if not success:
            raise HTTPException(
                status_code=404,
                detail=f"No sandbox found for project {project_id}",
            )

        # Publish event via Redis Stream (for SSE subscribers)
        if event_publisher:
            try:
                await event_publisher.publish_sandbox_terminated(
                    project_id=project_id,
                    sandbox_id=project_id,  # Association already deleted
                )
            except Exception as e:
                logger.warning(f"Failed to publish sandbox_terminated event: {e}")

        # Also broadcast via WebSocket for real-time sync
        try:
            from src.infrastructure.adapters.primary.web.websocket.connection_manager import (
                get_connection_manager,
            )

            manager = get_connection_manager()
            await manager.broadcast_sandbox_state(
                tenant_id=current_user.current_tenant_id or "",  # type: ignore[attr-defined]
                project_id=project_id,
                state={
                    "event_type": "terminated",
                    "sandbox_id": None,
                    "status": "terminated",
                    "is_healthy": False,
                },
            )
        except Exception as e:
            logger.warning(f"Failed to broadcast sandbox state via WebSocket: {e}")

        return SandboxActionResponse(
            success=True,
            message="Sandbox terminated successfully",
            sandbox=None,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to terminate sandbox for project {project_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Termination failed: {e!s}") from e


@router.get("/{project_id}/sandbox/sync", response_model=ProjectSandboxResponse)
async def sync_project_sandbox_status(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: ProjectSandboxLifecycleService = Depends(get_lifecycle_service),
) -> Any:
    """Synchronize database status with actual container status.

    Useful for recovering from inconsistent states.
    """
    await verify_project_access(project_id, current_user, db)

    try:
        info = await service.sync_sandbox_status(project_id)
        return ProjectSandboxResponse.from_info(info)

    except Exception as e:
        logger.error(f"Failed to sync sandbox status for project {project_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Sync failed: {e!s}") from e


# ============================================================================
# Admin/Tenant-level endpoints
# ============================================================================


@router.get("/sandboxes", response_model=ListProjectSandboxesResponse)
async def list_project_sandboxes(
    status: str | None = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    service: ProjectSandboxLifecycleService = Depends(get_lifecycle_service),
) -> ListProjectSandboxesResponse:
    """List all project sandboxes for the current tenant."""
    # Parse status filter
    status_filter = None
    if status:
        try:
            status_filter = ProjectSandboxStatus(status.lower())
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status: {status}",
            ) from None

    sandboxes = await service.list_project_sandboxes(
        tenant_id=tenant_id,
        status=status_filter,
        limit=limit,
        offset=offset,
    )

    return ListProjectSandboxesResponse(
        sandboxes=[ProjectSandboxResponse.from_info(s) for s in sandboxes],
        total=len(sandboxes),
    )


@router.post("/sandboxes/cleanup", response_model=CleanupStaleResponse)
async def cleanup_stale_sandboxes(
    request: CleanupStaleRequest,
    current_user: User = Depends(get_current_user),
    service: ProjectSandboxLifecycleService = Depends(get_lifecycle_service),
) -> CleanupStaleResponse:
    """Clean up sandboxes that haven't been accessed recently.

    Requires admin privileges.
    """
    is_admin = any(r.role.name == "admin" for r in current_user.roles)
    if not is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )

    terminated = await service.cleanup_stale_sandboxes(
        max_idle_seconds=request.max_idle_seconds,
        dry_run=request.dry_run,
    )

    return CleanupStaleResponse(
        terminated=terminated,
        dry_run=request.dry_run,
    )


# ============================================================================
# Desktop/Terminal endpoints via project
# ============================================================================


@router.post("/{project_id}/sandbox/desktop")
async def start_project_desktop(
    project_id: str,
    resolution: str = Query("1920x1080", description="Screen resolution"),
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    service: ProjectSandboxLifecycleService = Depends(get_lifecycle_service),
    orchestrator: SandboxOrchestrator = Depends(get_orchestrator),
) -> dict[str, Any]:
    """Start desktop service (KasmVNC) for the project's sandbox."""
    # Ensure sandbox exists and is running
    info = await service.ensure_sandbox_running(
        project_id=project_id,
        tenant_id=tenant_id,
    )

    try:
        from src.application.services.sandbox_orchestrator import DesktopConfig

        config = DesktopConfig(resolution=resolution)
        status = await orchestrator.start_desktop(info.sandbox_id, config)

        return {
            "success": status.running,
            "url": status.url,
            "display": status.display,
            "resolution": status.resolution,
            "port": status.port,
            "audio_enabled": status.audio_enabled,
            "dynamic_resize": status.dynamic_resize,
            "encoding": status.encoding,
        }

    except Exception as e:
        logger.error(f"Failed to start desktop for project {project_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to start desktop: {e!s}") from e


@router.delete("/{project_id}/sandbox/desktop")
async def stop_project_desktop(
    project_id: str,
    current_user: User = Depends(get_current_user),
    service: ProjectSandboxLifecycleService = Depends(get_lifecycle_service),
    orchestrator: SandboxOrchestrator = Depends(get_orchestrator),
) -> dict[str, Any]:
    """Stop desktop service for the project's sandbox."""
    info = await service.get_project_sandbox(project_id)

    if not info:
        raise HTTPException(
            status_code=404,
            detail=f"No sandbox found for project {project_id}",
        )

    try:
        success = await orchestrator.stop_desktop(info.sandbox_id)
        return {"success": success}

    except Exception as e:
        logger.error(f"Failed to stop desktop for project {project_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to stop desktop: {e!s}") from e


@router.post("/{project_id}/sandbox/terminal")
async def start_project_terminal(
    project_id: str,
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    service: ProjectSandboxLifecycleService = Depends(get_lifecycle_service),
    orchestrator: SandboxOrchestrator = Depends(get_orchestrator),
) -> dict[str, Any]:
    """Start terminal service for the project's sandbox."""
    info = await service.ensure_sandbox_running(
        project_id=project_id,
        tenant_id=tenant_id,
    )

    try:
        from src.application.services.sandbox_orchestrator import TerminalConfig

        config = TerminalConfig()
        status = await orchestrator.start_terminal(info.sandbox_id, config)

        return {
            "success": status.running,
            "url": status.url,
            "port": status.port,
            "session_id": status.session_id,
        }

    except Exception as e:
        logger.error(f"Failed to start terminal for project {project_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to start terminal: {e!s}") from e


@router.delete("/{project_id}/sandbox/terminal")
async def stop_project_terminal(
    project_id: str,
    current_user: User = Depends(get_current_user),
    service: ProjectSandboxLifecycleService = Depends(get_lifecycle_service),
    orchestrator: SandboxOrchestrator = Depends(get_orchestrator),
) -> dict[str, Any]:
    """Stop terminal service for the project's sandbox."""
    info = await service.get_project_sandbox(project_id)

    if not info:
        raise HTTPException(
            status_code=404,
            detail=f"No sandbox found for project {project_id}",
        )

    try:
        success = await orchestrator.stop_terminal(info.sandbox_id)
        return {"success": success}

    except Exception as e:
        logger.error(f"Failed to stop terminal for project {project_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to stop terminal: {e!s}") from e


# ============================================================================
# Desktop/Terminal Proxy endpoints
# ============================================================================


def _rewrite_desktop_content(
    content_bytes: bytes,
    content_type: str,
    project_id: str,
    token_param: str,
) -> bytes:
    """Rewrite URLs in HTML/JS content to use the desktop proxy path."""
    import re

    if not (
        content_type.startswith("text/html") or content_type.startswith("application/javascript")
    ):
        return content_bytes

    content_str = content_bytes.decode("utf-8", errors="replace")
    proxy_prefix = f"/api/v1/projects/{project_id}/sandbox/desktop/proxy/"

    def rewrite_url(match: re.Match[str]) -> str:
        """Rewrite URL with proxy prefix and token."""
        attr = match.group(1)
        quote = match.group(2)
        path_part = match.group(3)
        new_url = f"{proxy_prefix}{path_part}"
        if token_param and "?" not in path_part:
            new_url = f"{new_url}?token={token_param}"
        elif token_param and "?" in path_part:
            new_url = f"{new_url}&token={token_param}"
        return f"{attr}={quote}{new_url}"

    content_str = re.sub(r'(href|src)=(["\'])/([^"\']*)', rewrite_url, content_str)

    ws_proxy_url = f"/api/v1/projects/{project_id}/sandbox/desktop/proxy/websockify"
    if token_param:
        ws_proxy_url += f"?token={token_param}"
    content_str = content_str.replace(
        'ws://" + location.host + "/', f'ws://" + location.host + "{ws_proxy_url}'
    )
    content_str = content_str.replace(
        'wss://" + location.host + "/', f'wss://" + location.host + "{ws_proxy_url}'
    )

    return content_str.encode("utf-8")


async def _run_ws_relay_pair(
    browser_to_upstream: Any,
    upstream_to_browser: Any,
) -> None:
    """Run a pair of WebSocket relay coroutines, cancelling pending on first completion."""
    browser_task = asyncio.create_task(browser_to_upstream())
    upstream_task = asyncio.create_task(upstream_to_browser())

    _done, pending = await asyncio.wait(
        [browser_task, upstream_task],
        return_when=asyncio.FIRST_COMPLETED,
    )
    for task in pending:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


async def _handle_terminal_input(
    websocket: WebSocket,
    proxy: Any,
    session_id: str,
) -> None:
    """Process incoming terminal WebSocket messages (input, resize, ping)."""
    while True:
        msg = await websocket.receive_json()
        msg_type = msg.get("type")

        if msg_type == "input":
            data = msg.get("data", "")
            await proxy.send_input(session_id, data)
        elif msg_type == "resize":
            cols = msg.get("cols", 80)
            rows = msg.get("rows", 24)
            await proxy.resize(session_id, cols, rows)
        elif msg_type == "ping":
            await websocket.send_json({"type": "pong"})


async def _read_terminal_output_loop(
    websocket: WebSocket,
    proxy: Any,
    session: Any,
) -> None:
    """Background task to read and forward terminal output."""
    while session and session.is_active:
        try:
            output = await proxy.read_output(session.session_id)
            if output is None:
                break
            if output:
                await websocket.send_json({"type": "output", "data": output})
        except Exception as e:
            logger.error(f"Output reader error: {e}")
            break
        await asyncio.sleep(0.01)


def _create_desktop_ssl_context() -> Any:
    """Create an SSL context that skips certificate verification (for local containers)."""
    import ssl as ssl_module

    ctx = ssl_module.SSLContext(ssl_module.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl_module.CERT_NONE
    return ctx


async def _connect_desktop_upstream(ws_target: str, desktop_url: str) -> Any:
    """Connect to KasmVNC upstream WebSocket with TLS and binary subprotocol."""
    import websockets

    ssl_context = _create_desktop_ssl_context()
    return await websockets.connect(
        ws_target,
        subprotocols=["binary"],  # type: ignore[list-item]  # websockets expects Subprotocol
        additional_headers={"Origin": desktop_url},
        max_size=2**23,  # 8MB max frame for desktop data
        open_timeout=10,
        ping_interval=30,
        ping_timeout=10,
        proxy=None,  # bypass http_proxy env var for local container connections
        ssl=ssl_context,
    )


async def _relay_binary_browser_to_upstream(websocket: WebSocket, upstream_ws: Any) -> None:
    """Forward binary/text frames from browser to KasmVNC."""
    frame_count = 0
    try:
        while True:
            data = await websocket.receive()
            msg_type = data.get("type", "")
            if msg_type == "websocket.disconnect":
                logger.info("Browser disconnected normally")
                break
            if data.get("bytes"):
                frame_count += 1
                await upstream_ws.send(data["bytes"])
            elif data.get("text"):
                frame_count += 1
                await upstream_ws.send(data["text"])
    except WebSocketDisconnect:
        logger.info(f"Browser WebSocket disconnected after {frame_count} frames")
    except Exception as e:
        logger.warning(
            f"Browser->upstream relay ended after {frame_count} frames: {type(e).__name__}: {e}"
        )


async def _relay_binary_upstream_to_browser(websocket: WebSocket, upstream_ws: Any) -> None:
    """Forward binary/text frames from KasmVNC to browser."""
    frame_count = 0
    try:
        async for message in upstream_ws:
            frame_count += 1
            if isinstance(message, bytes):
                await websocket.send_bytes(message)
            else:
                await websocket.send_text(message)
    except Exception as e:
        logger.warning(
            f"Upstream->browser relay ended after {frame_count} frames: {type(e).__name__}: {e}"
        )


async def _connect_mcp_upstream(ws_target: str) -> Any:
    """Connect to MCP upstream WebSocket."""
    import websockets

    return await websockets.connect(
        ws_target,
        open_timeout=10,
        ping_interval=30,
        ping_timeout=10,
        max_size=2**22,  # 4MB max frame for MCP messages
        proxy=None,  # bypass http_proxy env var for local container connections
    )


async def _relay_mcp_browser_to_upstream(websocket: WebSocket, upstream_ws: Any) -> None:
    """Forward JSON-RPC messages from browser to MCP server."""
    try:
        while True:
            data = await websocket.receive()
            msg_type = data.get("type", "")
            if msg_type == "websocket.disconnect":
                break
            if data.get("text"):
                await upstream_ws.send(data["text"])
    except WebSocketDisconnect:
        logger.debug("MCP proxy: browser disconnected")
    except Exception as e:
        logger.warning(f"MCP proxy browser->upstream: {type(e).__name__}: {e}")
    finally:
        # Signal upstream to close when browser disconnects
        with contextlib.suppress(Exception):
            await upstream_ws.close()


# Expected mimeType for MCP App UI resources per @mcp-ui/client spec
_MCP_APP_MIME_TYPE = "text/html;profile=mcp-app"


def _normalize_mcp_resource_mime_type(message: str) -> str:
    """Rewrite ``text/html`` -> ``text/html;profile=mcp-app`` in resource content.

    The ``@mcp-ui/client`` library requires exactly ``text/html;profile=mcp-app``
    as the mimeType for UI resources.  Sandbox MCP servers often return plain
    ``text/html``.  This function patches the JSON-RPC response in-flight so
    that the client-side validation succeeds.

    Only modifies messages that look like a JSON-RPC result containing a
    ``contents`` array (i.e. ``resources/read`` responses).  All other messages
    pass through unchanged.
    """
    try:
        data = json.loads(message)
    except (json.JSONDecodeError, TypeError):
        return message

    result = data.get("result") if isinstance(data, dict) else None
    if not isinstance(result, dict):
        return message

    contents = result.get("contents")
    if not isinstance(contents, list):
        return message

    modified = False
    for item in contents:
        if not isinstance(item, dict):
            continue
        mime = item.get("mimeType", "")
        # Normalize plain text/html (case-insensitive) to the profile variant
        if mime.lower().strip() == "text/html":
            item["mimeType"] = _MCP_APP_MIME_TYPE
            modified = True

    if modified:
        logger.debug(
            "MCP proxy: normalized mimeType to %s in resources/read response",
            _MCP_APP_MIME_TYPE,
        )
        return json.dumps(data, ensure_ascii=False)

    return message


async def _relay_mcp_upstream_to_browser(websocket: WebSocket, upstream_ws: Any) -> None:
    """Forward JSON-RPC messages from MCP server to browser.

    Normalizes ``mimeType`` in ``resources/read`` responses so that the
    ``@mcp-ui/client`` library (which expects ``text/html;profile=mcp-app``)
    can render the resource.  Sandbox MCP servers commonly return plain
    ``text/html`` which is rejected by the client-side validator.
    """
    try:
        async for message in upstream_ws:
            if isinstance(message, str):
                message = _normalize_mcp_resource_mime_type(message)
                await websocket.send_text(message)
            else:
                await websocket.send_bytes(message)
    except Exception as e:
        logger.warning(f"MCP proxy upstream->browser: {type(e).__name__}: {e}")
    finally:
        # Signal browser to close when upstream disconnects
        with contextlib.suppress(Exception):
            await websocket.close(code=1001, reason="Upstream disconnected")


@router.get("/{project_id}/sandbox/desktop/proxy/{path:path}")
async def proxy_project_desktop(
    project_id: str,
    path: str,
    request: Request,
    current_user: User = Depends(get_current_user_from_desktop_proxy),
    service: ProjectSandboxLifecycleService = Depends(get_lifecycle_service),
) -> Any:
    """Proxy requests to the project's sandbox desktop (KasmVNC) web client.

    This allows browser access to the desktop without exposing container ports directly.
    Uses httpx to proxy all content (HTML, JS, CSS, WebSocket) through the API server.
    Supports token via query parameter for iframe access.
    """
    info = await service.get_project_sandbox(project_id)

    if not info:
        raise HTTPException(
            status_code=404,
            detail=f"No sandbox found for project {project_id}",
        )

    if not info.desktop_url:
        raise HTTPException(
            status_code=503,
            detail=f"Desktop service is not running for project {project_id}",
        )

    # Build target URL from the desktop service URL

    import httpx

    target_base = info.desktop_url.rstrip("/")
    target_path = path if path else ""
    target_url = f"{target_base}/{target_path}"

    # Extract token from query params to include in rewritten URLs
    token_param = request.query_params.get("token", "")

    # Copy query parameters (excluding token for proxied requests to container)
    other_params = {k: v for k, v in request.query_params.items() if k != "token"}
    if other_params:
        target_url += f"?{'&'.join(f'{k}={v}' for k, v in other_params.items())}"

    try:
        # verify=False: KasmVNC uses self-signed TLS on localhost container ports
        async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
            headers = {}
            for header in ["accept", "accept-encoding", "accept-language", "cache-control"]:
                if header in request.headers:
                    headers[header] = request.headers[header]

            response = await client.get(target_url, headers=headers)

            content_type = response.headers.get("content-type", "application/octet-stream")

            content = _rewrite_desktop_content(
                response.content, content_type, project_id, token_param
            )

            resp_headers = {"content-type": content_type}

            response_obj = Response(
                content=content,
                status_code=response.status_code,
                headers=resp_headers,
            )

            # Set auth cookie on initial request (when token in query param)
            # so subsequent asset requests (CSS/JS/SVG) are authenticated
            if token_param:
                response_obj.set_cookie(
                    key="desktop_token",
                    value=token_param,
                    httponly=True,
                    samesite="strict",
                    max_age=86400,
                    path=f"/api/v1/projects/{project_id}/sandbox/desktop/proxy",
                )

            return response_obj
    except httpx.RequestError as e:
        error_detail = str(e) or type(e).__name__
        logger.error(f"Failed to proxy desktop request to {target_url}: {error_detail}")
        raise HTTPException(
            status_code=502,
            detail=f"Failed to connect to desktop service at {target_url}: {error_detail}",
        ) from e


@router.websocket("/{project_id}/sandbox/desktop/proxy/websockify")
async def proxy_project_desktop_websocket(
    websocket: WebSocket,
    project_id: str,
    current_user: User = Depends(get_current_user_from_header_or_query),
    service: ProjectSandboxLifecycleService = Depends(get_lifecycle_service_for_websocket),
) -> None:
    """WebSocket proxy for the project's sandbox desktop (KasmVNC).

    Bridges browser WebSocket connections to the container's KasmVNC WebSocket,
    relaying binary VNC frames bidirectionally. This enables the KasmVNC
    web client to connect to the remote desktop through the API server.
    """

    info = await service.get_project_sandbox(project_id)

    if not info:
        await websocket.close(code=1008, reason=f"No sandbox found for project {project_id}")
        return

    if not info.desktop_url:
        await websocket.close(
            code=1008,
            reason=f"Desktop service is not running for project {project_id}",
        )
        return

    # Build WebSocket URL — KasmVNC websocket is at root path
    desktop_base = info.desktop_url.rstrip("/")
    ws_target = desktop_base.replace("http://", "ws://").replace("https://", "wss://") + "/"

    logger.info(
        f"Desktop WS proxy: project={project_id} "
        f"desktop_url={info.desktop_url} -> ws_target={ws_target}"
    )

    await websocket.accept(subprotocol="binary")

    upstream_ws = None
    try:
        upstream_ws = await _connect_desktop_upstream(ws_target, info.desktop_url)

        logger.info(f"Desktop WS proxy: upstream connected to {ws_target}")

        await _run_ws_relay_pair(
            lambda: _relay_binary_browser_to_upstream(websocket, upstream_ws),
            lambda: _relay_binary_upstream_to_browser(websocket, upstream_ws),
        )

    except Exception as e:
        logger.error(f"Desktop WebSocket proxy error for project {project_id}: {e}")
        with contextlib.suppress(Exception):
            await websocket.send_text(f'{{"error": "{e!s}"}}')
    finally:
        if upstream_ws:
            with contextlib.suppress(Exception):
                await upstream_ws.close()
        with contextlib.suppress(Exception):
            await websocket.close()


@router.websocket("/{project_id}/sandbox/terminal/proxy/ws")
async def proxy_project_terminal_websocket(
    websocket: WebSocket,
    project_id: str,
    session_id: str | None = None,
    current_user: User = Depends(get_current_user_from_header_or_query),
    service: ProjectSandboxLifecycleService = Depends(get_lifecycle_service_for_websocket),
) -> None:
    """WebSocket proxy for the project's sandbox terminal service.

    This allows browser WebSocket connections to the terminal without exposing container ports.
    Uses the terminal proxy to create/manage sessions with Docker containers.
    """
    from src.infrastructure.adapters.secondary.sandbox.terminal_proxy import (
        TerminalSession,
        get_terminal_proxy,
    )

    info = await service.get_project_sandbox(project_id)

    if not info:
        await websocket.close(code=1008, reason=f"No sandbox found for project {project_id}")
        return

    if not info.terminal_url:
        await websocket.close(
            code=1008, reason=f"Terminal service is not running for project {project_id}"
        )
        return

    # Accept the WebSocket connection
    await websocket.accept()

    proxy = get_terminal_proxy()
    session: TerminalSession | None = None

    output_task: asyncio.Task[None] | None = None
    try:
        # Create or get session using terminal proxy (docker exec)
        if session_id:
            session = proxy.get_session(session_id)
            if not session or session.container_id != info.sandbox_id:
                await websocket.send_json({"type": "error", "message": "Session not found"})
                await websocket.close()
                return
        else:
            # Create new session using docker exec
            try:
                session = await proxy.create_session(container_id=info.sandbox_id)
            except ValueError as e:
                await websocket.send_json({"type": "error", "message": str(e)})
                await websocket.close()
                return

        # Send connected message
        await websocket.send_json(
            {
                "type": "connected",
                "session_id": session.session_id,
                "cols": session.cols,
                "rows": session.rows,
            }
        )

        output_task = asyncio.create_task(_read_terminal_output_loop(websocket, proxy, session))
        # Process incoming messages
        try:
            await _handle_terminal_input(websocket, proxy, session.session_id)
        except WebSocketDisconnect:
            logger.info(f"WebSocket disconnected for session {session.session_id}")

    except Exception as e:
        logger.error(f"Terminal WebSocket proxy error: {e}")
        with contextlib.suppress(Exception):
            await websocket.send_json({"type": "error", "message": str(e)})

    finally:
        # Cleanup
        if output_task is not None:
            output_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await output_task

        # Don't close session on disconnect - allow reconnection
        with contextlib.suppress(Exception):
            await websocket.close()


@router.websocket("/{project_id}/sandbox/mcp/proxy")
async def proxy_project_mcp_websocket(
    websocket: WebSocket,
    project_id: str,
    current_user: User = Depends(get_current_user_from_header_or_query),
    service: ProjectSandboxLifecycleService = Depends(get_lifecycle_service_for_websocket),
) -> None:
    """WebSocket proxy for the project's sandbox MCP server.

    Tunnels MCP JSON-RPC protocol traffic between browser and sandbox MCP server.
    Enables direct MCP client connections from the frontend (Mode A) for
    low-latency tool calls without HTTP round-trips.
    """

    info = await service.get_project_sandbox(project_id)

    if not info:
        await websocket.close(code=1008, reason=f"No sandbox found for project {project_id}")
        return

    if not info.websocket_url:
        await websocket.close(
            code=1008,
            reason=f"MCP service is not running for project {project_id}",
        )
        return

    ws_target = info.websocket_url

    logger.info(f"MCP WS proxy: project={project_id} -> ws_target={ws_target}")

    await websocket.accept()

    upstream_ws = None
    try:
        upstream_ws = await _connect_mcp_upstream(ws_target)

        logger.info(f"MCP WS proxy: upstream connected to {ws_target}")

        await _run_ws_relay_pair(
            lambda: _relay_mcp_browser_to_upstream(websocket, upstream_ws),
            lambda: _relay_mcp_upstream_to_browser(websocket, upstream_ws),
        )

    except Exception as e:
        logger.error(f"MCP WebSocket proxy error for project {project_id}: {e}")
        with contextlib.suppress(Exception):
            await websocket.send_text(f'{{"error": "{e!s}"}}')
    finally:
        # Ensure both connections are closed
        if upstream_ws:
            with contextlib.suppress(Exception):
                await upstream_ws.close()
        with contextlib.suppress(Exception):
            await websocket.close()
