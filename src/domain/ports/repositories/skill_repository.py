"""
SkillRepository port for skill persistence.

Repository interface for persisting and retrieving skills,
following the Repository pattern.

Supports three-level scoping for multi-tenant isolation:
- system: Built-in skills shared by all tenants
- tenant: Tenant-level skills shared within a tenant
- project: Project-specific skills
"""

from abc import ABC, abstractmethod

from src.domain.model.agent.skill import Skill, SkillScope, SkillStatus


class SkillRepositoryPort(ABC):
    """
    Repository port for skill persistence.

    Provides CRUD operations for skills with three-level scoping
    (system, tenant, project) for multi-tenant isolation.
    """

    @abstractmethod
    async def create(self, skill: Skill) -> Skill:
        """
        Create a new skill.

        Args:
            skill: Skill to create

        Returns:
            Created skill with generated ID

        Raises:
            ValueError: If skill data is invalid
        """

    @abstractmethod
    async def get_by_id(self, skill_id: str) -> Skill | None:
        """
        Get a skill by its ID.

        Args:
            skill_id: Skill ID

        Returns:
            Skill if found, None otherwise
        """

    @abstractmethod
    async def get_by_name(
        self,
        tenant_id: str,
        name: str,
        scope: SkillScope | None = None,
    ) -> Skill | None:
        """
        Get a skill by name within a tenant.

        Args:
            tenant_id: Tenant ID
            name: Skill name
            scope: Optional scope filter

        Returns:
            Skill if found, None otherwise
        """

    @abstractmethod
    async def update(self, skill: Skill) -> Skill:
        """
        Update an existing skill.

        Args:
            skill: Skill to update

        Returns:
            Updated skill

        Raises:
            ValueError: If skill not found or data is invalid
        """

    @abstractmethod
    async def delete(self, skill_id: str) -> bool:
        """
        Delete a skill by ID.

        Args:
            skill_id: Skill ID to delete

        Raises:
            ValueError: If skill not found
        """

    @abstractmethod
    async def list_by_tenant(
        self,
        tenant_id: str,
        status: SkillStatus | None = None,
        scope: SkillScope | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Skill]:
        """
        List all skills for a tenant.

        Args:
            tenant_id: Tenant ID
            status: Optional status filter
            scope: Optional scope filter (tenant or project)
            limit: Maximum number of results
            offset: Number of results to skip

        Returns:
            List of skills for the tenant
        """

    @abstractmethod
    async def list_by_project(
        self,
        project_id: str,
        tenant_id: str | None = None,
        status: SkillStatus | None = None,
        scope: SkillScope | None = None,
    ) -> list[Skill]:
        """
        List all skills for a specific project.

        Args:
            project_id: Project ID
            tenant_id: Optional tenant ID for multi-tenant isolation
            status: Optional status filter
            scope: Optional scope filter

        Returns:
            List of skills for the project
        """

    @abstractmethod
    async def count_by_tenant(
        self,
        tenant_id: str,
        status: SkillStatus | None = None,
        scope: SkillScope | None = None,
    ) -> int:
        """
        Count skills for a tenant.

        Args:
            tenant_id: Tenant ID
            status: Optional status filter
            scope: Optional scope filter

        Returns:
            Number of skills
        """
