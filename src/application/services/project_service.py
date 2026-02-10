"""
ProjectService: Business logic for project management.

This service handles project CRUD operations and member management,
following the hexagonal architecture pattern.
"""

import logging
from datetime import datetime, timezone
from typing import List, Optional

from src.domain.model.project.project import Project
from src.domain.ports.repositories.project_repository import ProjectRepository
from src.domain.ports.repositories.user_repository import UserRepository

logger = logging.getLogger(__name__)


class ProjectService:
    """Service for managing projects"""

    def __init__(self, project_repo: ProjectRepository, user_repo: UserRepository):
        self._project_repo = project_repo
        self._user_repo = user_repo

    async def create_project(
        self,
        name: str,
        owner_id: str,
        tenant_id: str,
        description: Optional[str] = None,
        is_public: bool = False,
    ) -> Project:
        """
        Create a new project.

        Args:
            name: Project name
            owner_id: User ID of the project owner
            tenant_id: Tenant ID for the project
            description: Optional project description
            is_public: Whether the project is publicly visible

        Returns:
            Created project

        Raises:
            ValueError: If owner doesn't exist
        """
        # Validate owner exists
        owner = await self._user_repo.find_by_id(owner_id)
        if not owner:
            raise ValueError(f"Owner with ID {owner_id} does not exist")

        # Create project
        project = Project(
            id=Project.generate_id(),
            tenant_id=tenant_id,
            name=name,
            owner_id=owner_id,
            description=description,
            is_public=is_public,
            created_at=datetime.now(timezone.utc),
            member_ids=[owner_id],  # Owner is automatically a member
        )

        await self._project_repo.save(project)
        logger.info(f"Created project {project.id} for tenant {tenant_id}")
        return project

    async def get_project(self, project_id: str) -> Optional[Project]:
        """
        Retrieve a project by ID.

        Args:
            project_id: Project ID

        Returns:
            Project if found, None otherwise
        """
        return await self._project_repo.find_by_id(project_id)

    async def list_projects(
        self, tenant_id: str, owner_id: Optional[str] = None, limit: int = 50, offset: int = 0
    ) -> List[Project]:
        """
        List projects with optional filtering.

        Args:
            tenant_id: Tenant ID to filter by
            owner_id: Optional owner ID to filter by
            limit: Maximum number of results
            offset: Number of results to skip

        Returns:
            List of projects
        """
        if owner_id:
            # Filter by owner within tenant
            all_projects = await self._project_repo.find_by_tenant(
                tenant_id, limit=limit * 2, offset=offset
            )
            return [p for p in all_projects if p.owner_id == owner_id][:limit]
        else:
            # Return all tenant projects
            return await self._project_repo.find_by_tenant(tenant_id, limit=limit, offset=offset)

    async def update_project(
        self,
        project_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        is_public: Optional[bool] = None,
        memory_rules: Optional[dict] = None,
        graph_config: Optional[dict] = None,
    ) -> Project:
        """
        Update project properties.

        Args:
            project_id: Project ID
            name: New name (optional)
            description: New description (optional)
            is_public: New public status (optional)
            memory_rules: New memory rules (optional)
            graph_config: New graph configuration (optional)

        Returns:
            Updated project

        Raises:
            ValueError: If project doesn't exist
        """
        project = await self._project_repo.find_by_id(project_id)
        if not project:
            raise ValueError(f"Project {project_id} not found")

        # Update fields if provided
        if name is not None:
            project.name = name
        if description is not None:
            project.description = description
        if is_public is not None:
            project.is_public = is_public
        if memory_rules is not None:
            project.memory_rules = memory_rules
        if graph_config is not None:
            project.graph_config = graph_config

        project.updated_at = datetime.now(timezone.utc)

        await self._project_repo.save(project)
        logger.info(f"Updated project {project_id}")
        return project

    async def delete_project(self, project_id: str) -> None:
        """
        Delete a project.

        Args:
            project_id: Project ID

        Raises:
            ValueError: If project doesn't exist
        """
        project = await self._project_repo.find_by_id(project_id)
        if not project:
            raise ValueError(f"Project {project_id} not found")

        await self._project_repo.delete(project_id)
        logger.info(f"Deleted project {project_id}")

    async def add_member(self, project_id: str, user_id: str) -> None:
        """
        Add a user as a member of a project.

        Args:
            project_id: Project ID
            user_id: User ID to add

        Raises:
            ValueError: If project or user doesn't exist, or user is already a member
        """
        project = await self._project_repo.find_by_id(project_id)
        if not project:
            raise ValueError(f"Project {project_id} not found")

        user = await self._user_repo.find_by_id(user_id)
        if not user:
            raise ValueError(f"User {user_id} not found")

        if user_id in project.member_ids:
            logger.warning(f"User {user_id} is already a member of project {project_id}")
            return

        project.member_ids.append(user_id)
        project.updated_at = datetime.now(timezone.utc)

        await self._project_repo.save(project)
        logger.info(f"Added user {user_id} to project {project_id}")

    async def remove_member(self, project_id: str, user_id: str) -> None:
        """
        Remove a member from a project.

        Args:
            project_id: Project ID
            user_id: User ID to remove

        Raises:
            ValueError: If project doesn't exist or user is the owner
        """
        project = await self._project_repo.find_by_id(project_id)
        if not project:
            raise ValueError(f"Project {project_id} not found")

        # Prevent removing the owner
        if user_id == project.owner_id:
            raise ValueError("Cannot remove project owner")

        if user_id not in project.member_ids:
            logger.warning(f"User {user_id} is not a member of project {project_id}")
            return

        project.member_ids.remove(user_id)
        project.updated_at = datetime.now(timezone.utc)

        await self._project_repo.save(project)
        logger.info(f"Removed user {user_id} from project {project_id}")

    async def get_members(self, project_id: str) -> List[str]:
        """
        Get list of project member IDs.

        Args:
            project_id: Project ID

        Returns:
            List of user IDs

        Raises:
            ValueError: If project doesn't exist
        """
        project = await self._project_repo.find_by_id(project_id)
        if not project:
            raise ValueError(f"Project {project_id} not found")

        return project.member_ids
