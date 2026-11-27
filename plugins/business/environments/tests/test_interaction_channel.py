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


async def test_socket_uses_a_host_ticket_instead_of_the_caller_bearer(monkeypatch):
    from fastapi import FastAPI

    from src.host.operations.sandbox_proxy_ticket import user_for_sandbox_proxy_ticket

    app = FastAPI()
    ctx = SimpleNamespace(
        request=SimpleNamespace(app=app, headers={"Authorization": "Bearer caller-secret"}),
        user=SimpleNamespace(id="user-1"),
        scope=SimpleNamespace(project_id="p", tenant_id="t"),
    )
    captured: dict[str, object] = {}

    async def fake_connect(_url, **kwargs):  # type: ignore[no-untyped-def]
        captured["headers"] = kwargs["additional_headers"]
        return AsyncMock()

    monkeypatch.setattr(channel, "connect", fake_connect)
    monkeypatch.setattr(
        channel,
        "get_settings",
        lambda: SimpleNamespace(project_sandbox_authority_url=None, api_port=8000),
    )
    await channel._socket(ctx, "/terminal/proxy/ws", [], "ephemeral=true")
    header = captured["headers"]["Authorization"]
    assert isinstance(header, str)
    assert header.startswith("Bearer ms_sk_")
    assert "caller-secret" not in header
    token = header.removeprefix("Bearer ")
    assert user_for_sandbox_proxy_ticket(app, token) == "user-1"
    from src.infrastructure.adapters.primary.web.dependencies.auth_dependencies import (
        verify_api_key_from_header_query_or_cookie,
    )

    admitted = await verify_api_key_from_header_query_or_cookie(
        SimpleNamespace(scope={"app": app}), api_key=token
    )
    assert admitted is not None
    assert admitted.user_id == "user-1"


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
