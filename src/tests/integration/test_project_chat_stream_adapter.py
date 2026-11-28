"""Run the signed chat adapter through canonical Agent bindings and a real loopback SSE provider."""

import asyncio
import base64
import json
import os
import shutil
import socket
import subprocess
from contextlib import aclosing, asynccontextmanager
from pathlib import Path
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from memstack_plugin_sdk.pack import build
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.domain.llm_providers.llm_types import LLMConfig
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentRunAuthorityModel,
    Conversation,
)
from src.infrastructure.agent.core.llm_stream import LLMStream, StreamConfig
from src.infrastructure.agent.core.project_package_tools import bind_project_packages
from src.infrastructure.llm.litellm.litellm_client import LiteLLMClient
from src.infrastructure.llm.litellm.unified_llm_client import UnifiedLLMClient
from src.infrastructure.persistence.llm_providers_models import LLMProvider, TenantProviderMapping
from src.infrastructure.persistence.llm_providers_repository import SQLAlchemyProviderRepository
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_IDENTITY_SERVICE_V2,
    bind_operation_context_v2,
)
from src.infrastructure.plugins.v2.runtime import OperationContextV2
from src.infrastructure.plugins.v2.tool_set import bind_operation_tool_set_catalog_v2
from src.infrastructure.security.encryption_service import get_encryption_service
from src.tests.unit.infrastructure.plugins.v2.test_runtime import (
    _definition,
    _entry,
    _loader,
    _snapshot,
)
from src.tests.unit.routers.test_optional_business_http_v2 import (
    http as _http,
    publisher as _publisher,
)

http = _http
publisher = _publisher
pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]
ROOT = Path(__file__).resolve().parents[3] / "plugins/adapters/models/openai"
PLUGIN = "memstack-openai-chat"
SCOPE = {"tenant_id": "t", "project_id": "p"}
BASE = "/api/v1/platform-plugins/v2/optional-business"
PERMISSIONS = ["tools.execute", "model.chat.adapt.openai"]


