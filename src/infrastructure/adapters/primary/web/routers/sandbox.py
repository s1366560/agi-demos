"""Sandbox API routes for MCP sandbox operations.

Provides REST API endpoints for managing MCP sandboxes and executing
file system operations in isolated containers.

Refactored to use SandboxOrchestrator for unified sandbox service management.
"""

import asyncio
import json
import logging
import re
import threading
from typing import Any, AsyncIterator, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from src.application.services.sandbox_event_service import SandboxEventPublisher
from src.application.services.sandbox_health_service import HealthCheckLevel, SandboxHealthService
from src.application.services.sandbox_orchestrator import SandboxOrchestrator
from src.application.services.sandbox_profile import get_profile, list_profiles
from src.domain.ports.services.sandbox_port import SandboxConfig, SandboxStatus
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import MCPSandboxAdapter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/sandbox", tags=["sandbox"])

# Thread-safe singleton management with lock
_singleton_lock = threading.Lock()
_sandbox_adapter: Optional[MCPSandboxAdapter] = None
_sandbox_orchestrator: Optional[SandboxOrchestrator] = None
_event_publisher: Optional[SandboxEventPublisher] = None
_worker_id: Optional[int] = None  # Track worker ID for multi-worker detection
_sync_pending: bool = False  # Track if sync is pending
_sync_lock = asyncio.Lock()  # Async lock for sync operation


def _get_worker_id() -> int:
    """Get current worker/process ID for tracking."""
    import os

    return os.getpid()


def get_sandbox_adapter() -> MCPSandboxAdapter:
    """Get or create the sandbox adapter singleton with thread-safe initialization."""
    global _sandbox_adapter, _worker_id, _sync_pending

    current_worker = _get_worker_id()

    with _singleton_lock:
        # Reinitialize if worker changed (fork detection)
        if _worker_id is not None and _worker_id != current_worker:
            logger.warning(
                f"Worker ID changed from {_worker_id} to {current_worker}. "
                "Reinitializing sandbox adapter for new worker."
            )
            _sandbox_adapter = None
            _worker_id = current_worker
            _sync_pending = False  # Reset sync flag on reinit

        if _sandbox_adapter is None:
            _sandbox_adapter = MCPSandboxAdapter()
            _worker_id = current_worker
            _sync_pending = True  # Mark sync as pending
            logger.info(f"Initialized sandbox adapter for worker {current_worker}")

        return _sandbox_adapter


async def ensure_sandbox_sync() -> None:
    """Ensure sandbox adapter is synced with existing Docker containers.

    This should be called during application startup to discover and recover
    any existing sandbox containers that were created before the adapter was
    (re)initialized.

    This function is idempotent and will only sync once per adapter instance.
    """
    global _sync_pending

    adapter = get_sandbox_adapter()

    async with _sync_lock:
        if not _sync_pending:
            # Already synced
            return

        try:
            count = await adapter.sync_from_docker()
            if count > 0:
                logger.info(f"API Server: Synced {count} existing sandboxes from Docker")
            else:
                logger.info("API Server: No existing sandboxes found in Docker")
            _sync_pending = False
        except Exception as e:
            logger.warning(f"API Server: Failed to sync sandboxes from Docker: {e}")
            _sync_pending = False


def get_sandbox_orchestrator() -> SandboxOrchestrator:
    """Get or create the sandbox orchestrator singleton with thread-safe initialization."""
    global _sandbox_orchestrator, _event_publisher

    with _singleton_lock:
        if _sandbox_orchestrator is None:
            from src.configuration.config import get_settings
            from src.configuration.di_container import DIContainer

            container = DIContainer()
            settings = get_settings()

            # Initialize event publisher if not already
            if _event_publisher is None:
                _event_publisher = container.sandbox_event_publisher()

            _sandbox_orchestrator = SandboxOrchestrator(
                sandbox_adapter=get_sandbox_adapter(),
                event_publisher=_event_publisher,
                default_timeout=settings.sandbox_timeout_seconds,
            )
        return _sandbox_orchestrator


