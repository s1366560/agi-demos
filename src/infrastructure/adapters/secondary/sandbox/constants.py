"""Sandbox infrastructure constants.

This module provides centralized sandbox configuration values.
Domain constants are re-exported from the domain layer for backwards compatibility.
Infrastructure-specific constants (ports) are defined here.
"""

# Re-export domain constants for backwards compatibility
from src.domain.model.sandbox.constants import DEFAULT_SANDBOX_IMAGE

# WebSocket ports inside container
MCP_WEBSOCKET_PORT = 8765
DESKTOP_PORT = 6080  # noVNC
TERMINAL_PORT = 7681  # ttyd
ISOLATED_NETWORK_OPTIONS = {"com.docker.network.bridge.enable_icc": "false"}

__all__ = [
    "DEFAULT_SANDBOX_IMAGE",
    "DESKTOP_PORT",
    "ISOLATED_NETWORK_OPTIONS",
    "MCP_WEBSOCKET_PORT",
    "TERMINAL_PORT",
]
