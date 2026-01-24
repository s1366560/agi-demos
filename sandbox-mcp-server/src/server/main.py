"""Main entry point for sandbox MCP server."""

import argparse
import asyncio
import logging
import os
import signal
import sys

from .websocket_server import MCPWebSocketServer

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def setup_signal_handlers(server: MCPWebSocketServer, loop: asyncio.AbstractEventLoop) -> None:
    """Setup signal handlers for graceful shutdown."""

    def signal_handler(sig):
        logger.info(f"Received signal {sig}, shutting down...")
        loop.create_task(server.stop())

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda s=sig: signal_handler(s))
        except NotImplementedError:
            # Windows doesn't support add_signal_handler
            signal.signal(sig, lambda s, f: signal_handler(s))


async def run_server(
    host: str = "0.0.0.0",
    port: int = 8765,
    workspace_dir: str = "/workspace",
) -> None:
    """
    Run the MCP WebSocket server.

    Args:
        host: Host to bind to
        port: Port to listen on
        workspace_dir: Root directory for file operations
    """
    # Import tools here to avoid circular imports
    from src.tools.registry import get_tool_registry

    # Create server
    server = MCPWebSocketServer(
        host=host,
        port=port,
        workspace_dir=workspace_dir,
    )

    # Register all tools
    registry = get_tool_registry(workspace_dir)
    server.register_tools(registry.get_all_tools())

    logger.info(f"Registered {len(registry.get_all_tools())} tools")

    # Setup signal handlers
    loop = asyncio.get_event_loop()
    setup_signal_handlers(server, loop)

    # Start server
    await server.start()

    logger.info(f"Server running on ws://{host}:{port}")
    logger.info(f"Workspace directory: {workspace_dir}")
    logger.info("Press Ctrl+C to stop")

    # Wait for shutdown
    await server.wait_closed()


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Sandbox MCP Server")
    parser.add_argument(
        "--host",
        default=os.getenv("MCP_HOST", "0.0.0.0"),
        help="Host to bind to (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("MCP_PORT", "8765")),
        help="Port to listen on (default: 8765)",
    )
    parser.add_argument(
        "--workspace",
        default=os.getenv("MCP_WORKSPACE", "/workspace"),
        help="Workspace directory (default: /workspace)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    # Ensure workspace exists
    os.makedirs(args.workspace, exist_ok=True)

    try:
        asyncio.run(
            run_server(
                host=args.host,
                port=args.port,
                workspace_dir=args.workspace,
            )
        )
        return 0
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        return 0
    except Exception as e:
        logger.error(f"Server error: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
