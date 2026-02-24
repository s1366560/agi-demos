"""Sandbox API router module.

This module aggregates all sandbox-related endpoints from sub-modules.
"""

from fastapi import APIRouter, Depends

from src.domain.model.auth.user import User
from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import MCPSandboxAdapter

from . import events, lifecycle, services, tokens, tools
from .schemas import (
    CreateSandboxRequest,
    DesktopStartRequest,
    DesktopStatusResponse,
    DesktopStopResponse,
    HealthCheckResponse,
    ListProfilesResponse,
    ListSandboxesResponse,
    ListToolsResponse,
    ProfileInfo,
    SandboxResponse,
    SandboxTokenRequest,
    SandboxTokenResponse,
    TerminalStartRequest,
    TerminalStatusResponse,
    TerminalStopResponse,
    ToolCallRequest,
    ToolCallResponse,
    ToolInfo,
    ValidateTokenRequest,
    ValidateTokenResponse,
)
from .utils import (
    ensure_sandbox_sync,
    extract_project_id,
    get_current_user,
    get_event_publisher,
    get_sandbox_adapter,
    get_sandbox_orchestrator,
    get_sandbox_token_service,
)

# Create main router with prefix
router = APIRouter(prefix="/api/v1/sandbox", tags=["sandbox"])

# Include all sub-routers
router.include_router(tokens.router)
router.include_router(lifecycle.router)
router.include_router(tools.router)
router.include_router(services.router)
router.include_router(events.router)


# Re-export list_sandboxes at root path for backward compatibility
# This handles GET /api/v1/sandbox and GET /api/v1/sandbox/
@router.get("", response_model=ListSandboxesResponse, include_in_schema=False)
@router.get("/", response_model=ListSandboxesResponse, include_in_schema=False)
async def list_sandboxes_root(
    status: str | None = None,
    current_user: User = Depends(get_current_user),
    adapter: MCPSandboxAdapter = Depends(get_sandbox_adapter),
) -> None:
    """List all sandboxes (root path alias)."""
    from .lifecycle import list_sandboxes

    return await list_sandboxes(status=status, current_user=current_user, adapter=adapter)


__all__ = [
    # Schemas
    "CreateSandboxRequest",
    "DesktopStartRequest",
    "DesktopStatusResponse",
    "DesktopStopResponse",
    "HealthCheckResponse",
    "ListProfilesResponse",
    "ListSandboxesResponse",
    "ListToolsResponse",
    "ProfileInfo",
    "SandboxResponse",
    "SandboxTokenRequest",
    "SandboxTokenResponse",
    "TerminalStartRequest",
    "TerminalStatusResponse",
    "TerminalStopResponse",
    "ToolCallRequest",
    "ToolCallResponse",
    "ToolInfo",
    "ValidateTokenRequest",
    "ValidateTokenResponse",
    # Utilities
    "ensure_sandbox_sync",
    "extract_project_id",
    "get_event_publisher",
    "get_sandbox_adapter",
    "get_sandbox_orchestrator",
    "get_sandbox_token_service",
    "router",
]
