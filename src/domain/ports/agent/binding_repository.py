"""
AgentBindingRepositoryPort for binding persistence.

Repository interface for persisting and retrieving agent bindings,
following the Repository pattern.
"""

from abc import ABC, abstractmethod

from src.domain.model.agent.agent_binding import AgentBinding


class AgentBindingRepositoryPort(ABC):
    """
    Repository port for agent binding persistence.

    Provides CRUD operations for agent bindings with
    tenant-level scoping. Bindings map channel contexts
    to specific agents for routing.
    """

    @abstractmethod
    async def create(self, binding: AgentBinding) -> AgentBinding:
        """
        Create a new agent binding.

        Args:
            binding: AgentBinding to create

        Returns:
            Created binding

        Raises:
            ValueError: If binding data is invalid
        """

    @abstractmethod
    async def get_by_id(
        self,
        binding_id: str,
    ) -> AgentBinding | None:
        """
        Get a binding by its ID.

        Args:
            binding_id: Binding ID

        Returns:
            AgentBinding if found, None otherwise
        """

    @abstractmethod
    async def delete(self, binding_id: str) -> bool:
        """
        Delete a binding by ID.

        Args:
            binding_id: Binding ID to delete

        Raises:
            ValueError: If binding not found
        """

    @abstractmethod
    async def list_by_agent(
        self,
        agent_id: str,
        enabled_only: bool = False,
    ) -> list[AgentBinding]:
        """
        List all bindings for an agent.

        Args:
            agent_id: Agent ID
            enabled_only: If True, only return enabled bindings

        Returns:
            List of bindings for the agent
        """

    @abstractmethod
    async def list_by_tenant(
        self,
        tenant_id: str,
        enabled_only: bool = False,
    ) -> list[AgentBinding]:
        """
        List all bindings for a tenant.

        Args:
            tenant_id: Tenant ID
            enabled_only: If True, only return enabled bindings

        Returns:
            List of bindings for the tenant
        """

    @abstractmethod
    async def resolve_binding(
        self,
        tenant_id: str,
        channel_type: str | None = None,
        channel_id: str | None = None,
        account_id: str | None = None,
        peer_id: str | None = None,
    ) -> AgentBinding | None:
        """
        Resolve the best matching binding for a channel context.

        Uses specificity-based resolution (most-specific wins).

        Args:
            tenant_id: Tenant ID
            channel_type: Channel type filter
            channel_id: Channel instance filter
            account_id: User account filter
            peer_id: Peer identity filter

        Returns:
            Most specific matching binding, or None
        """

    @abstractmethod
    async def set_enabled(
        self,
        binding_id: str,
        enabled: bool,
    ) -> AgentBinding:
        """
        Enable or disable a binding.

        Args:
            binding_id: Binding ID
            enabled: Whether to enable or disable

        Returns:
            Updated binding

        Raises:
            ValueError: If binding not found
        """
