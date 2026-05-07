"""Token management endpoints for Sandbox API.

Provides token generation, validation, and revocation for sandbox authentication.
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.sandbox_token_service import SandboxTokenService
from src.infrastructure.adapters.primary.web.dependencies import get_current_user, get_db
from src.infrastructure.adapters.secondary.persistence.models import User

from .schemas import (
    SandboxTokenRequest,
    SandboxTokenResponse,
    ValidateTokenRequest,
    ValidateTokenResponse,
)
from .utils import assert_caller_owns_project, get_sandbox_token_service

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/projects/{project_id}/token", response_model=SandboxTokenResponse)
async def generate_sandbox_token(
    project_id: str,
    request: SandboxTokenRequest,
    current_user: User = Depends(get_current_user),
    token_service: SandboxTokenService = Depends(get_sandbox_token_service),
    db: AsyncSession = Depends(get_db),
) -> SandboxTokenResponse:
    """
    Generate a short-lived access token for sandbox WebSocket connection.

    This token is used to authenticate WebSocket connections to sandboxes,
    especially for local sandboxes accessed via tunnel (ngrok/cloudflare).
    """
    # Authorize: caller must own the project they're minting a token for.
    await assert_caller_owns_project(project_id=project_id, user=current_user, db=db)

    # Get user's tenant (assuming single tenant per user for simplicity)
    tenant_id = current_user.tenants[0].tenant_id if current_user.tenants else "default"

    # Generate token
    access_token = token_service.generate_token(
        project_id=project_id,
        user_id=current_user.id,
        tenant_id=tenant_id,
        sandbox_type=request.sandbox_type,
        ttl_override=request.ttl_seconds,
    )

    # Build WebSocket URL hint
    websocket_hint = f"wss://your-sandbox-host:8765?token={access_token.token}"
    if request.sandbox_type == "local":
        websocket_hint = f"wss://your-tunnel-url?token={access_token.token}"

    return SandboxTokenResponse(
        token=access_token.token,
        project_id=access_token.project_id,
        sandbox_type=access_token.sandbox_type,
        expires_at=access_token.expires_at.isoformat(),
        expires_in=max(0, int((access_token.expires_at - access_token.created_at).total_seconds())),
        websocket_url_hint=websocket_hint,
    )


@router.post("/token/validate", response_model=ValidateTokenResponse)
async def validate_sandbox_token(
    request: ValidateTokenRequest,
    token_service: SandboxTokenService = Depends(get_sandbox_token_service),
) -> ValidateTokenResponse:
    """
    Validate a sandbox access token.

    Called by the sandbox MCP server (service-to-service) to validate
    incoming WebSocket connection tokens. The response intentionally omits
    ``user_id`` to avoid cross-tenant identity leakage to any caller that
    happens to reach this endpoint.

    TODO(P1-15 follow-up): require a service-account bearer token for this
    endpoint and move it onto an internal-only path so unauthenticated
    network reachability is no longer enough to probe token validity.
    """
    result = token_service.validate_token(
        token=request.token,
        project_id=request.project_id,
    )

    return ValidateTokenResponse(
        valid=result.valid,
        project_id=result.project_id,
        user_id=None,
        sandbox_type=result.sandbox_type,
        error=result.error,
    )


@router.delete("/projects/{project_id}/tokens")
async def revoke_project_tokens(
    project_id: str,
    current_user: User = Depends(get_current_user),
    token_service: SandboxTokenService = Depends(get_sandbox_token_service),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Revoke all active tokens for a project.

    Useful when disconnecting a local sandbox or for security purposes.
    """
    await assert_caller_owns_project(project_id=project_id, user=current_user, db=db)
    count = token_service.revoke_all_for_project(project_id)

    return {
        "project_id": project_id,
        "revoked_count": count,
        "message": f"Revoked {count} tokens for project",
    }
