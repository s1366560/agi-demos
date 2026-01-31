"""Sandbox infrastructure constants.

This module provides centralized sandbox configuration values,
importing from application settings to maintain a single source of truth.
"""

from src.configuration.config import get_settings

_settings = get_settings()

# Default sandbox MCP server image - single source of truth from config
DEFAULT_SANDBOX_IMAGE = _settings.sandbox_default_image

# WebSocket ports inside container
MCP_WEBSOCKET_PORT = 8765
DESKTOP_PORT = 6080  # noVNC
TERMINAL_PORT = 7681  # ttyd
