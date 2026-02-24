"""Sandbox Tool Registry Service.

Manages dynamic registration of Sandbox MCP tools to Agent tool context.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from redis.asyncio import Redis

    from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import MCPSandboxAdapter


@dataclass
class SandboxToolRegistration:
    """Record of a sandbox's tool registration."""

    sandbox_id: str
    project_id: str
    tenant_id: str
    tool_names: list[str] = field(default_factory=list)
    registered_at: datetime = field(default_factory=datetime.now)

    def age_seconds(self) -> int:
        """Get age of registration in seconds."""
        return (datetime.now() - self.registered_at).total_seconds()


class SandboxToolRegistry:
    """
    Registry for managing Sandbox tool registration in Agent context.

    This service handles:
    - Registering Sandbox MCP tools as Agent tools
    - Tracking sandbox-to-project mappings
    - Cleaning up tools when sandboxes are terminated
    """

    def __init__(
        self,
        redis_client: Redis | None = None,
        mcp_adapter: MCPSandboxAdapter | None = None,
    ) -> None:
        """
        Initialize the registry.

        Args:
            redis_client: Redis client for caching (optional)
            mcp_adapter: MCPSandboxAdapter for tool loading (optional)
        """
        self._redis = redis_client
        self._mcp_adapter = mcp_adapter
        self._registrations: dict[str, SandboxToolRegistration] = {}

        # Redis key patterns
        self._key_prefix = "sandbox:tools:"
        self._tracking_key = "sandbox:tools:tracking"

    async def register_sandbox_tools(
        self,
        sandbox_id: str,
        project_id: str,
        tenant_id: str,
        tools: list[str] | None = None,
    ) -> list[str]:
        """
        Register a sandbox's MCP tools to the Agent tool context.

        Args:
            sandbox_id: The sandbox instance ID
            project_id: Project ID for tool caching
            tenant_id: Tenant ID for permission scoping
            tools: Optional pre-loaded tool list (if None, will fetch from adapter)

        Returns:
            List of registered tool names (namespaced)
        """
        logger.info(
            f"[SandboxToolRegistry] Registering tools for sandbox={sandbox_id}, "
            f"project={project_id}"
        )

        # If tools not provided, fetch from MCP adapter
        if tools is None and self._mcp_adapter:
            try:
                tool_list = await self._mcp_adapter.list_tools(sandbox_id)
                tools = [t["name"] for t in tool_list]
                logger.info(
                    f"[SandboxToolRegistry] Fetched {len(tools)} tools from sandbox={sandbox_id}"
                )
            except Exception as e:
                logger.warning(
                    f"[SandboxToolRegistry] Failed to fetch tools from sandbox={sandbox_id}: {e}"
                )
                return []

        if not tools:
            logger.warning(f"[SandboxToolRegistry] No tools to register for sandbox={sandbox_id}")
            return []

        # Create registration record
        registration = SandboxToolRegistration(
            sandbox_id=sandbox_id,
            project_id=project_id,
            tenant_id=tenant_id,
            tool_names=tools,
        )
        self._registrations[sandbox_id] = registration

        # Update Redis cache if available
        if self._redis:
            await self._save_to_redis(registration)

        logger.info(f"[SandboxToolRegistry] Registered {len(tools)} tools for sandbox={sandbox_id}")

        return tools

    async def unregister_sandbox_tools(
        self,
        sandbox_id: str,
    ) -> bool:
        """
        Remove a sandbox's tools from the registry.

        Args:
            sandbox_id: The sandbox instance ID

        Returns:
            True if tools were unregistered, False if sandbox not found
        """
        if sandbox_id not in self._registrations:
            logger.warning(f"[SandboxToolRegistry] Sandbox {sandbox_id} not found in registry")
            return False

        registration = self._registrations.pop(sandbox_id)

        # Clear from Redis
        if self._redis:
            await self._clear_from_redis(sandbox_id, registration.project_id)

        logger.info(
            f"[SandboxToolRegistry] Unregistered {len(registration.tool_names)} tools "
            f"for sandbox={sandbox_id}"
        )

        return True

    async def get_sandbox_tools(
        self,
        sandbox_id: str,
    ) -> list[str] | None:
        """
        Get tool names registered for a sandbox.

        Args:
            sandbox_id: The sandbox instance ID

        Returns:
            List of tool names, or None if sandbox not registered
        """
        registration = self._registrations.get(sandbox_id)
        return registration.tool_names if registration else None

    async def get_project_sandboxes(
        self,
        project_id: str,
    ) -> list[str]:
        """
        Get all sandbox IDs registered for a project.

        Args:
            project_id: Project ID

        Returns:
            List of sandbox IDs
        """
        return [
            reg.sandbox_id for reg in self._registrations.values() if reg.project_id == project_id
        ]

    def is_sandbox_active(
        self,
        sandbox_id: str,
        max_age_seconds: int = 3600,
    ) -> bool:
        """
        Check if a sandbox registration is still valid.

        Args:
            sandbox_id: Sandbox ID to check
            max_age_seconds: Maximum age before considered stale

        Returns:
            True if registration exists and is fresh
        """
        registration = self._registrations.get(sandbox_id)
        if not registration:
            return False

        # Check age
        return registration.age_seconds() < max_age_seconds

    async def cleanup_expired_registrations(
        self,
        max_age_seconds: int = 3600,
    ) -> int:
        """
        Remove registrations for expired sandboxes.

        Args:
            max_age_seconds: Maximum age before cleanup

        Returns:
            Number of registrations cleaned up
        """
        expired_ids = [
            sandbox_id
            for sandbox_id, registration in self._registrations.items()
            if registration.age_seconds() > max_age_seconds
        ]

        for sandbox_id in expired_ids:
            await self.unregister_sandbox_tools(sandbox_id)

        logger.info(f"[SandboxToolRegistry] Cleaned up {len(expired_ids)} expired registrations")

        return len(expired_ids)

    async def _save_to_redis(self, registration: SandboxToolRegistration) -> None:
        """Save registration to Redis cache."""
        try:
            # Save registration record
            reg_key = f"{self._key_prefix}{registration.sandbox_id}"
            reg_data = {
                "sandbox_id": registration.sandbox_id,
                "project_id": registration.project_id,
                "tenant_id": registration.tenant_id,
                "tool_names": registration.tool_names,
                "registered_at": registration.registered_at.isoformat(),
            }
            await self._redis.set(
                reg_key,
                str(reg_data),
                ex=3600,  # 1 hour TTL
            )

            # Add to tracking index
            await self._redis.sadd(
                self._tracking_key,
                registration.sandbox_id,
            )

            # Update project index
            project_key = f"{self._key_prefix}project:{registration.project_id}"
            await self._redis.sadd(project_key, registration.sandbox_id)

        except Exception as e:
            logger.warning(f"[SandboxToolRegistry] Failed to save to Redis: {e}")

    async def _clear_from_redis(
        self,
        sandbox_id: str,
        project_id: str,
    ) -> None:
        """Clear registration from Redis cache."""
        try:
            # Remove registration record
            reg_key = f"{self._key_prefix}{sandbox_id}"
            await self._redis.delete(reg_key)

            # Remove from tracking index
            await self._redis.srem(self._tracking_key, sandbox_id)

            # Remove from project index
            project_key = f"{self._key_prefix}project:{project_id}"
            await self._redis.srem(project_key, sandbox_id)

        except Exception as e:
            logger.warning(f"[SandboxToolRegistry] Failed to clear from Redis: {e}")

    async def load_from_redis(self, sandbox_id: str) -> SandboxToolRegistration | None:
        """Load registration from Redis cache."""
        if not self._redis:
            return None

        try:
            reg_key = f"{self._key_prefix}{sandbox_id}"
            data = await self._redis.get(reg_key)
            if not data:
                return None

            # Parse JSON (stored as str(dict) format)
            reg_data = json.loads(data)

            return SandboxToolRegistration(
                sandbox_id=reg_data["sandbox_id"],
                project_id=reg_data["project_id"],
                tenant_id=reg_data["tenant_id"],
                tool_names=reg_data["tool_names"],
                registered_at=datetime.fromisoformat(reg_data["registered_at"]),
            )

        except Exception as e:
            logger.warning(f"[SandboxToolRegistry] Failed to load from Redis: {e}")
            return None

    async def restore_from_redis(self, sandbox_id: str) -> bool:
        """
        Restore registration from Redis to in-memory cache.

        Args:
            sandbox_id: Sandbox ID to restore

        Returns:
            True if restored, False if not found
        """
        if sandbox_id in self._registrations:
            # Already in memory
            return True

        registration = await self.load_from_redis(sandbox_id)
        if registration:
            self._registrations[sandbox_id] = registration
            logger.info(f"[SandboxToolRegistry] Restored registration for sandbox={sandbox_id}")
            return True

        return False

    async def refresh_all_from_redis(self) -> int:
        """
        Refresh all registrations from Redis.

        Loads all sandbox IDs from tracking index and restores
        their registrations to in-memory cache.

        Returns:
            Number of registrations restored
        """
        if not self._redis:
            return 0

        try:
            # Get all sandbox IDs from tracking index
            sandbox_ids = await self._redis.smembers(self._tracking_key)

            restored_count = 0
            for sandbox_id in sandbox_ids:
                if await self.restore_from_redis(sandbox_id):
                    restored_count += 1

            logger.info(
                f"[SandboxToolRegistry] Refreshed {restored_count} registrations from Redis"
            )

            return restored_count

        except Exception as e:
            logger.warning(f"[SandboxToolRegistry] Failed to refresh from Redis: {e}")
            return 0

    async def get_or_restore_registration(self, sandbox_id: str) -> SandboxToolRegistration | None:
        """
        Get registration from memory or restore from Redis.

        This is the preferred method for accessing registrations
        as it handles cache misses automatically.

        Args:
            sandbox_id: Sandbox ID

        Returns:
            Registration or None if not found
        """
        # Check in-memory cache first
        if sandbox_id in self._registrations:
            return self._registrations[sandbox_id]

        # Try to restore from Redis
        await self.restore_from_redis(sandbox_id)

        return self._registrations.get(sandbox_id)
