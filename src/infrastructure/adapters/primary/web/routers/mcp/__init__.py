"""MCP API router module.

Aggregates all MCP-related endpoints from sub-modules.
MCP servers provide external tools and capabilities via the Model Context Protocol.
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.primary.web.dependencies import get_current_user_tenant
from src.infrastructure.adapters.secondary.persistence.database import get_db

from . import servers, tools
from .schemas import (
    MCPServerCreate,
    MCPServerResponse,
    MCPServerTestResult,
    MCPServerUpdate,
    MCPToolCallRequest,
    MCPToolCallResponse,
    MCPToolResponse,
)
from .utils import get_container_with_db

# Create main router with prefix
router = APIRouter(prefix="/api/v1/mcp", tags=["MCP Servers"])

# Include all sub-routers
router.include_router(servers.router)  # Database-backed server management
router.include_router(tools.router)  # Tool listing and calling


# Root path aliases for backward compatibility
@router.post("", response_model=MCPServerResponse, include_in_schema=False)
async def create_mcp_server_root(
    server_data: MCPServerCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_current_user_tenant),
):
    """Create MCP server (root path alias)."""
    return await servers.create_mcp_server(
        server_data=server_data, request=request, db=db, tenant_id=tenant_id
    )


@router.get("", response_model=List[MCPServerResponse], include_in_schema=False)
async def list_mcp_servers_root(
    project_id: Optional[str] = Query(None, description="Filter by project ID"),
    enabled_only: bool = Query(False, description="Only return enabled servers"),
    db: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_current_user_tenant),
):
    """List MCP servers (root path alias)."""
    return await servers.list_mcp_servers(
        project_id=project_id, enabled_only=enabled_only, db=db, tenant_id=tenant_id
    )


__all__ = [
    "router",
    # Utilities
    "get_container_with_db",
    # Database server schemas
    "MCPServerCreate",
    "MCPServerResponse",
    "MCPServerTestResult",
    "MCPServerUpdate",
    # Tool schemas
    "MCPToolCallRequest",
    "MCPToolCallResponse",
    "MCPToolResponse",
]
