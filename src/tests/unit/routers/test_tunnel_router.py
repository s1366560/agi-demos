from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

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
async def test_tunnel_connect_rejects_missing_auth_before_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    websocket = _FakeWebSocket()
    adapter = SimpleNamespace(handle_websocket=AsyncMock())
    monkeypatch.setattr(router_mod, "_tunnel_adapter", adapter)

    await router_mod.tunnel_connect(websocket, token=None, db=SimpleNamespace())

    assert websocket.accepted is False
    assert websocket.closed is True
    assert websocket.close_code == 4003
    adapter.handle_websocket.assert_not_awaited()


@pytest.mark.unit
async def test_tunnel_connect_preserves_authenticated_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    websocket = _FakeWebSocket()
    adapter = SimpleNamespace(handle_websocket=AsyncMock())
    monkeypatch.setattr(router_mod, "_tunnel_adapter", adapter)
    monkeypatch.setattr(
        router_mod,
        "authenticate_websocket_or_close",
        AsyncMock(return_value=("user-1", "tenant-1")),
    )

    await router_mod.tunnel_connect(websocket, token=None, db=SimpleNamespace())

    adapter.handle_websocket.assert_awaited_once_with(websocket, subprotocol=None)


@pytest.mark.unit
async def test_tunnel_status_rejects_non_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        router_mod,
        "has_global_admin_access",
        AsyncMock(return_value=False),
    )

    with pytest.raises(HTTPException) as exc_info:
        await router_mod.tunnel_status(
            SimpleNamespace(is_superuser=False, roles=[]),
            SimpleNamespace(),
        )

    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.unit
async def test_tunnel_status_hides_connection_identifiers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        router_mod,
        "has_global_admin_access",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        router_mod,
        "_tunnel_adapter",
        SimpleNamespace(
            get_status=lambda: {
                "active_connections": 1,
                "connection_ids": ["sensitive-connection-id"],
            }
        ),
    )

    result = await router_mod.tunnel_status(
        SimpleNamespace(is_superuser=True, roles=[]),
        SimpleNamespace(),
    )

    assert result == {"active_connections": 1}
