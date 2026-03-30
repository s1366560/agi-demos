from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter(tags=["tunnel"])


class TunnelAdapter:
    def __init__(self) -> None:
        self._connections: dict[str, WebSocket] = {}

    async def handle_websocket(self, websocket: WebSocket) -> None:
        await websocket.accept()
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
async def tunnel_connect(websocket: WebSocket) -> None:
    await _tunnel_adapter.handle_websocket(websocket)


@router.get("/api/v1/admin/tunnel/status")
async def tunnel_status() -> dict[str, Any]:
    return _tunnel_adapter.get_status()
