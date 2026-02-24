"""Enhanced Health Monitor - Background health monitoring with heartbeat and auto-recovery.

This module provides:
- Periodic health checks for all active sandboxes
- Heartbeat mechanism for WebSocket connections
- Automatic reconnection for disconnected sandboxes
- TTL-based automatic cleanup of stale entries

This improves upon the basic health check by running continuously in the background.
"""

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from src.infrastructure.adapters.secondary.sandbox.local_sandbox_adapter import LocalSandboxAdapter
from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import MCPSandboxAdapter

logger = logging.getLogger(__name__)


class HealthCheckLevel(Enum):
    """Level of health check to perform."""

    BASIC = "basic"  # Just check container running
    MCP = "mcp"  # Check MCP WebSocket connection
    SERVICES = "services"  # Check all services (desktop, terminal)
    FULL = "full"  # Full check with tool execution


@dataclass
class HealthCheckResult:
    """Result of a health check."""

    sandbox_id: str
    healthy: bool
    level: HealthCheckLevel
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    container_running: bool = False
    mcp_connected: bool = False
    services_healthy: bool = False
    latency_ms: float | None = None
    error_message: str | None = None
    recovery_attempted: bool = False
    recovery_succeeded: bool = False


@dataclass
class TTLEntry:
    """Entry with TTL tracking for automatic cleanup."""

    key: str
    value: Any
    created_at: float
    last_accessed_at: float
    ttl_seconds: float

    def is_expired(self) -> bool:
        """Check if this entry has expired based on last access time."""
        return (time.time() - self.last_accessed_at) > self.ttl_seconds

    def touch(self) -> None:
        """Update last accessed time."""
        self.last_accessed_at = time.time()


class TTLCache:
    """
    Simple TTL cache for tracking data with automatic expiration.

    Used for tracking rebuild timestamps and other temporary data
    that should be automatically cleaned up.
    """

    def __init__(self, default_ttl_seconds: float = 300.0, max_size: int = 1000) -> None:
        """
        Initialize TTL cache.

        Args:
            default_ttl_seconds: Default TTL for entries
            max_size: Maximum number of entries before forced cleanup
        """
        self._entries: dict[str, TTLEntry] = {}
        self._default_ttl = default_ttl_seconds
        self._max_size = max_size
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Any | None:
        """Get value if exists and not expired."""
        async with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            if entry.is_expired():
                del self._entries[key]
                return None
            entry.touch()
            return entry.value

    async def set(self, key: str, value: Any, ttl: float | None = None) -> None:
        """Set a value with optional custom TTL."""
        async with self._lock:
            # Check if cleanup needed
            if len(self._entries) >= self._max_size:
                self._cleanup_expired_unsafe()

            now = time.time()
            self._entries[key] = TTLEntry(
                key=key,
                value=value,
                created_at=now,
                last_accessed_at=now,
                ttl_seconds=ttl or self._default_ttl,
            )

    async def delete(self, key: str) -> bool:
        """Delete an entry."""
        async with self._lock:
            if key in self._entries:
                del self._entries[key]
                return True
            return False

    async def cleanup_expired(self) -> int:
        """Clean up all expired entries."""
        async with self._lock:
            return self._cleanup_expired_unsafe()

    def _cleanup_expired_unsafe(self) -> int:
        """Clean up expired entries without lock (must be called with lock held)."""
        expired = [key for key, entry in self._entries.items() if entry.is_expired()]
        for key in expired:
            del self._entries[key]
        return len(expired)

    async def size(self) -> int:
        """Get current size of cache."""
        async with self._lock:
            return len(self._entries)

    async def clear(self) -> None:
        """Clear all entries."""
        async with self._lock:
            self._entries.clear()


