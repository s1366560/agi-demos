"""Use the public authenticated MCP bridge with a dynamically discovered Python worker."""

import asyncio
import json
import os
import sys

from aiohttp import ClientSession

from src.server.websocket_server import AuthConfig, MCPWebSocketServer
from src.tools import mcp_management

# A stand-alone worker knows only the JSON-lines MCP protocol.
WORKER = """
import json, os, sys
from pathlib import Path
def send(value):
    print(json.dumps({"jsonrpc": "2.0", **value}), flush=True)
pending = {}
for line in sys.stdin:
    req = json.loads(line)
    method = req["method"]
    params = req.get("params", {})
    if method == "initialize":
        result = {"protocolVersion": params["protocolVersion"], "capabilities": {"tools": {}}}
    elif method == "tools/list":
        result = {"tools": [{"name": "scan", "description": "Scan a project", "inputSchema": {"type":"object"}}]}
    elif method == "tools/call":
        label = params["arguments"]["label"]
        if label.startswith("wait-"):
            pending[req["id"]] = label
            send({"method": "notifications/progress", "params": {
                "progressToken": params["_meta"]["progressToken"], "message": label, "progress": 1}})
            continue
        if label == "release":
            for request_id, label in list(pending.items()):
                send({"id": request_id, "result": {"content": [{"type": "text", "text": label}]}})
                del pending[request_id]
        result = {"content": [{"type": "text", "text": json.dumps({
            "isolated": os.getpid(), "grant": os.getenv("WORKER_GRANTED"),
            "inherited": "TEST_SANDBOX_CONTROL_AUTH" in os.environ})}]}
    elif method == "notifications/cancelled":
        Path("cancel-" + pending.pop(params["requestId"])).touch()
        continue
    else:
        continue
    send({"id": req["id"], "result": result})
"""


async def call(ws, key, name, args, token=None):
    params = {"name": name, "arguments": args}
    if token:
        params["_meta"] = {"progressToken": token}
    await ws.send_json({"jsonrpc": "2.0", "id": key, "method": "tools/call", "params": params})


def scan(label):
    return {"server_name": "worker", "tool_name": "scan", "arguments": {"label": label}}


async def test_authenticated_stdio_worker_progress_cancel_and_stop(tmp_path, monkeypatch):
    (tmp_path / "worker.py").write_text(WORKER)
    monkeypatch.setenv("TEST_SANDBOX_CONTROL_AUTH", "private-to-sandbox")
    monkeypatch.setattr(mcp_management, "_manager", None)
    server = MCPWebSocketServer(
        host="127.0.0.1",
        port=0,
        workspace_dir=str(tmp_path),
        auth_config=AuthConfig(static_token="fixture-capability"),
    )
    server.register_tools(
        [
            mcp_management.create_mcp_server_install_tool(),
            mcp_management.create_mcp_server_start_tool(),
            mcp_management.create_mcp_server_discover_tools_tool(),
            mcp_management.create_mcp_server_call_tool_tool(),
            mcp_management.create_mcp_server_stop_tool(),
        ]
    )
    args = {
        "name": "worker",
        "server_type": "stdio",
        "transport_config": {
            "command": sys.executable,
            "args": ["worker.py"],
            "env": {"WORKER_GRANTED": "yes"},
        },
    }
    await server.start()
    url = f"ws://127.0.0.1:{server._runner.addresses[0][1]}"
    try:
        async with (
            asyncio.timeout(10),
            ClientSession(headers={"Authorization": "Bearer fixture-capability"}) as session,
            session.ws_connect(url) as a,
            session.ws_connect(url) as b,
        ):
            for key, name in enumerate(("mcp_server_install", "mcp_server_start"), 1):
                await call(a, key, name, args.copy())
                assert not (await a.receive_json())["result"]["isError"]
            await call(a, 3, "mcp_server_discover_tools", {"name": "worker"})
            result = (await a.receive_json())["result"]
            assert json.loads(result["content"][0]["text"])[0]["name"] == "scan"

            await call(a, 4, "mcp_server_call_tool", scan("check"))
            result = json.loads((await a.receive_json())["result"]["content"][0]["text"])
            assert result["isolated"] != os.getpid()
            assert result["grant"] == "yes"
            assert result["inherited"] is False

            for ws, label in [(a, "wait-a"), (b, "wait-b")]:
                await call(ws, 7, "mcp_server_call_tool", scan(label), "same-client-token")
                assert (await ws.receive_json())["params"] == {
                    "progressToken": "same-client-token",
                    "progress": 1,
                    "message": label,
                }
            await a.send_json(
                {
                    "jsonrpc": "2.0",
                    "method": "notifications/cancelled",
                    "params": {"requestId": 7},
                }
            )
            while not (tmp_path / "cancel-wait-a").exists():
                await asyncio.sleep(0.01)
            assert not (tmp_path / "cancel-wait-b").exists()
            await call(a, 9, "mcp_server_call_tool", scan("release"))
            assert not (await a.receive_json())["result"]["isError"]
            result = await b.receive_json()
            assert result["id"] == 7 and result["result"]["content"][0]["text"] == "wait-b"

            # One socket can drain its worker and still cancel its previously admitted call.
            await call(a, 8, "mcp_server_call_tool", scan("wait-drain"), "progress")
            assert (await a.receive_json())["params"]["message"] == "wait-drain"
            await call(a, 10, "mcp_server_stop", {"name": "worker"})
            while True:
                await call(b, 11, "mcp_server_call_tool", scan("check"))
                if (await b.receive_json())["result"]["isError"]:
                    break
            await a.send_json(
                {
                    "jsonrpc": "2.0",
                    "method": "notifications/cancelled",
                    "params": {"requestId": 8},
                }
            )
            assert not (await a.receive_json())["result"]["isError"]
            await call(a, 11, "mcp_server_call_tool", scan("check"))
            assert (await a.receive_json())["result"]["isError"]
    finally:
        if mcp_management._manager is not None:
            await mcp_management._manager.shutdown()
        await server.stop()
