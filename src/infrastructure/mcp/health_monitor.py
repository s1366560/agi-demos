"""MCP Server Health Monitor.

Provides health checking, automatic restart, and resource monitoring
for MCP servers running inside sandbox containers.

Features:
- Periodic health checks with configurable intervals
- Automatic restart of unhealthy servers
- Resource usage monitoring (CPU, memory, uptime)
- Graceful shutdown with cleanup
- Restart count tracking to prevent infinite restarts
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import MCPSandboxAdapter


@dataclass
class MCPServerHealth:
    """Health status of an MCP server.

    Attributes:
        name: Server name.
        status: Health status - "healthy", "unhealthy", or "unknown".
        last_check: Timestamp of last health check.
        error_message: Error message if unhealthy.
        restart_count: Number of times server has been restarted.
    """

    name: str
    status: str  # "healthy", "unhealthy", "unknown"
    last_check: datetime
    error_message: str | None = None
    restart_count: int = 0


@dataclass
class MCPServerResourceUsage:
    """Resource usage metrics for an MCP server.

    Attributes:
        server_name: Server name.
        cpu_percent: CPU usage percentage (0-100).
        memory_mb: Memory usage in megabytes.
        uptime_seconds: Server uptime in seconds.
    """

    server_name: str
    cpu_percent: float | None = None
    memory_mb: float | None = None
    uptime_seconds: float | None = None


class MCPServerHealthMonitor:
    """Monitors and manages health of MCP servers in sandboxes.

    Provides periodic health checking, automatic restart capabilities,
    and resource usage monitoring for MCP servers.

    Usage:
        monitor = MCPServerHealthMonitor(sandbox_adapter)

        # Start monitoring a sandbox's servers
        await monitor.start_monitoring("sandbox-1")

        # Check health manually
        health = await monitor.health_check("sandbox-1", "my-server")

        # Restart if unhealthy
        restarted = await monitor.restart_if_unhealthy("sandbox-1", "my-server")

        # Get resource usage
        usage = await monitor.get_resource_usage("sandbox-1", "my-server")

        # Stop monitoring
        await monitor.stop_monitoring("sandbox-1")

        # Or shutdown all
        await monitor.shutdown()
    """

    def __init__(
        self,
        sandbox_adapter: MCPSandboxAdapter,
        check_interval_seconds: float = 30.0,
        health_check_timeout: float = 10.0,
    ) -> None:
        """Initialize the health monitor.

        Args:
            sandbox_adapter: Sandbox adapter for calling MCP tools.
            check_interval_seconds: Interval between health checks.
            health_check_timeout: Timeout for health check operations.
        """
        self._sandbox_adapter = sandbox_adapter
        self._check_interval_seconds = check_interval_seconds
        self._health_check_timeout = health_check_timeout

        # Active monitoring tasks
        self._monitoring_tasks: dict[str, asyncio.Task[None]] = {}

        # Server configurations for restart (sandbox_id -> {server_name -> config})
        self._server_configs: dict[str, dict[str, dict[str, Any]]] = {}

        # Restart counts per server
        self._restart_counts: dict[str, int] = {}

        # Running flag for monitoring loops
        self._running: dict[str, bool] = {}

    async def health_check(
        self,
        sandbox_id: str,
        server_name: str,
    ) -> MCPServerHealth:
        """Check health of a single MCP server.

        Queries the sandbox's mcp_server_list tool to check if
        the server is running and responding.

        Args:
            sandbox_id: Sandbox container ID.
            server_name: MCP server name.

        Returns:
            MCPServerHealth with current status.
        """
        now = datetime.utcnow()

        try:
            result = await asyncio.wait_for(
                self._sandbox_adapter.call_tool(
                    sandbox_id=sandbox_id,
                    tool_name="mcp_server_list",
                    arguments={},
                ),
                timeout=self._health_check_timeout,
            )

            # Parse result - expect a list of servers
            servers_data = self._parse_tool_result(result)

            # Find our server in the list
            server_status = None
            if isinstance(servers_data, list):
                for server in servers_data:
                    if isinstance(server, dict) and server.get("name") == server_name:
                        server_status = server.get("status")
                        break
            elif isinstance(servers_data, dict):
                # Handle case where result is wrapped
                servers_list = servers_data.get("servers", [servers_data])
                for server in servers_list:
                    if isinstance(server, dict) and server.get("name") == server_name:
                        server_status = server.get("status")
                        break

            if server_status is None:
                # Server not found in list - either not installed or removed
                return MCPServerHealth(
                    name=server_name,
                    status="unhealthy",
                    last_check=now,
                    error_message="Server not found",
                    restart_count=self._restart_counts.get(server_name, 0),
                )

            if server_status == "running":
                return MCPServerHealth(
                    name=server_name,
                    status="healthy",
                    last_check=now,
                    restart_count=self._restart_counts.get(server_name, 0),
                )
            elif server_status in ("stopped", "failed", "crashed"):
                return MCPServerHealth(
                    name=server_name,
                    status="unhealthy",
                    last_check=now,
                    error_message=f"Server {server_status}",
                    restart_count=self._restart_counts.get(server_name, 0),
                )
            else:
                return MCPServerHealth(
                    name=server_name,
                    status="unknown",
                    last_check=now,
                    error_message=f"Unknown status: {server_status}",
                    restart_count=self._restart_counts.get(server_name, 0),
                )

        except TimeoutError:
            return MCPServerHealth(
                name=server_name,
                status="unhealthy",
                last_check=now,
                error_message="Health check timed out",
                restart_count=self._restart_counts.get(server_name, 0),
            )
        except Exception as e:
            return MCPServerHealth(
                name=server_name,
                status="unhealthy",
                last_check=now,
                error_message=str(e),
                restart_count=self._restart_counts.get(server_name, 0),
            )

    async def restart_if_unhealthy(
        self,
        sandbox_id: str,
        server_name: str,
        max_restarts: int = 3,
    ) -> bool:
        """Restart server if unhealthy.

        Checks server health and performs restart if needed.
        Respects max_restarts limit to prevent infinite restarts.

        Args:
            sandbox_id: Sandbox container ID.
            server_name: MCP server name.
            max_restarts: Maximum restarts allowed.

        Returns:
            True if server was restarted, False otherwise.
        """
        restart_info = await self._should_restart(sandbox_id, server_name, max_restarts)
        if restart_info is None:
            return False

        try:
            return await self._perform_restart(
                sandbox_id,
                server_name,
                restart_info["server_type"],
                restart_info["transport_config"],
            )
        except Exception as e:
            logger.error(f"Error restarting server '{server_name}': {e}")
            return False

    async def _should_restart(
        self,
        sandbox_id: str,
        server_name: str,
        max_restarts: int,
    ) -> dict[str, Any] | None:
        """Check whether a server needs and can be restarted.

        Returns:
            Server config dict with server_type and transport_config if restart
            should proceed, or None if restart is not needed/allowed.
        """
        health = await self.health_check(sandbox_id, server_name)

        if health.status == "healthy":
            logger.debug(f"Server '{server_name}' is healthy, no restart needed")
            return None

        current_restarts = self._restart_counts.get(server_name, 0)
        if current_restarts >= max_restarts:
            logger.warning(
                f"Server '{server_name}' exceeded max restarts "
                f"({current_restarts}/{max_restarts}), not restarting"
            )
            return None

        config = self._get_server_config(sandbox_id, server_name)
        if not config:
            logger.warning(f"No config found for server '{server_name}', cannot restart")
            return None

        return {
            "server_type": config.get("server_type", "stdio"),
            "transport_config": config.get("transport_config", {}),
        }

    async def _perform_restart(
        self,
        sandbox_id: str,
        server_name: str,
        server_type: str,
        transport_config: dict[str, Any],
    ) -> bool:
        """Execute stop-install-start restart sequence.

        Returns:
            True if server was restarted successfully, False otherwise.
        """
        # Stop server first (in case it's in a bad state)
        await self._sandbox_adapter.call_tool(
            sandbox_id=sandbox_id,
            tool_name="mcp_server_stop",
            arguments={"name": server_name},
        )

        # Reinstall
        install_result = await self._sandbox_adapter.call_tool(
            sandbox_id=sandbox_id,
            tool_name="mcp_server_install",
            arguments={
                "name": server_name,
                "server_type": server_type,
                "transport_config": json.dumps(transport_config),
            },
        )
        install_data = self._parse_tool_result(install_result)
        if not install_data.get("success", False):
            error = install_data.get("error", "Install failed")
            logger.error(f"Failed to reinstall server '{server_name}': {error}")
            return False

        # Start
        start_result = await self._sandbox_adapter.call_tool(
            sandbox_id=sandbox_id,
            tool_name="mcp_server_start",
            arguments={
                "name": server_name,
                "server_type": server_type,
                "transport_config": json.dumps(transport_config),
            },
        )
        start_data = self._parse_tool_result(start_result)
        if not start_data.get("success", False):
            error = start_data.get("error", "Start failed")
            logger.error(f"Failed to start server '{server_name}': {error}")
            return False

        # Increment restart count
        current_restarts = self._restart_counts.get(server_name, 0)
        self._restart_counts[server_name] = current_restarts + 1

        logger.info(
            f"Successfully restarted server '{server_name}' "
            f"(restart #{self._restart_counts[server_name]})"
        )
        return True

    async def get_resource_usage(
        self,
        sandbox_id: str,
        server_name: str,
    ) -> MCPServerResourceUsage | None:
        """Get resource usage for an MCP server.

        Args:
            sandbox_id: Sandbox container ID.
            server_name: MCP server name.

        Returns:
            MCPServerResourceUsage or None on failure.
        """
        try:
            result = await asyncio.wait_for(
                self._sandbox_adapter.call_tool(
                    sandbox_id=sandbox_id,
                    tool_name="mcp_server_stats",
                    arguments={"name": server_name},
                ),
                timeout=self._health_check_timeout,
            )

            stats_data = self._parse_tool_result(result)

            if isinstance(stats_data, dict):
                return MCPServerResourceUsage(
                    server_name=server_name,
                    cpu_percent=stats_data.get("cpu_percent"),
                    memory_mb=stats_data.get("memory_mb"),
                    uptime_seconds=stats_data.get("uptime_seconds"),
                )

            return MCPServerResourceUsage(server_name=server_name)

        except Exception as e:
            logger.warning(f"Failed to get resource usage for '{server_name}': {e}")
            return None

    async def start_monitoring(self, sandbox_id: str) -> None:
        """Start background monitoring for a sandbox.

        Spawns an async task that periodically checks server health.

        Args:
            sandbox_id: Sandbox container ID.
        """
        if sandbox_id in self._monitoring_tasks:
            logger.debug(f"Monitoring already running for sandbox {sandbox_id}")
            return

        self._running[sandbox_id] = True

        async def monitoring_loop() -> None:
            while self._running.get(sandbox_id, False):
                try:
                    # Get list of servers to monitor
                    servers = await self._get_monitored_servers(sandbox_id)

                    for server_name, server_type, transport_config in servers:
                        # Store config for potential restart
                        self._store_server_config(
                            sandbox_id, server_name, server_type, transport_config
                        )

                        # Check health
                        health = await self.health_check(sandbox_id, server_name)

                        if health.status == "unhealthy":
                            logger.info(f"Server '{server_name}' is unhealthy, attempting restart")
                            await self.restart_if_unhealthy(sandbox_id, server_name)

                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"Error in monitoring loop for {sandbox_id}: {e}")

                # Wait for next check interval
                await asyncio.sleep(self._check_interval_seconds)

        task = asyncio.create_task(monitoring_loop())
        self._monitoring_tasks[sandbox_id] = task
        logger.info(f"Started monitoring for sandbox {sandbox_id}")

    async def stop_monitoring(self, sandbox_id: str) -> None:
        """Stop monitoring for a sandbox.

        Args:
            sandbox_id: Sandbox container ID.
        """
        self._running[sandbox_id] = False

        task = self._monitoring_tasks.pop(sandbox_id, None)
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            logger.info(f"Stopped monitoring for sandbox {sandbox_id}")

    async def shutdown(self) -> None:
        """Stop all monitoring tasks.

        Should be called during application shutdown.
        """
        sandbox_ids = list(self._monitoring_tasks.keys())
        for sandbox_id in sandbox_ids:
            await self.stop_monitoring(sandbox_id)

        logger.info("Health monitor shutdown complete")

    def register_server(
        self,
        sandbox_id: str,
        server_name: str,
        server_type: str,
        transport_config: dict[str, Any],
    ) -> None:
        """Register a server for monitoring.

        Call this when a server is installed/started to enable
        the monitor to restart it if needed.

        Args:
            sandbox_id: Sandbox container ID.
            server_name: MCP server name.
            server_type: Server type (stdio, sse, etc).
            transport_config: Transport configuration.
        """
        self._store_server_config(sandbox_id, server_name, server_type, transport_config)

    def unregister_server(self, sandbox_id: str, server_name: str) -> None:
        """Unregister a server from monitoring.

        Args:
            sandbox_id: Sandbox container ID.
            server_name: MCP server name.
        """
        if sandbox_id in self._server_configs:
            self._server_configs[sandbox_id].pop(server_name, None)

        # Also clear restart count
        self._restart_counts.pop(server_name, None)

    def reset_restart_count(self, server_name: str) -> None:
        """Reset the restart count for a server.

        Call this after a server has been stable for a while.

        Args:
            server_name: MCP server name.
        """
        self._restart_counts.pop(server_name, None)

    # Private methods

    def _store_server_config(
        self,
        sandbox_id: str,
        server_name: str,
        server_type: str,
        transport_config: dict[str, Any],
    ) -> None:
        """Store server configuration for potential restart."""
        if sandbox_id not in self._server_configs:
            self._server_configs[sandbox_id] = {}

        self._server_configs[sandbox_id][server_name] = {
            "server_type": server_type,
            "transport_config": transport_config,
        }

    def _get_server_config(self, sandbox_id: str, server_name: str) -> dict[str, Any] | None:
        """Get stored server configuration."""
        return self._server_configs.get(sandbox_id, {}).get(server_name)

    async def _get_monitored_servers(
        self, sandbox_id: str
    ) -> list[tuple[str, str, dict[str, Any]]]:
        """Get list of servers to monitor for a sandbox.

        Returns:
            List of (server_name, server_type, transport_config) tuples.
        """
        servers = []

        # Get servers from stored configs
        if sandbox_id in self._server_configs:
            for name, config in self._server_configs[sandbox_id].items():
                servers.append(
                    (
                        name,
                        config.get("server_type", "stdio"),
                        config.get("transport_config", {}),
                    )
                )

        # Also query sandbox for running servers
        try:
            result = await self._sandbox_adapter.call_tool(
                sandbox_id=sandbox_id,
                tool_name="mcp_server_list",
                arguments={},
            )

            server_list = self._parse_tool_result(result)
            if isinstance(server_list, list):
                existing_names = {s[0] for s in servers}
                for server in server_list:
                    name = server.get("name", "")
                    if name and name not in existing_names:
                        servers.append(
                            (
                                name,
                                server.get("server_type", "stdio"),
                                server.get("transport_config", {}),
                            )
                        )

        except Exception as e:
            logger.warning(f"Failed to list servers for monitoring: {e}")

        return servers

    @staticmethod
    def _parse_tool_result(result: dict[str, Any]) -> Any:
        """Parse tool result content, extracting JSON if present."""
        content = result.get("content", [])
        if not content:
            return result

        # Extract text from content items
        text_parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text_parts.append(item.get("text", ""))

        text = "\n".join(text_parts)
        if not text:
            return result

        # Try to parse as JSON
        try:
            return json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return text