def get_event_publisher() -> Optional[SandboxEventPublisher]:
    """Get or create the sandbox event publisher singleton with thread-safe initialization."""
    global _event_publisher

    with _singleton_lock:
        if _event_publisher is None:
            try:
                from src.configuration.di_container import DIContainer

                container = DIContainer()
                _event_publisher = container.sandbox_event_publisher()
            except Exception as e:
                logger.warning(f"Could not create event publisher: {e}")
                _event_publisher = None
        return _event_publisher


def extract_project_id(project_path: str) -> str:
    """
    Extract project_id from project_path.

    Args:
        project_path: Path in format /tmp/memstack_{project_id}

    Returns:
        Extracted project_id or "default" if not found
    """
    match = re.search(r"memstack_([a-zA-Z0-9_-]+)$", project_path)
    if match:
        return match.group(1)
    return "default"


# --- Request/Response Schemas ---


class CreateSandboxRequest(BaseModel):
    """Request to create a new sandbox."""

    project_path: str = Field(
        default="/tmp/sandbox_workspace", description="Path to mount as workspace"
    )
    profile: Optional[str] = Field(
        default="standard", description="Sandbox profile: lite, standard, or full"
    )
    image: Optional[str] = Field(
        default=None, description="Docker image (default: sandbox-mcp-server)"
    )
    memory_limit: Optional[str] = Field(
        default=None, description="Memory limit (overrides profile if set)"
    )
    cpu_limit: Optional[str] = Field(
        default=None, description="CPU limit (overrides profile if set)"
    )
    timeout_seconds: Optional[int] = Field(
        default=None, description="Max sandbox lifetime (overrides profile if set)"
    )
    network_isolated: bool = Field(default=False, description="Network isolation")
    environment: Dict[str, str] = Field(default_factory=dict, description="Environment variables")


class SandboxResponse(BaseModel):
    """Sandbox instance response."""

    id: str
    status: str
    project_path: str
    endpoint: Optional[str] = None
    websocket_url: Optional[str] = None
    created_at: str
    tools: List[str] = Field(default_factory=list)
    # Service ports and URLs
    mcp_port: Optional[int] = None
    desktop_port: Optional[int] = None
    terminal_port: Optional[int] = None
    desktop_url: Optional[str] = None
    terminal_url: Optional[str] = None


class ToolCallRequest(BaseModel):
    """Request to call an MCP tool."""

    tool_name: str = Field(..., description="Tool name (read, write, edit, glob, grep, bash)")
    arguments: Dict[str, Any] = Field(default_factory=dict, description="Tool arguments")
    timeout: float = Field(default=30.0, description="Timeout in seconds")


class ToolCallResponse(BaseModel):
    """Tool call response."""

    content: List[Dict[str, Any]]
    is_error: bool


class ListSandboxesResponse(BaseModel):
    """List sandboxes response."""

    sandboxes: List[SandboxResponse]
    total: int


class ToolInfo(BaseModel):
    """Tool information."""

    name: str
    description: Optional[str] = None
    input_schema: Dict[str, Any] = Field(default_factory=dict)


class ListToolsResponse(BaseModel):
    """List tools response."""

    tools: List[ToolInfo]


# --- Desktop Request/Response Schemas ---


class DesktopStartRequest(BaseModel):
    """Request to start desktop service."""

    resolution: str = Field(default="1280x720", description="Screen resolution (e.g., '1280x720')")
    display: str = Field(default=":1", description="X11 display number (e.g., ':1')")


class DesktopStatusResponse(BaseModel):
    """Desktop service status response."""

    running: bool = Field(..., description="Whether desktop service is running")
    url: Optional[str] = Field(None, description="noVNC WebSocket URL (if running)")
    display: str = Field(default="", description="X11 display number (e.g., ':1')")
    resolution: str = Field(default="", description="Screen resolution (e.g., '1280x720')")
    port: int = Field(default=0, description="noVNC port number")


class DesktopStopResponse(BaseModel):
    """Response from stopping desktop."""

    success: bool = Field(..., description="Whether the operation was successful")
    message: str = Field(default="", description="Status message")


# --- Terminal Request/Response Schemas ---


class TerminalStartRequest(BaseModel):
    """Request to start terminal service."""

    port: int = Field(default=7681, description="Port for the ttyd WebSocket server")


