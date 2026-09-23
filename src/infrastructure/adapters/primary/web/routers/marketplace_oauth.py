"""Scoped MCP OAuth controls and the single-use backend callback."""

from __future__ import annotations

import os
from typing import Any, Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.marketplace_oauth import MarketplaceOAuth
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.adapters.secondary.persistence.plugin_marketplace_models_v3 import (
    MarketplaceRecordV3,
)
from src.infrastructure.i18n import gettext as _
from src.infrastructure.plugins.marketplace_oauth_protocol import OAuthError

router = APIRouter()


class OAuthMutation(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=64)
    project_id: str | None = Field(default=None, max_length=64)
    idempotency_key: str = Field(min_length=1, max_length=128)
    client_id: str | None = Field(default=None, max_length=2048)
    client_metadata_url: str | None = Field(default=None, max_length=2048)


def callback_uri() -> str:
    value = os.environ.get("PLUGIN_MARKETPLACE_OAUTH_REDIRECT_URI", "")
    parsed = urlsplit(value)
    local = os.environ.get("ENVIRONMENT") in {"test", "development"} and parsed.hostname in {
        "127.0.0.1",
        "::1",
    }
    if (
        not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
        or parsed.query
        or (parsed.scheme != "https" and not (local and parsed.scheme == "http"))
    ):
        raise OAuthError("oauth_backend_callback_configuration_required")
    return value


@router.get("/installations/{installation_id}/oauth/{server}/status")
async def oauth_status(
    installation_id: str,
    server: str,
    tenant_id: str,
    project_id: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    from .plugin_marketplace_v3 import authorize_scope

    await authorize_scope(db, user, tenant_id, project_id)
    try:
        result = await MarketplaceOAuth(db, tenant_id, project_id or "").status(
            installation_id, server
        )
        await db.commit()
        return result
    except OAuthError as exc:
        raise HTTPException(400, _(str(exc))) from exc


@router.post("/installations/{installation_id}/oauth/{server}/{action}")
async def oauth_mutate(
    installation_id: str,
    server: str,
    action: Literal["start", "cancel", "disconnect"],
    data: OAuthMutation,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    from .plugin_marketplace_v3 import authorize_scope

    await authorize_scope(db, user, data.tenant_id, data.project_id)
    service = MarketplaceOAuth(db, data.tenant_id, data.project_id or "")
    try:
        if action == "start":
            try:
                redirect_uri = callback_uri()
            except OAuthError as exc:
                return {"status": "needs_configuration", "reason": str(exc)}
            result = await service.start(
                installation_id,
                server,
                str(user.id),
                redirect_uri,
                data.idempotency_key,
                {"client_id": data.client_id, "client_metadata_url": data.client_metadata_url},
            )
        else:
            result = await service.disconnect(
                installation_id, server, cancel_only=action == "cancel"
            )
        await db.commit()
        return result
    except OAuthError as exc:
        await db.commit()
        raise HTTPException(400, _(str(exc))) from exc


@router.get("/oauth/callback", response_class=HTMLResponse)
async def oauth_callback(
    state: str = "",
    code: str | None = None,
    error: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    # No login cookie is required: the random, hashed, expiring state is bound to its initiator.
    challenge = await db.scalar(
        select(MarketplaceRecordV3).where(
            MarketplaceRecordV3.id == state.partition(".")[0],
            MarketplaceRecordV3.kind == "oauth_challenge",
        )
    )
    try:
        if challenge is None:
            raise OAuthError("oauth_state_invalid")
        result = await MarketplaceOAuth(db, challenge.tenant_id, challenge.project_id).callback(
            state, code, error
        )
        await db.commit()
        connected = result["status"] == "connected"
    except OAuthError:
        await db.commit()
        connected = False
    message = (
        _("Authorization complete. You can close this window.")
        if connected
        else _("Authorization failed or expired. Return to the plugin marketplace to retry.")
    )
    return HTMLResponse(
        message,
        status_code=200 if connected else 400,
        headers={
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
        },
    )
