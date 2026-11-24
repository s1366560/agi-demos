"""Project channels bind each interaction to its admitted release, user and permission epoch."""

import asyncio
import base64
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from plugins.business.environments.backend import interaction_channel as channel
from src.host.packages.release_pin import ACTIVE_APPLICATION_PIN, AgentPackagePin
from src.infrastructure.plugins.v2.signed_optional_business_v2 import OptionalBusinessError

pytestmark = pytest.mark.unit


@pytest.fixture
def session(monkeypatch):
    scope = SimpleNamespace(tenant_id="t", project_id="p")
    ctx = SimpleNamespace(user=SimpleNamespace(id="u"), scope=scope)
    pin = AgentPackagePin(
        tenant_id="t",
        project_id="p",
        plugin_id="memstack-environments",
        version="1.5.0",
        digest="sha256:" + "0" * 64,
        authorization_epoch=3,
    )
    token = ACTIVE_APPLICATION_PIN.set(pin)
    socket = AsyncMock()
    monkeypatch.setattr(channel, "_connect", AsyncMock(return_value=socket))
    monkeypatch.setattr(channel, "_channels", channel.Channels())
    try:
        yield ctx, pin, socket
    finally:
        ACTIVE_APPLICATION_PIN.reset(token)


async def test_desktop_bytes_split_without_loss_and_channel_closes(session):
    ctx, _, socket = session
    data = b"v" * (channel.CHUNK_SIZE + 4)
    socket.recv.return_value = data
    handle = await channel.project_desktop(ctx, {"action": "open"}, None)
    chunks = [
        await channel.project_desktop(ctx, {"action": "read", **handle}, None) for _ in range(2)
    ]
    assert b"".join(base64.b64decode(c["data"]) for c in chunks) == data
    await channel.project_desktop(ctx, {"action": "write", **handle, "data": "YWJj"}, None)
    socket.send.assert_awaited_once_with(b"abc")
    await channel.project_desktop(ctx, {"action": "close", **handle}, None)
    await asyncio.sleep(0)
    socket.close.assert_awaited_once()


async def test_invalid_socket_destination_and_cross_authority_are_rejected(session):
    ctx, pin, socket = session
    with pytest.raises(ValidationError):
        await channel.project_desktop(ctx, {"action": "open", "url": "ws://elsewhere"}, None)
    handle = await channel.project_terminal(ctx, {"action": "open"}, None)
    read = {"action": "read", **handle}
    with pytest.raises(OptionalBusinessError):
        await channel.project_desktop(ctx, read, None)
    for update in (
        {"project_id": "other"},
        {"tenant_id": "other"},
        {"digest": "other"},
        {"authorization_epoch": 4},
    ):
        token = ACTIVE_APPLICATION_PIN.set(replace(pin, **update))
        try:
            with pytest.raises(OptionalBusinessError):
                await channel.project_terminal(ctx, read, None)
        finally:
            ACTIVE_APPLICATION_PIN.reset(token)
    ctx.user.id = "other"
    with pytest.raises(OptionalBusinessError):
        await channel.project_terminal(ctx, read, None)
    socket.recv.assert_not_awaited()
    ctx.user.id = "u"
    await channel.project_terminal(ctx, {"action": "close", **handle}, None)
