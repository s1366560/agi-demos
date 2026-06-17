from abc import ABC, abstractmethod

from src.domain.model.project.project import Project


class ProjectRepository(ABC):
    """Repository interface for Project entity"""

    @abstractmethod
    async def save(self, project: Project) -> Project:
        """Save a project (create or update). Returns the saved project."""

    @abstractmethod
    async def find_by_id(self, project_id: str) -> Project | None:
        """Find a project by ID"""

    @abstractmethod
    async def find_by_tenant(
        self, tenant_id: str, limit: int = 50, offset: int = 0
    ) -> list[Project]:
        """List all projects in a tenant"""

    @abstractmethod
    async def find_by_tenant_and_owner(
        self, tenant_id: str, owner_id: str, limit: int = 50, offset: int = 0
    ) -> list[Project]:
        """List all projects in a tenant owned by a user"""

    @abstractmethod
    async def find_by_owner(self, owner_id: str, limit: int = 50, offset: int = 0) -> list[Project]:
        """List all projects owned by a user"""

    @abstractmethod
    async def find_public_projects(self, limit: int = 50, offset: int = 0) -> list[Project]:
        """List all public projects"""

    @abstractmethod
    async def list_active_projects(self, limit: int = 1000, offset: int = 0) -> list[Project]:
        """List all active (non-deleted) projects across all tenants.

        Used by background sweeps (e.g. ``ReflectionRunner``) that need to
        iterate every project regardless of tenant or visibility. Ordered by
        ``created_at`` ascending for stable iteration. Soft-delete is not
        modeled today, so this returns every row in ``projects`` — callers
        should still respect tenant boundaries inside the iteration.
        """

    @abstractmethod
    async def delete(self, project_id: str) -> bool:
        """Delete a project. Returns True if deleted, False if not found."""
