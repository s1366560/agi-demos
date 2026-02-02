"""Project Sandbox API routes for project-dedicated sandbox lifecycle management.

Provides REST API endpoints for managing persistent sandboxes per project:
- Each project has exactly one persistent sandbox
- Lazy creation on first use
- Health monitoring and auto-recovery
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

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
    get_current_user_tenant,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import (
    MCPSandboxAdapter,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/projects", tags=["project-sandbox"])


# ============================================================================
# Request/Response Schemas
# ============================================================================


class ProjectSandboxResponse(BaseModel):
    """Response schema for project sandbox information."""

    sandbox_id: str = Field(..., description="Unique sandbox identifier")
    project_id: str = Field(..., description="Associated project ID")
    tenant_id: str = Field(..., description="Tenant ID")
    status: str = Field(..., description="Sandbox lifecycle status")
    endpoint: Optional[str] = Field(None, description="MCP WebSocket endpoint")
    websocket_url: Optional[str] = Field(None, description="WebSocket URL")
    mcp_port: Optional[int] = Field(None, description="MCP server port")
    desktop_port: Optional[int] = Field(None, description="noVNC desktop port")
    terminal_port: Optional[int] = Field(None, description="ttyd terminal port")
    desktop_url: Optional[str] = Field(None, description="noVNC access URL")
    terminal_url: Optional[str] = Field(None, description="Terminal access URL")
    created_at: Optional[str] = Field(None, description="Creation timestamp")
    last_accessed_at: Optional[str] = Field(None, description="Last access timestamp")
    is_healthy: bool = Field(False, description="Whether sandbox is healthy")
    error_message: Optional[str] = Field(None, description="Error description if any")

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

    profile: Optional[str] = Field(
        default=None, description="Sandbox profile: lite, standard, or full"
    )
    auto_create: bool = Field(default=True, description="Auto-create sandbox if it doesn't exist")


class ExecuteToolRequest(BaseModel):
    """Request to execute a tool in the project's sandbox."""

    tool_name: str = Field(..., description="MCP tool name (bash, read, write, etc.)")
    arguments: Dict[str, Any] = Field(default_factory=dict, description="Tool arguments")
    timeout: float = Field(default=30.0, description="Execution timeout in seconds")


class ExecuteToolResponse(BaseModel):
    """Response from tool execution."""

    success: bool = Field(..., description="Whether execution succeeded")
    content: List[Dict[str, Any]] = Field(default_factory=list, description="Tool output")
    is_error: bool = Field(default=False, description="Whether tool returned an error")
    execution_time_ms: Optional[int] = Field(None, description="Execution time")


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
    disk_usage: Optional[int] = Field(None, description="Disk usage in bytes")
    disk_limit: Optional[int] = Field(None, description="Disk limit in bytes")
    disk_percent: Optional[float] = Field(None, description="Disk usage percentage")
    network_rx_bytes: Optional[int] = Field(None, description="Network bytes received")
    network_tx_bytes: Optional[int] = Field(None, description="Network bytes transmitted")
    pids: int = Field(default=0, description="Number of processes")
    uptime_seconds: Optional[int] = Field(None, description="Container uptime in seconds")
    created_at: Optional[str] = Field(None, description="Container creation time")
    collected_at: str = Field(..., description="Timestamp when stats were collected")


class SandboxActionResponse(BaseModel):
    """Response from sandbox actions (restart, terminate)."""

    success: bool = Field(..., description="Whether action succeeded")
    message: str = Field(..., description="Status message")
    sandbox: Optional[ProjectSandboxResponse] = Field(None, description="Updated sandbox info")


class ListProjectSandboxesResponse(BaseModel):
    """Response for listing project sandboxes."""

    sandboxes: List[ProjectSandboxResponse] = Field(default_factory=list)
    total: int = Field(..., description="Total count")


class CleanupStaleRequest(BaseModel):
    """Request to clean up stale sandboxes."""

    max_idle_seconds: int = Field(default=3600, description="Max idle time before cleanup")
    dry_run: bool = Field(default=False, description="If True, only return IDs without terminating")


class CleanupStaleResponse(BaseModel):
    """Response from stale sandbox cleanup."""

    terminated: List[str] = Field(default_factory=list, description="Terminated sandbox IDs")
    dry_run: bool = Field(..., description="Whether this was a dry run")


# ============================================================================
# Dependency Injection
# ============================================================================


