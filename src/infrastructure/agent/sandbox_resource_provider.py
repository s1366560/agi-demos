"""Sandbox Resource Provider for Agent Workflow.

This module provides a simple way for agent workflow to access sandbox resources
through the SandboxResourcePort interface without direct coupling to implementation details.

The provider is initialized during worker startup and can be imported anywhere in the
agent workflow.
"""

import logging
from typing import Optional

from src.domain.ports.services.sandbox_resource_port import SandboxResourcePort

logger = logging.getLogger(__name__)

_sandbox_resource_port: Optional[SandboxResourcePort] = None


def set_sandbox_resource_port(port: SandboxResourcePort) -> None:
    """Set the sandbox resource port for agent workflow access.

    This should be called during worker initialization.

    Args:
        port: The SandboxResourcePort implementation (usually UnifiedSandboxService)
    """
    global _sandbox_resource_port
    _sandbox_resource_port = port
    logger.info("[SandboxResourceProvider] SandboxResourcePort registered")


def get_sandbox_resource_port() -> Optional[SandboxResourcePort]:
    """Get the sandbox resource port for agent workflow access.

    Returns:
        The SandboxResourcePort implementation, or None if not registered
    """
    return _sandbox_resource_port


def get_sandbox_resource_port_or_raise() -> SandboxResourcePort:
    """Get the sandbox resource port or raise an error if not available.

    Returns:
        The SandboxResourcePort implementation

    Raises:
        RuntimeError: If the sandbox resource port is not registered
    """
    port = get_sandbox_resource_port()
    if port is None:
        raise RuntimeError(
            "SandboxResourcePort not registered. "
            "Call set_sandbox_resource_port() during worker initialization."
        )
    return port


def is_sandbox_resource_available() -> bool:
    """Check if sandbox resource port is available.

    Returns:
        True if the port is registered, False otherwise
    """
    return _sandbox_resource_port is not None
