"""Main entry point for CUA MCP WebSocket server."""

import argparse
import asyncio
import logging
import os
import signal

from server.websocket_server import MCPWebSocketServer
from tools.registry import get_tool_registry

logger = logging.getLogger(__name__)


def setup_signal_handlers(server: MCPWebSocketServer, loop: asyncio.AbstractEventLoop) -> None:
    def signal_handler(sig):
        logger.info("Received signal %s, shutting down...", sig)
        loop.create_task(server.stop())

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda s=sig: signal_handler(s))
        except NotImplementedError:
            signal.signal(sig, lambda s, f: signal_handler(s))


async def run_server(host: str, port: int) -> None:
    server = MCPWebSocketServer(host=host, port=port)

    registry = get_tool_registry()
    server.register_tools(registry.get_all_tools())

    logger.info("Registered %d tools", len(registry.get_all_tools()))

    loop = asyncio.get_event_loop()
    setup_signal_handlers(server, loop)

    await server.start()
    logger.info("Server running on ws://%s:%s", host, port)

    await server.wait_closed()


def main() -> int:
    parser = argparse.ArgumentParser(description="CUA MCP Server")
    parser.add_argument(
        "--host",
        default=os.getenv("CUA_MCP_HOST", "0.0.0.0"),
        help="Host to bind to",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("CUA_MCP_PORT", "18766")),
        help="Port to listen on",
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    try:
        asyncio.run(run_server(args.host, args.port))
        return 0
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        logger.error("Server error: %s", exc, exc_info=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