def get_sandbox_adapter() -> MCPSandboxAdapter:
    """Get or create the sandbox adapter singleton."""
    from src.configuration.di_container import DIContainer

    container = DIContainer()
    return container.sandbox_adapter()


def get_lifecycle_service(db=Depends(get_db)) -> ProjectSandboxLifecycleService:
    """Get the project sandbox lifecycle service."""
    from src.configuration.di_container import DIContainer

    container = DIContainer().with_db(db)
    return container.project_sandbox_lifecycle_service()


def get_event_publisher(request: Request) -> Optional[SandboxEventPublisher]:
    """Get the sandbox event publisher from app container.

    Uses the properly initialized container from app.state which has
    redis_client configured for the event bus.
    """
    try:
        # Get container from app.state which has redis_client properly configured
        container = request.app.state.container
        return container.sandbox_event_publisher()
    except Exception as e:
        logger.warning(f"Could not create event publisher: {e}")
        return None


def get_orchestrator() -> SandboxOrchestrator:
    """Get the sandbox orchestrator."""
    from src.configuration.config import get_settings
    from src.configuration.di_container import DIContainer

    container = DIContainer()
    settings = get_settings()

    return SandboxOrchestrator(
        sandbox_adapter=container.sandbox_adapter(),
        event_publisher=container.sandbox_event_publisher(),
        default_timeout=settings.sandbox_timeout_seconds,
    )


# ============================================================================
# API Endpoints
# ============================================================================


@router.get("/{project_id}/sandbox", response_model=ProjectSandboxResponse)
async def get_project_sandbox(
    project_id: str,
    current_user: User = Depends(get_current_user),
    service: ProjectSandboxLifecycleService = Depends(get_lifecycle_service),
):
    """Get the sandbox for a project.

    Returns the current sandbox information if it exists.
    Does not create a new sandbox if one doesn't exist.
    """
    # Verify user has access to project
    # TODO: Add project membership check

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
    service: ProjectSandboxLifecycleService = Depends(get_lifecycle_service),
    event_publisher: Optional[SandboxEventPublisher] = Depends(get_event_publisher),
):
    """Ensure a project's sandbox exists and is running.

    Creates a new sandbox if one doesn't exist, or returns the existing one.
    Performs health checks and auto-recovery if needed.
    """
    # TODO: Verify user has write access to project

    # Parse profile
    profile = None
    if request.profile:
        try:
            profile = SandboxProfileType(request.profile.lower())
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid profile: {request.profile}. Use: lite, standard, full",
            )

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
            from src.infrastructure.adapters.primary.web.routers.agent_websocket import manager

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
        raise HTTPException(status_code=500, detail=f"Failed to create sandbox: {str(e)}")


