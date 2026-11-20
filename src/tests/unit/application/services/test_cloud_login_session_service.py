"""Cloud login refresh rotation, reuse revocation, and sign-out."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from src.application.services.auth_service_v2 import AuthService
from src.application.services.cloud_login_session_service import (
    ACCESS_TOKEN_TTL,
    REFRESH_TOKEN_TTL,
    CloudLoginSessionService,
    RefreshRejectedError,
    hash_refresh_token,
)
from src.infrastructure.adapters.secondary.persistence.models import APIKey, UserSession

pytestmark = pytest.mark.unit

_SECRET = "test-cloud-login-secret"


def _service(db) -> CloudLoginSessionService:
    return CloudLoginSessionService(db, secret=_SECRET)


async def _access_key(db, user_id: str, *, name: str = "Login Session") -> tuple[str, APIKey]:
    plain = AuthService.generate_api_key()
    key = APIKey(
        id=AuthService.generate_api_key(),
        user_id=user_id,
        key_hash=AuthService.hash_api_key(plain),
        name=name,
        permissions=["read", "write"],
        expires_at=datetime.now(UTC) + ACCESS_TOKEN_TTL,
        is_active=True,
        created_at=datetime.now(UTC),
    )
    db.add(key)
    await db.flush()
    return plain, key


async def test_bind_stores_refresh_hmac_and_one_hour_access(test_db, test_user) -> None:
    plain, key = await _access_key(test_db, test_user.id)
    issued = await _service(test_db).bind_access_key(
        user_id=test_user.id,
        access_api_key_id=key.id,
        auth_method="password",
        device_label="password",
    )
    await test_db.commit()

    assert plain.startswith("ms_sk_")
    assert issued.refresh_token.startswith("ms_rt_")
    stored = (
        await test_db.execute(select(UserSession).where(UserSession.id == issued.session_id))
    ).scalar_one()
    assert stored.refresh_token_hash == hash_refresh_token(issued.refresh_token, secret=_SECRET)
    assert issued.refresh_token not in stored.refresh_token_hash
    assert stored.refresh_token_hash != issued.refresh_token
    stored_expiry = stored.expires_at
    if stored_expiry.tzinfo is None:
        stored_expiry = stored_expiry.replace(tzinfo=UTC)
    assert stored_expiry - datetime.now(UTC) > REFRESH_TOKEN_TTL - timedelta(minutes=1)
    assert key.expires_at is not None
    access_expiry = key.expires_at
    if access_expiry.tzinfo is None:
        access_expiry = access_expiry.replace(tzinfo=UTC)
    assert access_expiry - datetime.now(UTC) < timedelta(hours=1, minutes=1)


async def test_rotate_replaces_refresh_and_reuse_revokes_family(test_db, test_user) -> None:
    _plain, key = await _access_key(test_db, test_user.id)
    service = _service(test_db)
    issued = await service.bind_access_key(
        user_id=test_user.id,
        access_api_key_id=key.id,
        auth_method="password",
        device_label="password",
    )
    rotated = await service.rotate(issued.refresh_token)
    await test_db.commit()

    assert rotated.access_token.startswith("ms_sk_")
    assert rotated.refresh_token != issued.refresh_token
    assert rotated.family_id == issued.family_id
    assert rotated.session_id != issued.session_id
    old_key = await test_db.get(APIKey, key.id)
    assert old_key is not None
    assert old_key.is_active is False

    with pytest.raises(RefreshRejectedError) as reused:
        await service.rotate(issued.refresh_token)
    assert reused.value.reused is True
    family = (
        await test_db.execute(select(UserSession).where(UserSession.family_id == issued.family_id))
    ).scalars().all()
    assert family
    assert all(row.revoked_at is not None for row in family)
    successor_key = (
        await test_db.execute(select(APIKey).where(APIKey.key_hash == AuthService.hash_api_key(rotated.access_token)))
    ).scalar_one()
    assert successor_key.is_active is False


async def test_unknown_refresh_does_not_revoke_existing_family(test_db, test_user) -> None:
    _plain, key = await _access_key(test_db, test_user.id)
    service = _service(test_db)
    issued = await service.bind_access_key(
        user_id=test_user.id,
        access_api_key_id=key.id,
        auth_method="device",
        device_label="device",
    )

    with pytest.raises(RefreshRejectedError) as rejected:
        await service.rotate("ms_rt_" + ("ab" * 32))
    assert rejected.value.reused is False
    stored = await test_db.get(UserSession, issued.session_id)
    assert stored is not None
    assert stored.revoked_at is None


async def test_revoke_access_token_retires_only_its_family(test_db, test_user) -> None:
    first_plain, first_key = await _access_key(test_db, test_user.id, name="one")
    second_plain, second_key = await _access_key(test_db, test_user.id, name="two")
    service = _service(test_db)
    first = await service.bind_access_key(
        user_id=test_user.id,
        access_api_key_id=first_key.id,
        auth_method="oauth",
        device_label="github",
    )
    second = await service.bind_access_key(
        user_id=test_user.id,
        access_api_key_id=second_key.id,
        auth_method="password",
        device_label="password",
    )

    await service.revoke_access_token(first_plain)
    await test_db.commit()

    retired = await test_db.get(UserSession, first.session_id)
    kept = await test_db.get(UserSession, second.session_id)
    assert retired is not None and retired.revoked_at is not None
    assert kept is not None and kept.revoked_at is None
    assert (await test_db.get(APIKey, first_key.id)).is_active is False
    assert (await test_db.get(APIKey, second_key.id)).is_active is True
    assert second_plain.startswith("ms_sk_")
