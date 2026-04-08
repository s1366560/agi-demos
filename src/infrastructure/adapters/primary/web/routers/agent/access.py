"""Shared access helpers for Agent API endpoints."""

from fastapi import HTTPException
from sqlalchemy import inspect as sa_inspect, select
from sqlalchemy.exc import NoInspectionAvailable
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.auth.roles import RoleDefinition
from src.domain.model.auth.user import User
from src.infrastructure.adapters.secondary.persistence.models import (
    Role,
    Tenant,
    UserRole,
    UserTenant,
)


def _get_user_state(current_user: User) -> dict[str, object]:
    """Return already-loaded user state without triggering ORM lazy loads."""
    try:
        state = sa_inspect(current_user)
    except NoInspectionAvailable:
        return getattr(current_user, "__dict__", {})

    loaded_state = getattr(state, "dict", None)
    if isinstance(loaded_state, dict):
        return loaded_state
    return getattr(current_user, "__dict__", {})


def _get_user_id(current_user: User) -> str:
    """Return the user id without triggering ORM lazy loads."""
    try:
        state = sa_inspect(current_user)
    except NoInspectionAvailable:
        return str(current_user.id)

    identity = getattr(state, "identity", None)
    if identity:
        return str(identity[0])

    loaded_state = getattr(state, "dict", None)
    if isinstance(loaded_state, dict) and loaded_state.get("id") is not None:
        return str(loaded_state["id"])

    return str(current_user.id)


def is_global_admin(current_user: User) -> bool:
    """Return whether the current user has global admin access."""
    user_state = _get_user_state(current_user)

    loaded_roles = user_state.get("roles")
    if not isinstance(loaded_roles, (list, tuple)):
        return False

    for user_role in loaded_roles:
        loaded_role = getattr(user_role, "__dict__", {}).get("role")
        role_name = getattr(loaded_role, "name", None)
        tenant_id = getattr(user_role, "__dict__", {}).get("tenant_id")
        if tenant_id is None and role_name == RoleDefinition.SYSTEM_ADMIN:
            return True
    return False


async def has_global_admin_access(
    db: AsyncSession,
    current_user: User,
) -> bool:
    """Return whether the current user has persisted global admin access."""
    if is_global_admin(current_user):
        return True

    user_id = _get_user_id(current_user)

    role_result = await db.execute(
        select(Role.id)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(
            UserRole.user_id == user_id,
            UserRole.tenant_id.is_(None),
            Role.name == RoleDefinition.SYSTEM_ADMIN,
        )
        .limit(1)
    )
    return role_result.scalar_one_or_none() is not None


async def _ensure_tenant_exists(
    db: AsyncSession,
    tenant_id: str,
) -> None:
    """Raise when the requested tenant does not exist."""
    result = await db.execute(select(Tenant.id).where(Tenant.id == tenant_id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Tenant not found")


async def get_tenant_role(
    db: AsyncSession,
    current_user: User,
    tenant_id: str,
) -> str | None:
    """Return the caller's tenant role, or None when they are not a member."""
    await _ensure_tenant_exists(db, tenant_id)

    if await has_global_admin_access(db, current_user):
        return "admin"

    user_id = _get_user_id(current_user)
    result = await db.execute(
        select(UserTenant.role).where(
            UserTenant.user_id == user_id,
            UserTenant.tenant_id == tenant_id,
        )
    )
    role = result.scalar_one_or_none()
    return str(role) if role is not None else None


async def has_tenant_admin_access(
    db: AsyncSession,
    current_user: User,
    tenant_id: str,
) -> bool:
    """Return whether the caller has admin-level access to the tenant."""
    role = await get_tenant_role(db, current_user, tenant_id)
    return role in {"admin", "owner"}


async def require_tenant_access(
    db: AsyncSession,
    current_user: User,
    tenant_id: str,
    *,
    require_admin: bool = False,
) -> None:
    """Require tenant membership, and admin rights when requested."""
    role = await get_tenant_role(db, current_user, tenant_id)
    if role is None:
        raise HTTPException(status_code=403, detail="Tenant access required")
    if require_admin and role not in {"admin", "owner"}:
        raise HTTPException(status_code=403, detail="Admin access required")
