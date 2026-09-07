"""Skill-Embedded MCP Manager.

Manages MCP server lifecycle for skills that declare MCP server dependencies.
Handles auto-start/stop with reference counting so shared servers only stop
when no skill needs them.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from src.domain.model.mcp.tool import MCPTool, MCPToolSchema
from src.infrastructure.agent.mcp.client import MCPClient

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SkillMCPConfig:
    """Declares an MCP server dependency for a skill.

    Attributes:
        server_name: Unique name identifying this MCP server.
        command: Executable to run (e.g., "npx", "uvx", "python").
        args: Command-line arguments for the executable.
        env: Additional environment variables merged with system env.
        auto_start: Whether to start the server when the skill activates.
    """

    server_name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    auto_start: bool = True


class SkillMCPManager:
    """Manages MCP server lifecycle tied to skill activation.

    Provides reference-counted server management so that:
    - Servers start when the first skill needing them activates.
    - Servers stop only when the last skill needing them deactivates.
    - Tools discovered from MCP servers are cached per server.

    Usage::

        manager = SkillMCPManager()
        manager.register_skill_mcps("my-skill", [
            SkillMCPConfig(server_name="fetch", command="npx",
                           args=["-y", "@anthropic/mcp-server-fetch"]),
        ])
        await manager.activate_skill("my-skill")
        tools = manager.get_skill_tools("my-skill")
        await manager.deactivate_skill("my-skill")
    """

    def __init__(self) -> None:
        self._skill_configs: dict[str, list[SkillMCPConfig]] = {}
        self._server_refcounts: dict[str, int] = {}
        self._active_clients: dict[str, MCPClient] = {}
        self._active_server_configs: dict[str, SkillMCPConfig] = {}
        self._active_skills: set[str] = set()
        self._server_tools: dict[str, list[MCPTool]] = {}
        self._lock = asyncio.Lock()

    @property
    def active_skills(self) -> frozenset[str]:
        """Return the set of currently active skill IDs."""
        return frozenset(self._active_skills)

    @property
    def active_servers(self) -> frozenset[str]:
        """Return the set of currently running server names."""
        return frozenset(self._active_clients.keys())

    def get_active_client(self, server_name: str) -> MCPClient | None:
        """Return the active MCP client for a server, if available."""
        return self._active_clients.get(server_name)

    def register_skill_mcps(
        self,
        skill_id: str,
        configs: list[SkillMCPConfig],
    ) -> None:
        """Register MCP server dependencies for a skill.

        Args:
            skill_id: Unique skill identifier.
            configs: List of MCP server configurations the skill needs.

        Raises:
            ValueError: If skill_id is empty or configs is empty.
        """
        if not skill_id:
            raise ValueError("skill_id cannot be empty")
        if not configs:
            raise ValueError("configs cannot be empty")

        self._skill_configs[skill_id] = list(configs)
        logger.info(
            "Registered %d MCP server(s) for skill %s: %s",
            len(configs),
            skill_id,
            [c.server_name for c in configs],
        )

    def unregister_skill_mcps(self, skill_id: str) -> None:
        """Remove MCP server registrations for a skill.

        If the skill is currently active, it will be deactivated first
        (synchronously removing from tracking; callers must handle
        async cleanup separately if the skill is active).

        Args:
            skill_id: Unique skill identifier.
        """
        if skill_id in self._active_skills:
            logger.warning(
                "Skill %s is still active during unregister; removing from tracking only",
                skill_id,
            )
            self._active_skills.discard(skill_id)

        self._skill_configs.pop(skill_id, None)
        logger.info("Unregistered MCP servers for skill %s", skill_id)

    async def activate_skill(self, skill_id: str) -> list[MCPTool]:
        """Activate a skill and start its required MCP servers.

        Increments reference counts for each server. Servers that are
        already running (ref > 0) are not restarted.

        Args:
            skill_id: Skill to activate.

        Returns:
            List of MCPTool objects available from the skill's servers.

        Raises:
            ValueError: If skill_id has no registered configs.
            RuntimeError: If an MCP server fails to start.
        """
        if skill_id not in self._skill_configs:
            raise ValueError(f"No MCP configs registered for skill '{skill_id}'")

        if skill_id in self._active_skills:
            logger.debug("Skill %s already active, returning cached tools", skill_id)
            return self.get_skill_tools(skill_id)

        configs = self._skill_configs[skill_id]
        started_servers: list[str] = []

        try:
            async with self._lock:
                for config in configs:
                    if not config.auto_start:
                        continue
                    await self._start_server_if_needed(config)
                    started_servers.append(config.server_name)

                self._active_skills.add(skill_id)
                logger.info("Activated skill %s", skill_id)
                return self.get_skill_tools(skill_id)

        except BaseException:
            # Roll back completed references in dependency-reverse order.
            # Cancellation is part of the lifecycle contract and must not
            # leave a zero-refcount client running.
            for server_name in reversed(started_servers):
                await self._stop_server_if_unused(server_name)
            raise

    async def deactivate_skill(self, skill_id: str) -> None:
        """Deactivate a skill and stop MCP servers no longer needed.

        Decrements reference counts. Servers are stopped only when
        their reference count reaches zero.

        Args:
            skill_id: Skill to deactivate.
        """
        if skill_id not in self._active_skills:
            logger.debug("Skill %s is not active, nothing to deactivate", skill_id)
            return

        configs = self._skill_configs.get(skill_id, [])

        async with self._lock:
            cleanup_error: BaseException | None = None
            for config in reversed(configs):
                if not config.auto_start:
                    continue
                try:
                    await self._stop_server_if_unused(config.server_name)
                except BaseException as exc:
                    if cleanup_error is None:
                        cleanup_error = exc

            self._active_skills.discard(skill_id)
            logger.info("Deactivated skill %s", skill_id)
            if cleanup_error is not None:
                raise cleanup_error

    def get_skill_tools(self, skill_id: str) -> list[MCPTool]:
        """Return all MCP tools available for a skill.

        Args:
            skill_id: Skill identifier.

        Returns:
            List of MCPTool objects from all servers the skill depends on.
        """
        configs = self._skill_configs.get(skill_id, [])
        tools: list[MCPTool] = []

        for config in configs:
            server_tools = self._server_tools.get(config.server_name, [])
            tools.extend(server_tools)

        return tools

    async def health_check(self) -> dict[str, bool]:
        """Check health of all active MCP servers.

        Returns:
            Dict mapping server_name to health status (True=healthy).
        """
        results: dict[str, bool] = {}

        for server_name, client in self._active_clients.items():
            try:
                healthy = await client.health_check()
                results[server_name] = healthy
            except Exception:
                logger.exception("Health check failed for server %s", server_name)
                results[server_name] = False

        return results

    async def restart_server(self, server_name: str) -> bool:
        """Restart a specific MCP server.

        Finds the config for the server, disconnects the old client,
        and starts a fresh one. Preserves the reference count.

        Args:
            server_name: Name of the server to restart.

        Returns:
            True if restart succeeded, False otherwise.
        """
        if server_name not in self._active_clients:
            logger.warning("Cannot restart server %s: not active", server_name)
            return False

        config = self._active_server_configs.get(server_name) or self._find_config_for_server(
            server_name
        )
        if config is None:
            logger.error("Cannot restart server %s: config not found", server_name)
            return False

        new_client: MCPClient | None = None
        try:
            async with self._lock:
                # Disconnect old client
                old_client = self._active_clients[server_name]
                await self._safe_disconnect(old_client)

                # Start new client
                new_client = self._create_client(config)
                await new_client.connect()
                self._active_clients[server_name] = new_client

                # Refresh tool cache
                await self._cache_server_tools(server_name, new_client)

                logger.info("Restarted MCP server %s", server_name)
                return True

        except Exception:
            logger.exception("Failed to restart MCP server %s", server_name)
            if new_client is not None:
                await self._safe_disconnect(new_client)
            # Remove broken client
            self._active_clients.pop(server_name, None)
            self._active_server_configs.pop(server_name, None)
            self._server_tools.pop(server_name, None)
            return False

    async def shutdown(self) -> None:
        """Disconnect all active MCP servers and reset state."""
        async with self._lock:
            for server_name, client in list(self._active_clients.items()):
                await self._safe_disconnect(client)
                logger.info("Shut down MCP server %s", server_name)

            self._active_clients.clear()
            self._active_server_configs.clear()
            self._server_refcounts.clear()
            self._server_tools.clear()
            self._active_skills.clear()

    def get_server_refcount(self, server_name: str) -> int:
        """Return the current reference count for a server.

        Args:
            server_name: Server to check.

        Returns:
            Current refcount (0 if server is not tracked).
        """
        return self._server_refcounts.get(server_name, 0)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _start_server_if_needed(self, config: SkillMCPConfig) -> None:
        """Start a server if not already running; always increment refcount."""
        server_name = config.server_name
        current_ref = self._server_refcounts.get(server_name, 0)

        if current_ref > 0:
            active_config = self._active_server_configs.get(server_name)
            if active_config is None or self._config_identity(
                active_config
            ) != self._config_identity(config):
                raise RuntimeError(
                    f"MCP server {server_name} is already active with a different configuration"
                )

        if current_ref == 0:
            # First reference -- actually start the server
            client = self._create_client(config)
            try:
                await client.connect()
                await self._cache_server_tools(server_name, client)
            except BaseException:
                try:
                    await self._safe_disconnect(client)
                finally:
                    self._active_clients.pop(server_name, None)
                    self._active_server_configs.pop(server_name, None)
                    self._server_tools.pop(server_name, None)
                    self._server_refcounts.pop(server_name, None)
                logger.error(
                    "Failed or cancelled while starting MCP server %s",
                    server_name,
                )
                raise

            self._active_clients[server_name] = client
            self._active_server_configs[server_name] = self._copy_config(config)
            logger.info("Started MCP server %s", server_name)

        self._server_refcounts[server_name] = current_ref + 1
        logger.debug(
            "Server %s refcount: %d -> %d",
            server_name,
            current_ref,
            current_ref + 1,
        )

    async def _stop_server_if_unused(self, server_name: str) -> None:
        """Decrement refcount and stop server if no longer needed."""
        self._decrement_refcount(server_name)

        if self._server_refcounts.get(server_name, 0) == 0:
            client = self._active_clients.pop(server_name, None)
            try:
                if client:
                    await self._safe_disconnect(client)
                    logger.info("Stopped MCP server %s (refcount=0)", server_name)
            finally:
                self._active_server_configs.pop(server_name, None)
                self._server_tools.pop(server_name, None)
                self._server_refcounts.pop(server_name, None)

    def _decrement_refcount(self, server_name: str) -> None:
        """Safely decrement a server's reference count."""
        current = self._server_refcounts.get(server_name, 0)
        if current > 0:
            self._server_refcounts[server_name] = current - 1

    def _create_client(self, config: SkillMCPConfig) -> MCPClient:
        """Create an MCPClient from a SkillMCPConfig."""
        transport_config: dict[str, Any] = {
            "command": config.command,
            "args": config.args,
        }
        if config.env:
            transport_config["env"] = config.env

        return MCPClient(
            server_type="stdio",
            transport_config=transport_config,
        )

    async def _cache_server_tools(self, server_name: str, client: MCPClient) -> None:
        """Discover and cache tools from a running MCP server."""
        try:
            raw_tools = await client.list_tools()
            tools: list[MCPTool] = []
            for raw_tool in raw_tools:
                schema = MCPToolSchema.from_dict(raw_tool)
                tool = MCPTool(
                    server_id=server_name,
                    server_name=server_name,
                    schema=schema,
                )
                tools.append(tool)
            self._server_tools[server_name] = tools
            logger.info("Cached %d tool(s) from server %s", len(tools), server_name)
        except Exception:
            logger.exception("Failed to list tools from server %s", server_name)
            self._server_tools.pop(server_name, None)
            raise

    @staticmethod
    def _config_identity(
        config: SkillMCPConfig,
    ) -> tuple[str, str, tuple[str, ...], tuple[tuple[str, str], ...], bool]:
        """Return an immutable identity without exposing environment values."""
        return (
            config.server_name,
            config.command,
            tuple(config.args),
            tuple(sorted(config.env.items())),
            config.auto_start,
        )

    @staticmethod
    def _copy_config(config: SkillMCPConfig) -> SkillMCPConfig:
        return SkillMCPConfig(
            server_name=config.server_name,
            command=config.command,
            args=list(config.args),
            env=dict(config.env),
            auto_start=config.auto_start,
        )

    def _find_config_for_server(self, server_name: str) -> SkillMCPConfig | None:
        """Find the first SkillMCPConfig matching a server name."""
        for configs in self._skill_configs.values():
            for config in configs:
                if config.server_name == server_name:
                    return config
        return None

    @staticmethod
    async def _safe_disconnect(client: MCPClient) -> None:
        """Disconnect a client, suppressing errors."""
        try:
            await client.disconnect()
        except Exception:
            logger.exception("Error disconnecting MCP client")
