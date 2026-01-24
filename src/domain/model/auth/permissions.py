"""
Permission definitions for Role-Based Access Control (RBAC).

This module defines all available permissions in the system using an Enum.
Permissions follow the pattern: resource:action
"""

from enum import Enum


class PermissionCode(str, Enum):
    """
    Enumeration of all system permissions.

    Permissions follow the naming convention: RESOURCE_ACTION
    where resource is the entity being accessed and action is the operation.
    """

    # ============== Tenant Permissions ==============
    TENANT_CREATE = "tenant:create"
    TENANT_READ = "tenant:read"
    TENANT_UPDATE = "tenant:update"
    TENANT_DELETE = "tenant:delete"
    TENANT_MANAGE_MEMBERS = "tenant:manage_members"

    # ============== Project Permissions ==============
    PROJECT_CREATE = "project:create"
    PROJECT_READ = "project:read"
    PROJECT_UPDATE = "project:update"
    PROJECT_DELETE = "project:delete"
    PROJECT_MANAGE_MEMBERS = "project:manage_members"

    # ============== Memory Permissions ==============
    MEMORY_CREATE = "memory:create"
    MEMORY_READ = "memory:read"
    MEMORY_UPDATE = "memory:update"
    MEMORY_DELETE = "memory:delete"
    MEMORY_SHARE = "memory:share"

    # ============== Memo Permissions ==============
    MEMO_CREATE = "memo:create"
    MEMO_READ = "memo:read"
    MEMO_UPDATE = "memo:update"
    MEMO_DELETE = "memo:delete"

    # ============== Schema Permissions ==============
    SCHEMA_MANAGE = "schema:manage"
    SCHEMA_READ = "schema:read"

    # ============== Task Permissions ==============
    TASK_READ = "task:read"
    TASK_MANAGE = "task:manage"
    TASK_DELETE = "task:delete"

    # ============== Analytics Permissions ==============
    ANALYTICS_VIEW = "analytics:view"
    ANALYTICS_EXPORT = "analytics:export"

    # ============== Admin Permissions ==============
    ADMIN_SYSTEM = "admin:system"
    ADMIN_USERS = "admin:users"
    ADMIN_SETTINGS = "admin:settings"


def get_all_permissions() -> list[str]:
    """
    Get a list of all permission codes.

    Returns:
        List of all permission string values
    """
    return [permission.value for permission in PermissionCode]


def get_resource_permissions(resource: str) -> list[str]:
    """
    Get all permissions for a specific resource.

    Args:
        resource: Resource name (e.g., 'tenant', 'project', 'memory')

    Returns:
        List of permissions for the resource
    """
    resource.upper()
    return [
        permission.value
        for permission in PermissionCode
        if permission.value.startswith(f"{resource}:")
    ]
