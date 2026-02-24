"""
Authentication middleware and dependencies for API Key validation.

This file serves as a FastAPI-specific adapter layer that bridges between
FastAPI's dependency injection system and the application's AuthService.
Business logic is delegated to AuthService in the application layer.
"""

import logging
from typing import Any
from uuid import uuid4

from fastapi import Depends, Header, HTTPException, Query, Request, status
from fastapi.security import HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.auth_service_v2 import AuthService
from src.infrastructure.adapters.secondary.persistence.database import async_session_factory, get_db
from src.infrastructure.adapters.secondary.persistence.models import (
    APIKey as DBAPIKey,
    Permission,
    Role,
    RolePermission,
    Tenant,
    User as DBUser,
    UserRole,
    UserTenant,
)
from src.infrastructure.adapters.secondary.persistence.sql_api_key_repository import (
    SqlAPIKeyRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_user_repository import (
    SqlUserRepository,
)

logger = logging.getLogger(__name__)

security = HTTPBearer()


# ============================================================================
# UTILITY FUNCTIONS (Pure functions, can stay here)
# ============================================================================


def generate_api_key() -> str:
    """Generate a new API key."""
    return AuthService.generate_api_key()


def hash_api_key(key: str) -> str:
    """Hash an API key for storage."""
    return AuthService.hash_api_key(key)


def verify_api_key(key: str, hashed_key: str) -> bool:
    """Verify an API key against its hash."""
    return AuthService.verify_api_key_hash(key, hashed_key)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    return AuthService.verify_password(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Hash a password for storage."""
    return AuthService.get_password_hash(password)


# ============================================================================
# FASTAPI DEPENDENCIES (Primary Adapter Layer)
# ============================================================================


async def get_api_key_from_header(
    authorization: str | None = Header(None),
) -> str:
    """Extract API key from Authorization header."""
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key. Please provide an API key in the Authorization header.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if authorization.startswith("Bearer "):
        api_key = authorization[7:]
    elif authorization.startswith("Token "):
        api_key = authorization[6:]
    else:
        api_key = authorization

    if not api_key.startswith("ms_sk_"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key format. API keys should start with 'ms_sk_'",
        )

    return api_key


async def get_api_key_from_header_or_query(
    authorization: str | None = Header(None),
    token: str | None = Query(None, description="API key for SSE/WebSocket authentication"),
) -> str:
    """Extract API key from Authorization header or query parameter.

    This is useful for SSE endpoints where EventSource cannot set headers.
    First checks Authorization header, then falls back to query parameter.
    """
    # Try header first
    if authorization:
        if authorization.startswith("Bearer "):
            api_key = authorization[7:]
        elif authorization.startswith("Token "):
            api_key = authorization[6:]
        else:
            api_key = authorization

        if api_key.startswith("ms_sk_"):
            return api_key

    # Fall back to query parameter
    if token:
        if token.startswith("ms_sk_"):
            return token
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key format. API keys should start with 'ms_sk_'",
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Missing API key. Please provide an API key in the Authorization header or 'token' query parameter.",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_api_key_from_header_query_or_cookie(
    request: Request,
    authorization: str | None = Header(None),
    token: str | None = Query(None, description="API key for authentication"),
) -> str:
    """Extract API key from Authorization header, query parameter, or cookie.

    Used by desktop proxy endpoints where sub-resources (CSS/JS/SVG) are loaded
    by the browser without query parameters. The initial request sets a cookie
    that subsequent asset requests use for authentication.
    """
    # Try header first
    if authorization:
        if authorization.startswith("Bearer "):
            api_key = authorization[7:]
        elif authorization.startswith("Token "):
            api_key = authorization[6:]
        else:
            api_key = authorization
        if api_key.startswith("ms_sk_"):
            return api_key

    # Try query parameter
    if token and token.startswith("ms_sk_"):
        return token

    # Fall back to cookie (for desktop proxy sub-resources)
    cookie_token = request.cookies.get("desktop_token")
    if cookie_token and cookie_token.startswith("ms_sk_"):
        return cookie_token

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Missing API key.",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def verify_api_key_from_header_or_query(
    api_key: str = Depends(get_api_key_from_header_or_query), db: AsyncSession = Depends(get_db)
) -> DBAPIKey | None:
    """Verify API key from header or query parameter.

    This is a FastAPI adapter that uses the AuthService for business logic.
    Useful for SSE endpoints where EventSource cannot set headers.
    """
    # Create AuthService with repositories
    auth_service = AuthService(
        user_repository=SqlUserRepository(db),
        api_key_repository=SqlAPIKeyRepository(db),
    )

    try:
        # Verify using application service
        domain_api_key = await auth_service.verify_api_key(api_key)

        # Convert to DB model for backward compatibility
        result = await db.execute(select(DBAPIKey).where(DBAPIKey.id == domain_api_key.id))  # type: ignore[arg-type]  # SQLAlchemy Column comparison
        db_key = result.scalar_one_or_none()

        return db_key

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
        ) from e


async def verify_api_key_from_header_query_or_cookie(
    api_key: str = Depends(get_api_key_from_header_query_or_cookie),
    db: AsyncSession = Depends(get_db),
) -> DBAPIKey | None:
    """Verify API key from header, query parameter, or cookie."""
    auth_service = AuthService(
        user_repository=SqlUserRepository(db),
        api_key_repository=SqlAPIKeyRepository(db),
    )
    try:
        domain_api_key = await auth_service.verify_api_key(api_key)
        result = await db.execute(select(DBAPIKey).where(DBAPIKey.id == domain_api_key.id))  # type: ignore[arg-type]  # SQLAlchemy Column comparison
        return result.scalar_one_or_none()
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
        ) from e


async def get_current_user_from_desktop_proxy(
    api_key: DBAPIKey = Depends(verify_api_key_from_header_query_or_cookie),
    db: AsyncSession = Depends(get_db),
) -> DBUser:
    """Get current user for desktop proxy (supports header, query, and cookie auth)."""
    auth_service = AuthService(
        user_repository=SqlUserRepository(db),
        api_key_repository=SqlAPIKeyRepository(db),
    )
    try:
        domain_user = await auth_service.get_user_by_id(api_key.user_id)
        if not domain_user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        result = await db.execute(select(DBUser).where(DBUser.id == domain_user.id))
        db_user = result.scalar_one_or_none()
        if not db_user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        return db_user
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e)) from e


async def get_current_user_from_header_or_query(
    api_key: DBAPIKey = Depends(verify_api_key_from_header_or_query),
    db: AsyncSession = Depends(get_db),
) -> DBUser:
    """Get current user from API key (header or query parameter).

    This is useful for SSE endpoints where EventSource cannot set headers.
    """
    # Create AuthService with repositories
    auth_service = AuthService(
        user_repository=SqlUserRepository(db),
        api_key_repository=SqlAPIKeyRepository(db),
    )

    try:
        # Get user using application service
        domain_user = await auth_service.get_user_by_id(api_key.user_id)

        if not domain_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )

        # Convert to DB model for backward compatibility
        result = await db.execute(select(DBUser).where(DBUser.id == domain_user.id))
        db_user = result.scalar_one_or_none()

        if not db_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )

        return db_user

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e),
        ) from e


async def verify_api_key_dependency(
    api_key: str = Depends(get_api_key_from_header), db: AsyncSession = Depends(get_db)
) -> DBAPIKey | None:
    """
    Dependency to verify API key from request header.

    This is a FastAPI adapter that uses the AuthService for business logic.
    """
    # Create AuthService with repositories
    auth_service = AuthService(
        user_repository=SqlUserRepository(db),
        api_key_repository=SqlAPIKeyRepository(db),
    )

    try:
        # Verify using application service
        domain_api_key = await auth_service.verify_api_key(api_key)

        # Convert to DB model for backward compatibility
        # Note: We only need to read the key, not update it.
        # last_used_at updates are disabled to prevent row-level lock contention.
        result = await db.execute(select(DBAPIKey).where(DBAPIKey.id == domain_api_key.id))  # type: ignore[arg-type]  # SQLAlchemy Column comparison
        db_key = result.scalar_one_or_none()

        return db_key

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
        ) from e


async def get_current_user(
    api_key: DBAPIKey = Depends(verify_api_key_dependency), db: AsyncSession = Depends(get_db)
) -> DBUser:
    """
    Get the current user from the API key.

    This is a FastAPI adapter that uses the AuthService for business logic.
    """
    # Create AuthService with repositories
    auth_service = AuthService(
        user_repository=SqlUserRepository(db),
        api_key_repository=SqlAPIKeyRepository(db),
    )

    try:
        # Get user using application service
        domain_user = await auth_service.get_user_by_id(api_key.user_id)

        if not domain_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )

        # Convert to DB model for backward compatibility
        # Note: Removed selectinload for roles to reduce query overhead
        # Roles should be loaded on-demand when needed
        result = await db.execute(select(DBUser).where(DBUser.id == domain_user.id))
        db_user = result.scalar_one_or_none()

        if not db_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )

        return db_user

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e),
        ) from e


async def get_current_user_tenant(
    current_user: DBUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> str:
    """
    Get the current user's default tenant_id.

    This dependency ensures the user belongs to at least one tenant
    and returns the tenant_id for use in business logic.

    Returns:
        str: The user's default tenant_id

    Raises:
        HTTPException: If the user does not belong to any tenant
    """
    result = await db.execute(
        select(UserTenant.tenant_id).where(UserTenant.user_id == current_user.id).limit(1)
    )
    tenant_id = result.scalar_one_or_none()

    if not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User does not belong to any tenant. Please contact administrator.",
        )

    return tenant_id


async def create_api_key(
    db: AsyncSession,
    user_id: str,
    name: str,
    permissions: list[str],
    expires_in_days: int | None = None,
) -> tuple[str, DBAPIKey | None]:
    """
    Create a new API key for a user.

    This is a FastAPI adapter that uses the AuthService for business logic.
    Returns (plain_key, stored_key) tuple.
    """
    # Create AuthService with repositories
    auth_service = AuthService(
        user_repository=SqlUserRepository(db),
        api_key_repository=SqlAPIKeyRepository(db),
    )

    # Create using application service
    plain_key, domain_key = await auth_service.create_api_key(
        user_id=user_id,
        name=name,
        permissions=permissions,
        expires_in_days=expires_in_days,
    )

    # Convert to DB model for backward compatibility
    result = await db.execute(select(DBAPIKey).where(DBAPIKey.id == domain_key.id))
    db_key = result.scalar_one_or_none()

    return plain_key, db_key


async def create_user(db: AsyncSession, email: str, name: str, password: str) -> DBUser | None:
    """
    Create a new user.

    This is a FastAPI adapter that uses the AuthService for business logic.
    """
    # Create AuthService with repositories
    auth_service = AuthService(
        user_repository=SqlUserRepository(db),
        api_key_repository=SqlAPIKeyRepository(db),
    )

    # Create using application service
    domain_user = await auth_service.create_user(email=email, name=name, password=password)

    # Convert to DB model for backward compatibility
    result = await db.execute(select(DBUser).where(DBUser.id == domain_user.id))
    db_user = result.scalar_one_or_none()

    return db_user


# ============================================================================
# INITIALIZATION (Infrastructure concern, can stay in adapter layer)
# ============================================================================


async def _init_permissions(db: AsyncSession) -> dict[str, Permission]:
    """Create permissions if they don't exist. Return code->Permission map."""
    permissions_data = [
        {"code": "tenant:create", "name": "Create Tenant", "description": "Create new tenants"},
        {"code": "tenant:read", "name": "Read Tenant", "description": "View tenant details"},
        {"code": "tenant:update", "name": "Update Tenant", "description": "Update tenant details"},
        {"code": "tenant:delete", "name": "Delete Tenant", "description": "Delete tenants"},
        {"code": "project:create", "name": "Create Project", "description": "Create new projects"},
        {"code": "project:read", "name": "Read Project", "description": "View project details"},
        {
            "code": "project:update",
            "name": "Update Project",
            "description": "Update project details",
        },
        {"code": "project:delete", "name": "Delete Project", "description": "Delete projects"},
        {"code": "memory:create", "name": "Create Memory", "description": "Create new memories"},
        {"code": "memory:read", "name": "Read Memory", "description": "View memories"},
        {"code": "user:read", "name": "Read User", "description": "View user details"},
        {"code": "user:update", "name": "Update User", "description": "Update user details"},
    ]
    created_permissions: dict[str, Permission] = {}
    for perm_data in permissions_data:
        result = await db.execute(select(Permission).where(Permission.code == perm_data["code"]))
        perm = result.scalar_one_or_none()
        if not perm:
            perm = Permission(id=str(uuid4()), **perm_data)
            db.add(perm)
            await db.commit()
            await db.refresh(perm)
        created_permissions[perm_data["code"]] = perm
    return created_permissions


async def _init_roles(db: AsyncSession) -> dict[str, Role]:
    """Create roles if they don't exist. Return name->Role map."""
    roles_data = [
        {"name": "admin", "description": "System Administrator"},
        {"name": "user", "description": "Regular User"},
    ]
    created_roles: dict[str, Role] = {}
    for role_data in roles_data:
        result = await db.execute(select(Role).where(Role.name == role_data["name"]))
        role = result.scalar_one_or_none()
        if not role:
            role = Role(id=str(uuid4()), **role_data)
            db.add(role)
            await db.commit()
            await db.refresh(role)
        created_roles[role_data["name"]] = role
    return created_roles


async def _assign_role_permissions(
    db: AsyncSession,
    created_roles: dict[str, Role],
    created_permissions: dict[str, Permission],
) -> None:
    """Assign permissions to roles (admin=all, user=read+create)."""
    admin_role = created_roles["admin"]
    for perm in created_permissions.values():
        result = await db.execute(
            select(RolePermission).where(
                RolePermission.role_id == admin_role.id,
                RolePermission.permission_id == perm.id,
            )
        )
        if not result.scalar_one_or_none():
            db.add(RolePermission(id=str(uuid4()), role_id=admin_role.id, permission_id=perm.id))

    user_role = created_roles["user"]
    for code, perm in created_permissions.items():
        if "read" in code or "create" in code:
            result = await db.execute(
                select(RolePermission).where(
                    RolePermission.role_id == user_role.id,
                    RolePermission.permission_id == perm.id,
                )
            )
            if not result.scalar_one_or_none():
                db.add(RolePermission(id=str(uuid4()), role_id=user_role.id, permission_id=perm.id))
    await db.commit()


async def _ensure_tenant_membership(
    db: AsyncSession,
    user_id: str,
    tenant_id: str,
    role: str = "member",
    permissions: dict[str, Any] | None = None,
) -> None:
    """Ensure a user has membership in a tenant."""
    result = await db.execute(
        select(UserTenant).where(
            UserTenant.user_id == user_id,
            UserTenant.tenant_id == tenant_id,
        )
    )
    if not result.scalar_one_or_none():
        membership = UserTenant(
            id=str(uuid4()),
            user_id=user_id,
            tenant_id=tenant_id,
            role=role,
            permissions=permissions or {"read": True, "write": True},
        )
        db.add(membership)


async def _ensure_tenant_exists(
    db: AsyncSession,
    name: str,
    slug: str,
    description: str,
    owner_id: str,
) -> Tenant:
    """Create a tenant if it doesn't exist. Return the tenant."""
    result = await db.execute(select(Tenant).where(Tenant.name == name))
    tenant = result.scalar_one_or_none()
    if not tenant:
        tenant = Tenant(
            id=str(uuid4()),
            name=name,
            slug=slug,
            description=description,
            owner_id=owner_id,
        )
        db.add(tenant)
        await db.flush()
        logger.info(f"Tenant created: {name} ({tenant.id})")
    return tenant


async def _init_admin_user(
    db: AsyncSession,
    admin_role: Role,
    default_tenant: Tenant | None,
) -> tuple[DBUser | None, Tenant | None]:
    """Create admin user with API key and tenant if needed."""
    result = await db.execute(select(DBUser).where(DBUser.email == "admin@memstack.ai"))
    user = result.scalar_one_or_none()

    if not user:
        user = await create_user(
            db, email="admin@memstack.ai", name="Default Admin", password="adminpassword"
        )
        db.add(UserRole(id=str(uuid4()), user_id=user.id, role_id=admin_role.id))
        plain_key, _ = await create_api_key(
            db, user_id=user.id, name="Default API Key", permissions=["read", "write", "admin"]
        )
        logger.info(f"Default Admin API Key created: {plain_key}")
        logger.info(f"Default Admin ID: {user.id}")
        logger.info(f"Default Admin Email: {user.email}")
        logger.info("Default Admin Password: adminpassword")

        if not default_tenant:
            default_tenant = await _ensure_tenant_exists(
                db,
                "Default Tenant",
                "default-tenant",
                "Default tenant for demonstration",
                user.id,
            )
            await _ensure_tenant_membership(
                db, user.id, default_tenant.id, "owner", {"admin": True}
            )
    elif default_tenant:
        await _ensure_tenant_membership(db, user.id, default_tenant.id, "owner", {"admin": True})

    return user, default_tenant


async def _init_normal_user(
    db: AsyncSession,
    user_role: Role,
    default_tenant: Tenant | None,
) -> None:
    """Create normal user with API key and tenant if needed."""
    result = await db.execute(select(DBUser).where(DBUser.email == "user@memstack.ai"))
    normal_user = result.scalar_one_or_none()

    if not normal_user:
        normal_user = await create_user(
            db, email="user@memstack.ai", name="Default User", password="userpassword"
        )
        db.add(UserRole(id=str(uuid4()), user_id=normal_user.id, role_id=user_role.id))
        plain_user_key, _ = await create_api_key(
            db,
            user_id=normal_user.id,
            name="Default User Key",
            permissions=["read", "write"],
        )
        logger.info(f"Default User API Key created: {plain_user_key}")
        logger.info(f"Default User ID: {normal_user.id}")
        logger.info(f"Default User Email: {normal_user.email}")
        logger.info("Default User Password: userpassword")

        user_tenant = await _ensure_tenant_exists(
            db, "User Tenant", "user-tenant", "Default tenant for user", normal_user.id
        )
        await _ensure_tenant_membership(
            db, normal_user.id, user_tenant.id, "owner", {"admin": True}
        )
        if default_tenant:
            await _ensure_tenant_membership(
                db,
                normal_user.id,
                default_tenant.id,
                "member",
                {"read": True, "write": True},
            )
    else:
        user_tenant = await _ensure_tenant_exists(
            db, "User Tenant", "user-tenant", "Default tenant for user", normal_user.id
        )
        await _ensure_tenant_membership(
            db, normal_user.id, user_tenant.id, "owner", {"admin": True}
        )
        if default_tenant:
            await _ensure_tenant_membership(
                db,
                normal_user.id,
                default_tenant.id,
                "member",
                {"read": True, "write": True},
            )


async def initialize_default_credentials() -> None:
    """Initialize default user and API key for development."""
    async with async_session_factory() as db:
        try:
            # 1. Initialize Permissions
            created_permissions = await _init_permissions(db)
            # 2. Initialize Roles
            created_roles = await _init_roles(db)
            # 3. Assign Permissions to Roles
            await _assign_role_permissions(db, created_roles, created_permissions)

            # 4. Check if default tenant exists
            result = await db.execute(select(Tenant).where(Tenant.name == "Default Tenant"))
            default_tenant = result.scalar_one_or_none()
            # 5. Create Admin User
            _, default_tenant = await _init_admin_user(db, created_roles["admin"], default_tenant)

            # 6. Create Normal User
            await _init_normal_user(db, created_roles["user"], default_tenant)

            await db.commit()

        except Exception as e:
            logger.exception(f"Error initializing default credentials: {e}")
