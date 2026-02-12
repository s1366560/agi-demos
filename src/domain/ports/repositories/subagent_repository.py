"""
SubAgentRepository port for subagent persistence.

Repository interface for persisting and retrieving subagents,
following the Repository pattern.
"""

from abc import ABC, abstractmethod
from typing import List, Optional

from src.domain.model.agent.subagent import SubAgent


class SubAgentRepositoryPort(ABC):
    """
    Repository port for subagent persistence.

    Provides CRUD operations for subagents with tenant-level
    scoping. SubAgents are shared across projects within a tenant
    but isolated between tenants.
    """

    @abstractmethod
    async def create(self, subagent: SubAgent) -> SubAgent:
        """
        Create a new subagent.

        Args:
            subagent: SubAgent to create

        Returns:
            Created subagent with generated ID

        Raises:
            ValueError: If subagent data is invalid or name already exists
        """
        pass

    @abstractmethod
    async def get_by_id(self, subagent_id: str) -> Optional[SubAgent]:
        """
        Get a subagent by its ID.

        Args:
            subagent_id: SubAgent ID

        Returns:
            SubAgent if found, None otherwise
        """
        pass

    @abstractmethod
    async def get_by_name(
        self,
        tenant_id: str,
        name: str,
    ) -> Optional[SubAgent]:
        """
        Get a subagent by name within a tenant.

        Args:
            tenant_id: Tenant ID
            name: SubAgent name

        Returns:
            SubAgent if found, None otherwise
        """
        pass

    @abstractmethod
    async def update(self, subagent: SubAgent) -> SubAgent:
        """
        Update an existing subagent.

        Args:
            subagent: SubAgent to update

        Returns:
            Updated subagent

        Raises:
            ValueError: If subagent not found or data is invalid
        """
        pass

    @abstractmethod
    async def delete(self, subagent_id: str) -> None:
        """
        Delete a subagent by ID.

        Args:
            subagent_id: SubAgent ID to delete

        Raises:
            ValueError: If subagent not found
        """
        pass

    @abstractmethod
    async def list_by_tenant(
        self,
        tenant_id: str,
        enabled_only: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> List[SubAgent]:
        """
        List all subagents for a tenant.

        Args:
            tenant_id: Tenant ID
            enabled_only: If True, only return enabled subagents
            limit: Maximum number of results
            offset: Number of results to skip

        Returns:
            List of subagents for the tenant
        """
        pass

    @abstractmethod
    async def list_by_project(
        self,
        project_id: str,
        tenant_id: Optional[str] = None,
        enabled_only: bool = False,
    ) -> List[SubAgent]:
        """
        List subagents for a project, including tenant-wide ones (project_id IS NULL).

        Args:
            project_id: Project ID
            tenant_id: If provided, includes tenant-wide SubAgents scoped to this tenant
            enabled_only: If True, only return enabled subagents

        Returns:
            List of subagents for the project
        """
        pass

    @abstractmethod
    async def set_enabled(
        self,
        subagent_id: str,
        enabled: bool,
    ) -> SubAgent:
        """
        Enable or disable a subagent.

        Args:
            subagent_id: SubAgent ID
            enabled: Whether to enable or disable

        Returns:
            Updated subagent

        Raises:
            ValueError: If subagent not found
        """
        pass

    @abstractmethod
    async def update_statistics(
        self,
        subagent_id: str,
        execution_time_ms: float,
        success: bool,
    ) -> SubAgent:
        """
        Update execution statistics for a subagent.

        Args:
            subagent_id: SubAgent ID
            execution_time_ms: Execution time in milliseconds
            success: Whether the execution was successful

        Returns:
            Updated subagent

        Raises:
            ValueError: If subagent not found
        """
        pass

    @abstractmethod
    async def count_by_tenant(
        self,
        tenant_id: str,
        enabled_only: bool = False,
    ) -> int:
        """
        Count subagents for a tenant.

        Args:
            tenant_id: Tenant ID
            enabled_only: If True, only count enabled subagents

        Returns:
            Number of subagents
        """
        pass

    @abstractmethod
    async def find_by_keywords(
        self,
        tenant_id: str,
        query: str,
        enabled_only: bool = True,
    ) -> List[SubAgent]:
        """
        Find subagents by keyword matching.

        Uses trigger keywords to find matching subagents.

        Args:
            tenant_id: Tenant ID
            query: Query string to match
            enabled_only: If True, only return enabled subagents

        Returns:
            List of matching subagents
        """
        pass
