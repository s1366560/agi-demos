"""Tests for WebSocket authentication helpers."""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast
from unittest.mock import ANY, AsyncMock

import pytest
from starlette.datastructures import Headers
from starlette.websockets import WebSocket

from src.infrastructure.adapters.primary.web.websocket import auth as auth_module
from src.infrastructure.adapters.primary.web.websocket.auth import (
    authenticate_websocket_or_close,
    extract_websocket_api_key,
    select_websocket_auth_subprotocol,
)


def _websocket_with_headers(headers: list[tuple[bytes, bytes]]) -> WebSocket:
    return cast(WebSocket, SimpleNamespace(headers=Headers(raw=headers)))


def test_extract_websocket_api_key_accepts_subprotocol_token() -> None:
    websocket = _websocket_with_headers(
        [(b"sec-websocket-protocol", b"memstack.auth, ms_sk_protocol_token")]
    )

    assert extract_websocket_api_key(websocket) == "ms_sk_protocol_token"


def test_select_websocket_auth_subprotocol_when_offered() -> None:
    websocket = _websocket_with_headers(
        [(b"sec-websocket-protocol", b"memstack.auth, ms_sk_protocol_token")]
    )

    assert select_websocket_auth_subprotocol(websocket) == "memstack.auth"


def test_select_websocket_auth_subprotocol_rejects_token_only() -> None:
    websocket = _websocket_with_headers([(b"sec-websocket-protocol", b"ms_sk_protocol_token")])

    assert select_websocket_auth_subprotocol(websocket) is None


def test_extract_websocket_api_key_prefers_authorization_header() -> None:
    websocket = _websocket_with_headers(
        [
            (b"authorization", b"Bearer ms_sk_header_token"),
            (b"sec-websocket-protocol", b"memstack.auth, ms_sk_protocol_token"),
        ]
    )

    assert extract_websocket_api_key(websocket, "ms_sk_query_token") == "ms_sk_header_token"


def test_extract_websocket_api_key_keeps_query_fallback() -> None:
    websocket = _websocket_with_headers([])

    assert extract_websocket_api_key(websocket, "ms_sk_query_token") == "ms_sk_query_token"


def test_extract_websocket_api_key_rejects_missing_token() -> None:
    websocket = _websocket_with_headers([(b"sec-websocket-protocol", b"memstack.auth")])

    assert extract_websocket_api_key(websocket) is None


@pytest.mark.unit
async def test_authenticate_websocket_or_close_rejects_missing_token_before_accept() -> None:
    websocket = SimpleNamespace(
        headers=Headers(raw=[]),
        close=AsyncMock(),
        accept=AsyncMock(),
    )

    result = await authenticate_websocket_or_close(websocket, SimpleNamespace())

    assert result is None
    websocket.close.assert_awaited_once_with(code=4003, reason="Authentication failed")
    websocket.accept.assert_not_awaited()


@pytest.mark.unit
async def test_authenticate_websocket_or_close_preserves_valid_principal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    websocket = SimpleNamespace(
        headers=Headers(raw=[(b"authorization", b"Bearer ms_sk_valid")]),
        close=AsyncMock(),
    )
    authenticate = AsyncMock(return_value=("user-1", "tenant-1"))
    monkeypatch.setattr(auth_module, "authenticate_websocket", authenticate)

    result = await authenticate_websocket_or_close(websocket, SimpleNamespace())

    assert result == ("user-1", "tenant-1")
    authenticate.assert_awaited_once_with("ms_sk_valid", ANY)
    websocket.close.assert_not_awaited()


@pytest.mark.unit
async def test_authenticate_websocket_or_close_rejects_invalid_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    websocket = SimpleNamespace(
        headers=Headers(raw=[(b"authorization", b"Bearer ms_sk_invalid")]),
        close=AsyncMock(),
        accept=AsyncMock(),
    )
    monkeypatch.setattr(
        auth_module,
        "authenticate_websocket",
        AsyncMock(return_value=None),
    )

    result = await authenticate_websocket_or_close(websocket, SimpleNamespace())

    assert result is None
    websocket.close.assert_awaited_once_with(code=4003, reason="Authentication failed")
    websocket.accept.assert_not_awaited()