@router.get("/{project_id}/sandbox/health", response_model=HealthCheckResponse)
async def check_project_sandbox_health(
    project_id: str,
    current_user: User = Depends(get_current_user),
    service: ProjectSandboxLifecycleService = Depends(get_lifecycle_service),
):
    """Check the health of a project's sandbox."""
    # TODO: Verify user has access to project

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
            checked_at=datetime.utcnow().isoformat(),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Health check failed for project {project_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Health check failed: {str(e)}")


@router.get("/{project_id}/sandbox/stats", response_model=SandboxStatsResponse)
async def get_project_sandbox_stats(
    project_id: str,
    current_user: User = Depends(get_current_user),
    service: ProjectSandboxLifecycleService = Depends(get_lifecycle_service),
    adapter: MCPSandboxAdapter = Depends(get_sandbox_adapter),
):
    """Get resource usage statistics for a project's sandbox.

    Returns CPU, memory, disk, network, and process metrics.
    """
    # TODO: Verify user has access to project

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
            # Use timezone-aware datetime to avoid naive vs aware comparison
            from datetime import timezone

            now = datetime.now(timezone.utc)
            created_at = info.created_at
            # Ensure created_at is timezone-aware
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
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
            pids=stats.get("pids", 0),
            uptime_seconds=uptime_seconds,
            created_at=info.created_at.isoformat() if info.created_at else None,
            collected_at=datetime.now(timezone.utc).isoformat(),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get sandbox stats for project {project_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Stats query failed: {str(e)}")


@router.post("/{project_id}/sandbox/execute", response_model=ExecuteToolResponse)
async def execute_tool_in_project_sandbox(
    project_id: str,
    request: ExecuteToolRequest,
    current_user: User = Depends(get_current_user),
    service: ProjectSandboxLifecycleService = Depends(get_lifecycle_service),
):
    """Execute a tool in the project's sandbox.

    Automatically ensures the sandbox is running before execution.
    """
    # TODO: Verify user has write access to project

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
        )

    except Exception as e:
        logger.error(f"Tool execution failed for project {project_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Execution failed: {str(e)}")


@router.post("/{project_id}/sandbox/restart", response_model=SandboxActionResponse)
async def restart_project_sandbox(
    project_id: str,
    current_user: User = Depends(get_current_user),
    service: ProjectSandboxLifecycleService = Depends(get_lifecycle_service),
    event_publisher: Optional[SandboxEventPublisher] = Depends(get_event_publisher),
):
    """Restart the sandbox for a project."""
    # TODO: Verify user has admin access to project

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
            from src.infrastructure.adapters.primary.web.routers.agent_websocket import manager

            # Get tenant_id from current user context
            await manager.broadcast_sandbox_state(
                tenant_id=current_user.current_tenant_id or "",
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
        raise HTTPException(status_code=500, detail=f"Restart failed: {str(e)}")


@router.delete("/{project_id}/sandbox", response_model=SandboxActionResponse)
async def terminate_project_sandbox(
    project_id: str,
    current_user: User = Depends(get_current_user),
    service: ProjectSandboxLifecycleService = Depends(get_lifecycle_service),
    event_publisher: Optional[SandboxEventPublisher] = Depends(get_event_publisher),
):
    """Terminate the sandbox for a project."""
    # TODO: Verify user has admin access to project

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
            from src.infrastructure.adapters.primary.web.routers.agent_websocket import manager

            await manager.broadcast_sandbox_state(
                tenant_id=current_user.current_tenant_id or "",
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
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to terminate sandbox for project {project_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Termination failed: {str(e)}")


@router.get("/{project_id}/sandbox/sync", response_model=ProjectSandboxResponse)
async def sync_project_sandbox_status(
    project_id: str,
    current_user: User = Depends(get_current_user),
    service: ProjectSandboxLifecycleService = Depends(get_lifecycle_service),
):
    """Synchronize database status with actual container status.

    Useful for recovering from inconsistent states.
    """
    # TODO: Verify user has access to project

    try:
        info = await service.sync_sandbox_status(project_id)
        return ProjectSandboxResponse.from_info(info)

    except Exception as e:
        logger.error(f"Failed to sync sandbox status for project {project_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Sync failed: {str(e)}")


# ============================================================================
# Admin/Tenant-level endpoints
# ============================================================================


@router.get("/sandboxes", response_model=ListProjectSandboxesResponse)
async def list_project_sandboxes(
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    service: ProjectSandboxLifecycleService = Depends(get_lifecycle_service),
):
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
            )

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
):
    """Clean up sandboxes that haven't been accessed recently.

    Requires admin privileges.
    """
    # TODO: Verify admin privileges

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
    resolution: str = Query("1280x720", description="Screen resolution"),
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    service: ProjectSandboxLifecycleService = Depends(get_lifecycle_service),
    orchestrator: SandboxOrchestrator = Depends(get_orchestrator),
):
    """Start desktop service for the project's sandbox."""
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
        }

    except Exception as e:
        logger.error(f"Failed to start desktop for project {project_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to start desktop: {str(e)}")


@router.delete("/{project_id}/sandbox/desktop")
async def stop_project_desktop(
    project_id: str,
    current_user: User = Depends(get_current_user),
    service: ProjectSandboxLifecycleService = Depends(get_lifecycle_service),
    orchestrator: SandboxOrchestrator = Depends(get_orchestrator),
):
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
        raise HTTPException(status_code=500, detail=f"Failed to stop desktop: {str(e)}")


@router.post("/{project_id}/sandbox/terminal")
async def start_project_terminal(
    project_id: str,
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    service: ProjectSandboxLifecycleService = Depends(get_lifecycle_service),
    orchestrator: SandboxOrchestrator = Depends(get_orchestrator),
):
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
        raise HTTPException(status_code=500, detail=f"Failed to start terminal: {str(e)}")


@router.delete("/{project_id}/sandbox/terminal")
async def stop_project_terminal(
    project_id: str,
    current_user: User = Depends(get_current_user),
    service: ProjectSandboxLifecycleService = Depends(get_lifecycle_service),
    orchestrator: SandboxOrchestrator = Depends(get_orchestrator),
):
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
        raise HTTPException(status_code=500, detail=f"Failed to stop terminal: {str(e)}")
