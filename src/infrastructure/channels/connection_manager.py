"""Channel connection manager for managing IM channel long connections.

This module provides a centralized manager for WebSocket connections to various
IM platforms (Feishu, DingTalk, WeCom, etc.). It handles connection lifecycle,
automatic reconnection with exponential backoff, health checks, and message routing.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.channels.message import (
    ChannelConfig,
    Message,
)
from src.infrastructure.adapters.secondary.persistence.channel_models import (
    ChannelConfigModel,
)
from src.infrastructure.adapters.secondary.persistence.channel_repository import (
    ChannelConfigRepository,
)

if TYPE_CHECKING:
    from src.infrastructure.agent.plugins.registry import PluginDiagnostic

import contextlib

from src.infrastructure.channels.outbox_worker import OutboxRetryWorker

logger = logging.getLogger(__name__)

# Constants
MAX_RECONNECT_DELAY = 60  # Maximum reconnect delay in seconds
INITIAL_RECONNECT_DELAY = 2  # Initial reconnect delay in seconds
HEALTH_CHECK_INTERVAL = 30  # Health check interval in seconds
API_PING_CYCLE = 10  # Ping Feishu API every Nth health check cycle
MAX_RECONNECT_ATTEMPTS = 20  # Max attempts before circuit breaker opens


class ConnectionStatus(str, Enum):
    """Status of a managed channel connection."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"
    CIRCUIT_OPEN = "circuit_open"


@dataclass
class ManagedConnection:
    """Represents a managed channel connection.

    Attributes:
        config_id: Unique identifier for the channel configuration.
        project_id: Project ID this channel belongs to.
        channel_type: Type of channel (feishu, dingtalk, wecom, etc.).
        adapter: The channel adapter instance.
        task: The asyncio task running the connection.
        status: Current connection status.
        last_heartbeat: Timestamp of last successful heartbeat.
        last_error: Last error message if any.
        reconnect_attempts: Number of reconnection attempts.
    """

    config_id: str
    project_id: str
    channel_type: str
    adapter: Any  # ChannelAdapter instance
    task: asyncio.Task | None = None
    status: ConnectionStatus = ConnectionStatus.DISCONNECTED
    last_heartbeat: datetime | None = None
    last_error: str | None = None
    reconnect_attempts: int = 0
    _stop_event: asyncio.Event = field(default_factory=asyncio.Event)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "config_id": self.config_id,
            "project_id": self.project_id,
            "channel_type": self.channel_type,
            "status": self.status,
            "connected": self.status == ConnectionStatus.CONNECTED,
            "last_heartbeat": self.last_heartbeat.isoformat() if self.last_heartbeat else None,
            "last_error": self.last_error,
            "reconnect_attempts": self.reconnect_attempts,
        }


