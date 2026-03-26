"""Agent Namespace Port - per-agent state keyspace isolation."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class AgentNamespacePort(Protocol):
    """Protocol for per-agent state namespace isolation.

    Each agent gets an isolated keyspace within a project scope,
    following the pattern: agent:state:{project_id}:{agent_id}:*
    """

    async def get_key(
        self,
        project_id: str,
        agent_id: str,
        key: str,
    ) -> str | None:
        """Retrieve a value from the agent's isolated namespace."""
        ...

    async def set_key(
        self,
        project_id: str,
        agent_id: str,
        key: str,
        value: str,
        ttl_seconds: int | None = None,
    ) -> None:
        """Store a value in the agent's isolated namespace."""
        ...

    async def delete_key(
        self,
        project_id: str,
        agent_id: str,
        key: str,
    ) -> bool:
        """Remove a key from the agent's namespace. Returns True if key existed."""
        ...

    async def list_keys(
        self,
        project_id: str,
        agent_id: str,
        pattern: str = "*",
    ) -> list[str]:
        """List keys in the agent's namespace matching a glob pattern."""
        ...

    async def clear_namespace(
        self,
        project_id: str,
        agent_id: str,
    ) -> int:
        """Remove all keys in the agent's namespace. Returns count of deleted keys."""
        ...

    async def get_many(
        self,
        project_id: str,
        agent_id: str,
        keys: list[str],
    ) -> dict[str, str | None]:
        """Retrieve multiple values from the agent's namespace."""
        ...

    async def set_many(
        self,
        project_id: str,
        agent_id: str,
        mapping: dict[str, str],
        ttl_seconds: int | None = None,
    ) -> None:
        """Store multiple key-value pairs in the agent's namespace."""
        ...
