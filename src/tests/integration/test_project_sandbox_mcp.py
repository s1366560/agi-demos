"""Run project MCP discovery and calls through the gateway and an authenticated sandbox socket."""

import asyncio
import json
import os
import secrets
import socket
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
import websockets
from fastapi import FastAPI, WebSocket
from starlette.websockets import WebSocketDisconnect

from src.infrastructure.adapters.secondary.persistence.models import (
    Project,
    Tenant,
    UserProject,
    UserTenant,
)
from src.tests.integration import package_gateway
from src.tests.unit.routers import test_optional_business_http_v2 as package_api

http = package_api.http
publisher = package_api.publisher
gateway_binary = package_gateway.gateway_binary
pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[3]


@asynccontextmanager
async def sandbox_authority(tmp_path, users):
    # Separate cloud upstream fixture vouches only its sandbox runtime token, as on the Rust server.
    with socket.socket() as port_socket:
        port_socket.bind(("127.0.0.1", 0))
        port = port_socket.getsockname()[1]
    capability = secrets.token_urlsafe(32)
    directory = ROOT / "plugins/business/environments/sandbox-mcp-server"
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "src.server.main",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--workspace",
        str(tmp_path),
        "--no-terminal",
        "--no-desktop",
        cwd=directory,
        env={
            "PATH": os.environ["PATH"],
            "PYTHONPATH": str(directory),
            "MCP_STATIC_TOKEN": capability,
            "MCP_TOOLSETS": "files",
            "MCP_AUTH_ENABLED": "true",
            "MCP_ALLOW_LOCALHOST": "false",
        },
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    server = FastAPI()
    relayed = []

    @server.websocket("/api/v1/projects/{project}/sandbox/mcp/proxy")
    async def transport(ws: WebSocket, project: str):
        protocols = ws.headers.get("sec-websocket-protocol", "").split(", ")
        actor = ws.headers.get("authorization", "").removeprefix("Bearer ")
        if not actor and "memstack.auth" in protocols:
            actor = protocols[protocols.index("memstack.auth") + 1]
        if project not in {"p", "isolated"} or actor not in users.values():
            await ws.close(code=1008)
            return
        async with websockets.connect(
            f"ws://127.0.0.1:{port}/",
            additional_headers={"Authorization": "Bearer " + capability},
            proxy=None,
        ) as upstream:
            await ws.accept(subprotocol="memstack.auth" if "memstack.auth" in protocols else None)
            try:
                while True:
                    data = await ws.receive_text()
                    relayed.append(json.loads(data))
                    await upstream.send(data)
                    if "id" in relayed[-1]:
                        await ws.send_text(await upstream.recv())
            except WebSocketDisconnect:
                pass

    try:
        async with httpx.AsyncClient() as probe, asyncio.timeout(10):
            while True:
                if process.returncode is not None:
                    pytest.fail("sandbox MCP server exited before startup")
                try:
                    if (await probe.get(f"http://127.0.0.1:{port}/health")).is_success:
                        break
                except httpx.TransportError:
                    pass
                await asyncio.sleep(0.05)
        yield server, relayed
    finally:
        if process.returncode is None:
            process.terminate()
        await process.wait()


async def rpc(ws, seq, method, params):
    await ws.send(json.dumps({"jsonrpc": "2.0", "id": seq, "method": method, "params": params}))
    async with asyncio.timeout(6):
        result = json.loads(await ws.recv())
    assert result["id"] == seq
    return result


async def initialize(ws):
    handshake = await rpc(
        ws,
        0,
        "initialize",
        {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "1"},
        },
    )
    assert "serverInfo" in handshake["result"]
    await ws.send(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}))


