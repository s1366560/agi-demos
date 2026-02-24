"""Repository interface for ProjectSandbox entity.

This module defines the repository port for managing Project-Sandbox
lifecycle associations.
"""

from abc import ABC, abstractmethod

from src.domain.model.sandbox.project_sandbox import ProjectSandbox, ProjectSandboxStatus


class ProjectSandboxRepository(ABC):
    """Repository interface for ProjectSandbox lifecycle association.

    This repository manages the mapping between Projects and their
    dedicated Sandbox instances, enabling persistent lifecycle management.
    """

    @abstractmethod
    async def save(self, association: ProjectSandbox) -> None:
        """Save or update a project-sandbox association.

        Args:
            association: The ProjectSandbox entity to save
        """
        pass

    @abstractmethod
    async def find_by_id(self, association_id: str) -> ProjectSandbox | None:
        """Find a project-sandbox association by its ID.

        Args:
            association_id: The association's unique identifier

        Returns:
            ProjectSandbox entity if found, None otherwise
        """
        pass

    @abstractmethod
    async def find_by_project(self, project_id: str) -> ProjectSandbox | None:
        """Find the sandbox association for a specific project.

        Each project should have at most one active sandbox association.

        Args:
            project_id: The project ID

        Returns:
            ProjectSandbox entity if found, None otherwise
        """
        pass

    @abstractmethod
    async def find_by_sandbox(self, sandbox_id: str) -> ProjectSandbox | None:
        """Find the project association for a specific sandbox.

        Args:
            sandbox_id: The sandbox ID

        Returns:
            ProjectSandbox entity if found, None otherwise
        """
        pass

    @abstractmethod
    async def find_by_tenant(
        self,
        tenant_id: str,
        status: ProjectSandboxStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ProjectSandbox]:
        """List all sandbox associations for a tenant.

        Args:
            tenant_id: The tenant ID
            status: Optional status filter
            limit: Maximum number of results
            offset: Pagination offset

        Returns:
            List of ProjectSandbox entities
        """
        pass

    @abstractmethod
    async def find_by_status(
        self,
        status: ProjectSandboxStatus,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ProjectSandbox]:
        """Find all associations with a specific status.

        Useful for health check sweeps and cleanup operations.

        Args:
            status: The status to filter by
            limit: Maximum number of results
            offset: Pagination offset

        Returns:
            List of ProjectSandbox entities
        """
        pass

    @abstractmethod
    async def find_stale(
        self,
        max_idle_seconds: int,
        limit: int = 50,
    ) -> list[ProjectSandbox]:
        """Find associations that haven't been accessed recently.

        Useful for identifying sandboxes that could be stopped to save resources.

        Args:
            max_idle_seconds: Maximum idle time before considered stale
            limit: Maximum number of results

        Returns:
            List of stale ProjectSandbox entities
        """
        pass

    @abstractmethod
    async def delete(self, association_id: str) -> bool:
        """Delete a project-sandbox association.

        Args:
            association_id: The association ID to delete

        Returns:
            True if deleted, False if not found
        """
        pass

    @abstractmethod
    async def delete_by_project(self, project_id: str) -> bool:
        """Delete the sandbox association for a project.

        Args:
            project_id: The project ID

        Returns:
            True if deleted, False if not found
        """
        pass

    @abstractmethod
    async def exists_for_project(self, project_id: str) -> bool:
        """Check if a project has a sandbox association.

        Args:
            project_id: The project ID

        Returns:
            True if an association exists
        """
        pass

    @abstractmethod
    async def count_by_tenant(
        self,
        tenant_id: str,
        status: ProjectSandboxStatus | None = None,
    ) -> int:
        """Count sandbox associations for a tenant.

        Args:
            tenant_id: The tenant ID
            status: Optional status filter

        Returns:
            Number of matching associations
        """
        pass

    @abstractmethod
    async def acquire_project_lock(
        self,
        project_id: str,
        timeout_seconds: int = 30,
        blocking: bool = True,
    ) -> bool:
        """Acquire a distributed SESSION-level lock for a project's sandbox creation.

        CRITICAL: This is a SESSION-level lock that persists until explicitly released.
        This is necessary because container creation is a long-running operation that
        spans multiple database transactions.

        Uses database-level locking (PostgreSQL advisory locks) to
        ensure mutual exclusion across all workers.

        Args:
            project_id: The project ID to lock
            timeout_seconds: Lock timeout (for blocking mode)
            blocking: If True, wait for lock; if False, return immediately

        Returns:
            True if lock acquired, False if another process holds the lock
        """
        pass

    @abstractmethod
    async def release_project_lock(self, project_id: str) -> None:
        """Release the SESSION-level distributed lock for a project.

        CRITICAL: Must be called explicitly after container creation completes.
        Unlike transaction-level locks, session locks persist until released.

        Args:
            project_id: The project ID to unlock
        """
        pass

    @abstractmethod
    async def find_and_lock_by_project(
        self,
        project_id: str,
    ) -> ProjectSandbox | None:
        """Find sandbox by project with row-level lock (SELECT FOR UPDATE).

        This prevents TOCTOU race conditions by locking the row while checking.

        Args:
            project_id: The project ID

        Returns:
            ProjectSandbox entity if found (with row locked), None otherwise
        """
        pass
