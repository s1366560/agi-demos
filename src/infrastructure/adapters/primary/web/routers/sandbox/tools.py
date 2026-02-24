"""Tool operations endpoints for Sandbox API.

Provides MCP tool operations:
- connect_mcp: Connect to sandbox MCP server
- list_tools: List available tools
- list_agent_tools: List tools registered to agent
- call_tool: Execute a tool
- read_file: Convenience file read
- write_file: Convenience file write
- execute_bash: Convenience bash execution
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import MCPSandboxAdapter

from .schemas import (
    ListToolsResponse,
    ToolCallRequest,
    ToolCallResponse,
    ToolInfo,
)
from .utils import get_sandbox_adapter

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/{sandbox_id}/connect")
async def connect_mcp(
    sandbox_id: str,
    current_user: User = Depends(get_current_user),
    adapter: MCPSandboxAdapter = Depends(get_sandbox_adapter),
) -> dict[str, Any]:
    """Connect MCP client to sandbox."""
    try:
        success = await adapter.connect_mcp(sandbox_id)

        if not success:
            raise HTTPException(status_code=500, detail="Failed to connect MCP client")

        return {"status": "connected", "sandbox_id": sandbox_id}

    except Exception as e:
        logger.error(f"MCP connection error: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/{sandbox_id}/tools", response_model=ListToolsResponse)
async def list_tools(
    sandbox_id: str,
    current_user: User = Depends(get_current_user),
    adapter: MCPSandboxAdapter = Depends(get_sandbox_adapter),
) -> ListToolsResponse:
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
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/{sandbox_id}/tools/agent")
async def list_agent_tools(
    sandbox_id: str,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """
    List sandbox tools registered to Agent context.

    Returns the tool names that have been registered to the Agent
    tool registry for this sandbox.
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

        # Return tool info with original names
        tools = [
            {
                "name": tool_name,
                "description": f"{tool_name}",
            }
            for tool_name in tool_names
        ]

        return {
            "sandbox_id": sandbox_id,
            "registered": True,
            "tools": tools,
            "count": len(tools),
        }

    except Exception as e:
        logger.error(f"Failed to list agent tools: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/{sandbox_id}/call", response_model=ToolCallResponse)
async def call_tool(
    sandbox_id: str,
    request: ToolCallRequest,
    current_user: User = Depends(get_current_user),
    adapter: MCPSandboxAdapter = Depends(get_sandbox_adapter),
) -> ToolCallResponse:
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
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/{sandbox_id}/read")
async def read_file(
    sandbox_id: str,
    file_path: str,
    offset: int = 0,
    limit: int = 2000,
    current_user: User = Depends(get_current_user),
    adapter: MCPSandboxAdapter = Depends(get_sandbox_adapter),
) -> None:
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
) -> None:
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
    working_dir: str | None = None,
    current_user: User = Depends(get_current_user),
    adapter: MCPSandboxAdapter = Depends(get_sandbox_adapter),
) -> None:
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
