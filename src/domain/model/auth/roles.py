"""
Role definitions for Role-Based Access Control (RBAC).

This module defines all system roles and their associated permissions.
Roles are hierarchical and organized by scope (tenant, project, system).
"""

from typing import ClassVar

from src.domain.model.auth.permissions import PermissionCode


class RoleDefinition:
    """
    Defines system roles and their associated permissions.

    Roles are organized into three categories:
    1. Tenant-level roles: Control access to tenant-wide operations
    2. Project-level roles: Control access within specific projects
    3. System-level roles: Control administrative operations
    """

    # ============== Tenant-Level Roles ==============
    TENANT_OWNER = "tenant_owner"
    TENANT_ADMIN = "tenant_admin"
    TENANT_MEMBER = "tenant_member"

    # ============== Project-Level Roles ==============
    PROJECT_ADMIN = "project_admin"
    PROJECT_EDITOR = "project_editor"
    PROJECT_VIEWER = "project_viewer"

    # ============== System-Level Roles ==============
    SYSTEM_ADMIN = "system_admin"

    # Mapping of role names to their permissions
    ROLES: ClassVar[dict[str, list[str]]] = {
        # ========== Tenant Roles ==========
        TENANT_OWNER: [
            # Full control over tenant
            PermissionCode.TENANT_READ,
            PermissionCode.TENANT_UPDATE,
            PermissionCode.TENANT_DELETE,
            PermissionCode.TENANT_MANAGE_MEMBERS,
            PermissionCode.PROJECT_CREATE,
            PermissionCode.PROJECT_READ,
            PermissionCode.PROJECT_UPDATE,
            PermissionCode.PROJECT_DELETE,
            PermissionCode.MEMORY_CREATE,
            PermissionCode.MEMORY_READ,
            PermissionCode.MEMORY_UPDATE,
            PermissionCode.MEMORY_DELETE,
            PermissionCode.MEMORY_SHARE,
            PermissionCode.MEMO_CREATE,
            PermissionCode.MEMO_READ,
            PermissionCode.MEMO_UPDATE,
            PermissionCode.MEMO_DELETE,
            PermissionCode.TASK_READ,
            PermissionCode.TASK_MANAGE,
            PermissionCode.ANALYTICS_VIEW,
            PermissionCode.ANALYTICS_EXPORT,
        ],
        TENANT_ADMIN: [
            # Administrative access without ownership
            PermissionCode.TENANT_READ,
            PermissionCode.TENANT_UPDATE,
            PermissionCode.TENANT_MANAGE_MEMBERS,
            PermissionCode.PROJECT_CREATE,
            PermissionCode.PROJECT_READ,
            PermissionCode.PROJECT_UPDATE,
            PermissionCode.MEMORY_CREATE,
            PermissionCode.MEMORY_READ,
            PermissionCode.MEMORY_UPDATE,
            PermissionCode.MEMORY_DELETE,
            PermissionCode.MEMORY_SHARE,
            PermissionCode.MEMO_CREATE,
            PermissionCode.MEMO_READ,
            PermissionCode.MEMO_UPDATE,
            PermissionCode.MEMO_DELETE,
            PermissionCode.TASK_READ,
            PermissionCode.TASK_MANAGE,
            PermissionCode.ANALYTICS_VIEW,
        ],
        TENANT_MEMBER: [
            # Basic member access
            PermissionCode.TENANT_READ,
            PermissionCode.PROJECT_CREATE,
            PermissionCode.PROJECT_READ,
            PermissionCode.MEMORY_CREATE,
            PermissionCode.MEMORY_READ,
            PermissionCode.MEMO_CREATE,
            PermissionCode.MEMO_READ,
            PermissionCode.TASK_READ,
            PermissionCode.ANALYTICS_VIEW,
        ],
        # ========== Project Roles ==========
        PROJECT_ADMIN: [
            # Full control over project
            PermissionCode.PROJECT_READ,
            PermissionCode.PROJECT_UPDATE,
            PermissionCode.PROJECT_DELETE,
            PermissionCode.PROJECT_MANAGE_MEMBERS,
            PermissionCode.MEMORY_CREATE,
            PermissionCode.MEMORY_READ,
            PermissionCode.MEMORY_UPDATE,
            PermissionCode.MEMORY_DELETE,
            PermissionCode.MEMORY_SHARE,
            PermissionCode.SCHEMA_MANAGE,
            PermissionCode.SCHEMA_READ,
            PermissionCode.TASK_READ,
            PermissionCode.TASK_MANAGE,
            PermissionCode.ANALYTICS_VIEW,
            PermissionCode.ANALYTICS_EXPORT,
        ],
        PROJECT_EDITOR: [
            # Can contribute but not manage
            PermissionCode.PROJECT_READ,
            PermissionCode.MEMORY_CREATE,
            PermissionCode.MEMORY_READ,
            PermissionCode.MEMORY_UPDATE,
            PermissionCode.MEMO_CREATE,
            PermissionCode.MEMO_READ,
            PermissionCode.MEMO_UPDATE,
            PermissionCode.SCHEMA_READ,
            PermissionCode.TASK_READ,
            PermissionCode.ANALYTICS_VIEW,
        ],
        PROJECT_VIEWER: [
            # Read-only access
            PermissionCode.PROJECT_READ,
            PermissionCode.MEMORY_READ,
            PermissionCode.MEMO_READ,
            PermissionCode.SCHEMA_READ,
            PermissionCode.TASK_READ,
            PermissionCode.ANALYTICS_VIEW,
        ],
        # ========== System Roles ==========
        SYSTEM_ADMIN: [
            # Full system access
            PermissionCode.ADMIN_SYSTEM,
            PermissionCode.ADMIN_USERS,
            PermissionCode.ADMIN_SETTINGS,
            PermissionCode.TENANT_CREATE,
            PermissionCode.TENANT_READ,
            PermissionCode.TENANT_UPDATE,
            PermissionCode.TENANT_DELETE,
        ],
    }

    @classmethod
    def get_permissions_for_role(cls, role_name: str) -> list[str]:
        """
        Get all permissions for a given role.

        Args:
            role_name: Name of the role

        Returns:
            List of permission codes for the role

        Raises:
            ValueError: If role doesn't exist
        """
        if role_name not in cls.ROLES:
            raise ValueError(f"Role '{role_name}' does not exist")

        return [permission.value for permission in cls.ROLES[role_name]]  # type: ignore[attr-defined]

    @classmethod
    def role_exists(cls, role_name: str) -> bool:
        """
        Check if a role exists.

        Args:
            role_name: Name of the role

        Returns:
            True if role exists, False otherwise
        """
        return role_name in cls.ROLES

    @classmethod
    def get_all_roles(cls) -> list[str]:
        """
        Get a list of all role names.

        Returns:
            List of all role names
        """
        return list(cls.ROLES.keys())

    @classmethod
    def get_tenant_roles(cls) -> list[str]:
        """
        Get all tenant-level roles.

        Returns:
            List of tenant role names
        """
        return [cls.TENANT_OWNER, cls.TENANT_ADMIN, cls.TENANT_MEMBER]

    @classmethod
    def get_project_roles(cls) -> list[str]:
        """
        Get all project-level roles.

        Returns:
            List of project role names
        """
        return [cls.PROJECT_ADMIN, cls.PROJECT_EDITOR, cls.PROJECT_VIEWER]

    @classmethod
    def has_permission(cls, role_name: str, permission: str) -> bool:
        """
        Check if a role has a specific permission.

        Args:
            role_name: Name of the role
            permission: Permission code to check

        Returns:
            True if role has the permission, False otherwise
        """
        if role_name not in cls.ROLES:
            return False

        role_permissions = [p.value for p in cls.ROLES[role_name]]  # type: ignore[attr-defined]
        return permission in role_permissions