@pytest.fixture(scope="module")
def releases(tmp_path_factory):
    if os.getenv("CHAT_ADAPTER_RUST_TESTS") != "1":
        pytest.skip("set CHAT_ADAPTER_RUST_TESTS=1 to compile the independent Wasm upgrade")
    key = Ed25519PrivateKey.generate()
    trusted = (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    old = build(ROOT / "package.json", key)
    work = tmp_path_factory.mktemp("independent-chat-adapter")
    shutil.copytree(ROOT, work / "publisher")
    manifest = work / "publisher/Cargo.toml"
    manifest.write_text(
        manifest.read_text().replace(
            "../../../../sdk/memstack-plugin-sdk/rust/chat-stream",
            str(ROOT.parents[3] / "sdk/memstack-plugin-sdk/rust/chat-stream"),
        )
    )
    source = work / "publisher/src/lib.rs"
    code = source.read_text()
    assert "else { 2048 }" in code and "publish_reasoning: false" in code
    source.write_text(
        code.replace("else { 2048 }", "else { 512 }").replace(
            "publish_reasoning: false",
            "publish_reasoning: true",
        )
    )
    release = work / "publisher/package.json"
    release.write_text(json.dumps({**json.loads(release.read_bytes()), "version": "2.0.0"}))
    subprocess.run(
        [
            "cargo",
            "build",
            "--release",
            "--locked",
            "--offline",
            "--target",
            "wasm32-unknown-unknown",
        ],
        cwd=source.parent.parent,
        env={**os.environ, "CARGO_TARGET_DIR": str(work / "target")},
        check=True,
        capture_output=True,
    )
    shutil.copyfile(
        work / "target/wasm32-unknown-unknown/release/memstack_openai_chat.wasm",
        work / "publisher/adapter.wasm",
    )
    new = build(release, key)
    alternate = {**json.loads(release.read_bytes()), "plugin_id": "another-chat-adapter"}
    release.write_text(json.dumps(alternate))
    return trusted, old, new, build(release, key), build(ROOT.parent / "deepseek/package.json", key)


@pytest.fixture
async def upstream(monkeypatch):
    connect = socket.socket.connect

    def loopback_only(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            assert address[0] in {"127.0.0.1", "::1"}
        return connect(sock, address)

    monkeypatch.setattr(socket.socket, "connect", loopback_only)
    received = []
    sent = asyncio.Event()
    resume = asyncio.Event()
    closed = asyncio.Event()

    async def serve(reader, writer):
        header = (await reader.readuntil(b"\r\n\r\n")).decode()
        fields = {
            s.split(":", 1)[0].lower(): s.split(":", 1)[1].strip()
            for s in header.split("\r\n")[1:]
            if ":" in s
        }
        body = json.loads(await reader.readexactly(int(fields["content-length"])))
        received.append((body, fields["authorization"] == "Bearer local-chat-fixture"))

        def chunk(delta, finish=None):
            return (
                "data: "
                + json.dumps(
                    {
                        "id": "fixture",
                        "model": body["model"],
                        "created": 1,
                        "object": "chat.completion.chunk",
                        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
                    }
                )
                + "\n\n"
            ).encode()

        try:
            writer.write(
                b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nConnection: close\r\n\r\n"
            )
            writer.write(
                chunk(
                    {
                        "role": "assistant",
                        "reasoning_content": "explicit thought",
                        "content": "first",
                    }
                )
            )
            await writer.drain()
            sent.set()
            if body["messages"][-1]["content"] == "pause":
                pending = asyncio.create_task(reader.read(1))
                go = asyncio.create_task(resume.wait())
                try:
                    done, _ = await asyncio.wait(
                        (pending, go), timeout=10, return_when=asyncio.FIRST_COMPLETED
                    )
                    if pending in done:
                        closed.set()
                        return
                finally:
                    for task in (pending, go):
                        task.cancel()
                    await asyncio.gather(pending, go, return_exceptions=True)
            writer.write(chunk({"content": "last"}, "stop") + b"data: [DONE]\n\n")
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    try:
        yield (
            f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}/v1",
            received,
            sent,
            resume,
            closed,
        )
    finally:
        resume.set()
        server.close()
        await server.wait_closed()


@pytest.fixture
async def project(http, db_session, releases):
    assert str(db_session.get_bind().url) == "sqlite+aiosqlite:///:memory:"
    client, actors = http
    key = releases[0]
    client._transport.app.state.plugin_marketplace_trusted_public_keys_v2 = (key,)
    db_session.add(
        Conversation(id="session", tenant_id="t", project_id="p", user_id="owner", title="fixture")
    )
    await db_session.flush()
    for name in ("unconfigured", "old", "new", "rolled", "viewer", "disabled"):
        db_session.add(
            AgentRunAuthorityModel(
                id=name,
                tenant_id="t",
                project_id="p",
                conversation_id="session",
                run_kind="chat",
                idempotency_key=name,
                message_id=name,
                request_message="neutral",
                status="running",
                permission_profile="full_access",
                authorization_snapshot={},
            )
        )
    await db_session.commit()
    sessions = async_sessionmaker(db_session.bind, expire_on_commit=False)
    entry = _entry("root", "builtin://runtime/root")
    snapshot = _snapshot(1, (entry,))
    generation = await _loader(
        snapshot, [_definition(snapshot, entry.module_ref, lambda *_: None)]
    ).stage(snapshot)

    async def post(method, payload=None, expected=200):
        r = await client.post(
            BASE + method,
            json={**SCOPE, **(payload or {})},
            headers={"Authorization": f"Bearer {actors['owner']}"},
        )
        assert r.status_code == expected, r.text

    async def install(raw, permissions=PERMISSIONS, expected=200, plugin=PLUGIN, enable_status=200):
        await post(
            "/install",
            {"archive_base64": base64.b64encode(raw).decode(), "approved_permissions": permissions},
            expected,
        )
        if expected == 200:
            await post("/" + plugin + "/enable", expected=enable_status)

    @asynccontextmanager
    async def turn(run, actor="owner"):
        async with OperationContextV2(
            generation=generation,
            operation_id=run,
            scope=ScopeV2(
                kind=ScopeKindV2.SESSION, tenant_id="t", project_id="p", session_id="session"
            ),
        ) as op:
            with bind_operation_context_v2(op):
                op.provide(OPERATION_IDENTITY_SERVICE_V2, {"user_id": actor})
                capabilities = await bind_project_packages(
                    op, bind_operation_tool_set_catalog_v2(op), run, sessions, trusted_keys=(key,)
                )
                assert not capabilities.tools
                yield

    yield install, post, turn
    await generation.dispose()


async def model(db, url, tenant="t", provider_type="openai", model_name="gpt-4o-mini"):
    provider_id = uuid4()
    db.add(
        LLMProvider(
            id=provider_id,
            name="loopback-" + tenant,
            provider_type=provider_type,
            operation_type="llm",
            api_key_encrypted=get_encryption_service().encrypt("local-chat-fixture"),
            llm_model=model_name,
            base_url=url,
            config={},
        )
    )
    await db.flush()
    db.add(
        TenantProviderMapping(
            id=uuid4(), tenant_id=tenant, provider_id=provider_id, operation_type="llm"
        )
    )
    await db.commit()
    provider = await SQLAlchemyProviderRepository(db).get_by_id(provider_id)
    # Pool resolution returns platform-scoped configs. Tenant authorization consults the persisted mapping.
    assert provider and provider.tenant_id == "default"
    return UnifiedLLMClient(LiteLLMClient(LLMConfig(model=model_name), provider, cache=False))


def stream(client, prompt="neutral"):
    return LLMStream(
        StreamConfig(model="gpt-4o-mini", max_tokens=6000), llm_client=client
    ).generate([{"role": "user", "content": prompt}])


@pytest.mark.parametrize("http", ["full"], indirect=True)
async def test_signed_chat_adapter_pins_real_model_request_and_stream(
    project, upstream, releases, db_session
):
    url, seen, *_ = upstream
    install, post, turn = project
    _, old, new, alternate, _ = releases
    transport = await model(db_session, url)

    async def result(limit, reasoning):
        events = [e async for e in stream(transport)]
        assert [e.data["delta"] for e in events if e.type == "text_delta"] == ["first", "last"], (
            events
        )
        assert [e.data["delta"] for e in events if e.type == "reasoning_delta"] == (
            ["explicit thought"] if reasoning else []
        )
        assert events[-1].type == "finish"
        request, trusted = seen[-1]
        assert (
            trusted
            and request["max_tokens"] == limit
            and request["messages"] == [{"role": "user", "content": "neutral"}]
        )

    async with turn("unconfigured"):
        await result(6000, True)
    await install(old, ["tools.execute"], 400)
    await install(old)
    await install(alternate, plugin="another-chat-adapter", enable_status=409)
    async with turn("old"):
        await result(2048, False)
        await install(new)
        async with turn("new"):
            await result(512, True)
        await result(2048, False)
    async with turn("old"):
        await result(2048, False)
    await post("/" + PLUGIN + "/rollback")
    async with turn("rolled"):
        await result(2048, False)
        count = len(seen)
        assert [e.type async for e in stream(await model(db_session, url, "another-tenant"))] == [
            "error"
        ]
        assert len(seen) == count
    async with turn("viewer", actor="viewer"):
        assert [e.type async for e in stream(transport)] == ["error"]
        assert len(seen) == count
    await post("/" + PLUGIN + "/disable")
    async with turn("old"):
        assert [e.type async for e in stream(transport)] == ["error"]
        assert len(seen) == count
    async with turn("disabled"):
        await result(6000, True)


@pytest.mark.parametrize("http", ["full"], indirect=True)
async def test_cancel_and_project_withdrawal_end_model_stream(
    project, upstream, releases, db_session
):
    url, _, sent, resume, closed = upstream
    install, post, turn = project
    await install(releases[1])
    transport = await model(db_session, url)
    async with turn("old"), aclosing(stream(transport, "pause")) as source:
        async for e in source:
            if e.type == "text_delta":
                break
        assert sent.is_set()
    await asyncio.wait_for(closed.wait(), timeout=3)
    sent.clear()
    closed.clear()

    async def consume():
        async with turn("old"), aclosing(stream(transport, "pause")) as source:
            async for _ in source:
                pass

    pending = asyncio.create_task(consume())
    await asyncio.wait_for(sent.wait(), timeout=3)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    await asyncio.wait_for(closed.wait(), timeout=3)
    async with turn("old"), aclosing(stream(transport, "pause")) as source:
        async for e in source:
            if e.type == "text_delta":
                break
        await post("/" + PLUGIN + "/disable")
        resume.set()
        remaining = [e async for e in source]
        assert [e.type for e in remaining] == ["error"]


@pytest.mark.parametrize("http", ["full"], indirect=True)
async def test_provider_assignment_withdrawal_cuts_off_admitted_stream(
    project, upstream, releases, db_session
):
    url, seen, _, resume, _ = upstream
    install, _, turn = project
    await install(releases[1])
    transport = await model(db_session, url)
    async with turn("old"), aclosing(stream(transport, "pause")) as source:
        async for event in source:
            if event.type == "text_delta":
                break
        # Removing the final assignment must not turn the pooled row into an unrestricted provider.
        await db_session.execute(
            delete(TenantProviderMapping).where(TenantProviderMapping.tenant_id == "t")
        )
        await db_session.commit()
        resume.set()
        assert [event.type async for event in source] == ["error"]
        assert [event.type async for event in stream(transport)] == ["error"]
        assert len(seen) == 1


@pytest.mark.parametrize("http", ["full"], indirect=True)
async def test_deepseek_tool_round_keeps_provider_reasoning(
    project, upstream, releases, db_session
):
    url, seen, *_ = upstream
    install, post, turn = project
    await install(releases[1])
    await install(
        releases[4],
        permissions=["tools.execute", "model.chat.adapt.deepseek"],
        plugin="memstack-deepseek-chat",
    )
    transport = await model(db_session, url, provider_type="deepseek", model_name="deepseek-chat")
    tools = [
        {
            "type": "function",
            "function": {
                "name": "lookup",
                "description": "Look up a record",
                "parameters": {"type": "object"},
            },
        }
    ]
    async with turn("old"):
        await post("/" + PLUGIN + "/disable")
        source = LLMStream(
            StreamConfig(model="deepseek-chat", max_tokens=6000, tools=tools), llm_client=transport
        ).generate([{"role": "user", "content": "neutral"}])
        events = [event async for event in source]
    assert [event.data["delta"] for event in events if event.type == "reasoning_delta"] == [
        "explicit thought"
    ], events
    assert events[-1].type == "finish"
    wire, authenticated = seen[0]
    assert (
        authenticated
        and wire["max_tokens"] == 4096
        and wire["tools"][0]["function"]["name"] == "lookup"
    )
