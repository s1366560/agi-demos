"""Exercise the production voice socket against project mutations and PostgreSQL."""

import asyncio
import json
import socket
from types import SimpleNamespace
from urllib.parse import urlencode

import httpx
import pytest
import uvicorn
import websockets
from fastapi import FastAPI

from src.infrastructure.adapters.primary.web.routers import voice_websocket
from src.infrastructure.adapters.secondary.external.volcengine import (
    asr_streaming_client,
    speech_credentials,
)
from src.tests.integration.marketplace_browser import business_release
from src.tests.integration.test_original_agent_web_layout import conversation, owner
from src.tests.integration.test_signed_agent_voice import change_installation

__all__ = ["conversation", "owner"]
pytestmark = pytest.mark.integration


def observe_provider(monkeypatch):
    captured = []
    receiving, release = asyncio.Event(), asyncio.Event()

    class ObservedASR:
        def __init__(self, *_args, **_kwargs):
            pass

        async def connect(self):
            pass

        async def send_audio(self, data, *, is_last):
            captured.append(data)
            if data:
                receiving.set()
                await release.wait()

        async def receive(self):
            await asyncio.Future()

        async def close(self):
            pass

    monkeypatch.setattr(asr_streaming_client, "AsyncASRStreamingClient", ObservedASR)
    monkeypatch.setattr(
        speech_credentials,
        "resolve_speech_credentials",
        lambda *_: SimpleNamespace(app_id="test", access_token="test"),
    )
    return captured, receiving, release


def issue_ticket(api, owner, scope, conversation):
    market = "/platform-plugins/v2/optional-business"
    token = api.post(
        "/auth/token", data={"username": owner["email"], "password": owner["password"]}
    ).json()["access_token"]
    api.headers["authorization"] = "Bearer " + token
    detail = api.get(
        market + "/npm/detail",
        params={
            **scope,
            "plugin_id": "memstack-agent",
            "package_name": "@memstack/agent",
            "version": business_release("agent"),
        },
    )
    detail.raise_for_status()
    digest = detail.json()["installation"]["actual_digest"]
    issued = api.post(
        market + "/memstack-agent/commands",
        json={
            **scope,
            "command_id": "chat-voice-authorize",
            "expected_digest": digest,
            "payload": {"conversation_id": conversation},
        },
    )
    issued.raise_for_status()
    assert "ticket" in issued.json()
    ticket = issued.json()["ticket"]
    return token, ticket


async def assert_denied(socket_url, config, protocols):
    async with websockets.connect(socket_url, subprotocols=protocols) as client:
        await client.send(json.dumps(config))
        assert json.loads(await client.recv())["message"] == "voice_grant_revoked"
        await client.wait_closed()
        assert client.close_code == 4003


def voice_server():
    app = FastAPI()
    app.include_router(voice_websocket.router)
    return uvicorn.Server(uvicorn.Config(app, access_log=False, log_level="critical"))


async def test_package_disable_cuts_existing_voice_socket_off_at_provider(
    owner, conversation, monkeypatch
):
    assert owner["project_name"] == "Shared Agent voice QA"
    captured, receiving, release = observe_provider(monkeypatch)
    scope = {key: owner[key] for key in ("tenant_id", "project_id")}
    server = voice_server()
    with (
        socket.socket() as listener,
        httpx.Client(base_url="http://127.0.0.1:8000/api/v1", timeout=30, trust_env=False) as api,
    ):
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        token, ticket = issue_ticket(api, owner, scope, conversation)
        query = urlencode({"project_id": scope["project_id"], "conversation_id": conversation})
        url = f"ws://127.0.0.1:{listener.getsockname()[1]}/api/v1/voice/chat?{query}"
        protocols = ["memstack.auth", token]
        server_task = asyncio.create_task(server.serve(sockets=[listener]))
        restore = False
        try:
            async with asyncio.timeout(10):
                while not server.started:
                    await asyncio.sleep(0.02)

            config = {"type": "voice_config", "mode": "dictation", "package_ticket": ticket}
            bound = url + "&package_session=1"
            await assert_denied(url, config, protocols)
            await assert_denied(bound, {"type": "voice_config"}, protocols)
            await assert_denied(bound, {**config, "package_ticket": "invalid"}, protocols)
            async with websockets.connect(bound, subprotocols=protocols) as client:
                await client.send(json.dumps(config))
                await client.send(b"admitted")
                await asyncio.wait_for(receiving.wait(), 5)
                disabling = asyncio.create_task(
                    asyncio.to_thread(change_installation, api, scope, "disable")
                )
                restore = True
                try:
                    await asyncio.sleep(0.1)
                    assert not disabling.done()
                finally:
                    release.set()
                    await disabling
                await client.send(b"revoked")
                assert json.loads(await client.recv())["message"] == "voice_grant_revoked"
                await client.wait_closed()
                assert client.close_code == 4003
            await asyncio.to_thread(change_installation, api, scope, "enable")
            restore = False
            await assert_denied(bound, config, protocols)
            assert captured == [b"admitted"]
        finally:
            release.set()
            if restore:
                await asyncio.to_thread(change_installation, api, scope, "enable")
            server.should_exit = True
            await asyncio.wait_for(server_task, 10)
