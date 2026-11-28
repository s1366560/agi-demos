"""Disconnects can interrupt an ASGI body send while its iterator is suspended at yield."""

import asyncio

import pytest
from starlette.requests import ClientDisconnect

from src.infrastructure.adapters.primary.web.routers.optional_business_http_v2 import (
    _InvocationStream,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("asgi_version", ["2.3", "2.4"])
async def test_disconnect_during_body_send_closes_producer(asgi_version):
    started = asyncio.Event()
    cleaned = asyncio.Event()

    async def events():
        try:
            yield b'{"type":"progress"}\n'
            await asyncio.Future()
        finally:
            await asyncio.sleep(0)
            cleaned.set()

    async def receive():
        await started.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        if message["type"] == "http.response.body":
            started.set()
            if asgi_version == "2.4":
                raise OSError("peer closed")
            await asyncio.Future()

    response = _InvocationStream(events())
    scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": asgi_version}}
    async with asyncio.timeout(2):
        if asgi_version == "2.4":
            with pytest.raises(ClientDisconnect):
                await response(scope, receive, send)
        else:
            await response(scope, receive, send)
    assert cleaned.is_set()
