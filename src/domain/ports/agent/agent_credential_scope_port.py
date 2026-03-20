"""Agent Credential Scope Port - per-agent credential isolation."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class AgentCredentialScopePort(Protocol):
    """Protocol for per-agent credential scope isolation.

    Provides isolated credential storage per agent within a project,
    ensuring agents cannot access each other's secrets or API keys.
    """

    async def get_credential(
        self,
        project_id: str,
        agent_id: str,
        credential_key: str,
    ) -> str | None:
        """Retrieve a credential from the agent's isolated scope."""
        ...

    async def set_credential(
        self,
        project_id: str,
        agent_id: str,
        credential_key: str,
        credential_value: str,
        ttl_seconds: int | None = None,
    ) -> None:
        """Store a credential in the agent's isolated scope."""
        ...

    async def delete_credential(
        self,
        project_id: str,
        agent_id: str,
        credential_key: str,
    ) -> bool:
        """Remove a credential. Returns True if it existed."""
        ...

    async def list_credential_keys(
        self,
        project_id: str,
        agent_id: str,
    ) -> list[str]:
        """List all credential keys for this agent (values not returned)."""
        ...

    async def has_credential(
        self,
        project_id: str,
        agent_id: str,
        credential_key: str,
    ) -> bool:
        """Check if a credential exists without retrieving its value."""
        ...

    async def clear_credentials(
        self,
        project_id: str,
        agent_id: str,
    ) -> int:
        """Remove all credentials for this agent. Returns count deleted."""
        ...
