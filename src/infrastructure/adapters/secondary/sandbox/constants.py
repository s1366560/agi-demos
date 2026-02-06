"""Sandbox infrastructure constants.

This module provides centralized sandbox configuration values.
Domain constants are re-exported from the domain layer for backwards compatibility.
Infrastructure-specific constants (ports) are defined here.
"""

from src.domain.model.sandbox.constants import DEFAULT_SANDBOX_IMAGE  # noqa: F401

# WebSocket ports inside container
MCP_WEBSOCKET_PORT = 8765
DESKTOP_PORT = 6080  # noVNC
TERMINAL_PORT = 7681  # ttyd
