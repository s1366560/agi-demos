"""CUA MCP Stdio Server.

Provides CUA tools over MCP JSON-RPC via stdin/stdout. This allows
CUA to run as an MCP service similar to the sandbox (codebox) MCP server,
while using stdio transport for local execution.
"""

import asyncio
import json
import logging
import sys
from dataclasses import dataclass
from typing import Any, Dict, Optional

from src.configuration.cua_factory import CUAFactory
from src.infrastructure.agent.cua.config import CUAConfig

logger = logging.getLogger(__name__)


@dataclass
class MCPServerInfo:
    """MCP server information."""

    name: str = "cua-mcp-server"
    version: str = "0.1.0"
    protocol_version: str = "2024-11-05"


class CUAMCPServer:
    """Minimal MCP server for exposing CUA tools over stdio."""

    def __init__(self) -> None:
        self._server_info = MCPServerInfo()
        self._factory = CUAFactory(CUAConfig.from_env())
        self._tools: Dict[str, Any] = {}
        self._initialized = False

    async def _ensure_initialized(self) -> None:
        if self._initialized:
            return

        if not self._factory.is_enabled:
            logger.warning("CUA is disabled; MCP server will expose no tools")
            self._tools = {}
            self._initialized = True
            return

        await self._factory.initialize()
        self._tools = self._factory.create_tools()
        self._initialized = True
        logger.info("CUA MCP server initialized with %d tools", len(self._tools))

    async def initialize(self) -> Dict[str, Any]:
        await self._ensure_initialized()
        return {
            "serverInfo": {
                "name": self._server_info.name,
                "version": self._server_info.version,
            },
            "protocolVersion": self._server_info.protocol_version,
            "capabilities": {
                "tools": {},
            },
        }

    async def list_tools(self) -> Dict[str, Any]:
        await self._ensure_initialized()

        tools = []
        for name, tool in self._tools.items():
            input_schema = {}
            if hasattr(tool, "get_parameters_schema"):
                input_schema = tool.get_parameters_schema()
            tools.append(
                {
                    "name": name,
                    "description": getattr(tool, "description", ""),
                    "inputSchema": input_schema
                    or {"type": "object", "properties": {}, "required": []},
                }
            )
        return {"tools": tools}

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        await self._ensure_initialized()

        tool = self._tools.get(name)
        if not tool:
            return {
                "content": [{"type": "text", "text": f"Unknown tool: {name}"}],
                "isError": True,
            }

        try:
            result = await tool.safe_execute(**arguments)
            return {
                "content": [{"type": "text", "text": result}],
                "isError": False,
            }
        except Exception as exc:
            logger.error("CUA MCP tool error: %s", exc, exc_info=True)
            return {
                "content": [{"type": "text", "text": f"Error: {exc}"}],
                "isError": True,
            }


async def _handle_request(
    server: CUAMCPServer, request: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    method = request.get("method")
    params = request.get("params", {})
    request_id = request.get("id")

    # Notifications (no id) don't require response
    if request_id is None and method:
        return None

    try:
        if method == "initialize":
            result = await server.initialize()
        elif method == "tools/list":
            result = await server.list_tools()
        elif method == "tools/call":
            result = await server.call_tool(
                name=params.get("name", ""),
                arguments=params.get("arguments", {}) or {},
            )
        else:
            raise ValueError(f"Unsupported method: {method}")

        return {"jsonrpc": "2.0", "result": result, "id": request_id}
    except Exception as exc:
        logger.error("CUA MCP server error: %s", exc, exc_info=True)
        return {
            "jsonrpc": "2.0",
            "error": {"code": -32603, "message": str(exc)},
            "id": request_id,
        }


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    server = CUAMCPServer()

    while True:
        line = await asyncio.to_thread(sys.stdin.readline)
        if not line:
            break
        line = line.strip()
        if not line:
            continue

        try:
            request = json.loads(line)
        except json.JSONDecodeError as exc:
            response = {
                "jsonrpc": "2.0",
                "error": {"code": -32700, "message": f"Parse error: {exc}"},
                "id": None,
            }
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()
            continue

        response = await _handle_request(server, request)
        if response is not None:
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
