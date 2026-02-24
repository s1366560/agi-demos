"""MCP OAuth Callback HTTP Server.

This module provides a simple HTTP server for handling OAuth callbacks
from MCP servers during the authorization code flow.

The server runs on port 19876 and handles the /mcp/oauth/callback endpoint.

Based on vendor/opencode/packages/opencode/src/mcp/oauth-callback.ts
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiohttp import web

logger = logging.getLogger(__name__)

# HTML templates
HTML_SUCCESS = """<!DOCTYPE html>
<html>
<head>
  <title>MemStack - Authorization Successful</title>
  <style>
    body { font-family: system-ui, -apple-system, sans-serif; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; background: #1a1a2e; color: #eee; }
    .container { text-align: center; padding: 2rem; }
    h1 { color: #4ade80; margin-bottom: 1rem; }
    p { color: #aaa; }
  </style>
</head>
<body>
  <div class="container">
    <h1>Authorization Successful</h1>
    <p>You can close this window and return to MemStack.</p>
  </div>
  <script>setTimeout(() => window.close(), 2000);</script>
</body>
</html>"""

HTML_ERROR = """<!DOCTYPE html>
<html>
<head>
  <title>MemStack - Authorization Failed</title>
  <style>
    body { font-family: system-ui, -apple-system, sans-serif; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; background: #1a1a2e; color: #eee; }
    .container { text-align: center; padding: 2rem; }
    h1 { color: #f87171; margin-bottom: 1rem; }
    p { color: #aaa; }
    .error { color: #fca5a5; font-family: monospace; margin-top: 1rem; padding: 1rem; background: rgba(248,113,113,0.1); border-radius: 0.5rem; }
  </style>
</head>
<body>
  <div class="container">
    <h1>Authorization Failed</h1>
    <p>An error occurred during authorization.</p>
    <div class="error">{error}</div>
  </div>
</body>
</html>"""

CALLBACK_TIMEOUT_MS = 5 * 60 * 1000  # 5 minutes
CALLBACK_PATH = "/mcp/oauth/callback"


class PendingAuth:
    """Pending OAuth authorization."""

    def __init__(
        self,
        resolve: Callable[[str], None],
        reject: Callable[[Exception], None],
        timeout_handle: asyncio.Handle,
    ) -> None:
        self.resolve = resolve
        self.reject = reject
        self.timeout_handle = timeout_handle


class MCPOAuthCallbackServer:
    """OAuth callback HTTP server for MCP authorization flow.

    Handles OAuth callbacks from MCP servers, validates state parameters,
    and resolves pending authorization promises.
    """

    def __init__(self, port: int = 19876) -> None:
        """Initialize OAuth callback server.

        Args:
            port: Port to listen on (default: 19876)
        """
        self._port = port
        self._app: web.Application | None = None
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self._pending_auths: dict[str, PendingAuth] = {}

    @property
    def is_running(self) -> bool:
        """Check if server is running."""
        return self._site is not None

    async def _handle_callback(self, request: web.Request) -> web.Response:
        """Handle OAuth callback request.

        Args:
            request: Incoming HTTP request

        Returns:
            HTTP response with success or error HTML
        """
        # Extract parameters
        code = request.query.get("code")
        state = request.query.get("state")
        error = request.query.get("error")
        error_description = request.query.get("error_description")

        logger.info(f"Received OAuth callback: state={state}, error={error}")

        # Validate state parameter (required for CSRF protection)
        if not state:
            error_msg = "Missing required state parameter - potential CSRF attack"
            logger.error(f"OAuth callback missing state parameter: {request.url}")
            return web.Response(
                text=HTML_ERROR.format(error=error_msg),
                status=400,
                content_type="text/html",
            )

        # Handle error response
        if error:
            error_msg = error_description or error
            if state in self._pending_auths:
                pending = self._pending_auths.pop(state)
                pending.timeout_handle.cancel()
                pending.reject(Exception(error_msg))
            return web.Response(
                text=HTML_ERROR.format(error=error_msg),
                content_type="text/html",
            )

        # Validate authorization code
        if not code:
            return web.Response(
                text=HTML_ERROR.format(error="No authorization code provided"),
                status=400,
                content_type="text/html",
            )

        # Validate state parameter
        if state not in self._pending_auths:
            error_msg = "Invalid or expired state parameter - potential CSRF attack"
            logger.error(f"OAuth callback with invalid state: {state}")
            return web.Response(
                text=HTML_ERROR.format(error=error_msg),
                status=400,
                content_type="text/html",
            )

        # Resolve pending authorization
        pending = self._pending_auths.pop(state)
        pending.timeout_handle.cancel()
        pending.resolve(code)

        return web.Response(
            text=HTML_SUCCESS,
            content_type="text/html",
        )

    async def start(self) -> None:
        """Start the OAuth callback server.

        Raises:
            OSError: If port is already in use
        """
        if self.is_running:
            logger.info("OAuth callback server already running")
            return

        # Create aiohttp application
        self._app = web.Application()
        self._app.router.add_get(CALLBACK_PATH, self._handle_callback)

        # Create and start runner
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()

        # Create site
        self._site = web.TCPSite(self._runner, "127.0.0.1", self._port)
        await self._site.start()

        logger.info(f"OAuth callback server started on port {self._port}")

    async def stop(self) -> None:
        """Stop the OAuth callback server."""
        if not self.is_running:
            return

        # Reject all pending authorizations
        for state, pending in list(self._pending_auths.items()):
            pending.timeout_handle.cancel()
            pending.reject(Exception("OAuth callback server stopped"))
            del self._pending_auths[state]

        # Stop site
        if self._site:
            await self._site.stop()
            self._site = None

        # Cleanup runner
        if self._runner:
            await self._runner.cleanup()
            self._runner = None

        self._app = None

        logger.info("OAuth callback server stopped")

    def wait_for_callback(self, oauth_state: str) -> Awaitable[str]:
        """Wait for OAuth callback with given state.

        Args:
            oauth_state: OAuth state parameter to wait for

        Returns:
            Awaitable that resolves with authorization code

        Raises:
            asyncio.TimeoutError: If callback timeout
            Exception: If authorization failed or was cancelled
        """
        loop = asyncio.get_event_loop()

        # Create promise/future
        future: asyncio.Future[str] = loop.create_future()

        # Set timeout
        timeout_handle = loop.call_later(
            CALLBACK_TIMEOUT_MS / 1000,
            self._timeout_callback,
            future,
            oauth_state,
        )

        # Store pending auth
        self._pending_auths[oauth_state] = PendingAuth(
            resolve=lambda code: loop.call_soon_threadsafe(future.set_result, code),
            reject=lambda exc: loop.call_soon_threadsafe(future.set_exception, exc),
            timeout_handle=timeout_handle,
        )

        return future

    def _timeout_callback(self, future: asyncio.Future[Any], oauth_state: str) -> None:
        """Handle callback timeout.

        Args:
            future: Future to reject
            oauth_state: OAuth state parameter
        """
        if oauth_state in self._pending_auths:
            del self._pending_auths[oauth_state]

        if not future.done():
            future.set_exception(
                TimeoutError("OAuth callback timeout - authorization took too long")
            )

    def cancel_pending(self, oauth_state: str) -> None:
        """Cancel pending authorization for given state.

        Args:
            oauth_state: OAuth state parameter to cancel
        """
        if oauth_state in self._pending_auths:
            pending = self._pending_auths.pop(oauth_state)
            pending.timeout_handle.cancel()
            pending.reject(Exception("Authorization cancelled"))

    def get_pending_states(self) -> set[str]:
        """Get all pending OAuth states.

        Returns:
            Set of pending state parameters
        """
        return set(self._pending_auths.keys())


# Global singleton instance
_global_server: MCPOAuthCallbackServer | None = None


async def get_oauth_callback_server() -> MCPOAuthCallbackServer:
    """Get or create global OAuth callback server singleton.

    Returns:
        Global OAuth callback server instance
    """
    global _global_server

    if _global_server is None:
        _global_server = MCPOAuthCallbackServer()
        await _global_server.start()

    return _global_server


async def stop_oauth_callback_server() -> None:
    """Stop global OAuth callback server."""
    global _global_server

    if _global_server:
        await _global_server.stop()
        _global_server = None
