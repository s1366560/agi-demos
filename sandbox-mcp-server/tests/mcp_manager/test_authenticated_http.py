"""Authenticated HTTP transports retain credentials and remote liveness."""

import pytest
from aiohttp import web

from src.mcp_manager.manager import MCPServerManager


@pytest.mark.asyncio
async def test_remote_http_headers_cover_initialize_discover_call_and_resource():
    seen = []

    async def handle(request):
        assert request.headers.get("Authorization") == "Bearer test-fixture-only"
        data = await request.json()
        seen.append(data["method"])
        if "id" not in data:
            return web.Response(status=202)
        result = {
            "initialize": {"serverInfo": {"name": "test"}},
            "tools/list": {
                "tools": [
                    {
                        "name": "echo",
                        "inputSchema": {},
                        "_meta": {"ui": {"resourceUri": "ui://test"}},
                    }
                ]
            },
            "tools/call": {"content": [{"type": "text", "text": "accepted"}]},
            "resources/read": {"contents": [{"uri": "ui://test", "text": "app"}]},
        }[data["method"]]
        return web.json_response({"jsonrpc": "2.0", "id": data["id"], "result": result})

    app = web.Application()
    app.router.add_post("/mcp", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    manager = MCPServerManager()
    try:
        result = await manager.start_server(
            "authenticated",
            "http",
            {
                "url": f"http://127.0.0.1:{port}/mcp",
                "headers": {"Authorization": "Bearer test-fixture-only"},
            },
        )
        assert result["success"]
        tools = await manager.discover_tools("authenticated")
        assert tools[0]["_meta"]["ui"]["resourceUri"] == "ui://test"
        result = await manager.call_tool("authenticated", "echo", {})
        assert not result["isError"]
        resource = await manager.read_resource("authenticated", "ui://test")
        assert resource == "app"
        await manager._send_http_notification("authenticated", "notifications/initialized")
        assert {
            "initialize",
            "notifications/initialized",
            "tools/list",
            "tools/call",
            "resources/read",
        }.issubset(seen)
        server = manager._tracker.get_server("authenticated")
        assert "Authorization" not in server.to_dict()
        assert "test-fixture-only" not in repr(server)
    finally:
        if manager._http_session is not None:
            await manager._http_session.close()
        await runner.cleanup()
