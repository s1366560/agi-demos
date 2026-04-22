"""
Authentication router.
"""

import json as _json
import logging
import secrets
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.application.schemas.auth import (
    APIKeyCreate,
    APIKeyResponse,
    ForceChangePasswordRequest,
    ForceChangePasswordResponse,
    Token,
    User as UserSchema,
    UserUpdate,
)
from src.infrastructure.adapters.primary.web.dependencies import (
    create_api_key,
    get_current_user,
    verify_password,
)
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import (
    APIKey as DBAPIKey,
    Project as DBProject,
    Tenant,
    User as DBUser,
    UserProject,
    UserRole,
    UserTenant,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Authentication"])


async def _ensure_default_project(db: AsyncSession, user: DBUser) -> None:
    """
    Ensure user has a default project.

    If user has no projects, create a default project in their first tenant.
    This is called after successful login to ensure first-time users have a project.
    """
    # Check if user already has any projects
    result = await db.execute(refresh_select_statement(select(UserProject).where(UserProject.user_id == user.id).limit(1)))
    existing_project = result.scalar_one_or_none()

    if existing_project:
        # User already has a project, no need to create default
        return

    # Get user's first tenant (should exist from initialization)
    result = await db.execute(refresh_select_statement(select(UserTenant).where(UserTenant.user_id == user.id).limit(1)))
    user_tenant = result.scalar_one_or_none()

    if not user_tenant:
        logger.warning(f"User {user.id} has no tenant, cannot create default project")
        return

    # Get tenant details
    tenant_result = await db.execute(refresh_select_statement(select(Tenant).where(Tenant.id == user_tenant.tenant_id)))
    tenant = tenant_result.scalar_one_or_none()

    if not tenant:
        logger.warning(f"Tenant {user_tenant.tenant_id} not found for user {user.id}")
        return

    # Create default project
    default_project = DBProject(
        id=str(uuid4()),
        tenant_id=tenant.id,
        name="默认项目",
        description=f"{user.full_name or user.email} 的默认项目",
        owner_id=user.id,
        memory_rules={},
        graph_config={},
        is_public=False,
    )
    db.add(default_project)
    await db.flush()  # Flush to get the project ID

    # Create user-project relationship with owner role
    user_project = UserProject(
        id=str(uuid4()),
        user_id=user.id,
        project_id=default_project.id,
        role="owner",
        permissions={"admin": True, "read": True, "write": True, "delete": True},
    )
    db.add(user_project)

    logger.info(
        f"Created default project '{default_project.name}' ({default_project.id}) for user {user.id}"
    )


@router.post("/auth/token", response_model=Token)
async def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Login endpoint to get an access token (API Key).
    """
    logger.info(f"Login attempt for user: {form_data.username}")

    # Query user
    result = await db.execute(
        refresh_select_statement(select(DBUser)
        .where(DBUser.email == form_data.username)
        .options(selectinload(DBUser.roles).selectinload(UserRole.role)))
    )
    user = result.scalar_one_or_none()

    if user:
        logger.debug(f"User found: {user.email}")
        is_valid = verify_password(form_data.password, user.hashed_password)
        logger.debug(f"Password valid: {is_valid}")
    else:
        logger.debug("User not found")

    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is inactive",
        )

    # Check for admin role
    is_admin = any(r.role.name == "admin" for r in user.roles)
    permissions = ["read", "write"]
    if is_admin:
        permissions.append("admin")

    # Generate a temporary session API key
    plain_key, _ = await create_api_key(
        db,
        user_id=user.id,
        name=f"Login Session {form_data.username}",
        permissions=permissions,
        expires_in_days=1,  # Short lived token
    )

    # Ensure user has a default project (first-time login)
    await _ensure_default_project(db, user)

    # Commit the transaction to persist the API key and default project (if created)
    await db.commit()

    return {
        "access_token": plain_key,
        "token_type": "bearer",
        "must_change_password": bool(user.must_change_password),
    }


@router.post("/auth/force-change-password", response_model=ForceChangePasswordResponse)
async def force_change_password(
    request: ForceChangePasswordRequest,
    current_user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ForceChangePasswordResponse:
    if not verify_password(request.old_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )

    from src.application.services.auth_service_v2 import AuthService

    current_user.hashed_password = AuthService.get_password_hash(request.new_password)
    current_user.must_change_password = False
    db.add(current_user)
    await db.commit()

    return ForceChangePasswordResponse(
        success=True,
        message="Password changed successfully",
    )


@router.post("/auth/keys", response_model=APIKeyResponse)
async def create_new_api_key(
    key_data: APIKeyCreate,
    current_user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> APIKeyResponse:
    """Create a new API key."""
    plain_key, api_key = await create_api_key(
        db,
        user_id=current_user.id,
        name=key_data.name,
        permissions=key_data.permissions,
        expires_in_days=key_data.expires_in_days,
    )

    await db.commit()

    assert api_key is not None
    return APIKeyResponse(
        key_id=api_key.id,
        key=plain_key,  # Show only once
        name=api_key.name,
        created_at=api_key.created_at,
        expires_at=api_key.expires_at,
        permissions=api_key.permissions,
    )


@router.get("/auth/keys", response_model=list[APIKeyResponse])
async def list_api_keys(
    current_user: DBUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[Any]:
    """List all API keys for the current user."""
    result = await db.execute(refresh_select_statement(select(DBAPIKey).where(DBAPIKey.user_id == current_user.id)))
    keys = result.scalars().all()

    return [
        APIKeyResponse(
            key_id=k.id,
            key="*****************",  # Masked
            name=k.name,
            created_at=k.created_at,
            expires_at=k.expires_at,
            permissions=k.permissions,
        )
        for k in keys
    ]


@router.delete("/auth/keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(
    key_id: str,
    current_user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Revoke (delete) an API key."""
    result = await db.execute(
        refresh_select_statement(select(DBAPIKey).where(DBAPIKey.id == key_id, DBAPIKey.user_id == current_user.id))
    )
    key = result.scalar_one_or_none()

    if not key:
        raise HTTPException(status_code=404, detail="API key not found")

    await db.delete(key)
    await db.commit()


@router.get("/users/me", response_model=UserSchema)
@router.get("/auth/me", response_model=UserSchema)
async def read_users_me(
    current_user: DBUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> UserSchema:
    """Get current user information."""
    logger.info(f"Reading user info for: {current_user.id}")

    # Eager load roles to avoid lazy loading in async mode
    result = await db.execute(
        refresh_select_statement(select(DBUser)
        .options(selectinload(DBUser.roles).selectinload(UserRole.role))
        .where(DBUser.id == current_user.id))
    )
    user_with_roles = result.scalar_one_or_none()

    role_names = [r.role.name for r in user_with_roles.roles] if user_with_roles else []

    return UserSchema(
        user_id=current_user.id,
        email=current_user.email,
        name=current_user.full_name or "",
        roles=role_names,
        is_active=current_user.is_active,
        created_at=current_user.created_at,
        profile={},
    )


@router.put("/users/me", response_model=UserSchema)
async def update_user_me(
    user_update: UserUpdate,
    current_user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserSchema:
    """Update current user information."""
    if user_update.name is not None:
        current_user.full_name = user_update.name

    if user_update.profile is not None:
        # Merge existing profile with new profile data
        # Note: Profile is not currently supported in DBUser, so we skip it for now
        # current_profile = current_user.profile or {}
        # new_profile_data = user_update.profile.dict(exclude_unset=True)
        # current_profile.update(new_profile_data)
        # current_user.profile = current_profile
        pass

    db.add(current_user)
    await db.commit()
    await db.refresh(current_user)

    return UserSchema(
        user_id=current_user.id,
        email=current_user.email,
        name=current_user.full_name or "",
        roles=[r.role.name for r in current_user.roles],
        is_active=current_user.is_active,
        created_at=current_user.created_at,
        profile={},
    )


# ---------------------------------------------------------------------------
# Device-code flow (RFC 8628) — for CLI `memstack login`
# ---------------------------------------------------------------------------
#
# Flow:
#   1. CLI  → POST /auth/device/code        (unauthenticated)
#      Returns: {device_code, user_code, verification_uri, interval, expires_in}
#   2. User → browser to verification_uri, logs in, enters user_code, approves.
#      Approval happens via authenticated POST /auth/device/approve
#      {"user_code": "ABCD1234"} which binds the session to a user and
#      creates a session ms_sk_.
#   3. CLI  → POST /auth/device/token {device_code}  (polling, every `interval`)
#      Returns: 428 Precondition Required while pending,
#               200 {access_token, token_type} once approved,
#               410 Gone once expired.
#
# Storage: Redis key `memstack:device_code:{device_code}` → JSON
#   {"user_code": str, "status": "pending|approved|expired",
#    "approved_user_id": str|null, "access_token": str|null}
# Additional index `memstack:device_user_code:{user_code}` → device_code.
# TTL: 600 seconds (10 minutes).

_DEVICE_CODE_TTL = 600
_DEVICE_CODE_INTERVAL = 5
_USER_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no I,O,0,1 ambiguity
_USER_CODE_LEN = 8


def _new_user_code() -> str:
    return "".join(secrets.choice(_USER_CODE_ALPHABET) for _ in range(_USER_CODE_LEN))


def _device_key(device_code: str) -> str:
    return f"memstack:device_code:{device_code}"


def _user_code_key(user_code: str) -> str:
    return f"memstack:device_user_code:{user_code}"


@router.post("/auth/device/code")
async def device_code_request(request: dict[str, Any] | None = None) -> dict[str, Any]:
    """Create a new device-code session.

    Accepts an optional JSON body (currently unused but kept for forward
    compatibility with client_id / scope hints).
    """
    _ = request  # reserved
    from src.infrastructure.agent.state.agent_worker_state import get_redis_client

    redis_client = await get_redis_client()

    # Avoid collisions on user_code by retrying a few times.
    for _attempt in range(5):
        user_code = _new_user_code()
        if not await redis_client.exists(_user_code_key(user_code)):
            break
    else:
        raise HTTPException(status_code=503, detail="Could not allocate user code")

    device_code = secrets.token_urlsafe(32)
    payload = {
        "user_code": user_code,
        "status": "pending",
        "approved_user_id": None,
        "access_token": None,
    }
    await redis_client.setex(
        _device_key(device_code), _DEVICE_CODE_TTL, _json.dumps(payload)
    )
    await redis_client.setex(
        _user_code_key(user_code), _DEVICE_CODE_TTL, device_code
    )

    # The verification URI is the frontend route that reads user_code from
    # the URL, authenticates the user, and calls /auth/device/approve.
    # We return only the path; the CLI composes the full URL from its
    # configured base.
    return {
        "device_code": device_code,
        "user_code": user_code,
        "verification_uri": "/device",
        "verification_uri_complete": f"/device?user_code={user_code}",
        "expires_in": _DEVICE_CODE_TTL,
        "interval": _DEVICE_CODE_INTERVAL,
    }


@router.post("/auth/device/approve")
async def device_code_approve(
    payload: dict[str, Any],
    current_user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Approve a pending device code. Requires an authenticated user.

    The frontend `/device` page posts here with {"user_code": "..."}.
    """
    from src.infrastructure.agent.state.agent_worker_state import get_redis_client

    user_code = str(payload.get("user_code", "")).strip().upper()
    if not user_code:
        raise HTTPException(status_code=400, detail="user_code required")

    redis_client = await get_redis_client()
    device_code_raw = await redis_client.get(_user_code_key(user_code))
    if device_code_raw is None:
        raise HTTPException(status_code=404, detail="user_code expired or unknown")
    device_code = device_code_raw.decode() if isinstance(device_code_raw, bytes) else device_code_raw

    raw = await redis_client.get(_device_key(device_code))
    if raw is None:
        raise HTTPException(status_code=410, detail="device code expired")
    session = _json.loads(raw)
    if session.get("status") != "pending":
        raise HTTPException(status_code=409, detail=f"already {session.get('status')}")

    # Determine permissions like /auth/token does.
    is_admin = any(r.role.name == "admin" for r in current_user.roles)
    permissions = ["read", "write"] + (["admin"] if is_admin else [])

    plain_key, _api_key = await create_api_key(
        db,
        user_id=current_user.id,
        name=f"CLI device login ({user_code})",
        permissions=permissions,
        expires_in_days=30,
    )
    await db.commit()

    session["status"] = "approved"
    session["approved_user_id"] = current_user.id
    session["access_token"] = plain_key
    ttl = await redis_client.ttl(_device_key(device_code))
    ttl_seconds = ttl if ttl and ttl > 0 else _DEVICE_CODE_TTL
    await redis_client.setex(_device_key(device_code), ttl_seconds, _json.dumps(session))

    return {"status": "approved"}


@router.post("/auth/device/token")
async def device_code_token(payload: dict[str, Any]) -> dict[str, Any]:
    """Poll for a device-code approval. Unauthenticated — device_code is the secret."""
    from src.infrastructure.agent.state.agent_worker_state import get_redis_client

    device_code = str(payload.get("device_code", "")).strip()
    if not device_code:
        raise HTTPException(status_code=400, detail="device_code required")

    redis_client = await get_redis_client()
    raw = await redis_client.get(_device_key(device_code))
    if raw is None:
        raise HTTPException(status_code=410, detail="expired_token")
    session = _json.loads(raw)
    status_val = session.get("status", "pending")
    if status_val == "pending":
        # RFC 8628 uses 400 + error=authorization_pending. We use 428 so that
        # HTTP-generic retry logic can distinguish "not ready" from "bad".
        raise HTTPException(
            status_code=428,
            detail={"error": "authorization_pending", "interval": _DEVICE_CODE_INTERVAL},
        )
    if status_val != "approved":
        raise HTTPException(status_code=410, detail=status_val)

    access_token = session.get("access_token")
    if not access_token:
        raise HTTPException(status_code=500, detail="approved but no token stored")

    # Single-use: delete the device code + user_code index.
    await redis_client.delete(_device_key(device_code))
    user_code = session.get("user_code")
    if user_code:
        await redis_client.delete(_user_code_key(user_code))

    return {"access_token": access_token, "token_type": "bearer"}
