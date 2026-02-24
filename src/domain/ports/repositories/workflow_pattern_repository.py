"""
WorkflowPatternRepository port (T084)

Repository interface for workflow pattern persistence.

This port defines the contract for persisting and retrieving
workflow patterns, following the Repository pattern.
"""

from abc import ABC, abstractmethod

from src.domain.model.agent.workflow_pattern import WorkflowPattern


class WorkflowPatternRepositoryPort(ABC):
    """
    Repository port for workflow pattern persistence.

    Provides CRUD operations for workflow patterns with tenant-level
    scoping (FR-019). Patterns are shared across projects within
    a tenant but isolated between tenants.
    """

    @abstractmethod
    async def create(self, pattern: WorkflowPattern) -> WorkflowPattern:
        """
        Create a new workflow pattern.

        Args:
            pattern: Pattern to create

        Returns:
            Created pattern with generated ID

        Raises:
            ValueError: If pattern data is invalid
        """

    @abstractmethod
    async def get_by_id(self, pattern_id: str) -> WorkflowPattern | None:
        """
        Get a pattern by its ID.

        Args:
            pattern_id: Pattern ID

        Returns:
            Pattern if found, None otherwise
        """

    @abstractmethod
    async def update(self, pattern: WorkflowPattern) -> WorkflowPattern:
        """
        Update an existing pattern.

        Args:
            pattern: Pattern to update

        Returns:
            Updated pattern

        Raises:
            ValueError: If pattern not found or data is invalid
        """

    @abstractmethod
    async def delete(self, pattern_id: str) -> None:
        """
        Delete a pattern by ID.

        Args:
            pattern_id: Pattern ID to delete

        Raises:
            ValueError: If pattern not found
        """

    @abstractmethod
    async def list_by_tenant(
        self,
        tenant_id: str,
    ) -> list[WorkflowPattern]:
        """
        List all patterns for a tenant.

        This implements tenant-level scoping (FR-019) where patterns
        are shared across all projects within a tenant.

        Args:
            tenant_id: Tenant ID

        Returns:
            List of all patterns for the tenant
        """

    @abstractmethod
    async def find_by_name(
        self,
        tenant_id: str,
        name: str,
    ) -> WorkflowPattern | None:
        """
        Find a pattern by name within a tenant.

        Args:
            tenant_id: Tenant ID
            name: Pattern name

        Returns:
            Pattern if found, None otherwise
        """

    @abstractmethod
    async def increment_usage_count(
        self,
        pattern_id: str,
    ) -> WorkflowPattern:
        """
        Increment the usage count for a pattern.

        Called when a pattern is matched and used for planning.

        Args:
            pattern_id: Pattern ID

        Returns:
            Updated pattern

        Raises:
            ValueError: If pattern not found
        """
