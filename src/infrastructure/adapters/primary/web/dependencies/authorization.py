"""
Authorization decorators for protecting API endpoints.

These decorators provide a declarative way to enforce permissions
on FastAPI endpoints using the RBAC system.
"""

import functools
import logging
from collections.abc import Callable

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.authorization_service import AuthorizationService
from src.domain.model.auth.user import User

logger = logging.getLogger(__name__)


def require_permission(permission: str):
    """
    Decorator to require a specific permission for endpoint access.

    Usage:
        @router.get("/projects/{project_id}")
        @require_permission(PermissionCode.PROJECT_READ)
        async def get_project(project_id: str, current_user: User = Depends(get_current_user), ...):
            ...

    Args:
        permission: Permission code required (e.g., "project:read")

    Returns:
        Decorator function
    """

    def decorator(func: Callable):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # Extract current_user from kwargs (injected by FastAPI Depends)
            current_user: User | None = kwargs.get("current_user")
            if not current_user:
                # Try to get it from args (less common)
                if len(args) > 0 and isinstance(args[0], User):
                    current_user = args[0]

            if not current_user:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required"
                )

            # Get auth_service from kwargs if available, or use the one passed as dependency
            auth_service: AuthorizationService | None = kwargs.get("auth_service")
            if not auth_service:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Authorization service not configured",
                )

            # Extract tenant_id and project_id from kwargs for context
            tenant_id = kwargs.get("tenant_id")
            project_id = kwargs.get("project_id")

            # Also check path parameters
            if not tenant_id and "tenant_id" in kwargs:
                tenant_id = kwargs["tenant_id"]
            if not project_id and "project_id" in kwargs:
                project_id = kwargs["project_id"]

            # Check permission
            has_permission = await auth_service.check_permission(
                user_id=current_user.id,
                permission=permission,
                tenant_id=tenant_id,
                project_id=project_id,
            )

            if not has_permission:
                logger.warning(
                    f"User {current_user.id} denied access to {func.__name__}: "
                    f"missing permission {permission}"
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Permission '{permission}' required",
                )

            # Permission granted, proceed with the endpoint
            return await func(*args, **kwargs)

        return wrapper

    return decorator


def require_any_permission(*permissions: str):
    """
    Decorator to require ANY of the specified permissions.

    Grants access if user has at least one of the permissions.

    Usage:
        @router.post("/projects")
        @require_any_permission(PermissionCode.PROJECT_CREATE, PermissionCode.PROJECT_CREATE)
        async def create_project(...):
            ...

    Args:
        *permissions: Variable number of permission codes

    Returns:
        Decorator function
    """

    def decorator(func: Callable):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            current_user: User | None = kwargs.get("current_user")
            if not current_user:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required"
                )

            auth_service: AuthorizationService | None = kwargs.get("auth_service")
            if not auth_service:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Authorization service not configured",
                )

            tenant_id = kwargs.get("tenant_id")
            project_id = kwargs.get("project_id")

            # Check if user has ANY of the required permissions
            has_any_permission = False
            for permission in permissions:
                has_perm = await auth_service.check_permission(
                    user_id=current_user.id,
                    permission=permission,
                    tenant_id=tenant_id,
                    project_id=project_id,
                )
                if has_perm:
                    has_any_permission = True
                    break

            if not has_any_permission:
                logger.warning(
                    f"User {current_user.id} denied access to {func.__name__}: "
                    f"missing any of {permissions}"
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"One of permissions {permissions} required",
                )

            return await func(*args, **kwargs)

        return wrapper

    return decorator


def require_all_permissions(*permissions: str):
    """
    Decorator to require ALL of the specified permissions.

    Grants access only if user has ALL the permissions.

    Usage:
        @router.delete("/projects/{project_id}")
        @require_all_permissions(PermissionCode.PROJECT_DELETE, PermissionCode.PROJECT_READ)
        async def delete_project(project_id: str, ...):
            ...

    Args:
        *permissions: Variable number of permission codes

    Returns:
        Decorator function
    """

    def decorator(func: Callable):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            current_user: User | None = kwargs.get("current_user")
            if not current_user:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required"
                )

            auth_service: AuthorizationService | None = kwargs.get("auth_service")
            if not auth_service:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Authorization service not configured",
                )

            tenant_id = kwargs.get("tenant_id")
            project_id = kwargs.get("project_id")

            # Check if user has ALL the required permissions
            missing_permissions = []
            for permission in permissions:
                has_perm = await auth_service.check_permission(
                    user_id=current_user.id,
                    permission=permission,
                    tenant_id=tenant_id,
                    project_id=project_id,
                )
                if not has_perm:
                    missing_permissions.append(permission)

            if missing_permissions:
                logger.warning(
                    f"User {current_user.id} denied access to {func.__name__}: "
                    f"missing permissions {missing_permissions}"
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Permissions required: {missing_permissions}",
                )

            return await func(*args, **kwargs)

        return wrapper

    return decorator


def require_role(role: str):
    """
    Decorator to require a specific role.

    This is a simpler alternative to permission-based checks when
    you want to check for a specific role.

    Usage:
        @router.post("/admin/settings")
        @require_role("system_admin")
        async def update_settings(...):
            ...

    Args:
        role: Role name required

    Returns:
        Decorator function
    """

    def decorator(func: Callable):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            current_user: User | None = kwargs.get("current_user")
            if not current_user:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required"
                )

            auth_service: AuthorizationService | None = kwargs.get("auth_service")
            if not auth_service:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Authorization service not configured",
                )

            # Get user's roles
            user_roles = await auth_service.get_user_roles(
                user_id=current_user.id, tenant_id=kwargs.get("tenant_id")
            )

            # Check if user has the required role
            has_role = any(r["name"] == role for r in user_roles)

            if not has_role:
                logger.warning(
                    f"User {current_user.id} denied access to {func.__name__}: missing role {role}"
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN, detail=f"Role '{role}' required"
                )

            return await func(*args, **kwargs)

        return wrapper

    return decorator


# Convenience functions that can be used as FastAPI dependencies
async def get_authorization_service(session: AsyncSession = Depends(...)) -> AuthorizationService:
    """
    FastAPI dependency to get AuthorizationService instance.

    Usage in endpoints:
        @router.get("/projects")
        async def get_projects(
            auth_service: AuthorizationService = Depends(get_authorization_service),
            ...
        ):
            ...
    """
    # This will be properly configured with DI container
    # For now, return a basic instance
    return AuthorizationService(session=session)
