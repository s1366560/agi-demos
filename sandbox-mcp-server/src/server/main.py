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


def setup_signal_handlers(
    server: MCPWebSocketServer,
    session_manager: "SessionManager | None",
    loop: asyncio.AbstractEventLoop,
) -> None:
    """Setup signal handlers for graceful shutdown."""

    def signal_handler(sig):
        logger.info(f"Received signal {sig}, shutting down...")
        loop.create_task(_shutdown(server, session_manager))

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda s=sig: signal_handler(s))
        except NotImplementedError:
            # Windows doesn't support add_signal_handler
            signal.signal(sig, lambda s, f: signal_handler(s))


async def _shutdown(
    server: MCPWebSocketServer,
    session_manager: "SessionManager | None",
) -> None:
    """Perform graceful shutdown."""
    # Stop MCP server first
    await server.stop()

    # Stop sessions if manager exists
    if session_manager:
        await session_manager.stop_all()


async def run_server(
    host: str = "0.0.0.0",
    port: int = 8765,
    workspace_dir: str = "/workspace",
    terminal_port: int = 7681,
    desktop_port: int = 6080,
    terminal_enabled: bool = True,
    desktop_enabled: bool = True,
    auto_start_sessions: bool = False,
) -> None:
    """
    Run the MCP WebSocket server.

    Args:
        host: Host to bind to
        port: Port to listen on
        workspace_dir: Root directory for file operations
        terminal_port: Port for web terminal
        desktop_port: Port for noVNC desktop
        terminal_enabled: Whether to enable terminal sessions
        desktop_enabled: Whether to enable desktop sessions
        auto_start_sessions: Whether to auto-start sessions on server start
    """
    # Import tools here to avoid circular imports
    from src.tools.registry import get_tool_registry

    # Import session manager
    from src.server.session_manager import SessionManager

    # Create session manager
    session_manager = SessionManager(
        workspace_dir=workspace_dir,
        terminal_port=terminal_port,
        desktop_port=desktop_port,
        terminal_enabled=terminal_enabled,
        desktop_enabled=desktop_enabled,
    )

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
    setup_signal_handlers(server, session_manager, loop)

    # Start server
    await server.start()

    # Auto-start sessions if requested
    if auto_start_sessions:
        logger.info("Auto-starting sessions...")
        try:
            await session_manager.start_all()
        except Exception as e:
            logger.error(f"Failed to auto-start sessions: {e}")

    logger.info(f"Server running on ws://{host}:{port}")
    logger.info(f"Workspace directory: {workspace_dir}")

    if terminal_enabled:
        logger.info(f"Terminal available at ws://{host}:{terminal_port}")
    if desktop_enabled:
        logger.info(f"Desktop available at http://{host}:{desktop_port}/vnc.html")

    logger.info("Press Ctrl+C to stop")

    # Wait for shutdown
    await server.wait_closed()

    # Ensure sessions are stopped
    await session_manager.stop_all()


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
        "--terminal-port",
        type=int,
        default=int(os.getenv("TERMINAL_PORT", "7681")),
        help="Port for web terminal (default: 7681)",
    )
    parser.add_argument(
        "--desktop-port",
        type=int,
        default=int(os.getenv("DESKTOP_PORT", "6080")),
        help="Port for noVNC desktop (default: 6080)",
    )
    parser.add_argument(
        "--no-terminal",
        action="store_true",
        help="Disable web terminal",
    )
    parser.add_argument(
        "--no-desktop",
        action="store_true",
        help="Disable remote desktop",
    )
    parser.add_argument(
        "--auto-start-sessions",
        action="store_true",
        help="Auto-start terminal and desktop sessions on server start",
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
                terminal_port=args.terminal_port,
                desktop_port=args.desktop_port,
                terminal_enabled=not args.no_terminal,
                desktop_enabled=not args.no_desktop,
                auto_start_sessions=args.auto_start_sessions,
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
