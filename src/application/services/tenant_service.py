"""
TenantService: Business logic for tenant management.

This service handles tenant CRUD operations and member management,
including roles and permissions.
"""

import logging
from datetime import datetime, timezone
from typing import List, Optional

from src.domain.model.tenant.tenant import Tenant
from src.domain.ports.repositories.tenant_repository import TenantRepository
from src.domain.ports.repositories.user_repository import UserRepository

logger = logging.getLogger(__name__)


class TenantService:
    """Service for managing tenants"""

    def __init__(self, tenant_repo: TenantRepository, user_repo: UserRepository):
        self._tenant_repo = tenant_repo
        self._user_repo = user_repo

    async def create_tenant(
        self, name: str, owner_id: str, description: Optional[str] = None, plan: str = "free"
    ) -> Tenant:
        """
        Create a new tenant.

        Args:
            name: Tenant name
            owner_id: User ID of the tenant owner
            description: Optional tenant description
            plan: Subscription plan (free, pro, enterprise)

        Returns:
            Created tenant

        Raises:
            ValueError: If owner doesn't exist
        """
        # Validate owner exists
        owner = await self._user_repo.find_by_id(owner_id)
        if not owner:
            raise ValueError(f"Owner with ID {owner_id} does not exist")

        # Create tenant
        tenant = Tenant(
            id=Tenant.generate_id(),
            name=name,
            owner_id=owner_id,
            description=description,
            plan=plan,
            created_at=datetime.now(timezone.utc),
        )

        await self._tenant_repo.save(tenant)
        logger.info(f"Created tenant {tenant.id} for owner {owner_id}")
        return tenant

    async def get_tenant(self, tenant_id: str) -> Optional[Tenant]:
        """
        Retrieve a tenant by ID.

        Args:
            tenant_id: Tenant ID

        Returns:
            Tenant if found, None otherwise
        """
        return await self._tenant_repo.find_by_id(tenant_id)

    async def list_tenants(self, owner_id: str, limit: int = 50, offset: int = 0) -> List[Tenant]:
        """
        List tenants owned by a user.

        Args:
            owner_id: User ID
            limit: Maximum number of results
            offset: Number of results to skip

        Returns:
            List of tenants
        """
        return await self._tenant_repo.find_by_owner(owner_id, limit=limit, offset=offset)

    async def update_tenant(
        self,
        tenant_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        plan: Optional[str] = None,
    ) -> Tenant:
        """
        Update tenant properties.

        Args:
            tenant_id: Tenant ID
            name: New name (optional)
            description: New description (optional)
            plan: New plan (optional)

        Returns:
            Updated tenant

        Raises:
            ValueError: If tenant doesn't exist
        """
        tenant = await self._tenant_repo.find_by_id(tenant_id)
        if not tenant:
            raise ValueError(f"Tenant {tenant_id} not found")

        # Update fields if provided
        if name is not None:
            tenant.name = name
        if description is not None:
            tenant.description = description
        if plan is not None:
            tenant.plan = plan

        tenant.updated_at = datetime.now(timezone.utc)

        await self._tenant_repo.save(tenant)
        logger.info(f"Updated tenant {tenant_id}")
        return tenant

    async def delete_tenant(self, tenant_id: str) -> None:
        """
        Delete a tenant.

        WARNING: This will cascade delete all projects and memories in the tenant.

        Args:
            tenant_id: Tenant ID

        Raises:
            ValueError: If tenant doesn't exist
        """
        tenant = await self._tenant_repo.find_by_id(tenant_id)
        if not tenant:
            raise ValueError(f"Tenant {tenant_id} not found")

        await self._tenant_repo.delete(tenant_id)
        logger.info(f"Deleted tenant {tenant_id}")

    async def get_tenant_stats(self, tenant_id: str) -> dict:
        """
        Get statistics for a tenant.

        Args:
            tenant_id: Tenant ID

        Returns:
            Dictionary with tenant statistics including:
            - project_count: Number of projects
            - user_count: Number of users
            - storage_used: Storage used in bytes
            - plan: Current plan

        Raises:
            ValueError: If tenant doesn't exist
        """
        tenant = await self._tenant_repo.find_by_id(tenant_id)
        if not tenant:
            raise ValueError(f"Tenant {tenant_id} not found")

        # Get statistics from repository
        # Note: These methods would need to be implemented in the repository
        project_count = 0  # await self._tenant_repo.count_projects(tenant_id)
        user_count = 0  # await self._tenant_repo.count_users(tenant_id)
        storage_used = 0  # await self._tenant_repo.calculate_storage(tenant_id)

        return {
            "tenant_id": tenant.id,
            "name": tenant.name,
            "plan": tenant.plan,
            "project_count": project_count,
            "user_count": user_count,
            "storage_used": storage_used,
            "max_projects": tenant.max_projects,
            "max_users": tenant.max_users,
            "max_storage": tenant.max_storage,
        }
