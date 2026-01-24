"""
Authentication middleware and dependencies for API Key validation.

This file serves as a FastAPI-specific adapter layer that bridges between
FastAPI's dependency injection system and the application's AuthService.
Business logic is delegated to AuthService in the application layer.
"""

import logging
from typing import Optional, Tuple
from uuid import uuid4

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.application.services.auth_service_v2 import AuthService
from src.infrastructure.adapters.secondary.persistence.database import async_session_factory, get_db
from src.infrastructure.adapters.secondary.persistence.models import APIKey as DBAPIKey
from src.infrastructure.adapters.secondary.persistence.models import (
    Permission,
    Role,
    RolePermission,
    Tenant,
    UserRole,
    UserTenant,
)
from src.infrastructure.adapters.secondary.persistence.models import User as DBUser
from src.infrastructure.adapters.secondary.persistence.sql_api_key_repository import (
    SqlAlchemyAPIKeyRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_user_repository import (
    SqlAlchemyUserRepository,
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
    authorization: Optional[str] = Header(None),
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


async def verify_api_key_dependency(
    api_key: str = Depends(get_api_key_from_header), db: AsyncSession = Depends(get_db)
) -> DBAPIKey:
    """
    Dependency to verify API key from request header.

    This is a FastAPI adapter that uses the AuthService for business logic.
    """
    # Create AuthService with repositories
    auth_service = AuthService(
        user_repository=SqlAlchemyUserRepository(db),
        api_key_repository=SqlAlchemyAPIKeyRepository(db),
    )

    try:
        # Verify using application service
        domain_api_key = await auth_service.verify_api_key(api_key)

        # Convert to DB model for backward compatibility
        result = await db.execute(select(DBAPIKey).where(DBAPIKey.id == domain_api_key.id))
        db_key = result.scalar_one_or_none()

        if db_key:
            # Update in DB to match domain model
            db_key.last_used_at = domain_api_key.last_used_at
            await db.commit()
            await db.refresh(db_key)

        return db_key

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
        )


async def get_current_user(
    api_key: DBAPIKey = Depends(verify_api_key_dependency), db: AsyncSession = Depends(get_db)
) -> DBUser:
    """
    Get the current user from the API key.

    This is a FastAPI adapter that uses the AuthService for business logic.
    """
    # Create AuthService with repositories
    auth_service = AuthService(
        user_repository=SqlAlchemyUserRepository(db),
        api_key_repository=SqlAlchemyAPIKeyRepository(db),
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
        result = await db.execute(
            select(DBUser)
            .where(DBUser.id == domain_user.id)
            .options(selectinload(DBUser.roles).selectinload(UserRole.role))
        )
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
        )


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
    expires_in_days: Optional[int] = None,
) -> Tuple[str, DBAPIKey]:
    """
    Create a new API key for a user.

    This is a FastAPI adapter that uses the AuthService for business logic.
    Returns (plain_key, stored_key) tuple.
    """
    # Create AuthService with repositories
    auth_service = AuthService(
        user_repository=SqlAlchemyUserRepository(db),
        api_key_repository=SqlAlchemyAPIKeyRepository(db),
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


async def create_user(db: AsyncSession, email: str, name: str, password: str) -> DBUser:
    """
    Create a new user.

    This is a FastAPI adapter that uses the AuthService for business logic.
    """
    # Create AuthService with repositories
    auth_service = AuthService(
        user_repository=SqlAlchemyUserRepository(db),
        api_key_repository=SqlAlchemyAPIKeyRepository(db),
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


async def initialize_default_credentials():
    """Initialize default user and API key for development."""
    async with async_session_factory() as db:
        try:
            # 1. Initialize Permissions
            permissions_data = [
                {
                    "code": "tenant:create",
                    "name": "Create Tenant",
                    "description": "Create new tenants",
                },
                {
                    "code": "tenant:read",
                    "name": "Read Tenant",
                    "description": "View tenant details",
                },
                {
                    "code": "tenant:update",
                    "name": "Update Tenant",
                    "description": "Update tenant details",
                },
                {"code": "tenant:delete", "name": "Delete Tenant", "description": "Delete tenants"},
                {
                    "code": "project:create",
                    "name": "Create Project",
                    "description": "Create new projects",
                },
                {
                    "code": "project:read",
                    "name": "Read Project",
                    "description": "View project details",
                },
                {
                    "code": "project:update",
                    "name": "Update Project",
                    "description": "Update project details",
                },
                {
                    "code": "project:delete",
                    "name": "Delete Project",
                    "description": "Delete projects",
                },
                {
                    "code": "memory:create",
                    "name": "Create Memory",
                    "description": "Create new memories",
                },
                {"code": "memory:read", "name": "Read Memory", "description": "View memories"},
                {"code": "user:read", "name": "Read User", "description": "View user details"},
                {
                    "code": "user:update",
                    "name": "Update User",
                    "description": "Update user details",
                },
            ]

            created_permissions = {}
            for perm_data in permissions_data:
                result = await db.execute(
                    select(Permission).where(Permission.code == perm_data["code"])
                )
                perm = result.scalar_one_or_none()
                if not perm:
                    perm = Permission(id=str(uuid4()), **perm_data)
                    db.add(perm)
                    await db.commit()
                    await db.refresh(perm)
                created_permissions[perm_data["code"]] = perm

            # 2. Initialize Roles
            roles_data = [
                {"name": "admin", "description": "System Administrator"},
                {"name": "user", "description": "Regular User"},
            ]

            created_roles = {}
            for role_data in roles_data:
                result = await db.execute(select(Role).where(Role.name == role_data["name"]))
                role = result.scalar_one_or_none()
                if not role:
                    role = Role(id=str(uuid4()), **role_data)
                    db.add(role)
                    await db.commit()
                    await db.refresh(role)
                created_roles[role_data["name"]] = role

            # 3. Assign Permissions to Roles
            # Admin gets all permissions
            admin_role = created_roles["admin"]
            for perm in created_permissions.values():
                result = await db.execute(
                    select(RolePermission).where(
                        RolePermission.role_id == admin_role.id,
                        RolePermission.permission_id == perm.id,
                    )
                )
                if not result.scalar_one_or_none():
                    db.add(
                        RolePermission(
                            id=str(uuid4()), role_id=admin_role.id, permission_id=perm.id
                        )
                    )

            # User gets read permissions
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
                        db.add(
                            RolePermission(
                                id=str(uuid4()), role_id=user_role.id, permission_id=perm.id
                            )
                        )

            await db.commit()

            # 4. Create Users using AuthService
            # Check if default user exists
            result = await db.execute(select(DBUser).where(DBUser.email == "admin@memstack.ai"))
            user = result.scalar_one_or_none()

            # Check if default tenant exists
            result = await db.execute(select(Tenant).where(Tenant.name == "Default Tenant"))
            default_tenant = result.scalar_one_or_none()

            if not user:
                user = await create_user(
                    db, email="admin@memstack.ai", name="Default Admin", password="adminpassword"
                )

                # Assign Admin Role
                db.add(UserRole(id=str(uuid4()), user_id=user.id, role_id=admin_role.id))

                plain_key, _ = await create_api_key(
                    db,
                    user_id=user.id,
                    name="Default API Key",
                    permissions=["read", "write", "admin"],
                )

                logger.info(f"🔑 Default Admin API Key created: {plain_key}")
                logger.info(f"👤 Default Admin ID: {user.id}")
                logger.info(f"📧 Default Admin Email: {user.email}")
                logger.info("🔑 Default Admin Password: adminpassword")

                # Create Default Tenant if not exists and assign admin as owner
                if not default_tenant:
                    default_tenant = Tenant(
                        id=str(uuid4()),
                        name="Default Tenant",
                        slug="default-tenant",  # Required unique field
                        description="Default tenant for demonstration",
                        owner_id=user.id,
                    )
                    db.add(default_tenant)
                    await db.flush()  # flush to get ID
                    logger.info(f"🏢 Default Tenant created: {default_tenant.id}")

                    # Add admin as owner of the tenant
                    admin_tenant_membership = UserTenant(
                        id=str(uuid4()),
                        user_id=user.id,
                        tenant_id=default_tenant.id,
                        role="owner",
                        permissions={"admin": True},
                    )
                    db.add(admin_tenant_membership)

            # If user exists but tenant was just created (edge case or partial init), ensure membership
            elif default_tenant:
                # Check if admin is member
                result = await db.execute(
                    select(UserTenant).where(
                        UserTenant.user_id == user.id, UserTenant.tenant_id == default_tenant.id
                    )
                )
                if not result.scalar_one_or_none():
                    admin_tenant_membership = UserTenant(
                        id=str(uuid4()),
                        user_id=user.id,
                        tenant_id=default_tenant.id,
                        role="owner",
                        permissions={"admin": True},
                    )
                    db.add(admin_tenant_membership)

            # Check if default regular user exists
            result = await db.execute(select(DBUser).where(DBUser.email == "user@memstack.ai"))
            normal_user = result.scalar_one_or_none()

            if not normal_user:
                normal_user = await create_user(
                    db, email="user@memstack.ai", name="Default User", password="userpassword"
                )

                # Assign User Role
                db.add(UserRole(id=str(uuid4()), user_id=normal_user.id, role_id=user_role.id))

                plain_user_key, _ = await create_api_key(
                    db,
                    user_id=normal_user.id,
                    name="Default User Key",
                    permissions=["read", "write"],
                )

                logger.info(f"🔑 Default User API Key created: {plain_user_key}")
                logger.info(f"👤 Default User ID: {normal_user.id}")
                logger.info(f"📧 Default User Email: {normal_user.email}")
                logger.info("🔑 Default User Password: userpassword")

                # Create Tenant for User if not exists
                result = await db.execute(select(Tenant).where(Tenant.name == "User Tenant"))
                user_tenant = result.scalar_one_or_none()
                if not user_tenant:
                    user_tenant = Tenant(
                        id=str(uuid4()),
                        name="User Tenant",
                        slug="user-tenant",  # Required unique field
                        description="Default tenant for user",
                        owner_id=normal_user.id,
                    )
                    db.add(user_tenant)
                    await db.flush()  # flush to get ID
                    logger.info(f"🏢 User Tenant created: {user_tenant.id}")

                    # Add normal user as owner of their tenant
                    user_tenant_membership = UserTenant(
                        id=str(uuid4()),
                        user_id=normal_user.id,
                        tenant_id=user_tenant.id,
                        role="owner",
                        permissions={"admin": True},
                    )
                    db.add(user_tenant_membership)

                # Add normal user to default tenant as member (optional, but good for demo)
                if default_tenant:
                    # Check if already member
                    result = await db.execute(
                        select(UserTenant).where(
                            UserTenant.user_id == normal_user.id,
                            UserTenant.tenant_id == default_tenant.id,
                        )
                    )
                    if not result.scalar_one_or_none():
                        user_tenant_membership = UserTenant(
                            id=str(uuid4()),
                            user_id=normal_user.id,
                            tenant_id=default_tenant.id,
                            role="member",
                            permissions={"read": True, "write": True},
                        )
                        db.add(user_tenant_membership)

            elif normal_user:
                # Ensure user has their own tenant
                result = await db.execute(select(Tenant).where(Tenant.name == "User Tenant"))
                user_tenant = result.scalar_one_or_none()
                if not user_tenant:
                    user_tenant = Tenant(
                        id=str(uuid4()),
                        name="User Tenant",
                        slug="user-tenant",
                        description="Default tenant for user",
                        owner_id=normal_user.id,
                    )
                    db.add(user_tenant)
                    await db.flush()
                    logger.info(f"🏢 User Tenant created: {user_tenant.id}")

                    # Add normal user as owner
                    user_tenant_membership = UserTenant(
                        id=str(uuid4()),
                        user_id=normal_user.id,
                        tenant_id=user_tenant.id,
                        role="owner",
                        permissions={"admin": True},
                    )
                    db.add(user_tenant_membership)

                else:
                    # Check membership in own tenant
                    result = await db.execute(
                        select(UserTenant).where(
                            UserTenant.user_id == normal_user.id,
                            UserTenant.tenant_id == user_tenant.id,
                        )
                    )
                    if not result.scalar_one_or_none():
                        user_tenant_membership = UserTenant(
                            id=str(uuid4()),
                            user_id=normal_user.id,
                            tenant_id=user_tenant.id,
                            role="owner",
                            permissions={"admin": True},
                        )
                        db.add(user_tenant_membership)

                # Check if normal user is member of default tenant
                if default_tenant:
                    result = await db.execute(
                        select(UserTenant).where(
                            UserTenant.user_id == normal_user.id,
                            UserTenant.tenant_id == default_tenant.id,
                        )
                    )
                    if not result.scalar_one_or_none():
                        user_tenant_membership = UserTenant(
                            id=str(uuid4()),
                            user_id=normal_user.id,
                            tenant_id=default_tenant.id,
                            role="member",
                            permissions={"read": True, "write": True},
                        )
                        db.add(user_tenant_membership)

            # 5. Optional: Register CUA/Codebox MCP servers for default tenant
            try:
                from src.configuration.config import get_settings
                from src.infrastructure.adapters.secondary.persistence.sql_mcp_server_repository import (
                    SQLMCPServerRepository,
                )

                settings = get_settings()
                if settings.cua_enabled and default_tenant:
                    mcp_repo = SQLMCPServerRepository(db)
                    existing = await mcp_repo.get_by_name(
                        tenant_id=default_tenant.id,
                        name="cua",
                    )
                    if not existing:
                        await mcp_repo.create(
                            tenant_id=default_tenant.id,
                            name="cua",
                            description="CUA MCP server (websocket)",
                            server_type="websocket",
                            transport_config={
                                "url": settings.cua_mcp_url,
                                "headers": {},
                                "timeout": 30000,
                            },
                            enabled=True,
                        )
                        logger.info(
                            "🧩 CUA MCP server registered for Default Tenant (name=cua, websocket)"
                        )

                if default_tenant:
                    mcp_repo = SQLMCPServerRepository(db)
                    existing = await mcp_repo.get_by_name(
                        tenant_id=default_tenant.id,
                        name="codebox",
                    )
                    if not existing:
                        await mcp_repo.create(
                            tenant_id=default_tenant.id,
                            name="codebox",
                            description="Codebox MCP server (websocket)",
                            server_type="websocket",
                            transport_config={
                                "url": settings.codebox_mcp_url,
                                "headers": {},
                                "timeout": 30000,
                            },
                            enabled=True,
                        )
                        logger.info(
                            "🧩 Codebox MCP server registered for Default Tenant (name=codebox, websocket)"
                        )
            except Exception as e:
                logger.warning(f"Failed to register default MCP servers (CUA/codebox): {e}")

            await db.commit()

        except Exception as e:
            logger.exception(f"Error initializing default credentials: {e}")
