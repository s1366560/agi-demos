"""
AgentRegistryPort for agent persistence.

Repository interface for persisting and retrieving agents,
following the Repository pattern.
"""

from abc import ABC, abstractmethod

from src.domain.model.agent.agent_definition import Agent


class AgentRegistryPort(ABC):
    """
    Registry port for agent persistence.

    Provides CRUD operations for agents with tenant-level
    scoping. Agents are shared across projects within a tenant
    but isolated between tenants.
    """

    @abstractmethod
    async def create(self, agent: Agent) -> Agent:
        """
        Create a new agent.

        Args:
            agent: Agent to create

        Returns:
            Created agent with generated ID

        Raises:
            ValueError: If agent data is invalid or name exists
        """

    @abstractmethod
    async def get_by_id(
        self,
        agent_id: str,
        *,
        tenant_id: str | None = None,
        project_id: str | None = None,
    ) -> Agent | None:
        """
        Get an agent by its ID.

        Args:
            agent_id: Agent ID
            tenant_id: Optional tenant context for built-in agents
            project_id: Optional project context for built-in agents

        Returns:
            Agent if found, None otherwise
        """

    @abstractmethod
    async def get_by_name(
        self,
        tenant_id: str,
        name: str,
    ) -> Agent | None:
        """
        Get an agent by name within a tenant.

        Args:
            tenant_id: Tenant ID
            name: Agent name

        Returns:
            Agent if found, None otherwise
        """

    @abstractmethod
    async def update(self, agent: Agent) -> Agent:
        """
        Update an existing agent.

        Args:
            agent: Agent to update

        Returns:
            Updated agent

        Raises:
            ValueError: If agent not found or data is invalid
        """

    @abstractmethod
    async def delete(self, agent_id: str) -> bool:
        """
        Delete an agent by ID.

        Args:
            agent_id: Agent ID to delete

        Raises:
            ValueError: If agent not found
        """

    @abstractmethod
    async def list_by_tenant(
        self,
        tenant_id: str,
        enabled_only: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Agent]:
        """
        List all agents for a tenant.

        Args:
            tenant_id: Tenant ID
            enabled_only: If True, only return enabled agents
            limit: Maximum number of results
            offset: Number of results to skip

        Returns:
            List of agents for the tenant
        """

    @abstractmethod
    async def list_by_project(
        self,
        project_id: str,
        tenant_id: str | None = None,
        enabled_only: bool = False,
    ) -> list[Agent]:
        """
        List agents for a project, including tenant-wide ones.

        When tenant_id is provided, includes tenant-wide agents
        (project_id IS NULL) scoped to that tenant.

        Args:
            project_id: Project ID
            tenant_id: Optional tenant ID for tenant-wide agents
            enabled_only: If True, only return enabled agents

        Returns:
            List of agents for the project
        """

    @abstractmethod
    async def set_enabled(
        self,
        agent_id: str,
        enabled: bool,
    ) -> Agent:
        """
        Enable or disable an agent.

        Args:
            agent_id: Agent ID
            enabled: Whether to enable or disable

        Returns:
            Updated agent

        Raises:
            ValueError: If agent not found
        """

    @abstractmethod
    async def update_statistics(
        self,
        agent_id: str,
        execution_time_ms: float,
        success: bool,
    ) -> Agent:
        """
        Update execution statistics for an agent.

        Args:
            agent_id: Agent ID
            execution_time_ms: Execution time in milliseconds
            success: Whether the execution was successful

        Returns:
            Updated agent

        Raises:
            ValueError: If agent not found
        """

    @abstractmethod
    async def count_by_tenant(
        self,
        tenant_id: str,
        enabled_only: bool = False,
    ) -> int:
        """
        Count agents for a tenant.

        Args:
            tenant_id: Tenant ID
            enabled_only: If True, only count enabled agents

        Returns:
            Number of agents
        """
