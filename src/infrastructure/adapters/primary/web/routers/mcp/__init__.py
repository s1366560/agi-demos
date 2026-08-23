"""MCP API router module.

Aggregates all MCP-related endpoints from sub-modules.
MCP servers provide external tools and capabilities via the Model Context Protocol.
"""

from typing import cast

from fastapi import APIRouter, Depends, Query

from src.infrastructure.adapters.primary.web.mcp_application_authority_v2 import (
    MCPApplicationAuthorityV2,
    mcp_application_authority_dependency_v2,
)

from . import apps, servers, tools
from .schemas import (
    MCPServerCreate,
    MCPServerResponse,
    MCPServerTestResult,
    MCPServerUpdate,
    MCPToolCallRequest,
    MCPToolCallResponse,
    MCPToolResponse,
)

# Create main router with prefix
router = APIRouter(prefix="/api/v1/mcp", tags=["MCP Servers"])

# Include all sub-routers (apps before servers to avoid /{server_id} catching /apps)
router.include_router(apps.router)  # MCP Apps management
router.include_router(servers.router)  # Database-backed server management
router.include_router(tools.router)  # Tool listing and calling


# Root path aliases for backward compatibility
@router.post("", response_model=MCPServerResponse, include_in_schema=False)
async def create_mcp_server_root(
    server_data: MCPServerCreate,
    authority: MCPApplicationAuthorityV2 = Depends(mcp_application_authority_dependency_v2),
) -> MCPServerResponse:
    """Create MCP server (root path alias)."""
    return cast(
        MCPServerResponse,
        await servers.create_mcp_server(
            server_data=server_data,
            authority=authority,
        ),
    )


@router.get("", response_model=list[MCPServerResponse], include_in_schema=False)
async def list_mcp_servers_root(
    project_id: str | None = Query(None, description="Filter by project ID"),
    enabled_only: bool = Query(False, description="Only return enabled servers"),
    authority: MCPApplicationAuthorityV2 = Depends(mcp_application_authority_dependency_v2),
) -> list[MCPServerResponse]:
    """List MCP servers (root path alias)."""
    return await servers.list_mcp_servers(
        project_id=project_id,
        enabled_only=enabled_only,
        authority=authority,
    )


__all__ = [
    # Database server schemas
    "MCPServerCreate",
    "MCPServerResponse",
    "MCPServerTestResult",
    "MCPServerUpdate",
    # Tool schemas
    "MCPToolCallRequest",
    "MCPToolCallResponse",
    "MCPToolResponse",
    "router",
]
