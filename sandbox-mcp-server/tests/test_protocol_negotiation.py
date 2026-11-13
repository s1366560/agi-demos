"""Sandbox MCP initialize accepts supported revisions and rejects the rest."""

from __future__ import annotations

import asyncio

from src.mcp_protocol import LATEST_PROTOCOL_VERSION
from src.server.websocket_server import MCPWebSocketServer


def test_initialize_negotiates_the_offered_revision_and_discover_lists_it() -> None:
    server = MCPWebSocketServer(auth_config=None)

    async def run() -> None:
        negotiated = await server._handle_initialize(
            {
                "protocolVersion": LATEST_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "probe", "version": "1"},
            }
        )
        assert negotiated["protocolVersion"] == "2026-07-28"
        assert set(negotiated["capabilities"]) == {"tools", "resources", "prompts"}
        assert "tasks" not in negotiated["capabilities"]
        discovered = await server._dispatch_method("server/discover", {})
        assert "2026-07-28" in discovered["protocolVersions"]
        assert "2024-11-05" in discovered["protocolVersions"]
        legacy = await server._handle_initialize(
            {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {}}
        )
        assert legacy["protocolVersion"] == "2024-11-05"
        rejected = await server._handle_message(
            {
                "jsonrpc": "2.0",
                "id": 7,
                "method": "initialize",
                "params": {"protocolVersion": "1999-01-01", "capabilities": {}},
            }
        )
        assert rejected["error"]["code"] == -32602
        assert "unsupported_protocol_version" in rejected["error"]["message"]

    asyncio.run(run())
