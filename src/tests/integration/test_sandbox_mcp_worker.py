"""A worker admitted through project MCP keeps its release and follows socket cancellation."""

import asyncio
import base64
import json
import os
from io import BytesIO
from zipfile import ZipFile

import pytest
import websockets
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.configuration.config import get_settings
from src.infrastructure.adapters.primary.web.routers.auth import revoke_api_key
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import APIKey, User
from src.tests.integration import package_gateway, test_project_sandbox_mcp as sandbox_client
from src.tests.integration.test_oci_mcp_worker_docker import disposable_worker_registry
from src.tests.unit.routers import test_optional_business_http_v2 as package_api

http = package_api.http
publisher = package_api.publisher
gateway_binary = package_gateway.gateway_binary
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.getenv("OCI_WORKER_DOCKER_TESTS") != "1", reason="requires Docker"),
]
BASE = "/api/v1/platform-plugins/v2/optional-business"
SCOPE = {"tenant_id": "t", "project_id": "p"}
TOOL = {
    "name": "calculate",
    "abi": "mcp.stdio",
    "permissions": ["tools.execute"],
    "input_schema": {
        "type": "object",
        "properties": {"delay": {"type": "integer", "minimum": 0, "maximum": 25}},
        "additionalProperties": False,
    },
    "output_schema": {
        "type": "object",
        "properties": {"release": {"type": "string"}},
        "required": ["release"],
    },
}
WORKER = """#!/usr/local/bin/python
import json, sys, time
for line in sys.stdin:
    message = json.loads(line)
    method, params = message['method'], message.get('params', {})
    if method == 'initialize':
        result = {'protocolVersion': params['protocolVersion'], 'capabilities': {'tools': {}}}
    elif method == 'tools/list':
        result = {'tools': [{'name': TOOL['name'], 'inputSchema': TOOL['input_schema'], 'outputSchema': TOOL['output_schema']}]}
    elif method == 'tools/call':
        time.sleep(params['arguments'].get('delay', 0))
        result = {'structuredContent': {'release': VERSION}}
    else:
        continue
    print(json.dumps({'jsonrpc':'2.0', 'id':message['id'], 'result':result}), flush=True)
"""


@pytest.fixture(scope="module")
def workers(tmp_path_factory):
    from memstack_plugin_sdk.pack import build

    path = tmp_path_factory.mktemp("sandbox-project-release")
    (path / "Dockerfile").write_text("FROM python:3.12-alpine\nCOPY worker /app/worker\n")
    (path / "contributions.json").write_text(
        json.dumps(
            {
                "schema": "memstack.plugin.contributions/1",
                "tools": [TOOL],
            }
        )
    )
    signer = Ed25519PrivateKey.generate()
    key = (
        signer.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    packages = []
    with disposable_worker_registry() as (publish, registry, engine):
        for version in ("1.0.0", "1.1.0"):
            exe = path / "worker"
            exe.write_text(WORKER.replace("TOOL", repr(TOOL)).replace("VERSION", repr(version)))
            exe.chmod(0o755)
            (path / "worker.json").write_text(
                json.dumps(
                    {
                        "schema": "memstack.mcp-oci-worker/1",
                        "image": publish(path),
                        "entrypoint": "/app/worker",
                    }
                )
            )
            cfg = path / "package.json"
            cfg.write_text(
                json.dumps(
                    {
                        "plugin_id": "sandbox.test",
                        "tool_name": "calculate",
                        "target": "python",
                        "version": version,
                        "worker": "worker.json",
                        "contribution": "contributions.json",
                        "provenance": "repo://qa",
                    }
                )
            )
            content = build(cfg, signer)
            with ZipFile(BytesIO(content)) as archive:
                digest = json.loads(archive.read("bundle.json"))["digest"]
            packages.append(
                (
                    digest,
                    {
                        **SCOPE,
                        "approved_permissions": ["tools.execute"],
                        "archive_base64": base64.b64encode(content).decode(),
                    },
                )
            )
        yield packages, key, registry, engine


async def activate(client, owner, package):
    (await client.post(BASE + "/install", headers=owner, json=package)).raise_for_status()
    (await client.post(BASE + "/sandbox.test/enable", headers=owner, json=SCOPE)).raise_for_status()


async def worker_state(engine, digest, *, running):
    async with asyncio.timeout(8):
        while True:
            rows = await asyncio.to_thread(
                engine.api.containers,
                all=not running,
                filters={"label": "memstack.release=" + digest},
            )
            if bool(rows) is running:
                return
            await asyncio.sleep(0.05)


async def alias(ws, seq):
    tools = (await sandbox_client.rpc(ws, seq, "tools/list", {}))["result"]["tools"]
    (tool,) = [row["name"] for row in tools if row["name"].startswith("pkg_")]
    return tool


async def start_call(ws, seq, name, delay):
    await ws.send(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": seq,
                "method": "tools/call",
                "params": {"name": name, "arguments": {"delay": delay}},
            }
        )
    )


