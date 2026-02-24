"""Channel manager startup and shutdown functions.

This module provides functions to initialize and shutdown the
ChannelConnectionManager during application lifecycle.
"""

import asyncio
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
from src.infrastructure.agent.plugins.manager import get_plugin_runtime_manager
from src.infrastructure.channels.connection_manager import ChannelConnectionManager

from .channel_reload import ChannelReloadPlan, reconcile_channel_connections

if TYPE_CHECKING:
    from src.domain.model.channels.message import Message

logger = logging.getLogger(__name__)

# Global channel manager instance
_channel_manager: ChannelConnectionManager | None = None
_channel_plugins_loaded = False
_channel_plugins_lock = asyncio.Lock()


def get_channel_manager() -> ChannelConnectionManager | None:
    """Get the global channel manager instance.

    Returns:
        The ChannelConnectionManager instance or None if not initialized.
    """
    return _channel_manager


async def initialize_channel_manager(
    message_router: Callable[["Message"], None] | None = None,
) -> ChannelConnectionManager | None:
    """Initialize and start the channel connection manager.

    This function:
    1. Creates the ChannelConnectionManager singleton
    2. Loads all enabled channel configurations from database
    3. Establishes WebSocket connections for each configuration
    4. Starts the health check loop

    Args:
        message_router: Optional callback to route incoming messages to the
            agent system. If not provided, uses the default router that
            routes messages to agent conversations.

    Returns:
        The initialized ChannelConnectionManager instance, or None if failed.
    """
    global _channel_manager

    if _channel_manager is not None:
        logger.warning("[ChannelStartup] Channel manager already initialized")
        return _channel_manager

    try:
        logger.info("[ChannelStartup] Initializing channel connection manager...")
        await _ensure_channel_plugins_loaded()

        # Use default message router if not provided
        if message_router is None:
            from src.application.services.channels import route_channel_message

            message_router = route_channel_message

        _channel_manager = ChannelConnectionManager(
            message_router=message_router,
            session_factory=async_session_factory,
        )

        # Start all enabled connections
        count = await _channel_manager.start_all(async_session_factory)
        reload_plan = await reload_channel_manager_connections(apply_changes=False)

        logger.info(
            "[ChannelStartup] Channel manager initialized with %d connections (reload_plan=%s)",
            count,
            reload_plan.summary() if reload_plan else None,
        )

        return _channel_manager

    except Exception as e:
        logger.error(f"[ChannelStartup] Failed to initialize channel manager: {e}")
        _channel_manager = None
        return None


async def _ensure_channel_plugins_loaded() -> None:
    """Load built-in channel plugins exactly once."""
    global _channel_plugins_loaded

    async with _channel_plugins_lock:
        if _channel_plugins_loaded:
            return

        runtime_manager = get_plugin_runtime_manager()
        diagnostics = await runtime_manager.ensure_loaded()
        for diagnostic in diagnostics:
            message = (
                f"[ChannelStartup][Plugin:{diagnostic.plugin_name}] "
                f"{diagnostic.code}: {diagnostic.message}"
            )
            if diagnostic.level == "error":
                logger.error(message)
                continue
            if diagnostic.level == "info":
                logger.info(message)
                continue
            logger.warning(message)
        _channel_plugins_loaded = True


async def shutdown_channel_manager() -> None:
    """Shutdown the channel connection manager.

    This function gracefully closes all WebSocket connections
    and cleans up resources.
    """
    global _channel_manager

    if _channel_manager is None:
        return

    try:
        logger.info("[ChannelStartup] Shutting down channel manager...")
        await _channel_manager.shutdown_all()
        _channel_manager = None
        logger.info("[ChannelStartup] Channel manager shut down successfully")

    except Exception as e:
        logger.error(f"[ChannelStartup] Error shutting down channel manager: {e}")
        _channel_manager = None


def set_message_router(router: Callable[["Message"], None]) -> None:
    """Set the message router on the channel manager.

    This can be called after initialization to update the message router.

    Args:
        router: The callback function to route incoming messages.
    """
    if _channel_manager:
        _channel_manager.set_message_router(router)
    else:
        logger.warning("[ChannelStartup] Cannot set message router: manager not initialized")


async def reload_channel_manager_connections(
    *,
    apply_changes: bool = False,
) -> ChannelReloadPlan | None:
    """Reconcile channel manager state against enabled DB configs."""
    if _channel_manager is None:
        logger.warning("[ChannelStartup] Cannot reload channels: manager not initialized")
        return None

    return await reconcile_channel_connections(
        _channel_manager,
        async_session_factory,
        apply_changes=apply_changes,
    )