class TerminalStatusResponse(BaseModel):
    """Terminal service status response."""

    running: bool = Field(..., description="Whether terminal service is running")
    url: Optional[str] = Field(None, description="WebSocket URL (if running)")
    port: int = Field(default=0, description="Ttyd port number")
    pid: Optional[int] = Field(None, description="Process ID")
    session_id: Optional[str] = Field(None, description="Terminal session ID")


class TerminalStopResponse(BaseModel):
    """Response from stopping terminal."""

    success: bool = Field(..., description="Whether the operation was successful")
    message: str = Field(default="", description="Status message")


# --- Profile Response Schemas ---


class ProfileInfo(BaseModel):
    """Information about a sandbox profile."""

    name: str = Field(..., description="Profile name (e.g., 'Lite', 'Standard', 'Full')")
    profile_type: str = Field(..., description="Profile type identifier (lite, standard, full)")
    description: str = Field(..., description="Profile description")
    desktop_enabled: bool = Field(..., description="Whether desktop environment is enabled")
    memory_limit: str = Field(..., description="Memory limit (e.g., '512m', '2g', '4g')")
    cpu_limit: str = Field(..., description="CPU limit (e.g., '0.5', '2', '4')")
    timeout_seconds: int = Field(..., description="Maximum sandbox lifetime in seconds")
    preinstalled_tools: List[str] = Field(..., description="List of preinstalled tools")
    max_instances: int = Field(..., description="Maximum concurrent instances")


class ListProfilesResponse(BaseModel):
    """Response listing all available sandbox profiles."""

    profiles: List[ProfileInfo]


# --- Health Check Response Schemas ---


class HealthCheckResponse(BaseModel):
    """Health check response."""

    level: str = Field(..., description="Health check level performed")
    status: str = Field(..., description="Overall health status")
    healthy: bool = Field(..., description="Whether the sandbox is healthy")
    details: Dict[str, Any] = Field(default_factory=dict, description="Detailed health information")
    timestamp: str = Field(..., description="ISO format timestamp")
    sandbox_id: str = Field(..., description="Sandbox ID")
    errors: List[str] = Field(default_factory=list, description="List of errors found")