class ChannelConnectionManager:
    """Manages long-lived connections to IM channels.

    This singleton manager handles:
    - Loading enabled configurations at startup
    - Establishing WebSocket connections
    - Automatic reconnection with exponential backoff
    - Health monitoring
    - Message routing to the agent system
    - Graceful shutdown

    Usage:
        manager = ChannelConnectionManager(message_router=my_router)
        await manager.start_all(async_session_factory)

        # Later, when adding a new config:
        await manager.add_connection(config_model)

        # On shutdown:
        await manager.shutdown_all()
    """

    def __init__(
        self,
        message_router: Callable[[Message], None] | None = None,
        session_factory: Callable[[], AsyncSession] | None = None,
    ) -> None:
        """Initialize the connection manager.

        Args:
            message_router: Optional callback to route incoming messages.
            session_factory: Factory function to create database sessions.
        """
        self._connections: dict[str, ManagedConnection] = {}
        self._message_router = message_router
        self._session_factory = session_factory
        self._health_check_task: asyncio.Task | None = None
        self._outbox_worker: OutboxRetryWorker | None = None
        self._main_loop: asyncio.AbstractEventLoop | None = None
        self._started = False

    @property
    def connections(self) -> dict[str, ManagedConnection]:
        """Get all managed connections."""
        return self._connections

    async def start_all(
        self,
        session_factory: Callable[[], AsyncSession] | None = None,
    ) -> int:
        """Load all enabled configurations and establish connections.

        Args:
            session_factory: Factory function to create database sessions.
                If not provided, uses the factory passed to __init__.

        Returns:
            Number of connections started.
        """
        if self._started:
            logger.warning("[ChannelManager] Already started, skipping start_all")
            return 0

        if session_factory:
            self._session_factory = session_factory

        if not self._session_factory:
            logger.error("[ChannelManager] No session factory provided")
            return 0

        logger.info("[ChannelManager] Starting all channel connections...")
        self._started = True
        self._main_loop = asyncio.get_running_loop()

        # Load all enabled configurations
        async with self._session_factory() as session:
            repo = ChannelConfigRepository(session)
            configs = await self._list_all_enabled(repo)

        logger.info(f"[ChannelManager] Found {len(configs)} enabled configurations")

        # Start connections
        started = 0
        for config in configs:
            try:
                await self.add_connection(config)
                started += 1
            except Exception as e:
                logger.error(f"[ChannelManager] Failed to start connection {config.id}: {e}")

        # Start health check loop
        self._health_check_task = asyncio.create_task(self._health_check_loop())

        # Start outbox retry worker
        if self._session_factory:
            self._outbox_worker = OutboxRetryWorker(
                session_factory=self._session_factory,
                get_connection_fn=lambda cid: self._connections.get(cid),
            )
            self._outbox_worker.start()

        logger.info(f"[ChannelManager] Started {started}/{len(configs)} connections")
        return started

    async def _list_all_enabled(self, repo: ChannelConfigRepository) -> list[ChannelConfigModel]:
        """List all enabled configurations."""
        from sqlalchemy import select

        query = select(ChannelConfigModel).where(ChannelConfigModel.enabled.is_(True))
        result = await repo._session.execute(query)
        return list(result.scalars().all())

    async def add_connection(self, config: ChannelConfigModel) -> ManagedConnection:
        """Add and establish a new connection.

        Args:
            config: The channel configuration model.

        Returns:
            The managed connection instance.

        Raises:
            ValueError: If config already exists or is invalid.
        """
        if config.id in self._connections:
            raise ValueError(f"Connection {config.id} already exists")

        if not config.enabled:
            raise ValueError(f"Configuration {config.id} is not enabled")

        logger.info(f"[ChannelManager] Adding connection {config.id} ({config.channel_type})")

        current_loop = asyncio.get_running_loop()
        if (
            self._main_loop is None
            or self._main_loop.is_closed()
            or not self._main_loop.is_running()
        ):
            self._main_loop = current_loop

        # Create adapter based on channel type
        adapter = await self._create_adapter(config)

        # Create managed connection
        connection = ManagedConnection(
            config_id=config.id,
            project_id=config.project_id,
            channel_type=config.channel_type,
            adapter=adapter,
            status=ConnectionStatus.CONNECTING,
        )

        self._connections[config.id] = connection

        # Start connection task
        connection.task = asyncio.create_task(self._connection_loop(connection, config))

        return connection

    async def _create_adapter(self, config: ChannelConfigModel) -> Any:
        """Create a channel adapter based on configuration.

        Args:
            config: The channel configuration.

        Returns:
            The created adapter instance.

        Raises:
            ValueError: If channel type is not supported.
        """
        from src.infrastructure.agent.plugins.registry import (
            ChannelAdapterBuildContext,
            get_plugin_registry,
        )

        plugin_registry = get_plugin_registry()
        metadata = plugin_registry.list_channel_type_metadata().get(
            (config.channel_type or "").lower()
        )
        secret_paths = self._resolve_secret_paths(metadata)

        app_secret, encrypt_key, verification_token, extra_settings = self._decrypt_config_secrets(
            config, secret_paths
        )

        channel_config = ChannelConfig(
            enabled=config.enabled,
            app_id=config.app_id,
            app_secret=app_secret,
            encrypt_key=encrypt_key,
            verification_token=verification_token,
            connection_mode=config.connection_mode,
            webhook_port=config.webhook_port,
            webhook_path=config.webhook_path,
            domain=config.domain,
            extra=extra_settings,
        )
        adapter, diagnostics = await plugin_registry.build_channel_adapter(
            ChannelAdapterBuildContext(
                channel_type=config.channel_type,
                config_model=config,
                channel_config=channel_config,
            )
        )
        for diagnostic in diagnostics:
            self._log_plugin_diagnostic(diagnostic)
        if adapter is not None:
            return adapter

        raise ValueError(f"Unsupported channel type: {config.channel_type}")

    @staticmethod
    def _resolve_secret_paths(metadata: Any) -> list[str]:
        """Extract secret_paths list from channel type metadata."""
        secret_paths_raw = getattr(metadata, "secret_paths", None)
        if isinstance(secret_paths_raw, list):
            return [path for path in secret_paths_raw if isinstance(path, str)]
        return []

    @staticmethod
    def _decrypt_config_secrets(
        config: ChannelConfigModel,
        secret_paths: list[str],
    ) -> tuple[str, str | None, str | None, dict[str, Any]]:
        """Decrypt secret fields in the channel configuration.

        Returns:
            Tuple of (app_secret, encrypt_key, verification_token, extra_settings).
        """
        from src.infrastructure.security.encryption_service import get_encryption_service

        encryption_service = get_encryption_service()

        def _decrypt_if_needed(value: str | None) -> str | None:
            if not value:
                return value
            try:
                return encryption_service.decrypt(value)
            except Exception:
                return value

        app_secret = config.app_secret or ""
        if app_secret and (not secret_paths or "app_secret" in secret_paths):
            app_secret = _decrypt_if_needed(app_secret) or ""

        encrypt_key = config.encrypt_key
        if encrypt_key and "encrypt_key" in secret_paths:
            encrypt_key = _decrypt_if_needed(encrypt_key)

        verification_token = config.verification_token
        if verification_token and "verification_token" in secret_paths:
            verification_token = _decrypt_if_needed(verification_token)

        extra_settings = dict(config.extra_settings or {})
        for sp in secret_paths:
            if sp in {"app_secret", "encrypt_key", "verification_token"}:
                continue
            if "." in sp:
                continue
            secret_value = extra_settings.get(sp)
            if isinstance(secret_value, str) and secret_value:
                extra_settings[sp] = _decrypt_if_needed(secret_value)

        return app_secret, encrypt_key, verification_token, extra_settings

    @staticmethod
    def _log_plugin_diagnostic(diagnostic: PluginDiagnostic) -> None:
        """Log plugin diagnostic records emitted during adapter creation."""
        message = (
            f"[ChannelManager][Plugin:{diagnostic.plugin_name}] "
            f"{diagnostic.code}: {diagnostic.message}"
        )
        if diagnostic.level == "error":
            logger.error(message)
            return
        if diagnostic.level == "info":
            logger.info(message)
            return
        logger.warning(message)

    async def _connection_loop(
        self,
        connection: ManagedConnection,
        config: ChannelConfigModel,
    ) -> None:
        """Run the connection loop with automatic reconnection."""
        while not connection._stop_event.is_set():
            try:
                await self._attempt_connect(connection, config)

                if connection._stop_event.is_set():
                    break

                logger.warning(f"[ChannelManager] Connection lost: {config.id}")
                connection.status = ConnectionStatus.DISCONNECTED

            except Exception as e:
                logger.error(f"[ChannelManager] Connection error for {config.id}: {e}")
                connection.status = ConnectionStatus.ERROR
                connection.last_error = str(e)
                await self._update_db_status(config.id, "error", str(e))

            should_stop = await self._handle_reconnect_backoff(connection, config)
            if should_stop:
                break

        await self._cleanup_connection(connection, config)

    async def _attempt_connect(
        self,
        connection: ManagedConnection,
        config: ChannelConfigModel,
    ) -> None:
        """Attempt to connect and wait until disconnect or stop."""
        connection.status = ConnectionStatus.CONNECTING
        await self._update_db_status(config.id, "connecting")

        handler = self._build_message_handler(config)
        connection.adapter.on_message(handler)

        await connection.adapter.connect()

        connection.status = ConnectionStatus.CONNECTED
        connection.last_heartbeat = datetime.now(UTC)
        connection.reconnect_attempts = 0
        connection.last_error = None
        await self._update_db_status(config.id, "connected")
        logger.info(f"[ChannelManager] Connected: {config.id} ({config.channel_type})")

        while connection.adapter.connected and not connection._stop_event.is_set():
            await asyncio.sleep(1)

    def _build_message_handler(self, config: ChannelConfigModel) -> Callable[[Message], None]:
        """Create a message handler closure for the given config."""

        def message_handler(message: Message) -> None:
            message.project_id = config.project_id

            raw_data = message.raw_data if isinstance(message.raw_data, dict) else {}
            routing_meta = raw_data.get("_routing")
            if not isinstance(routing_meta, dict):
                routing_meta = {}

            event = raw_data.get("event")
            event_message = event.get("message") if isinstance(event, dict) else None
            if isinstance(event_message, dict):
                source_message_id = event_message.get("message_id")
                if isinstance(source_message_id, str) and source_message_id:
                    routing_meta["channel_message_id"] = source_message_id

            routing_meta["channel_config_id"] = config.id
            routing_meta["project_id"] = config.project_id
            routing_meta["channel_type"] = config.channel_type
            routing_meta["rate_limit_per_minute"] = getattr(config, "rate_limit_per_minute", 60)
            raw_data["_routing"] = routing_meta
            message.raw_data = raw_data

            if self._message_router:
                try:
                    self._schedule_route_message(message)
                except Exception as e:
                    logger.error(f"[ChannelManager] Error routing message: {e}")

        return message_handler

    async def _handle_reconnect_backoff(
        self,
        connection: ManagedConnection,
        config: ChannelConfigModel,
    ) -> bool:
        """Handle reconnect backoff with circuit breaker.

        Returns:
            True if the loop should stop, False to continue reconnecting.
        """
        if connection._stop_event.is_set():
            return True

        connection.reconnect_attempts += 1
        if connection.reconnect_attempts >= MAX_RECONNECT_ATTEMPTS:
            connection.status = ConnectionStatus.CIRCUIT_OPEN
            await self._update_db_status(
                config.id,
                "error",
                f"Circuit breaker open after {MAX_RECONNECT_ATTEMPTS} "
                f"failed attempts. Manual restart required.",
            )
            logger.error(
                f"[ChannelManager] Circuit breaker open for {config.id} "
                f"after {connection.reconnect_attempts} attempts"
            )
            return True

        delay = min(
            INITIAL_RECONNECT_DELAY**connection.reconnect_attempts,
            MAX_RECONNECT_DELAY,
        )
        logger.info(
            f"[ChannelManager] Reconnecting {config.id} in {delay}s "
            f"(attempt {connection.reconnect_attempts})"
        )
        await asyncio.sleep(delay)
        return False

    async def _cleanup_connection(
        self, connection: ManagedConnection, config: ChannelConfigModel
    ) -> None:
        """Clean up after connection loop ends."""
        try:
            await connection.adapter.disconnect()
        except Exception as e:
            logger.warning(f"[ChannelManager] Error disconnecting {config.id}: {e}")

        connection.status = ConnectionStatus.DISCONNECTED
        logger.info(f"[ChannelManager] Connection loop ended: {config.id}")

    async def _safe_route_message(self, message: Message) -> None:
        """Safely route a message to the handler."""
        try:
            if self._message_router:
                if asyncio.iscoroutinefunction(self._message_router):
                    await self._message_router(message)
                else:
                    self._message_router(message)
        except Exception as e:
            logger.error(f"[ChannelManager] Message routing error: {e}")

    def _schedule_route_message(self, message: Message) -> None:
        """Schedule message routing on the manager's main event loop."""
        # If main loop is not available, try to get current running loop
        if (
            self._main_loop is None
            or self._main_loop.is_closed()
            or not self._main_loop.is_running()
        ):
            try:
                self._main_loop = asyncio.get_running_loop()
            except RuntimeError:
                # No running loop available - try to route synchronously if possible
                logger.warning("[ChannelManager] No event loop available, attempting sync routing")
                if self._message_router:
                    try:
                        # If it's a coroutine function, we can't run it sync
                        if asyncio.iscoroutinefunction(self._message_router):
                            logger.error(
                                "[ChannelManager] Cannot route async function without event loop"
                            )
                            return
                        # Otherwise run sync
                        self._message_router(message)
                        return
                    except Exception as e:
                        logger.error(f"[ChannelManager] Sync routing failed: {e}")
                        return

        coro = self._safe_route_message(message)
        try:
            future = asyncio.run_coroutine_threadsafe(coro, self._main_loop)
        except Exception as e:
            coro.close()
            logger.error(f"[ChannelManager] Failed to schedule message routing: {e}")
            return

        future.add_done_callback(self._on_route_future_done)

    def _on_route_future_done(self, future: Future[Any]) -> None:
        """Log unexpected routing task failures."""
        try:
            _ = future.result()
        except Exception as e:
            logger.error(f"[ChannelManager] Scheduled message routing failed: {e}")

    async def _update_db_status(
        self,
        config_id: str,
        status: str,
        error: str | None = None,
    ) -> None:
        """Update connection status in database."""
        if not self._session_factory:
            return

        try:
            async with self._session_factory() as session:
                repo = ChannelConfigRepository(session)
                await repo.update_status(config_id, status, error)
                await session.commit()
        except Exception as e:
            logger.warning(f"[ChannelManager] Failed to update DB status: {e}")

    async def remove_connection(self, config_id: str) -> bool:
        """Remove and disconnect a connection.

        Args:
            config_id: The configuration ID to remove.

        Returns:
            True if removed, False if not found.
        """
        connection = self._connections.get(config_id)
        if not connection:
            return False

        logger.info(f"[ChannelManager] Removing connection {config_id}")

        # Signal stop
        connection._stop_event.set()

        # Wait for task to complete
        if connection.task and not connection.task.done():
            try:
                await asyncio.wait_for(connection.task, timeout=5.0)
            except TimeoutError:
                connection.task.cancel()

        del self._connections[config_id]

        await self._update_db_status(config_id, "disconnected")

        return True

    async def restart_connection(self, config_id: str) -> bool:
        """Restart a connection (e.g., after config update).

        Args:
            config_id: The configuration ID to restart.

        Returns:
            True if restarted, False if not found.
        """
        connection = self._connections.get(config_id)
        if not connection:
            return False

        logger.info(f"[ChannelManager] Restarting connection {config_id}")

        # Get fresh config from DB
        if not self._session_factory:
            logger.error("[ChannelManager] No session factory for restart")
            return False

        async with self._session_factory() as session:
            repo = ChannelConfigRepository(session)
            config = await repo.get_by_id(config_id)

        if not config:
            logger.error(f"[ChannelManager] Config {config_id} not found in DB")
            return False

        # Remove old connection
        await self.remove_connection(config_id)

        # Add new connection with fresh config
        if config.enabled:
            try:
                await self.add_connection(config)
                return True
            except Exception as e:
                logger.error(f"[ChannelManager] Failed to restart {config_id}: {e}")
                return False

        return True

    async def shutdown_all(self) -> None:
        """Shutdown all connections gracefully."""
        logger.info("[ChannelManager] Shutting down all connections...")

        # Stop outbox worker
        if self._outbox_worker:
            await self._outbox_worker.stop()
            self._outbox_worker = None

        # Stop health check
        if self._health_check_task and not self._health_check_task.done():
            self._health_check_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._health_check_task

        # Stop all connections
        stop_tasks = []
        for config_id in list(self._connections.keys()):
            stop_tasks.append(self.remove_connection(config_id))

        if stop_tasks:
            await asyncio.gather(*stop_tasks, return_exceptions=True)

        self._started = False
        self._main_loop = None
        logger.info("[ChannelManager] All connections shut down")

    async def _health_check_loop(self) -> None:
        """Periodic health check for all connections."""
        cycle = 0
        while self._started:
            try:
                await asyncio.sleep(HEALTH_CHECK_INTERVAL)
                cycle += 1
                deep_ping = cycle % API_PING_CYCLE == 0

                for connection in list(self._connections.values()):
                    if connection.status == ConnectionStatus.CONNECTED:
                        if connection.adapter.connected:
                            if deep_ping and hasattr(connection.adapter, "health_check"):
                                alive = await connection.adapter.health_check()
                                if not alive:
                                    logger.warning(
                                        "[ChannelManager] API ping failed for %s, "
                                        "marking disconnected",
                                        connection.config_id,
                                    )
                                    connection.status = ConnectionStatus.DISCONNECTED
                                    continue
                            connection.last_heartbeat = datetime.now(UTC)
                        else:
                            # Connection lost, will be handled by connection loop
                            logger.warning(
                                f"[ChannelManager] Health check: {connection.config_id} disconnected"
                            )

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[ChannelManager] Health check error: {e}")

    def get_status(self, config_id: str) -> dict[str, Any] | None:
        """Get the status of a specific connection.

        Args:
            config_id: The configuration ID.

        Returns:
            Connection status dict or None if not found.
        """
        connection = self._connections.get(config_id)
        if connection:
            return connection.to_dict()
        return None

    def get_all_status(self) -> list[dict[str, Any]]:
        """Get the status of all connections.

        Returns:
            List of connection status dicts.
        """
        return [conn.to_dict() for conn in self._connections.values()]

    def set_message_router(self, router: Callable[[Message], None]) -> None:
        """Set the message router callback.

        Args:
            router: The callback function to route incoming messages.
        """
        self._message_router = router
