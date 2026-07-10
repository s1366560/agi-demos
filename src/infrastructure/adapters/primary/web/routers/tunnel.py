from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.routers.agent.access import has_global_admin_access
from src.infrastructure.adapters.primary.web.websocket.auth import (
    authenticate_websocket_or_close,
    select_websocket_auth_subprotocol,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.i18n import gettext as _

logger = logging.getLogger(__name__)

router = APIRouter(tags=["tunnel"])


class TunnelAdapter:
    def __init__(self) -> None:
        self._connections: dict[str, WebSocket] = {}

    async def handle_websocket(
        self,
        websocket: WebSocket,
        *,
        subprotocol: str | None = None,
    ) -> None:
        await websocket.accept(subprotocol=subprotocol)
        conn_id = str(id(websocket))
        self._connections[conn_id] = websocket
        logger.info("Tunnel connected: %s (total: %d)", conn_id, len(self._connections))
        try:
            while True:
                data = await websocket.receive_text()
                logger.debug("Tunnel %s received %d bytes", conn_id, len(data))
        except WebSocketDisconnect:
            logger.info("Tunnel disconnected: %s", conn_id)
        finally:
            self._connections.pop(conn_id, None)

    def get_status(self) -> dict[str, Any]:
        return {
            "active_connections": len(self._connections),
            "connection_ids": list(self._connections.keys()),
        }


_tunnel_adapter = TunnelAdapter()


@router.websocket("/api/v1/tunnel/connect")
async def tunnel_connect(
    websocket: WebSocket,
    token: str | None = Query(None, description="Legacy API key query parameter"),
    db: AsyncSession = Depends(get_db),
) -> None:
    if await authenticate_websocket_or_close(websocket, db, token) is None:
        return

    await _tunnel_adapter.handle_websocket(
        websocket,
        subprotocol=select_websocket_auth_subprotocol(websocket),
    )


@router.get("/api/v1/admin/tunnel/status")
async def tunnel_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if not await has_global_admin_access(db, current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_("Admin access required"),
        )

    adapter_status = _tunnel_adapter.get_status()
    return {"active_connections": adapter_status["active_connections"]}
