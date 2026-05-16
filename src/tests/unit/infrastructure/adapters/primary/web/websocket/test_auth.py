"""Tests for WebSocket authentication helpers."""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast

from starlette.datastructures import Headers
from starlette.websockets import WebSocket

from src.infrastructure.adapters.primary.web.websocket.auth import (
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
