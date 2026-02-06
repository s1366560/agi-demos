"""Sandbox domain constants.

Configuration constants for sandbox management used across application
and infrastructure layers.
"""

from src.configuration.config import get_settings

_settings = get_settings()

# Default sandbox MCP server image - single source of truth from config
DEFAULT_SANDBOX_IMAGE = _settings.sandbox_default_image
