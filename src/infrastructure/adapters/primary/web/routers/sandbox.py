"""Sandbox API routes for MCP sandbox operations.

Provides REST API endpoints for managing MCP sandboxes and executing
file system operations in isolated containers.
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

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
):
    """
    Create a new MCP sandbox.

    Creates a Docker container running the sandbox-mcp-server, which provides
    file system operations via MCP protocol over WebSocket.
    """
    try:
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

        return SandboxResponse(
            id=instance.id,
            status=instance.status.value,
            project_path=instance.project_path,
            endpoint=instance.endpoint,
            websocket_url=instance.websocket_url,
            created_at=instance.created_at.isoformat(),
            tools=tools,
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


@router.get("/", response_model=ListSandboxesResponse)
async def list_sandboxes(
    status: Optional[str] = None,
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
