from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from starlette.datastructures import Headers
from starlette.websockets import WebSocketDisconnect

from src.infrastructure.adapters.primary.web.routers import security_ws as router_mod


class _FakeWebSocket:
    def __init__(self, headers: list[tuple[bytes, bytes]] | None = None) -> None:
        self.headers = Headers(raw=headers or [])
        self.accepted = False
        self.closed = False
        self.close_code: int | None = None
        self.accepted_subprotocol: str | None = None

    async def accept(self, subprotocol: str | None = None) -> None:
        self.accepted = True
        self.accepted_subprotocol = subprotocol

    async def close(self, code: int | None = None, reason: str | None = None) -> None:
        self.closed = True
        self.close_code = code


@pytest.mark.unit
async def test_security_ws_rejects_missing_auth_before_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    websocket = _FakeWebSocket()
    pipeline = AsyncMock()
    monkeypatch.setattr(router_mod, "get_pipeline", pipeline)

    await router_mod.security_ws(websocket, token=None, db=SimpleNamespace())

    assert websocket.accepted is False
    assert websocket.closed is True
    assert websocket.close_code == 4003
    pipeline.assert_not_called()


@pytest.mark.unit
async def test_security_ws_preserves_authenticated_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    websocket = _FakeWebSocket([(b"sec-websocket-protocol", b"memstack.auth, ms_sk_valid")])
    receive = AsyncMock(side_effect=WebSocketDisconnect())
    monkeypatch.setattr(
        router_mod,
        "authenticate_websocket_or_close",
        AsyncMock(return_value=("user-1", "tenant-1")),
    )
    monkeypatch.setattr(router_mod, "receive_json_with_limit", receive)

    await router_mod.security_ws(websocket, token=None, db=SimpleNamespace())

    assert websocket.accepted is True
    assert websocket.accepted_subprotocol == "memstack.auth"
    assert websocket.closed is False
    receive.assert_awaited_once_with(websocket)
