"""Sandbox API routes for MCP sandbox operations.

Provides REST API endpoints for managing MCP sandboxes and executing
file system operations in isolated containers.
"""

import asyncio
import json
import logging
import re
from typing import Any, AsyncIterator, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from src.application.services.sandbox_event_service import SandboxEventPublisher
from src.domain.ports.services.sandbox_port import SandboxConfig, SandboxStatus
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import (
    MCPSandboxAdapter,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/sandbox", tags=["sandbox"])

# Global adapter instance (singleton pattern)
_sandbox_adapter: Optional[MCPSandboxAdapter] = None
_event_publisher: Optional[SandboxEventPublisher] = None


def get_sandbox_adapter() -> MCPSandboxAdapter:
    """Get or create the sandbox adapter singleton."""
    global _sandbox_adapter
    if _sandbox_adapter is None:
        _sandbox_adapter = MCPSandboxAdapter()
    return _sandbox_adapter


def get_event_publisher() -> Optional[SandboxEventPublisher]:
    """Get or create the sandbox event publisher singleton."""
    global _event_publisher
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
    image: Optional[str] = Field(
        default=None, description="Docker image (default: sandbox-mcp-server)"
    )
    memory_limit: Optional[str] = Field(default="2g", description="Memory limit")
    cpu_limit: Optional[str] = Field(default="2", description="CPU limit")
    timeout_seconds: Optional[int] = Field(default=3600, description="Max sandbox lifetime")
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

# Global adapter instance (singleton pattern)
_sandbox_adapter: Optional[MCPSandboxAdapter] = None


def get_sandbox_adapter() -> MCPSandboxAdapter:
    """Get or create the sandbox adapter singleton."""
    global _sandbox_adapter
    if _sandbox_adapter is None:
        _sandbox_adapter = MCPSandboxAdapter()
    return _sandbox_adapter


# --- Request/Response Schemas ---


class CreateSandboxRequest(BaseModel):
    """Request to create a new sandbox."""

    project_path: str = Field(
        default="/tmp/sandbox_workspace", description="Path to mount as workspace"
    )
    image: Optional[str] = Field(
        default=None, description="Docker image (default: sandbox-mcp-server)"
    )
    memory_limit: Optional[str] = Field(default="2g", description="Memory limit")
    cpu_limit: Optional[str] = Field(default="2", description="CPU limit")
    timeout_seconds: Optional[int] = Field(default=3600, description="Max sandbox lifetime")
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


# --- Endpoints ---


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
    """
    try:
        # Extract project_id from project_path
        project_id = extract_project_id(request.project_path)

        config = SandboxConfig(
            image=request.image,
            memory_limit=request.memory_limit,
            cpu_limit=request.cpu_limit,
            timeout_seconds=request.timeout_seconds,
            network_isolated=request.network_isolated,
            environment=request.environment,
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
            mcp_port=getattr(instance, 'mcp_port', None),
            desktop_port=getattr(instance, 'desktop_port', None),
            terminal_port=getattr(instance, 'terminal_port', None),
            desktop_url=getattr(instance, 'desktop_url', None),
            terminal_url=getattr(instance, 'terminal_url', None),
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
    """Terminate a sandbox."""
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
    event_publisher: Optional[SandboxEventPublisher] = Depends(get_event_publisher),
):
    """
    Start the remote desktop service (noVNC) for a sandbox.

    Starts Xvfb (virtual display), TigerVNC server, and noVNC web client,
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
        raise HTTPException(
            status_code=404,
            detail=f"Sandbox not found: {sandbox_id}"
        )

    # Extract project_id from sandbox instance
    project_id = extract_project_id(instance.project_path)

    try:
        # Call MCP tool to start desktop
        result = await adapter.call_tool(
            sandbox_id=sandbox_id,
            tool_name="start_desktop",
            arguments={
                "display": request.display,
                "resolution": request.resolution,
            },
            timeout=30.0,
        )

        # Check for error in tool result
        if result.get("is_error"):
            error_content = result.get("content", [{}])[0].get("text", "Unknown error")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to start desktop: {error_content}"
            )

        # Parse tool response
        content = result.get("content", [])
        if not content:
            raise HTTPException(
                status_code=500,
                detail="Empty response from desktop tool"
            )

        import json
        response_text = content[0].get("text", "{}")
        desktop_data = json.loads(response_text) if isinstance(response_text, str) else response_text

        if not desktop_data.get("success"):
            error_msg = desktop_data.get("error", "Unknown error")
            raise HTTPException(
                status_code=500,
                detail=f"Desktop start failed: {error_msg}"
            )

        # Emit desktop_started event
        if event_publisher:
            try:
                await event_publisher.publish_desktop_started(
                    project_id=project_id,
                    sandbox_id=sandbox_id,
                    url=desktop_data.get("url"),
                    display=desktop_data.get("display", request.display),
                    resolution=desktop_data.get("resolution", request.resolution),
                    port=desktop_data.get("port", 6080),
                )
            except Exception as e:
                logger.warning(f"Failed to publish desktop_started event: {e}")

        return DesktopStatusResponse(
            running=True,
            url=desktop_data.get("url"),
            display=desktop_data.get("display", request.display),
            resolution=desktop_data.get("resolution", request.resolution),
            port=desktop_data.get("port", 6080),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to start desktop for sandbox {sandbox_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to start desktop: {str(e)}"
        )


@router.delete("/{sandbox_id}/desktop", response_model=DesktopStopResponse)
async def stop_desktop(
    sandbox_id: str,
    current_user: User = Depends(get_current_user),
    adapter: MCPSandboxAdapter = Depends(get_sandbox_adapter),
    event_publisher: Optional[SandboxEventPublisher] = Depends(get_event_publisher),
):
    """
    Stop the remote desktop service for a sandbox.

    Stops the Xvfb, TigerVNC, and noVNC processes.

    Args:
        sandbox_id: Sandbox identifier

    Returns:
        Operation success status
    """
    # Verify sandbox exists
    instance = await adapter.get_sandbox(sandbox_id)
    if not instance:
        raise HTTPException(
            status_code=404,
            detail=f"Sandbox not found: {sandbox_id}"
        )

    # Extract project_id from sandbox instance
    project_id = extract_project_id(instance.project_path)

    try:
        # Call MCP tool to stop desktop
        result = await adapter.call_tool(
            sandbox_id=sandbox_id,
            tool_name="stop_desktop",
            arguments={},
            timeout=10.0,
        )

        # Parse tool response
        content = result.get("content", [])
        if content:
            import json
            response_text = content[0].get("text", "{}")
            desktop_data = json.loads(response_text) if isinstance(response_text, str) else response_text
            success = desktop_data.get("success", True)
            message = desktop_data.get("message", "Desktop stopped")
        else:
            success = True
            message = "Desktop stopped"

        # Emit desktop_stopped event
        if event_publisher and success:
            try:
                await event_publisher.publish_desktop_stopped(
                    project_id=project_id,
                    sandbox_id=sandbox_id,
                )
            except Exception as e:
                logger.warning(f"Failed to publish desktop_stopped event: {e}")

        return DesktopStopResponse(success=success, message=message)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to stop desktop for sandbox {sandbox_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to stop desktop: {str(e)}"
        )


@router.get("/{sandbox_id}/desktop", response_model=DesktopStatusResponse)
async def get_desktop_status(
    sandbox_id: str,
    current_user: User = Depends(get_current_user),
    adapter: MCPSandboxAdapter = Depends(get_sandbox_adapter),
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
        raise HTTPException(
            status_code=404,
            detail=f"Sandbox not found: {sandbox_id}"
        )

    try:
        # Call MCP tool to get desktop status
        result = await adapter.call_tool(
            sandbox_id=sandbox_id,
            tool_name="get_desktop_status",
            arguments={},
            timeout=10.0,
        )

        # Parse tool response
        content = result.get("content", [])
        if content:
            import json
            response_text = content[0].get("text", "{}")
            desktop_data = json.loads(response_text) if isinstance(response_text, str) else response_text

            return DesktopStatusResponse(
                running=desktop_data.get("running", False),
                url=desktop_data.get("url"),
                display=desktop_data.get("display", ""),
                resolution=desktop_data.get("resolution", ""),
                port=desktop_data.get("port", 0),
            )

        # Return default "not running" status
        return DesktopStatusResponse(
            running=False,
            url=None,
            display="",
            resolution="",
            port=0,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get desktop status for sandbox {sandbox_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get desktop status: {str(e)}"
        )


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