class EnhancedHealthMonitor:
    """
    Background health monitor for sandbox lifecycle.

    Features:
    - Periodic health checks with configurable interval
    - Heartbeat mechanism for MCP WebSocket connections
    - Automatic reconnection for failed connections
    - TTL-based cleanup of stale tracking data
    - Callback support for health state changes

    Usage:
        monitor = EnhancedHealthMonitor(
            sandbox_adapter=adapter,
            check_interval_seconds=60,
            heartbeat_interval_seconds=30,
        )

        # Register callbacks
        monitor.on_unhealthy(handle_unhealthy_sandbox)
        monitor.on_recovered(handle_recovered_sandbox)

        # Start monitoring
        await monitor.start()

        # Stop monitoring
        await monitor.stop()
    """

    def __init__(
        self,
        sandbox_adapter: MCPSandboxAdapter | None,
        local_sandbox_adapter: LocalSandboxAdapter | None = None,
        check_interval_seconds: float = 60.0,
        heartbeat_interval_seconds: float = 30.0,
        auto_recover: bool = True,
        max_recovery_attempts: int = 3,
        recovery_backoff_base: float = 5.0,
        ttl_cleanup_interval_seconds: float = 300.0,
    ) -> None:
        """
        Initialize the health monitor.

        Args:
            sandbox_adapter: MCP sandbox adapter for cloud sandboxes
            local_sandbox_adapter: Optional local sandbox adapter
            check_interval_seconds: Interval between health checks
            heartbeat_interval_seconds: Interval for WebSocket heartbeats
            auto_recover: Whether to automatically recover unhealthy sandboxes
            max_recovery_attempts: Maximum recovery attempts before giving up
            recovery_backoff_base: Base backoff time for recovery retries
            ttl_cleanup_interval_seconds: Interval for TTL cache cleanup
        """
        self._adapter = sandbox_adapter
        self._local_adapter = local_sandbox_adapter
        self._check_interval = check_interval_seconds
        self._heartbeat_interval = heartbeat_interval_seconds
        self._auto_recover = auto_recover
        self._max_recovery_attempts = max_recovery_attempts
        self._recovery_backoff_base = recovery_backoff_base
        self._ttl_cleanup_interval = ttl_cleanup_interval_seconds

        # Running state
        self._running = False
        self._health_check_task: asyncio.Task | None = None
        self._heartbeat_task: asyncio.Task | None = None
        self._ttl_cleanup_task: asyncio.Task | None = None

        # TTL caches for various tracking data
        self._rebuild_timestamps = TTLCache(default_ttl_seconds=300.0, max_size=1000)
        self._recovery_attempts = TTLCache(default_ttl_seconds=3600.0, max_size=1000)
        self._last_health_results = TTLCache(default_ttl_seconds=600.0, max_size=1000)

        # Callbacks for state changes
        self._on_unhealthy_callbacks: list[Callable[[str, HealthCheckResult], Coroutine]] = []
        self._on_recovered_callbacks: list[Callable[[str, HealthCheckResult], Coroutine]] = []
        self._on_terminated_callbacks: list[Callable[[str], Coroutine]] = []

        # Track sandboxes currently being recovered (prevent concurrent recovery)
        self._recovering: set[str] = set()
        self._recovering_lock = asyncio.Lock()

    def on_unhealthy(
        self, callback: Callable[[str, HealthCheckResult], Coroutine]
    ) -> "EnhancedHealthMonitor":
        """Register callback for when a sandbox becomes unhealthy."""
        self._on_unhealthy_callbacks.append(callback)
        return self

    def on_recovered(
        self, callback: Callable[[str, HealthCheckResult], Coroutine]
    ) -> "EnhancedHealthMonitor":
        """Register callback for when a sandbox recovers."""
        self._on_recovered_callbacks.append(callback)
        return self

    def on_terminated(self, callback: Callable[[str], Coroutine]) -> "EnhancedHealthMonitor":
        """Register callback for when a sandbox is terminated."""
        self._on_terminated_callbacks.append(callback)
        return self

    async def start(self) -> None:
        """Start the health monitor background tasks."""
        if self._running:
            logger.warning("Health monitor already running")
            return

        self._running = True

        # Start background tasks
        self._health_check_task = asyncio.create_task(
            self._health_check_loop(),
            name="sandbox-health-check",
        )
        self._heartbeat_task = asyncio.create_task(
            self._heartbeat_loop(),
            name="sandbox-heartbeat",
        )
        self._ttl_cleanup_task = asyncio.create_task(
            self._ttl_cleanup_loop(),
            name="sandbox-ttl-cleanup",
        )

        logger.info(
            f"EnhancedHealthMonitor started "
            f"(check={self._check_interval}s, heartbeat={self._heartbeat_interval}s)"
        )

    async def stop(self) -> None:
        """Stop the health monitor background tasks."""
        self._running = False

        # Cancel all tasks
        tasks = [self._health_check_task, self._heartbeat_task, self._ttl_cleanup_task]
        for task in tasks:
            if task:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

        self._health_check_task = None
        self._heartbeat_task = None
        self._ttl_cleanup_task = None

        logger.info("EnhancedHealthMonitor stopped")

    async def _health_check_loop(self) -> None:
        """Main health check loop."""
        while self._running:
            try:
                await asyncio.sleep(self._check_interval)
                await self._check_all_sandboxes()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in health check loop: {e}")
                await asyncio.sleep(5)  # Brief pause on error

    async def _heartbeat_loop(self) -> None:
        """WebSocket heartbeat loop."""
        while self._running:
            try:
                await asyncio.sleep(self._heartbeat_interval)
                await self._send_heartbeats()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in heartbeat loop: {e}")
                await asyncio.sleep(5)

    async def _ttl_cleanup_loop(self) -> None:
        """TTL cache cleanup loop."""
        while self._running:
            try:
                await asyncio.sleep(self._ttl_cleanup_interval)
                await self._cleanup_ttl_caches()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in TTL cleanup loop: {e}")

    async def _check_all_sandboxes(self) -> None:
        """Check health of all active sandboxes."""
        # Get list of active sandboxes
        sandboxes = []

        if hasattr(self._adapter, "_active_sandboxes"):
            async with self._adapter._lock:
                sandboxes = list(self._adapter._active_sandboxes.keys())

        if not sandboxes:
            return

        logger.debug(f"Health checking {len(sandboxes)} sandboxes")

        # Check each sandbox
        for sandbox_id in sandboxes:
            try:
                result = await self.check_sandbox_health(sandbox_id)

                # Store result
                await self._last_health_results.set(sandbox_id, result)

                # Handle unhealthy sandbox
                if not result.healthy:
                    await self._handle_unhealthy(sandbox_id, result)

            except Exception as e:
                logger.error(f"Error checking sandbox {sandbox_id}: {e}")

    async def check_sandbox_health(
        self,
        sandbox_id: str,
        level: HealthCheckLevel = HealthCheckLevel.MCP,
    ) -> HealthCheckResult:
        """
        Perform a health check on a specific sandbox.

        Args:
            sandbox_id: The sandbox to check
            level: Level of health check to perform

        Returns:
            HealthCheckResult with check details
        """
        start_time = time.time()
        result = HealthCheckResult(
            sandbox_id=sandbox_id,
            healthy=False,
            level=level,
        )

        try:
            # Basic check - container running
            if hasattr(self._adapter, "get_sandbox"):
                instance = await self._adapter.get_sandbox(sandbox_id)
                if instance:
                    from src.domain.ports.services.sandbox_port import SandboxStatus

                    result.container_running = instance.status == SandboxStatus.RUNNING

            if not result.container_running:
                result.error_message = "Container not running"
                return result

            if level == HealthCheckLevel.BASIC:
                result.healthy = True
                return result

            # MCP check - WebSocket connection
            if hasattr(self._adapter, "_active_sandboxes"):
                async with self._adapter._lock:
                    instance = self._adapter._active_sandboxes.get(sandbox_id)
                    if instance and instance.mcp_client:
                        result.mcp_connected = instance.mcp_client.is_connected

            if not result.mcp_connected:
                # Try to reconnect
                try:
                    connected = await self._adapter.connect_mcp(sandbox_id, timeout=10)
                    result.mcp_connected = connected
                except Exception as e:
                    result.error_message = f"MCP connection failed: {e}"
                    return result

            if level == HealthCheckLevel.MCP:
                result.healthy = result.mcp_connected
                result.latency_ms = (time.time() - start_time) * 1000
                return result

            # Services check - desktop and terminal
            if level in (HealthCheckLevel.SERVICES, HealthCheckLevel.FULL):
                # For now, assume services are healthy if MCP is connected
                result.services_healthy = result.mcp_connected

            # Full check - execute a simple command
            if level == HealthCheckLevel.FULL and result.mcp_connected:
                try:
                    await self._adapter.call_tool(
                        sandbox_id,
                        "bash",
                        {"command": "echo health_check"},
                        timeout=5,
                    )
                    result.services_healthy = True
                except Exception as e:
                    result.error_message = f"Tool execution failed: {e}"
                    result.services_healthy = False

            result.healthy = result.container_running and result.mcp_connected
            result.latency_ms = (time.time() - start_time) * 1000

        except Exception as e:
            result.error_message = str(e)
            logger.error(f"Health check error for {sandbox_id}: {e}")

        return result

    async def _handle_unhealthy(self, sandbox_id: str, result: HealthCheckResult) -> None:
        """Handle an unhealthy sandbox."""
        # Notify callbacks
        for callback in self._on_unhealthy_callbacks:
            try:
                await callback(sandbox_id, result)
            except Exception as e:
                logger.error(f"Error in unhealthy callback: {e}")

        # Attempt recovery if enabled
        if self._auto_recover:
            await self._attempt_recovery(sandbox_id, result)

    async def _attempt_recovery(self, sandbox_id: str, result: HealthCheckResult) -> bool:
        """
        Attempt to recover an unhealthy sandbox.

        Args:
            sandbox_id: The sandbox to recover
            result: The health check result

        Returns:
            True if recovery succeeded
        """
        # Prevent concurrent recovery attempts
        async with self._recovering_lock:
            if sandbox_id in self._recovering:
                logger.debug(f"Recovery already in progress for {sandbox_id}")
                return False
            self._recovering.add(sandbox_id)

        try:
            # Check recovery attempts count
            attempts = await self._recovery_attempts.get(sandbox_id) or 0
            if attempts >= self._max_recovery_attempts:
                logger.warning(
                    f"Max recovery attempts ({self._max_recovery_attempts}) "
                    f"reached for {sandbox_id}"
                )
                return False

            # Update attempt count
            await self._recovery_attempts.set(sandbox_id, attempts + 1)

            # Calculate backoff
            backoff = self._recovery_backoff_base * (2**attempts)
            logger.info(
                f"Attempting recovery for {sandbox_id} "
                f"(attempt {attempts + 1}/{self._max_recovery_attempts}, backoff={backoff}s)"
            )

            await asyncio.sleep(backoff)

            # Try to reconnect MCP
            if not result.mcp_connected and result.container_running:
                try:
                    connected = await self._adapter.connect_mcp(sandbox_id, timeout=30)
                    if connected:
                        logger.info(f"Recovery succeeded for {sandbox_id} (MCP reconnect)")
                        result.recovery_attempted = True
                        result.recovery_succeeded = True

                        # Reset recovery attempts on success
                        await self._recovery_attempts.delete(sandbox_id)

                        # Notify callbacks
                        for callback in self._on_recovered_callbacks:
                            try:
                                await callback(sandbox_id, result)
                            except Exception as e:
                                logger.error(f"Error in recovered callback: {e}")

                        return True
                except Exception as e:
                    logger.warning(f"MCP reconnect failed for {sandbox_id}: {e}")

            # If container not running, try rebuild
            if not result.container_running and hasattr(self._adapter, "_rebuild_sandbox"):
                # Check rebuild cooldown
                last_rebuild = await self._rebuild_timestamps.get(sandbox_id)
                if last_rebuild and (time.time() - last_rebuild) < 30:
                    logger.debug(f"Rebuild cooldown active for {sandbox_id}")
                    return False

                await self._rebuild_timestamps.set(sandbox_id, time.time())

                try:
                    # This would need the project_path which we might not have
                    # For now, just log and return false
                    logger.warning(
                        f"Container not running for {sandbox_id}, "
                        "rebuild would be needed but not implemented in monitor"
                    )
                except Exception as e:
                    logger.error(f"Rebuild failed for {sandbox_id}: {e}")

            result.recovery_attempted = True
            result.recovery_succeeded = False
            return False

        finally:
            async with self._recovering_lock:
                self._recovering.discard(sandbox_id)

    async def _send_heartbeats(self) -> None:
        """Send heartbeats to all connected MCP clients."""
        if not hasattr(self._adapter, "_active_sandboxes"):
            return

        sandbox_clients = []
        async with self._adapter._lock:
            for sandbox_id, instance in self._adapter._active_sandboxes.items():
                if instance.mcp_client and instance.mcp_client.is_connected:
                    sandbox_clients.append((sandbox_id, instance.mcp_client))

        for sandbox_id, client in sandbox_clients:
            try:
                # Send ping via WebSocket client.
                # Use a generous timeout (30s) to avoid false unhealthy reports
                # when the sandbox event loop is busy processing long tool calls.
                if hasattr(client, "ping"):
                    await asyncio.wait_for(client.ping(), timeout=30)
                elif hasattr(client, "_ws") and client._ws:
                    await asyncio.wait_for(client._ws.ping(), timeout=30)
            except Exception as e:
                logger.warning(f"Heartbeat failed for {sandbox_id}: {e}")
                # Mark for health check
                result = HealthCheckResult(
                    sandbox_id=sandbox_id,
                    healthy=False,
                    level=HealthCheckLevel.MCP,
                    error_message=f"Heartbeat failed: {e}",
                )
                await self._handle_unhealthy(sandbox_id, result)

    async def _cleanup_ttl_caches(self) -> None:
        """Clean up all TTL caches."""
        rebuild_cleaned = await self._rebuild_timestamps.cleanup_expired()
        recovery_cleaned = await self._recovery_attempts.cleanup_expired()
        results_cleaned = await self._last_health_results.cleanup_expired()

        total_cleaned = rebuild_cleaned + recovery_cleaned + results_cleaned
        if total_cleaned > 0:
            logger.debug(f"TTL cleanup: removed {total_cleaned} expired entries")

    async def get_health_status(self, sandbox_id: str) -> HealthCheckResult | None:
        """Get the last health check result for a sandbox."""
        return await self._last_health_results.get(sandbox_id)

    async def force_check(self, sandbox_id: str) -> HealthCheckResult:
        """Force an immediate health check for a sandbox."""
        result = await self.check_sandbox_health(sandbox_id, HealthCheckLevel.FULL)
        await self._last_health_results.set(sandbox_id, result)
        return result

    async def get_stats(self) -> dict[str, Any]:
        """Get health monitor statistics."""
        return {
            "running": self._running,
            "check_interval": self._check_interval,
            "heartbeat_interval": self._heartbeat_interval,
            "auto_recover": self._auto_recover,
            "recovering_count": len(self._recovering),
            "cache_sizes": {
                "rebuild_timestamps": await self._rebuild_timestamps.size(),
                "recovery_attempts": await self._recovery_attempts.size(),
                "health_results": await self._last_health_results.size(),
            },
        }
