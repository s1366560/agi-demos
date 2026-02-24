"""MCP Tool endpoints (database-backed).

Endpoints for listing and calling tools from database-backed MCP servers.
"""

import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.primary.web.dependencies import get_current_user_tenant
from src.infrastructure.adapters.secondary.persistence.database import get_db

from .schemas import (
    MCPToolCallRequest,
    MCPToolCallResponse,
    MCPToolListResponse,
    MCPToolResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/tools/all", response_model=MCPToolListResponse)
async def list_all_mcp_tools(
    project_id: str | None = Query(None, description="Filter by project ID"),
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(50, ge=1, le=200, description="Items per page"),
    db: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_current_user_tenant),
):
    """
    List all MCP tools from all enabled servers, optionally filtered by project.
    Supports pagination via page/per_page query parameters.
    """
    from src.infrastructure.adapters.secondary.persistence.sql_mcp_server_repository import (
        SqlMCPServerRepository,
    )

    repository = SqlMCPServerRepository(db)

    servers = await repository.get_enabled_servers(tenant_id, project_id=project_id)

    all_tools = []
    for server in servers:
        for tool in server.discovered_tools:
            all_tools.append(
                MCPToolResponse(
                    server_id=server.id,
                    server_name=server.name,
                    name=tool.get("name", "unknown"),
                    description=tool.get("description", ""),
                    input_schema=tool.get("inputSchema", {}),
                )
            )

    total = len(all_tools)
    total_pages = max(1, (total + per_page - 1) // per_page)
    start = (page - 1) * per_page
    end = start + per_page
    items = all_tools[start:end]

    return MCPToolListResponse(
        items=items,
        total=total,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
    )


@router.post("/tools/call", response_model=MCPToolCallResponse)
async def call_mcp_tool(
    request_data: MCPToolCallRequest,
    db: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_current_user_tenant),
):
    """
    Call a tool on an MCP server.

    Useful for testing tools before integrating them into agents.
    """
    from src.infrastructure.adapters.secondary.persistence.sql_mcp_server_repository import (
        SqlMCPServerRepository,
    )
    from src.infrastructure.agent.mcp.client import MCPClient

    repository = SqlMCPServerRepository(db)

    # Verify server exists and tenant ownership
    server = await repository.get_by_id(request_data.server_id)
    if not server:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"MCP server not found: {request_data.server_id}",
        )

    if server.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    if not server.enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"MCP server '{server.name}' is disabled",
        )

    try:
        # Connect to MCP server and call tool
        start_time = time.time()

        async with MCPClient(
            server_type=server.server_type,
            transport_config=server.transport_config,
        ) as client:
            result = await client.call_tool(
                tool_name=request_data.tool_name,
                arguments=request_data.arguments,
            )

        execution_time_ms = (time.time() - start_time) * 1000

        # Extract error state from MCP protocol response
        is_error = False
        error_message = None
        if isinstance(result, dict):
            is_error = result.get("isError", False)
            if is_error:
                content = result.get("content", [])
                if content and isinstance(content, list):
                    error_message = content[0].get("text", "") if content else None

        return MCPToolCallResponse(
            result=result,
            is_error=is_error,
            error_message=error_message,
            execution_time_ms=execution_time_ms,
        )

    except Exception as e:
        logger.error(f"Failed to call MCP tool: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to call MCP tool: {e!s}",
        ) from e