async def verify_foreign_scope(client, origin, users, publisher, db_session):
    db_session.add(Tenant(id="foreign", name="Foreign", slug="isolated", owner_id="viewer"))
    await db_session.flush()
    db_session.add(Project(id="isolated", tenant_id="foreign", name="Other", owner_id="viewer"))
    await db_session.flush()
    db_session.add(
        UserTenant(id="foreign-owner", user_id="viewer", tenant_id="foreign", role="owner")
    )
    db_session.add(
        UserProject(id="other-owner", user_id="viewer", project_id="isolated", role="owner")
    )
    await db_session.commit()
    base = "/api/v1/platform-plugins/v2/optional-business"
    owner = {"Authorization": "Bearer " + users["viewer"]}
    scope = {"tenant_id": "foreign", "project_id": "isolated"}
    body, _ = publisher[1]("1.0.0", result="away")
    (await client.post(base + "/install", headers=owner, json=body | scope)).raise_for_status()
    (await client.post(base + "/sample.notes/enable", headers=owner, json=scope)).raise_for_status()
    path = base + "/sandbox-mcp/projects/isolated/tools"
    own_tools = await client.get(path, headers=owner)
    own_tools.raise_for_status()
    (handle,) = [tool["name"] for tool in own_tools.json()["tools"]]
    async with websockets.connect(
        origin + "/api/v1/projects/isolated/sandbox/mcp/proxy",
        subprotocols=["memstack.auth", users["owner"]],
        proxy=None,
    ) as foreign:
        await initialize(foreign)
        tools = (await rpc(foreign, 1, "tools/list", {"project_id": "p", "tenant_id": "t"}))[
            "result"
        ]["tools"]
        assert tools and all(not tool["name"].startswith("pkg_") for tool in tools)
        denied = await rpc(foreign, 2, "tools/call", {"name": handle, "arguments": {"op": "ping"}})
        assert "error" in denied


async def test_unknown_package_tools_follow_live_project_authority(
    http, publisher, tmp_path, gateway_binary, db_session
):
    backend, users = http
    app = backend._transport.app
    headers = {"Authorization": "Bearer " + users["owner"]}
    async with (
        sandbox_authority(tmp_path, users) as (sandbox, relayed),
        package_gateway.gateway_client(gateway_binary, app, rust_app=sandbox) as client,
    ):
        origin = str(client.base_url).rstrip("/").replace("http://", "ws://")
        async with websockets.connect(
            origin + "/api/v1/projects/p/sandbox/mcp/proxy",
            subprotocols=["memstack.auth", users["owner"]],
            proxy=None,
        ) as ws:
            await initialize(ws)
            local = (await rpc(ws, 1, "tools/list", {}))["result"]["tools"]
            assert local and all(not row["name"].startswith("pkg_") for row in local)
            native = await rpc(ws, 20, "tools/call", {"name": "list", "arguments": {"path": "."}})
            assert native["result"]["content"] and not native["result"].get("isError", False)
            scope = {"tenant_id": "t", "project_id": "p"}
            base = "/api/v1/platform-plugins/v2/optional-business"

            async def install(version, value):
                body, _ = publisher[1](version, result=value)
                (
                    await client.post(base + "/install", headers=headers, json=body)
                ).raise_for_status()
                (
                    await client.post(base + "/sample.notes/enable", headers=headers, json=scope)
                ).raise_for_status()

            async def discover(i):
                tools = (await rpc(ws, i, "tools/list", {}))["result"]["tools"]
                return [t for t in tools if t["name"].startswith("pkg_")]

            async def call(i, name):
                return await rpc(ws, i, "tools/call", {"name": name, "arguments": {"op": "ping"}})

            await install("1.0.0", "ping")
            await verify_foreign_scope(client, origin, users, publisher, db_session)
            (first,) = await discover(2)
            assert first["inputSchema"]["type"] == "object"
            assert (await call(3, first["name"]))["result"]["structuredContent"]["op"] == "ping"
            await install("1.1.0", "pong")
            assert "error" in await call(4, first["name"])
            (second,) = await discover(5)
            assert second["name"] != first["name"]
            assert (await call(6, second["name"]))["result"]["structuredContent"]["op"] == "pong"
            (
                await client.post(base + "/sample.notes/rollback", headers=headers, json=scope)
            ).raise_for_status()
            (restored,) = await discover(30)
            assert restored["name"] != first["name"] and "error" in await call(31, first["name"])
            assert (await call(32, restored["name"]))["result"]["structuredContent"]["op"] == "ping"
            (
                await client.post(base + "/sample.notes/disable", headers=headers, json=scope)
            ).raise_for_status()
            assert "error" in await call(7, restored["name"])
            assert await discover(8) == []
            (
                await client.post(base + "/sample.notes/enable", headers=headers, json=scope)
            ).raise_for_status()
            (third,) = await discover(9)
            assert third["name"] != restored["name"] and "error" in await call(10, restored["name"])
            membership = await db_session.get(UserProject, "up-owner")
            membership.role = "viewer"
            await db_session.commit()
            assert "error" in await call(11, third["name"])
            forged = await rpc(
                ws,
                21,
                "tools/call",
                {
                    "name": third["name"],
                    "arguments": {"op": "ping"},
                    "user_id": "owner",
                    "role": "admin",
                    "tenant_id": "t",
                },
            )
            assert "error" in forged
            assert await discover(12) == []
            assert not any(
                row.get("params", {}).get("name", "").startswith("pkg_") for row in relayed
            )
