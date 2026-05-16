"""Token management endpoints for Sandbox API.

Provides token generation, validation, and revocation for sandbox authentication.
"""

import hmac
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.sandbox_token_service import SandboxTokenService
from src.configuration.config import get_settings
from src.infrastructure.adapters.primary.web.dependencies import get_current_user, get_db
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.i18n import gettext as _

from .schemas import (
    SandboxTokenRequest,
    SandboxTokenResponse,
    ValidateTokenRequest,
    ValidateTokenResponse,
)
from .utils import assert_caller_owns_project, get_sandbox_token_service

logger = logging.getLogger(__name__)

router = APIRouter()


def _extract_bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    prefix = "Bearer "
    if not authorization.startswith(prefix):
        return None
    token = authorization[len(prefix) :].strip()
    return token or None


def require_sandbox_service_auth(
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    """Require the internal sandbox service token for platform token validation."""
    expected_token = get_settings().sandbox_service_token
    if not expected_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_("Sandbox service token is not configured"),
        )

    supplied_token = _extract_bearer_token(authorization)
    if not supplied_token or not hmac.compare_digest(supplied_token, expected_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_("Invalid sandbox service credentials"),
            headers={"WWW-Authenticate": "Bearer"},
        )


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

    # Keep credentials out of URL-shaped fields; callers already receive the
    # token separately and should send it through an auth header or WebSocket
    # subprotocol instead of query parameters.
    websocket_hint = "wss://your-sandbox-host:8765"
    if request.sandbox_type == "local":
        websocket_hint = "wss://your-tunnel-url"

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
    _service_auth: None = Depends(require_sandbox_service_auth),
    token_service: SandboxTokenService = Depends(get_sandbox_token_service),
) -> ValidateTokenResponse:
    """
    Validate a sandbox access token.

    Called by the sandbox MCP server (service-to-service) to validate
    incoming WebSocket connection tokens. The response intentionally omits
    ``user_id`` to avoid cross-tenant identity leakage to any caller that
    happens to reach this endpoint.

    Requires a service-account bearer token so network reachability alone is
    not enough to probe token validity.
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
