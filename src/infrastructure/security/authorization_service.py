"""
AuthorizationService: SQLAlchemy implementation of authorization (RBAC).

This service handles permission checking, role assignment, and authorization
decisions using SQLAlchemy ORM models directly.
"""

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.auth.permissions import PermissionCode
from src.domain.model.auth.roles import RoleDefinition
from src.domain.ports.services.authorization_port import AuthorizationPort
from src.infrastructure.adapters.secondary.persistence.models import (
    Permission,
    Role,
    RolePermission,
    User,
    UserRole,
)

logger = logging.getLogger(__name__)


class AuthorizationService(AuthorizationPort):
    """SQLAlchemy implementation of authorization and permissions."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def check_permission(
        self,
        user_id: str,
        permission: str,
        tenant_id: str | None = None,
        project_id: str | None = None,
    ) -> bool:
        """
        Check if a user has a specific permission in the given context.

        Args:
            user_id: User ID to check
            permission: Permission code to check (e.g., "project:read")
            tenant_id: Optional tenant ID for tenant-scoped checks
            project_id: Optional project ID for project-scoped checks

        Returns:
            True if user has the permission, False otherwise
        """
        try:
            # System admins have all permissions
            if await self._is_system_admin(user_id):
                return True

            # Get all user roles in the relevant context
            user_permissions = await self.get_user_permissions(
                user_id=user_id, tenant_id=tenant_id, project_id=project_id
            )

            return permission in user_permissions

        except Exception as e:
            logger.error(f"Error checking permission for user {user_id}: {e}")
            return False

    async def get_user_permissions(
        self, user_id: str, tenant_id: str | None = None, project_id: str | None = None
    ) -> list[str]:
        """
        Get all permissions for a user in a specific context.

        Args:
            user_id: User ID
            tenant_id: Optional tenant ID
            project_id: Optional project ID (not yet implemented in DB model)

        Returns:
            List of permission codes
        """
        try:
            # System admins get all permissions
            if await self._is_system_admin(user_id):
                return [p.value for p in PermissionCode]

            # Build query to get user's roles and permissions
            # Get roles that are either:
            # 1. System-wide (no tenant_id)
            # 2. Tenant-scoped (matching tenant_id)
            query = (
                select(Permission.code)
                .join(RolePermission, Permission.id == RolePermission.permission_id)
                .join(Role, RolePermission.role_id == Role.id)
                .join(UserRole, UserRole.role_id == Role.id)
                .where(UserRole.user_id == user_id)
            )

            # Filter by tenant context if provided
            if tenant_id:
                query = query.where(
                    (UserRole.tenant_id == tenant_id) | (UserRole.tenant_id.is_(None))
                )
            else:
                # If no tenant context, only get system-wide roles
                query = query.where(UserRole.tenant_id.is_(None))

            result = await self._session.execute(query)
            permissions = [row[0] for row in result.all()]

            return list(set(permissions))  # Remove duplicates

        except Exception as e:
            logger.error(f"Error getting permissions for user {user_id}: {e}")
            return []

    async def assign_role(
        self,
        user_id: str,
        role_name: str,
        tenant_id: str | None = None,
        project_id: str | None = None,
    ) -> None:
        """
        Assign a role to a user in a specific context.

        Args:
            user_id: User ID
            role_name: Role name (e.g., "tenant_admin", "project_viewer")
            tenant_id: Optional tenant ID for tenant-scoped roles
            project_id: Optional project ID (for future project-scoped roles)

        Raises:
            ValueError: If role doesn't exist or user doesn't exist
        """
        # Validate role exists
        if not RoleDefinition.role_exists(role_name):
            raise ValueError(f"Role '{role_name}' does not exist")

        # Validate user exists
        user = await self._session.execute(select(User).where(User.id == user_id))
        if not user.scalar_one_or_none():
            raise ValueError(f"User {user_id} does not exist")

        # Get role from database
        role = await self._session.execute(select(Role).where(Role.name == role_name))
        role_obj = role.scalar_one_or_none()

        # Create role if it doesn't exist in database
        if not role_obj:
            role_obj = Role(
                id=Role.generate_id(), name=role_name, description=f"System role: {role_name}"
            )
            self._session.add(role_obj)
            await self._session.flush()

        # Check if user already has this role in this context
        existing = await self._session.execute(
            select(UserRole).where(
                UserRole.user_id == user_id,
                UserRole.role_id == role_obj.id,
                UserRole.tenant_id == tenant_id if tenant_id else True,  # Handle None case
            )
        )
        if existing.scalar_one_or_none():
            logger.warning(f"User {user_id} already has role {role_name} in this context")
            return

        # Assign role
        user_role = UserRole(
            id=UserRole.generate_id(), user_id=user_id, role_id=role_obj.id, tenant_id=tenant_id
        )
        self._session.add(user_role)
        await self._session.commit()

        logger.info(
            f"Assigned role {role_name} to user {user_id}"
            + (f" in tenant {tenant_id}" if tenant_id else "")
        )

    async def remove_role(
        self,
        user_id: str,
        role_name: str,
        tenant_id: str | None = None,
        project_id: str | None = None,
    ) -> None:
        """
        Remove a role from a user in a specific context.

        Args:
            user_id: User ID
            role_name: Role name
            tenant_id: Optional tenant ID
            project_id: Optional project ID

        Raises:
            ValueError: If role assignment doesn't exist
        """
        # Get role
        role = await self._session.execute(select(Role).where(Role.name == role_name))
        role_obj = role.scalar_one_or_none()

        if not role_obj:
            raise ValueError(f"Role '{role_name}' does not exist")

        # Find and delete user role assignment
        query = select(UserRole).where(UserRole.user_id == user_id, UserRole.role_id == role_obj.id)

        if tenant_id:
            query = query.where(UserRole.tenant_id == tenant_id)
        else:
            query = query.where(UserRole.tenant_id.is_(None))

        user_role = await self._session.execute(query)
        user_role_obj = user_role.scalar_one_or_none()

        if not user_role_obj:
            raise ValueError(f"User {user_id} does not have role {role_name} in this context")

        await self._session.delete(user_role_obj)
        await self._session.commit()

        logger.info(f"Removed role {role_name} from user {user_id}")

    async def get_user_roles(self, user_id: str, tenant_id: str | None = None) -> list[dict[str, Any]]:
        """
        Get all roles assigned to a user.

        Args:
            user_id: User ID
            tenant_id: Optional tenant ID to filter by

        Returns:
            List of dicts with role information
        """
        query = (
            select(UserRole, Role)
            .join(Role, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user_id)
        )

        if tenant_id:
            query = query.where((UserRole.tenant_id == tenant_id) | (UserRole.tenant_id.is_(None)))

        result = await self._session.execute(query)
        roles = []
        for user_role, role in result.all():
            roles.append(
                {
                    "id": role.id,
                    "name": role.name,
                    "description": role.description,
                    "tenant_id": user_role.tenant_id,
                }
            )

        return roles

    async def _is_system_admin(self, user_id: str) -> bool:
        """
        Check if user is a system admin.

        Args:
            user_id: User ID

        Returns:
            True if user has system admin role
        """
        result = await self._session.execute(
            select(UserRole)
            .join(Role, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user_id, Role.name == RoleDefinition.SYSTEM_ADMIN)
        )
        return result.scalar_one_or_none() is not None

    async def initialize_default_roles(self) -> None:
        """
        Initialize all default roles and permissions in the database.

        This should be called during application setup or migration.
        Creates all roles defined in RoleDefinition and associates
        them with their permissions.
        """
        logger.info("Initializing default roles and permissions...")

        # Create all permissions
        for permission in PermissionCode:
            existing = await self._session.execute(
                select(Permission).where(Permission.code == permission.value)
            )
            if not existing.scalar_one_or_none():
                perm = Permission(
                    id=Permission.generate_id(),
                    code=permission.value,
                    name=permission.value.replace(":", " ").title(),
                    description=f"Permission for {permission.value}",
                )
                self._session.add(perm)

        # Create all roles
        for role_name in RoleDefinition.get_all_roles():
            existing = await self._session.execute(select(Role).where(Role.name == role_name))
            role = existing.scalar_one_or_none()

            if not role:
                role = Role(
                    id=Role.generate_id(), name=role_name, description=f"System role: {role_name}"
                )
                self._session.add(role)
                await self._session.flush()  # Get the role ID

            # Get permissions for this role
            permission_codes = RoleDefinition.get_permissions_for_role(role_name)

            # Associate permissions with role
            for perm_code in permission_codes:
                # Get permission from database
                perm = await self._session.execute(
                    select(Permission).where(Permission.code == perm_code)
                )
                perm_obj = perm.scalar_one_or_none()

                if perm_obj:
                    # Check if role_permission already exists
                    existing_rp = await self._session.execute(
                        select(RolePermission).where(
                            RolePermission.role_id == role.id,
                            RolePermission.permission_id == perm_obj.id,
                        )
                    )

                    if not existing_rp.scalar_one_or_none():
                        role_perm = RolePermission(
                            id=RolePermission.generate_id(),
                            role_id=role.id,
                            permission_id=perm_obj.id,
                        )
                        self._session.add(role_perm)

        await self._session.commit()
        logger.info("Default roles and permissions initialized successfully")
