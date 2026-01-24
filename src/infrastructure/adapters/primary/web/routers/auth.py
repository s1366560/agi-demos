"""
Authentication router.
"""

import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.application.schemas.auth import (
    APIKeyCreate,
    APIKeyResponse,
    Token,
    UserUpdate,
)
from src.application.schemas.auth import (
    User as UserSchema,
)
from src.infrastructure.adapters.primary.web.dependencies import (
    create_api_key,
    get_current_user,
    verify_password,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import APIKey as DBAPIKey
from src.infrastructure.adapters.secondary.persistence.models import User as DBUser
from src.infrastructure.adapters.secondary.persistence.models import UserRole

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Authentication"])


@router.post("/auth/token", response_model=Token)
async def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
):
    """
    Login endpoint to get an access token (API Key).
    """
    logger.info(f"Login attempt for user: {form_data.username}")

    # Query user
    result = await db.execute(
        select(DBUser)
        .where(DBUser.email == form_data.username)
        .options(selectinload(DBUser.roles).selectinload(UserRole.role))
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

    # Commit the transaction to persist the API key
    await db.commit()

    return {"access_token": plain_key, "token_type": "bearer"}


@router.post("/auth/keys", response_model=APIKeyResponse)
async def create_new_api_key(
    key_data: APIKeyCreate,
    current_user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new API key."""
    plain_key, api_key = await create_api_key(
        db,
        user_id=current_user.id,
        name=key_data.name,
        permissions=key_data.permissions,
        expires_in_days=key_data.expires_in_days,
    )

    return APIKeyResponse(
        key_id=api_key.id,
        key=plain_key,  # Show only once
        name=api_key.name,
        created_at=api_key.created_at,
        expires_at=api_key.expires_at,
        permissions=api_key.permissions,
    )


@router.get("/auth/keys", response_model=List[APIKeyResponse])
async def list_api_keys(
    current_user: DBUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    """List all API keys for the current user."""
    result = await db.execute(select(DBAPIKey).where(DBAPIKey.user_id == current_user.id))
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
):
    """Revoke (delete) an API key."""
    result = await db.execute(
        select(DBAPIKey).where(DBAPIKey.id == key_id, DBAPIKey.user_id == current_user.id)
    )
    key = result.scalar_one_or_none()

    if not key:
        raise HTTPException(status_code=404, detail="API key not found")

    await db.delete(key)
    await db.commit()


@router.get("/users/me", response_model=UserSchema)
@router.get("/auth/me", response_model=UserSchema)
async def read_users_me(current_user: DBUser = Depends(get_current_user)):
    """Get current user information."""
    logger.info(f"Reading user info for: {current_user.id}")
    return UserSchema(
        user_id=current_user.id,
        email=current_user.email,
        name=current_user.full_name,
        roles=[r.role.name for r in current_user.roles],
        is_active=current_user.is_active,
        created_at=current_user.created_at,
        profile={},
    )


@router.put("/users/me", response_model=UserSchema)
async def update_user_me(
    user_update: UserUpdate,
    current_user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
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
        name=current_user.full_name,
        roles=[r.role.name for r in current_user.roles],
        is_active=current_user.is_active,
        created_at=current_user.created_at,
        profile={},
    )
