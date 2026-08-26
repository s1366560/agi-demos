from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, WebSocket

from src.infrastructure.adapters.primary.web.tunnel_application_authority_v2 import (
    TunnelApplicationAuthorityV2,
    tunnel_admin_application_authority_dependency_v2,
    tunnel_websocket_application_authority_dependency_v2,
)

router = APIRouter(tags=["tunnel"])


@router.websocket("/api/v1/tunnel/connect")
async def tunnel_connect(
    websocket: WebSocket,
    tunnel: TunnelApplicationAuthorityV2 | None = Depends(
        tunnel_websocket_application_authority_dependency_v2
    ),
) -> None:
    if tunnel is None:
        return

    await tunnel.connect(websocket)


@router.get("/api/v1/admin/tunnel/status")
async def tunnel_status(
    tunnel: TunnelApplicationAuthorityV2 = Depends(
        tunnel_admin_application_authority_dependency_v2
    ),
) -> dict[str, Any]:
    return tunnel.status()