async def revoke_during_call(ws, sessions, engine, digest, current):
    await start_call(ws, 52, current, 2)
    await worker_state(engine, digest, running=True)
    async with sessions() as db:
        owner = await db.get(User, "owner")
        key_id = await db.scalar(select(APIKey.id).where(APIKey.user_id == owner.id))
        await revoke_api_key(key_id, owner, db)
    async with asyncio.timeout(8):
        denied = json.loads(await ws.recv())
    assert denied["id"] == 52 and "error" in denied
    listing = await sandbox_client.rpc(ws, 53, "tools/list", {})
    assert not any(tool["name"].startswith("pkg_") for tool in listing["result"]["tools"])


async def test_upgrade_keeps_admitted_guest_and_cancellation_reaps_only_its_worker(
    gateway_binary,
    http,
    workers,
    tmp_path,
    test_engine,
    monkeypatch,
):
    (first, second), key, registry, engine = workers
    backend, users = http
    app = backend._transport.app
    app.state.plugin_marketplace_trusted_public_keys_v2 = (key,)
    monkeypatch.setattr(get_settings(), "plugin_worker_allowed_registries", (registry,))
    sessions = async_sessionmaker(test_engine, expire_on_commit=False)

    async def database():
        async with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = database
    owner = {"Authorization": "Bearer " + users["owner"]}
    async with (
        sandbox_client.sandbox_authority(tmp_path, users) as (sandbox, relayed),
        package_gateway.gateway_client(gateway_binary, app, rust_app=sandbox) as client,
    ):
        await activate(client, owner, first[1])
        origin = str(client.base_url).rstrip("/").replace("http://", "ws://")
        async with websockets.connect(
            origin + "/api/v1/projects/p/sandbox/mcp/proxy", additional_headers=owner, proxy=None
        ) as ws:
            await sandbox_client.initialize(ws)
            old = await alias(ws, 10)
            await start_call(ws, 40, old, 4)
            await worker_state(engine, first[0], running=True)
            await activate(client, owner, second[1])
            async with asyncio.timeout(8):
                finished = json.loads(await ws.recv())
            assert (
                finished["id"] == 40
                and finished["result"]["structuredContent"]["release"] == "1.0.0"
            )
            current = await alias(ws, 11)
            assert current != old
            await start_call(ws, 50, current, 25)
            await worker_state(engine, second[0], running=True)
            await ws.send(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "method": "notifications/cancelled",
                        "params": {"requestId": 50},
                    }
                )
            )
            await worker_state(engine, second[0], running=False)
            result = await sandbox_client.rpc(
                ws, 51, "tools/call", {"name": current, "arguments": {}}
            )
            assert result["result"]["structuredContent"]["release"] == "1.1.0"
            await revoke_during_call(ws, sessions, engine, second[0], current)
            assert not any(
                req.get("method") in {"notifications/cancelled", "tools/call"} for req in relayed
            )
