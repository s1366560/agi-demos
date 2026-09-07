from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException, status
from starlette.datastructures import Headers

from src.infrastructure.adapters.primary.web.routers import tunnel as router_mod


class _FakeWebSocket:
    def __init__(self) -> None:
        self.headers = Headers(raw=[])
        self.accepted = False
        self.closed = False
        self.close_code: int | None = None

    async def accept(self, subprotocol: str | None = None) -> None:
        self.accepted = True

    async def close(self, code: int | None = None, reason: str | None = None) -> None:
        self.closed = True
        self.close_code = code


@pytest.mark.unit
async def test_tunnel_connect_rejects_missing_auth_before_adapter() -> None:
    websocket = _FakeWebSocket()

    await router_mod.tunnel_connect(websocket, tunnel=None)

    assert websocket.accepted is False
    assert websocket.closed is False


@pytest.mark.unit
async def test_tunnel_connect_preserves_authenticated_connection() -> None:
    websocket = _FakeWebSocket()
    authority = SimpleNamespace(connect=AsyncMock())

    await router_mod.tunnel_connect(websocket, tunnel=authority)

    authority.connect.assert_awaited_once_with(websocket)


@pytest.mark.unit
async def test_tunnel_status_rejects_non_admin() -> None:
    authority = SimpleNamespace(
        status=Mock(
            side_effect=HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin access required",
            )
        )
    )

    with pytest.raises(HTTPException) as exc_info:
        await router_mod.tunnel_status(tunnel=authority)

    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.unit
async def test_tunnel_status_hides_connection_identifiers() -> None:
    authority = SimpleNamespace(
        status=Mock(return_value={"active_connections": 1}),
    )

    result = await router_mod.tunnel_status(tunnel=authority)

    assert result == {"active_connections": 1}
