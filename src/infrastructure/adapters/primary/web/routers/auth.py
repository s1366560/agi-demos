"""
Authentication router.
"""

from __future__ import annotations

import json as _json
import logging
import secrets
from collections.abc import AsyncIterator, Awaitable
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, cast
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, ConfigDict
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
from src.application.use_cases.auth.list_api_keys import ListAPIKeysQuery, ListAPIKeysUseCase
from src.infrastructure.adapters.primary.web.dependencies import (
    create_api_key,
    get_api_key_from_header,
    get_current_user,
    hash_api_key,
    verify_password,
)
from src.infrastructure.adapters.secondary.cache.redis_lock import RedisDistributedLock
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import (
    APIKey as DBAPIKey,
    Project as DBProject,
    Role,
    Tenant,
    User as DBUser,
    UserProject,
    UserRole,
    UserTenant,
)
from src.infrastructure.adapters.secondary.persistence.sql_api_key_repository import (
    SqlAPIKeyRepository,
)
from src.infrastructure.i18n import gettext as _

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Authentication"])


class OAuthCallbackRequest(BaseModel):
    code: str
    state: str | None = None
    redirect_uri: str | None = None


class DeviceCodeCancelRequest(BaseModel):
    """Device-code cancellation request; caller-supplied token fields are rejected."""

    model_config = ConfigDict(extra="forbid")

    device_code: str


def _user_profile(user: DBUser) -> dict[str, Any]:
    return dict(user.profile or {})


async def _ensure_default_project(db: AsyncSession, user: DBUser) -> None:
    """
    Ensure user has a default project.

    If user has no projects, create a default project in their first tenant.
    This is called after successful login to ensure first-time users have a project.
    """
    # Check if user already has any projects
    result = await db.execute(
        refresh_select_statement(select(UserProject).where(UserProject.user_id == user.id).limit(1))
    )
    existing_project = result.scalar_one_or_none()

    if existing_project:
        # User already has a project, no need to create default
        return

    # Get user's first tenant (should exist from initialization)
    result = await db.execute(
        refresh_select_statement(
            select(UserTenant)
            .where(UserTenant.user_id == user.id)
            .order_by(UserTenant.created_at.asc(), UserTenant.id.asc())
            .limit(1)
        )
    )
    user_tenant = result.scalar_one_or_none()

    if not user_tenant:
        logger.warning(f"User {user.id} has no tenant, cannot create default project")
        return

    # Get tenant details
    tenant_result = await db.execute(
        refresh_select_statement(select(Tenant).where(Tenant.id == user_tenant.tenant_id))
    )
    tenant = tenant_result.scalar_one_or_none()

    if not tenant:
        logger.warning(f"Tenant {user_tenant.tenant_id} not found for user {user.id}")
        return

    # Create default project
    owner_display = user.full_name or user.email
    default_project = DBProject(
        id=str(uuid4()),
        tenant_id=tenant.id,
        name=_("Default project"),
        description=_("Default project for {owner}").format(owner=owner_display),
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
        refresh_select_statement(
            select(DBUser)
            .where(DBUser.email == form_data.username)
            .options(selectinload(DBUser.roles).selectinload(UserRole.role))
        )
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
            detail=_("Incorrect username or password"),
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_("User account is inactive"),
        )

    # Check for admin role
    is_admin = any(r.role.name == "admin" for r in user.roles)
    permissions = ["read", "write"]
    if is_admin:
        permissions.append("admin")

    # Generate a temporary session API key
    plain_key, _hashed_key = await create_api_key(
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


@router.post("/auth/signout")
async def sign_out(
    api_key: str = Depends(get_api_key_from_header),
    db: AsyncSession = Depends(get_db),
) -> dict[str, bool]:
    """Revoke only the API key supplied by the Authorization header.

    The route deliberately does not bind a request body. Looking up by the
    bearer hash makes repeated sign-out calls successful without authenticating
    a key that may already have been deleted.
    """
    repository = SqlAPIKeyRepository(db)
    await repository.delete_by_hash(hash_api_key(api_key))
    await db.commit()
    return {"success": True}


@router.post("/auth/oauth/{provider}/callback", status_code=status.HTTP_501_NOT_IMPLEMENTED)
async def oauth_callback(provider: str, _request: OAuthCallbackRequest) -> None:
    """Return an explicit unsupported response until OAuth providers are configured."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=_("OAuth login is not configured"),
    )


@router.post("/auth/force-change-password", response_model=ForceChangePasswordResponse)
async def force_change_password(
    request: ForceChangePasswordRequest,
    current_user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ForceChangePasswordResponse:
    if not verify_password(request.old_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_("Current password is incorrect"),
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
    limit: int = Query(100, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[APIKeyResponse]:
    """List all API keys for the current user."""
    use_case = ListAPIKeysUseCase(SqlAPIKeyRepository(db))
    keys = await use_case.execute(
        ListAPIKeysQuery(
            user_id=current_user.id,
            limit=limit,
            offset=offset,
        )
    )

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
        refresh_select_statement(
            select(DBAPIKey).where(DBAPIKey.id == key_id, DBAPIKey.user_id == current_user.id)
        )
    )
    key = result.scalar_one_or_none()

    if not key:
        raise HTTPException(status_code=404, detail=_("API key not found"))

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
        refresh_select_statement(
            select(DBUser)
            .options(selectinload(DBUser.roles).selectinload(UserRole.role))
            .where(DBUser.id == current_user.id)
        )
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
        profile=_user_profile(current_user),
        preferred_language=current_user.preferred_language,
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

    if user_update.preferred_language is not None:
        current_user.preferred_language = user_update.preferred_language

    if user_update.profile is not None:
        profile_update = user_update.profile.model_dump(exclude_unset=True)
        current_user.profile = {**_user_profile(current_user), **profile_update}

    db.add(current_user)
    await db.commit()
    await db.refresh(current_user)

    # Reload roles for response
    result = await db.execute(
        refresh_select_statement(
            select(DBUser)
            .options(selectinload(DBUser.roles).selectinload(UserRole.role))
            .where(DBUser.id == current_user.id)
        )
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
        profile=_user_profile(current_user),
        preferred_language=current_user.preferred_language,
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
#   4. CLI  → POST /auth/device/cancel {device_code} when abandoning the flow.
#      This revokes a bound token, including one returned during a cancellation race.
#
# Storage: Redis key `memstack:device_code:{device_code}` → JSON
#   {"user_code": str, "status": "pending|approved|consumed|expired",
#    "approved_user_id": str|null, "access_token": str|null}
# Additional index `memstack:device_user_code:{user_code}` → device_code.
# TTL: 600 seconds (10 minutes).

_DEVICE_CODE_TTL = 600
_DEVICE_CODE_INTERVAL = 5
_DEVICE_SESSION_LOCK_TTL = 60
_USER_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no I,O,0,1 ambiguity
_USER_CODE_LEN = 8


def _new_user_code() -> str:
    return "".join(secrets.choice(_USER_CODE_ALPHABET) for _ in range(_USER_CODE_LEN))


def _device_key(device_code: str) -> str:
    return f"memstack:device_code:{device_code}"


def _user_code_key(user_code: str) -> str:
    return f"memstack:device_user_code:{user_code}"


@asynccontextmanager
async def _device_session_lock(
    redis_client: Redis,
    device_code: str,
) -> AsyncIterator[RedisDistributedLock]:
    """Serialize approval, token redemption, and cancellation without logging the secret."""
    lock = RedisDistributedLock(
        redis_client,
        hash_api_key(device_code),
        ttl=_DEVICE_SESSION_LOCK_TTL,
        retry_interval=0.05,
        max_retries=100,
        namespace="memstack:device-lock",
    )
    if not await lock.acquire(timeout=5):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_("Device authorization is busy; retry shortly"),
        )
    try:
        yield lock
    finally:
        await lock.release()


async def _compare_and_set_device_grant(
    redis_client: Redis,
    lock: RedisDistributedLock,
    device_code: str,
    expected: str,
    replacement: str,
    *,
    remove_user_code: str | None = None,
) -> bool:
    """Replace a grant only while this request still owns the matching lease."""
    script = """
    if redis.call("GET", KEYS[1]) ~= ARGV[1] then
        return 0
    end
    if redis.call("GET", KEYS[2]) ~= ARGV[2] then
        return 0
    end
    redis.call("SET", KEYS[2], ARGV[3], "KEEPTTL")
    if #KEYS == 3 and redis.call("GET", KEYS[3]) == ARGV[4] then
        redis.call("DEL", KEYS[3])
    end
    return 1
    """
    keys = [lock.key, _device_key(device_code)]
    if remove_user_code is not None:
        keys.append(_user_code_key(remove_user_code))
    result = await cast(
        Awaitable[int],
        redis_client.eval(
            script,
            len(keys),
            *keys,
            lock.owner,
            expected,
            replacement,
            device_code,
        ),
    )
    return result == 1


async def _compare_and_delete_device_grant(
    redis_client: Redis,
    lock: RedisDistributedLock,
    device_code: str,
    expected: str,
    user_code: str,
) -> int:
    """Delete one exact grant and its still-matching user-code index."""
    script = """
    if redis.call("GET", KEYS[1]) ~= ARGV[1] then
        return -1
    end
    if redis.call("GET", KEYS[2]) ~= ARGV[2] then
        return 0
    end
    redis.call("DEL", KEYS[2])
    if redis.call("GET", KEYS[3]) == ARGV[3] then
        redis.call("DEL", KEYS[3])
    end
    return 1
    """
    return await cast(
        Awaitable[int],
        redis_client.eval(
            script,
            3,
            lock.key,
            _device_key(device_code),
            _user_code_key(user_code),
            lock.owner,
            expected,
            device_code,
        ),
    )


@router.post("/auth/device/code")
async def device_code_request(request: dict[str, Any] | None = None) -> dict[str, Any]:
    """Create a new device-code session.

    Accepts an optional JSON body (currently unused but kept for forward
    compatibility with client_id / scope hints).
    """
    _request_unused = request  # reserved
    from src.infrastructure.agent.state.agent_worker_state import get_redis_client

    redis_client = await get_redis_client()

    # Avoid collisions on user_code by retrying a few times.
    for _attempt in range(5):
        user_code = _new_user_code()
        if not await redis_client.exists(_user_code_key(user_code)):
            break
    else:
        raise HTTPException(status_code=503, detail=_("Could not allocate user code"))

    device_code = secrets.token_urlsafe(32)
    payload = {
        "user_code": user_code,
        "status": "pending",
        "approved_user_id": None,
        "access_token": None,
    }
    await redis_client.setex(_device_key(device_code), _DEVICE_CODE_TTL, _json.dumps(payload))
    await redis_client.setex(_user_code_key(user_code), _DEVICE_CODE_TTL, device_code)

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
        raise HTTPException(status_code=400, detail=_("user_code required"))

    redis_client = await get_redis_client()
    device_code_raw = await redis_client.get(_user_code_key(user_code))
    if device_code_raw is None:
        raise HTTPException(status_code=404, detail=_("user_code expired or unknown"))
    device_code = (
        device_code_raw.decode() if isinstance(device_code_raw, bytes) else device_code_raw
    )

    async with _device_session_lock(redis_client, device_code) as device_lock:
        raw = await redis_client.get(_device_key(device_code))
        if raw is None:
            raise HTTPException(status_code=410, detail=_("device code expired"))
        original = raw.decode() if isinstance(raw, bytes) else str(raw)
        session = _json.loads(original)
        if session.get("status") != "pending":
            raise HTTPException(
                status_code=409,
                detail=_("Device code has already been handled"),
            )

        # Determine permissions like /auth/token does without async lazy loading.
        role_result = await db.execute(
            refresh_select_statement(
                select(Role.name)
                .join(UserRole, UserRole.role_id == Role.id)
                .where(UserRole.user_id == current_user.id)
            )
        )
        is_admin = "admin" in role_result.scalars().all()
        permissions = ["read", "write"] + (["admin"] if is_admin else [])

        plain_key, _api_key = await create_api_key(
            db,
            user_id=current_user.id,
            name=f"CLI device login ({user_code})",
            permissions=permissions,
            expires_in_days=30,
        )
        session["status"] = "approved"
        session["approved_user_id"] = current_user.id
        session["access_token"] = plain_key
        approved = _json.dumps(session)
        try:
            await db.commit()
        except BaseException:
            await db.rollback()
            repository = SqlAPIKeyRepository(db)
            await repository.delete_by_hash(hash_api_key(plain_key))
            await db.commit()
            raise

        try:
            published = await _compare_and_set_device_grant(
                redis_client,
                device_lock,
                device_code,
                original,
                approved,
            )
        except BaseException:
            repository = SqlAPIKeyRepository(db)
            await repository.delete_by_hash(hash_api_key(plain_key))
            await db.commit()
            raise
        if not published:
            repository = SqlAPIKeyRepository(db)
            await repository.delete_by_hash(hash_api_key(plain_key))
            await db.commit()
            raise HTTPException(
                status_code=409,
                detail=_("Device code has already been handled"),
            )

    return {"status": "approved"}


@router.post("/auth/device/token")
async def device_code_token(payload: dict[str, Any]) -> dict[str, Any]:
    """Poll for a device-code approval. Unauthenticated — device_code is the secret."""
    from src.infrastructure.agent.state.agent_worker_state import get_redis_client

    device_code = str(payload.get("device_code", "")).strip()
    if not device_code:
        raise HTTPException(status_code=400, detail=_("device_code required"))

    redis_client = await get_redis_client()
    async with _device_session_lock(redis_client, device_code) as device_lock:
        raw = await redis_client.get(_device_key(device_code))
        if raw is None:
            raise HTTPException(status_code=410, detail=_("expired_token"))
        original = raw.decode() if isinstance(raw, bytes) else str(raw)
        session = _json.loads(original)
        status_val = session.get("status", "pending")
        if status_val == "pending":
            # RFC 8628 uses 400 + error=authorization_pending. We use 428 so that
            # HTTP-generic retry logic can distinguish "not ready" from "bad".
            raise HTTPException(
                status_code=428,
                detail={"error": "authorization_pending", "interval": _DEVICE_CODE_INTERVAL},
            )
        if status_val != "approved":
            raise HTTPException(status_code=410, detail=_("device code was not approved"))

        access_token = session.get("access_token")
        if not access_token:
            raise HTTPException(status_code=500, detail=_("approved but no token stored"))

        # Mark single-use without dropping the server-bound token immediately.
        # A racing client cancellation can still revoke it until this grant expires.
        session["status"] = "consumed"
        user_code = session.get("user_code")
        consumed = await _compare_and_set_device_grant(
            redis_client,
            device_lock,
            device_code,
            original,
            _json.dumps(session),
            remove_user_code=user_code if isinstance(user_code, str) else None,
        )
        if not consumed:
            raise HTTPException(status_code=410, detail=_("expired_token"))

        return {"access_token": access_token, "token_type": "bearer"}


@router.post("/auth/device/cancel")
async def device_code_cancel(
    request: DeviceCodeCancelRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, bool]:
    """Idempotently abandon a device grant and revoke only its server-bound token."""
    from src.infrastructure.agent.state.agent_worker_state import get_redis_client

    device_code = request.device_code.strip()
    if not device_code:
        raise HTTPException(status_code=400, detail=_("device_code required"))

    redis_client = await get_redis_client()
    async with _device_session_lock(redis_client, device_code) as device_lock:
        while True:
            raw = await redis_client.get(_device_key(device_code))
            if raw is None:
                return {"success": True}

            original = raw.decode() if isinstance(raw, bytes) else str(raw)
            session = _json.loads(original)
            access_token = session.get("access_token")
            if isinstance(access_token, str) and access_token:
                repository = SqlAPIKeyRepository(db)
                await repository.delete_by_hash(hash_api_key(access_token))
                await db.commit()

            user_code = session.get("user_code")
            if not isinstance(user_code, str) or not user_code:
                raise HTTPException(
                    status_code=500,
                    detail=_("device authorization record is invalid"),
                )
            deleted = await _compare_and_delete_device_grant(
                redis_client,
                device_lock,
                device_code,
                original,
                user_code,
            )
            if deleted == 1:
                return {"success": True}
            if deleted == -1:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=_("Device authorization is busy; retry shortly"),
                )
