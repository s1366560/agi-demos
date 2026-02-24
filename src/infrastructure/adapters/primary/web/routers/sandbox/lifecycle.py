"""Sandbox lifecycle management endpoints.

Provides CRUD operations for sandbox instances:
- create_sandbox: Create a new sandbox
- get_sandbox: Get sandbox status
- terminate_sandbox: Delete a sandbox
- list_sandboxes: List all sandboxes
- cleanup_expired: Clean up expired sandboxes
- list_sandbox_profiles: List available profiles
- check_sandbox_health: Health check endpoint
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from src.application.services.sandbox_event_service import SandboxEventPublisher
from src.application.services.sandbox_health_service import HealthCheckLevel, SandboxHealthService
from src.application.services.sandbox_profile import list_profiles
from src.domain.ports.services.sandbox_port import SandboxStatus
from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user,
    get_current_user_tenant,
)
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import MCPSandboxAdapter

from .schemas import (
    CreateSandboxRequest,
    HealthCheckResponse,
    ListProfilesResponse,
    ListSandboxesResponse,
    ProfileInfo,
    SandboxResponse,
)
from .utils import extract_project_id, get_event_publisher, get_sandbox_adapter

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/profiles", response_model=ListProfilesResponse)
async def list_sandbox_profiles():
    """
    List all available sandbox profiles.

    Returns a list of predefined sandbox configurations with different
    resource limits and capabilities.
    """
    profiles = list_profiles()

    profile_infos = [
        ProfileInfo(
            name=p.name,
            profile_type=p.profile_type.value,
            description=p.description,
            desktop_enabled=p.desktop_enabled,
            memory_limit=p.memory_limit,
            cpu_limit=p.cpu_limit,
            timeout_seconds=p.timeout_seconds,
            preinstalled_tools=p.preinstalled_tools,
            max_instances=p.max_instances,
        )
        for p in profiles
    ]

    return ListProfilesResponse(profiles=profile_infos)


@router.get("/{sandbox_id}/health", response_model=HealthCheckResponse)
async def check_sandbox_health(
    sandbox_id: str,
    level: str = Query("basic", description="Health check level: basic, mcp, services, full"),
    _current_user: User = Depends(get_current_user),
    adapter: MCPSandboxAdapter = Depends(get_sandbox_adapter),
):
    """
    Check sandbox health status.

    Performs health checks at the specified level:
    - basic: Container running status
    - mcp: MCP connection status
    - services: Desktop and Terminal service status
    - full: All checks combined
    """
    # Validate and parse level
    try:
        health_level = HealthCheckLevel(level)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid health check level: {level}. Valid values: basic, mcp, services, full",
        )

    # Create health service
    health_service = SandboxHealthService(sandbox_adapter=adapter)

    # Perform health check
    result = await health_service.check_health(sandbox_id, level=health_level)

    return HealthCheckResponse(
        level=result.level.value,
        status=result.status.value,
        healthy=result.healthy,
        details=result.details,
        timestamp=(result.timestamp.isoformat()) if result.timestamp else "",
        sandbox_id=result.sandbox_id,
        errors=result.errors,
    )


@router.post("/create", response_model=SandboxResponse)
async def create_sandbox(
    request: CreateSandboxRequest,
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    adapter: MCPSandboxAdapter = Depends(get_sandbox_adapter),
    event_publisher: SandboxEventPublisher | None = Depends(get_event_publisher),
):
    """
    Create a new MCP sandbox.

    IMPORTANT: This API is DEPRECATED. Use POST /api/v1/projects/{project_id}/sandbox instead.
    """
    try:
        # Extract project_id from project_path
        project_id = extract_project_id(request.project_path)

        # CRITICAL: Use ProjectSandboxLifecycleService for proper locking
        from src.configuration.di_container import DIContainer

        container = DIContainer()
        lifecycle_service = container.project_sandbox_lifecycle_service()

        logger.info(
            f"[SandboxAPI] /create delegating to ProjectSandboxLifecycleService "
            f"for project={project_id}, tenant={tenant_id}"
        )

        # Use the unified lifecycle service
        sandbox_info = await lifecycle_service.get_or_create_sandbox(
            project_id=project_id,
            tenant_id=tenant_id,
        )

        # Auto-connect and get tools
        tools = []
        try:
            if sandbox_info.sandbox_id:
                await adapter.connect_mcp(sandbox_info.sandbox_id)
                tool_list = await adapter.list_tools(sandbox_info.sandbox_id)
                tools = [t["name"] for t in tool_list]

                # Register tools to Agent context via SandboxToolRegistry
                if tools:
                    try:
                        tool_registry = container.sandbox_tool_registry()
                        registered_tools = await tool_registry.register_sandbox_tools(
                            sandbox_id=sandbox_info.sandbox_id,
                            project_id=project_id,
                            tenant_id=tenant_id,
                            tools=tools,
                        )
                        logger.info(
                            f"[SandboxAPI] Registered {len(registered_tools)} tools "
                            f"for sandbox={sandbox_info.sandbox_id} to Agent context"
                        )
                    except Exception as e:
                        logger.warning(f"[SandboxAPI] Failed to register tools to Agent: {e}")
        except Exception as e:
            logger.warning(f"Could not connect MCP: {e}")

        # Emit sandbox_created event
        if event_publisher:
            try:
                await event_publisher.publish_sandbox_created(
                    project_id=project_id,
                    sandbox_id=sandbox_info.sandbox_id,
                    status=sandbox_info.status,
                    endpoint=sandbox_info.endpoint,
                    websocket_url=sandbox_info.websocket_url,
                )
            except Exception as e:
                logger.warning(f"Failed to publish sandbox_created event: {e}")

        return SandboxResponse(
            id=sandbox_info.sandbox_id,
            status=sandbox_info.status,
            project_path=request.project_path,
            endpoint=sandbox_info.endpoint,
            websocket_url=sandbox_info.websocket_url,
            created_at=sandbox_info.created_at.isoformat() if sandbox_info.created_at else "",
            tools=tools,
            mcp_port=sandbox_info.mcp_port,
            desktop_port=sandbox_info.desktop_port,
            terminal_port=sandbox_info.terminal_port,
            desktop_url=sandbox_info.desktop_url,
            terminal_url=sandbox_info.terminal_url,
        )

    except Exception as e:
        logger.error(f"Failed to create sandbox: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{sandbox_id}", response_model=SandboxResponse)
async def get_sandbox(
    sandbox_id: str,
    current_user: User = Depends(get_current_user),
    adapter: MCPSandboxAdapter = Depends(get_sandbox_adapter),
):
    """Get sandbox status and information."""
    instance = await adapter.get_sandbox(sandbox_id)

    if not instance:
        raise HTTPException(status_code=404, detail=f"Sandbox not found: {sandbox_id}")

    tools = []
    if instance.mcp_client and instance.mcp_client.is_connected:
        try:
            tool_list = await adapter.list_tools(sandbox_id)
            tools = [t["name"] for t in tool_list]
        except Exception:
            pass

    return SandboxResponse(
        id=instance.id,
        status=instance.status.value,
        project_path=instance.project_path,
        endpoint=instance.endpoint,
        websocket_url=instance.websocket_url,
        created_at=instance.created_at.isoformat(),
        tools=tools,
    )


@router.delete("/{sandbox_id}")
async def terminate_sandbox(
    sandbox_id: str,
    current_user: User = Depends(get_current_user),
    adapter: MCPSandboxAdapter = Depends(get_sandbox_adapter),
):
    """Terminate a sandbox and unregister its tools from Agent context."""
    # Unregister tools from Agent context first
    try:
        from src.configuration.di_container import DIContainer

        container = DIContainer()
        tool_registry = container.sandbox_tool_registry()

        unregistered = await tool_registry.unregister_sandbox_tools(sandbox_id)
        if unregistered:
            logger.info(f"[SandboxAPI] Unregistered tools for sandbox={sandbox_id}")
    except Exception as e:
        logger.warning(f"[SandboxAPI] Failed to unregister tools: {e}")

    success = await adapter.terminate_sandbox(sandbox_id)

    if not success:
        raise HTTPException(status_code=404, detail=f"Sandbox not found: {sandbox_id}")

    return {"status": "terminated", "sandbox_id": sandbox_id}


@router.get("/list", response_model=ListSandboxesResponse)
async def list_sandboxes(
    status: str | None = None,
    current_user: User = Depends(get_current_user),
    adapter: MCPSandboxAdapter = Depends(get_sandbox_adapter),
):
    """List all sandboxes."""
    status_filter = None
    if status:
        try:
            status_filter = SandboxStatus(status)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")

    instances = await adapter.list_sandboxes(status=status_filter)

    sandboxes = [
        SandboxResponse(
            id=inst.id,
            status=inst.status.value,
            project_path=inst.project_path,
            endpoint=inst.endpoint,
            websocket_url=getattr(inst, "websocket_url", None),
            created_at=inst.created_at.isoformat(),
            tools=[],
        )
        for inst in instances
    ]

    return ListSandboxesResponse(sandboxes=sandboxes, total=len(sandboxes))


@router.post("/cleanup")
async def cleanup_expired(
    max_age_seconds: int = 3600,
    current_user: User = Depends(get_current_user),
    adapter: MCPSandboxAdapter = Depends(get_sandbox_adapter),
):
    """Clean up expired sandboxes."""
    count = await adapter.cleanup_expired(max_age_seconds=max_age_seconds)
    return {"cleaned_up": count}