# --- Endpoints ---


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
    adapter: MCPSandboxAdapter = Depends(get_sandbox_adapter),
    event_publisher: Optional[SandboxEventPublisher] = Depends(get_event_publisher),
):
    """
    Create a new MCP sandbox.

    Creates a Docker container running the sandbox-mcp-server, which provides
    file system operations via MCP protocol over WebSocket.

    After successful creation and MCP connection, registers sandbox tools
    to the Agent tool registry for dynamic tool injection.
    """
    try:
        # Extract project_id from project_path
        project_id = extract_project_id(request.project_path)

        # Get profile and apply settings (with override support)
        profile = get_profile(request.profile or "standard")

        # Use profile defaults, allow explicit overrides
        memory_limit = (
            request.memory_limit if request.memory_limit is not None else profile.memory_limit
        )
        cpu_limit = request.cpu_limit if request.cpu_limit is not None else profile.cpu_limit
        timeout_seconds = (
            request.timeout_seconds
            if request.timeout_seconds is not None
            else profile.timeout_seconds
        )

        # Determine image: request > profile > settings default
        image = request.image or profile.image_name
        if not image:
            from src.configuration.config import get_settings
            image = get_settings().sandbox_default_image

        config = SandboxConfig(
            image=image,
            memory_limit=memory_limit,
            cpu_limit=cpu_limit,
            timeout_seconds=timeout_seconds,
            network_isolated=request.network_isolated,
            environment=request.environment,
            desktop_enabled=profile.desktop_enabled,
        )

        instance = await adapter.create_sandbox(
            project_path=request.project_path,
            config=config,
        )

        # Auto-connect to get tools
        tools = []
        try:
            await adapter.connect_mcp(instance.id)
            tool_list = await adapter.list_tools(instance.id)
            tools = [t["name"] for t in tool_list]

            # Register tools to Agent context via SandboxToolRegistry
            if tools:
                try:
                    from src.configuration.di_container import DIContainer

                    container = DIContainer()
                    tool_registry = container.sandbox_tool_registry()

                    # Use current_user's tenant_id
                    tenant_id = (
                        str(current_user.tenant_id)
                        if hasattr(current_user, "tenant_id")
                        else "default"
                    )

                    registered_tools = await tool_registry.register_sandbox_tools(
                        sandbox_id=instance.id,
                        project_id=project_id,
                        tenant_id=tenant_id,
                        tools=tools,
                    )

                    logger.info(
                        f"[SandboxAPI] Registered {len(registered_tools)} tools "
                        f"for sandbox={instance.id} to Agent context"
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
                    sandbox_id=instance.id,
                    status=instance.status.value,
                    endpoint=instance.endpoint,
                    websocket_url=instance.websocket_url,
                )
            except Exception as e:
                logger.warning(f"Failed to publish sandbox_created event: {e}")

        return SandboxResponse(
            id=instance.id,
            status=instance.status.value,
            project_path=instance.project_path,
            endpoint=instance.endpoint,
            websocket_url=instance.websocket_url,
            created_at=instance.created_at.isoformat(),
            tools=tools,
            mcp_port=getattr(instance, "mcp_port", None),
            desktop_port=getattr(instance, "desktop_port", None),
            terminal_port=getattr(instance, "terminal_port", None),
            desktop_url=getattr(instance, "desktop_url", None),
            terminal_url=getattr(instance, "terminal_url", None),
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


@router.get("", response_model=ListSandboxesResponse)
@router.get("/", response_model=ListSandboxesResponse)
async def list_sandboxes(
    status: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    adapter: MCPSandboxAdapter = Depends(get_sandbox_adapter),
):
    """List all sandboxes.

    Note: Two route decorators are used to handle both:
    - GET /api/v1/sandbox (no trailing slash) - from frontend
    - GET /api/v1/sandbox/ (with trailing slash) - backward compatibility

    This prevents FastAPI from returning 307 redirect which would drop
    the Authorization header (HTTP security behavior).
    """
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


@router.post("/{sandbox_id}/connect")
async def connect_mcp(
    sandbox_id: str,
    current_user: User = Depends(get_current_user),
    adapter: MCPSandboxAdapter = Depends(get_sandbox_adapter),
):
    """Connect MCP client to sandbox."""
    try:
        success = await adapter.connect_mcp(sandbox_id)

        if not success:
            raise HTTPException(status_code=500, detail="Failed to connect MCP client")

        return {"status": "connected", "sandbox_id": sandbox_id}

    except Exception as e:
        logger.error(f"MCP connection error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{sandbox_id}/tools", response_model=ListToolsResponse)
async def list_tools(
    sandbox_id: str,
    current_user: User = Depends(get_current_user),
    adapter: MCPSandboxAdapter = Depends(get_sandbox_adapter),
):
    """List available MCP tools in sandbox."""
    try:
        tools = await adapter.list_tools(sandbox_id)

        return ListToolsResponse(
            tools=[
                ToolInfo(
                    name=t["name"],
                    description=t.get("description"),
                    input_schema=t.get("input_schema", {}),
                )
                for t in tools
            ]
        )

    except Exception as e:
        logger.error(f"Failed to list tools: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{sandbox_id}/tools/agent")
async def list_agent_tools(
    sandbox_id: str,
    current_user: User = Depends(get_current_user),
):
    """
    List sandbox tools registered to Agent context.

    Returns the namespaced tool names that have been registered
    to the Agent tool registry for this sandbox.

    The tools are returned with their Agent-side namespaced names
    (e.g., "sandbox_abc123_bash") which can be used directly in
    Agent tool execution.
    """
    from src.configuration.di_container import DIContainer

    try:
        container = DIContainer()
        tool_registry = container.sandbox_tool_registry()

        # Get registered tool names
        tool_names = await tool_registry.get_sandbox_tools(sandbox_id)

        if tool_names is None:
            return {
                "sandbox_id": sandbox_id,
                "registered": False,
                "tools": [],
                "message": "Sandbox tools not registered to Agent context",
            }

        # Generate namespaced tool names
        namespaced_tools = [
            {
                "agent_name": f"sandbox_{sandbox_id}_{tool_name}",
                "original_name": tool_name,
                "description": f"[Sandbox:{sandbox_id[:8]}...] {tool_name}",
            }
            for tool_name in tool_names
        ]

        return {
            "sandbox_id": sandbox_id,
            "registered": True,
            "tools": namespaced_tools,
            "count": len(namespaced_tools),
        }

    except Exception as e:
        logger.error(f"Failed to list agent tools: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{sandbox_id}/call", response_model=ToolCallResponse)
async def call_tool(
    sandbox_id: str,
    request: ToolCallRequest,
    current_user: User = Depends(get_current_user),
    adapter: MCPSandboxAdapter = Depends(get_sandbox_adapter),
):
    """
    Call an MCP tool on the sandbox.

    Available tools:
    - read: Read file contents
    - write: Write/create files
    - edit: Replace text in files
    - glob: Find files by pattern
    - grep: Search file contents
    - bash: Execute shell commands
    """
    try:
        result = await adapter.call_tool(
            sandbox_id=sandbox_id,
            tool_name=request.tool_name,
            arguments=request.arguments,
            timeout=request.timeout,
        )

        return ToolCallResponse(
            content=result.get("content", []),
            is_error=result.get("is_error", False),
        )

    except Exception as e:
        logger.error(f"Tool call error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{sandbox_id}/read")
async def read_file(
    sandbox_id: str,
    file_path: str,
    offset: int = 0,
    limit: int = 2000,
    current_user: User = Depends(get_current_user),
    adapter: MCPSandboxAdapter = Depends(get_sandbox_adapter),
):
    """Read a file from sandbox (convenience endpoint)."""
    result = await adapter.call_tool(
        sandbox_id=sandbox_id,
        tool_name="read",
        arguments={"file_path": file_path, "offset": offset, "limit": limit},
    )
    return result


@router.post("/{sandbox_id}/write")
async def write_file(
    sandbox_id: str,
    file_path: str,
    content: str,
    current_user: User = Depends(get_current_user),
    adapter: MCPSandboxAdapter = Depends(get_sandbox_adapter),
):
    """Write a file to sandbox (convenience endpoint)."""
    result = await adapter.call_tool(
        sandbox_id=sandbox_id,
        tool_name="write",
        arguments={"file_path": file_path, "content": content},
    )
    return result


@router.post("/{sandbox_id}/bash")
async def execute_bash(
    sandbox_id: str,
    command: str,
    timeout: int = 300,
    working_dir: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    adapter: MCPSandboxAdapter = Depends(get_sandbox_adapter),
):
    """Execute bash command in sandbox (convenience endpoint)."""
    args = {"command": command, "timeout": timeout}
    if working_dir:
        args["working_dir"] = working_dir

    result = await adapter.call_tool(
        sandbox_id=sandbox_id,
        tool_name="bash",
        arguments=args,
    )
    return result


@router.post("/cleanup")
async def cleanup_expired(
    max_age_seconds: int = 3600,
    current_user: User = Depends(get_current_user),
    adapter: MCPSandboxAdapter = Depends(get_sandbox_adapter),
):
    """Clean up expired sandboxes."""
    count = await adapter.cleanup_expired(max_age_seconds=max_age_seconds)
    return {"cleaned_up": count}


# --- Desktop Management Endpoints ---


@router.post("/{sandbox_id}/desktop", response_model=DesktopStatusResponse)
async def start_desktop(
    sandbox_id: str,
    request: DesktopStartRequest = DesktopStartRequest(),
    current_user: User = Depends(get_current_user),
    adapter: MCPSandboxAdapter = Depends(get_sandbox_adapter),
    orchestrator: SandboxOrchestrator = Depends(get_sandbox_orchestrator),
    event_publisher: Optional[SandboxEventPublisher] = Depends(get_event_publisher),
):
    """
    Start the remote desktop service (noVNC) for a sandbox.

    Starts Xvfb (virtual display), VNC server, and noVNC web client,
    allowing browser-based GUI access to the sandbox.

    Args:
        sandbox_id: Sandbox identifier
        request: Desktop start configuration (resolution, display)

    Returns:
        Desktop status with connection URL
    """
    # Verify sandbox exists
    instance = await adapter.get_sandbox(sandbox_id)
    if not instance:
        raise HTTPException(status_code=404, detail=f"Sandbox not found: {sandbox_id}")

    # Extract project_id from sandbox instance
    project_id = extract_project_id(instance.project_path)

    try:
        from src.application.services.sandbox_orchestrator import DesktopConfig

        config = DesktopConfig(
            resolution=request.resolution,
            display=request.display,
        )

        status = await orchestrator.start_desktop(sandbox_id, config)

        # Emit desktop_started event via event_publisher
        if event_publisher and status.running:
            try:
                await event_publisher.publish_desktop_started(
                    project_id=project_id,
                    sandbox_id=sandbox_id,
                    url=status.url,
                    display=status.display,
                    resolution=status.resolution,
                    port=status.port,
                )
            except Exception as e:
                logger.warning(f"Failed to publish desktop_started event: {e}")

        return DesktopStatusResponse(
            running=status.running,
            url=status.url,
            display=status.display,
            resolution=status.resolution,
            port=status.port,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to start desktop for sandbox {sandbox_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to start desktop: {str(e)}")


@router.delete("/{sandbox_id}/desktop", response_model=DesktopStopResponse)
async def stop_desktop(
    sandbox_id: str,
    current_user: User = Depends(get_current_user),
    adapter: MCPSandboxAdapter = Depends(get_sandbox_adapter),
    orchestrator: SandboxOrchestrator = Depends(get_sandbox_orchestrator),
    event_publisher: Optional[SandboxEventPublisher] = Depends(get_event_publisher),
):
    """
    Stop the remote desktop service for a sandbox.

    Stops the Xvfb, VNC, and noVNC processes.

    Args:
        sandbox_id: Sandbox identifier

    Returns:
        Operation success status
    """
    # Verify sandbox exists
    instance = await adapter.get_sandbox(sandbox_id)
    if not instance:
        raise HTTPException(status_code=404, detail=f"Sandbox not found: {sandbox_id}")

    # Extract project_id from sandbox instance
    project_id = extract_project_id(instance.project_path)

    try:
        success = await orchestrator.stop_desktop(sandbox_id)

        # Emit desktop_stopped event via event_publisher
        if event_publisher and success:
            try:
                await event_publisher.publish_desktop_stopped(
                    project_id=project_id,
                    sandbox_id=sandbox_id,
                )
            except Exception as e:
                logger.warning(f"Failed to publish desktop_stopped event: {e}")

        return DesktopStopResponse(
            success=success, message="Desktop stopped" if success else "Failed to stop desktop"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to stop desktop for sandbox {sandbox_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to stop desktop: {str(e)}")


@router.get("/{sandbox_id}/desktop", response_model=DesktopStatusResponse)
async def get_desktop_status(
    sandbox_id: str,
    current_user: User = Depends(get_current_user),
    adapter: MCPSandboxAdapter = Depends(get_sandbox_adapter),
    orchestrator: SandboxOrchestrator = Depends(get_sandbox_orchestrator),
):
    """
    Get the current status of the remote desktop service.

    Returns information about whether the desktop is running,
    display, resolution, port, and connection URL.

    Args:
        sandbox_id: Sandbox identifier

    Returns:
        Desktop status information
    """
    # Verify sandbox exists
    instance = await adapter.get_sandbox(sandbox_id)
    if not instance:
        raise HTTPException(status_code=404, detail=f"Sandbox not found: {sandbox_id}")

    try:
        status = await orchestrator.get_desktop_status(sandbox_id)

        return DesktopStatusResponse(
            running=status.running,
            url=status.url,
            display=status.display,
            resolution=status.resolution,
            port=status.port,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get desktop status for sandbox {sandbox_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get desktop status: {str(e)}")


# --- Terminal Management Endpoints ---


@router.post("/{sandbox_id}/terminal", response_model=TerminalStatusResponse)
async def start_terminal(
    sandbox_id: str,
    request: TerminalStartRequest = TerminalStartRequest(),
    current_user: User = Depends(get_current_user),
    adapter: MCPSandboxAdapter = Depends(get_sandbox_adapter),
    orchestrator: SandboxOrchestrator = Depends(get_sandbox_orchestrator),
    event_publisher: Optional[SandboxEventPublisher] = Depends(get_event_publisher),
):
    """
    Start the web terminal service (ttyd) for a sandbox.

    Starts a ttyd server that provides shell access via WebSocket.

    Args:
        sandbox_id: Sandbox identifier
        request: Terminal start configuration (port)

    Returns:
        Terminal status with connection URL
    """
    # Verify sandbox exists
    instance = await adapter.get_sandbox(sandbox_id)
    if not instance:
        raise HTTPException(status_code=404, detail=f"Sandbox not found: {sandbox_id}")

    # Extract project_id from sandbox instance
    project_id = extract_project_id(instance.project_path)

    try:
        from src.application.services.sandbox_orchestrator import TerminalConfig

        config = TerminalConfig(port=request.port)

        status = await orchestrator.start_terminal(sandbox_id, config)

        # Emit terminal_started event via event_publisher
        if event_publisher and status.running:
            try:
                await event_publisher.publish_terminal_started(
                    project_id=project_id,
                    sandbox_id=sandbox_id,
                    url=status.url,
                    port=status.port,
                    pid=status.pid,
                    session_id=status.session_id,
                )
            except Exception as e:
                logger.warning(f"Failed to publish terminal_started event: {e}")

        return TerminalStatusResponse(
            running=status.running,
            url=status.url,
            port=status.port,
            pid=status.pid,
            session_id=status.session_id,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to start terminal for sandbox {sandbox_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to start terminal: {str(e)}")


@router.delete("/{sandbox_id}/terminal", response_model=TerminalStopResponse)
async def stop_terminal(
    sandbox_id: str,
    current_user: User = Depends(get_current_user),
    adapter: MCPSandboxAdapter = Depends(get_sandbox_adapter),
    orchestrator: SandboxOrchestrator = Depends(get_sandbox_orchestrator),
    event_publisher: Optional[SandboxEventPublisher] = Depends(get_event_publisher),
):
    """
    Stop the web terminal service for a sandbox.

    Stops the ttyd server process.

    Args:
        sandbox_id: Sandbox identifier

    Returns:
        Operation success status
    """
    # Verify sandbox exists
    instance = await adapter.get_sandbox(sandbox_id)
    if not instance:
        raise HTTPException(status_code=404, detail=f"Sandbox not found: {sandbox_id}")

    # Extract project_id from sandbox instance
    project_id = extract_project_id(instance.project_path)

    try:
        success = await orchestrator.stop_terminal(sandbox_id)

        # Emit terminal_stopped event via event_publisher
        if event_publisher and success:
            try:
                await event_publisher.publish_terminal_stopped(
                    project_id=project_id,
                    sandbox_id=sandbox_id,
                )
            except Exception as e:
                logger.warning(f"Failed to publish terminal_stopped event: {e}")

        return TerminalStopResponse(
            success=success, message="Terminal stopped" if success else "Failed to stop terminal"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to stop terminal for sandbox {sandbox_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to stop terminal: {str(e)}")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to stop terminal for sandbox {sandbox_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to stop terminal: {str(e)}")


@router.get("/{sandbox_id}/terminal", response_model=TerminalStatusResponse)
async def get_terminal_status(
    sandbox_id: str,
    current_user: User = Depends(get_current_user),
    adapter: MCPSandboxAdapter = Depends(get_sandbox_adapter),
    orchestrator: SandboxOrchestrator = Depends(get_sandbox_orchestrator),
):
    """
    Get the current status of the web terminal service.

    Returns information about whether the terminal is running,
    port, URL, and session ID.

    Args:
        sandbox_id: Sandbox identifier

    Returns:
        Terminal status information
    """
    # Verify sandbox exists
    instance = await adapter.get_sandbox(sandbox_id)
    if not instance:
        raise HTTPException(status_code=404, detail=f"Sandbox not found: {sandbox_id}")

    try:
        status = await orchestrator.get_terminal_status(sandbox_id)

        return TerminalStatusResponse(
            running=status.running,
            url=status.url,
            port=status.port,
            pid=status.pid,
            session_id=status.session_id,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get terminal status for sandbox {sandbox_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get terminal status: {str(e)}")


# --- SSE Event Stream Endpoints ---


async def sandbox_event_stream(
    project_id: str,
    last_id: str = "0",
    event_publisher: Optional[SandboxEventPublisher] = None,
) -> AsyncIterator[Dict[str, Any]]:
    """
    Stream sandbox events from Redis Stream.

    Args:
        project_id: Project ID to stream events for
        last_id: Last received event ID for resuming (default: "0")
        event_publisher: Event publisher with Redis event bus

    Yields:
        Event dictionaries from Redis Stream
    """
    if not event_publisher or not event_publisher._event_bus:
        logger.warning("[SandboxSSE] Event bus not available")
        return

    stream_key = f"sandbox:events:{project_id}"
    event_bus = event_publisher._event_bus

    logger.info(f"[SandboxSSE] Starting stream for {stream_key} from {last_id}")

    try:
        async for message in event_bus.stream_read(
            stream_key=stream_key,
            last_id=last_id,
            count=100,
            block_ms=5000,  # Block for 5 seconds waiting for new events
        ):
            # Yield the event data with the message ID
            yield {
                "id": message.get("id", ""),
                "data": message.get("data", {}),
            }
    except asyncio.CancelledError:
        logger.info(f"[SandboxSSE] Stream cancelled for {stream_key}")
    except Exception as e:
        logger.error(f"[SandboxSSE] Stream error for {stream_key}: {e}")


async def sse_generator(
    project_id: str,
    last_id: str = "0",
    event_publisher: Optional[SandboxEventPublisher] = None,
) -> AsyncIterator[str]:
    """
    SSE response generator.

    Formats events as SSE messages:
    event: sandbox
    data: {"type": "...", "data": {...}, "timestamp": "..."}
    id: 1234567890-0

    Args:
        project_id: Project ID to stream events for
        last_id: Last received event ID for resuming
        event_publisher: Event publisher with Redis event bus

    Yields:
        SSE formatted strings
    """
    async for message in sandbox_event_stream(project_id, last_id, event_publisher):
        event_data = message.get("data", {})
        event_id = message.get("id", "")

        # Format as SSE
        # event: sandbox - indicates this is a sandbox event
        # data: {...} - JSON event data
        # id: {msg_id} - message ID for reconnection resume
        sse_message = f"event: sandbox\ndata: {json.dumps(event_data)}\nid: {event_id}\n\n"
        yield sse_message


@router.get("/events/{project_id}")
async def subscribe_sandbox_events(
    project_id: str,
    last_id: str = Query("0", description="Last event ID for resuming stream"),
    _current_user: User = Depends(get_current_user),
    event_publisher: Optional[SandboxEventPublisher] = Depends(get_event_publisher),
):
    """
    SSE endpoint for sandbox events.

    Subscribes to sandbox lifecycle events (created, terminated, status)
    and service events (desktop_started, desktop_stopped, terminal_started, etc.).

    Query Parameters:
    - last_id: Last received event ID for resuming (default: "0")
             Use the ID from the last received event's id field

    SSE Format:
    - Event type: "sandbox"
    - Data: JSON with "type", "data", "timestamp" fields
    - ID: Redis Stream message ID for reconnection resume

    Example:
    ```
    event: sandbox
    data: {"type": "desktop_started", "data": {"sandbox_id": "...", "url": "..."}, "timestamp": "2024-01-01T00:00:00Z"}
    id: 1234567890-0

    event: sandbox
    data: {"type": "terminal_started", "data": {"sandbox_id": "...", "port": 7681}, "timestamp": "2024-01-01T00:00:00Z"}
    id: 1234567891-0
    ```

    Reconnection:
    - Save the last received `id` value
    - Reconnect with `last_id=<saved_id>` to resume from that point
    - Client will receive only new events after the saved ID
    """
    from fastapi.responses import StreamingResponse

    return StreamingResponse(
        sse_generator(project_id, last_id, event_publisher),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )
