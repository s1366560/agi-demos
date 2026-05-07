"""Tests for the inbound WS payload size limiter (P2-20)."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.infrastructure.adapters.primary.web.websocket._limits import (
    MAX_INBOUND_MESSAGE_BYTES,
    InboundMessageTooLarge,
    receive_json_with_limit,
)


def _make_websocket(text: str) -> Any:
    ws = AsyncMock()
    ws.receive_text = AsyncMock(return_value=text)
    return ws


@pytest.mark.unit
async def test_default_limit_is_1_mib() -> None:
    assert MAX_INBOUND_MESSAGE_BYTES == 1 << 20


@pytest.mark.unit
async def test_returns_parsed_object_for_valid_payload() -> None:
    ws = _make_websocket(json.dumps({"type": "ping", "id": "x"}))
    parsed = await receive_json_with_limit(ws)
    assert parsed == {"type": "ping", "id": "x"}


@pytest.mark.unit
async def test_raises_when_payload_exceeds_limit() -> None:
    payload = "a" * 1024
    ws = _make_websocket(payload)
    with pytest.raises(InboundMessageTooLarge) as exc:
        await receive_json_with_limit(ws, max_bytes=512)
    assert exc.value.size == 1024
    assert exc.value.limit == 512


@pytest.mark.unit
async def test_oversized_payload_is_not_parsed() -> None:
    # If the message is too large we MUST short-circuit before parsing.
    # That is the whole point — we cannot afford to JSON-parse arbitrarily
    # large attacker-controlled input.
    payload = "{" + ("x" * 4096) + "}"
    ws = _make_websocket(payload)
    with pytest.raises(InboundMessageTooLarge):
        await receive_json_with_limit(ws, max_bytes=128)


@pytest.mark.unit
async def test_invalid_json_raises_decode_error() -> None:
    ws = _make_websocket("not-json{{{")
    with pytest.raises(json.JSONDecodeError):
        await receive_json_with_limit(ws)


@pytest.mark.unit
async def test_top_level_array_is_rejected() -> None:
    ws = _make_websocket(json.dumps([1, 2, 3]))
    with pytest.raises(json.JSONDecodeError):
        await receive_json_with_limit(ws)


@pytest.mark.unit
async def test_top_level_scalar_is_rejected() -> None:
    ws = _make_websocket(json.dumps("hello"))
    with pytest.raises(json.JSONDecodeError):
        await receive_json_with_limit(ws)


@pytest.mark.unit
async def test_payload_at_limit_is_accepted() -> None:
    # Exactly at the limit must succeed; the limit is inclusive of the
    # accepted size and exclusive of the rejected size.
    obj = {"k": "v" * 100}
    text = json.dumps(obj)
    ws = _make_websocket(text)
    parsed = await receive_json_with_limit(ws, max_bytes=len(text.encode("utf-8")))
    assert parsed == obj


@pytest.mark.unit
async def test_unicode_size_counted_by_utf8_bytes() -> None:
    # 4-byte emoji should count as 4 bytes against the limit.
    obj = {"msg": "😀😀😀"}  # 12 utf-8 bytes for the emoji content
    text = json.dumps(obj, ensure_ascii=False)
    ws = _make_websocket(text)
    encoded_size = len(text.encode("utf-8"))
    with pytest.raises(InboundMessageTooLarge):
        await receive_json_with_limit(ws, max_bytes=encoded_size - 1)
