from datetime import UTC, datetime, timedelta

import pytest

from src.application.services.auth_service_v2 import AuthService
from src.domain.model.auth.api_key import APIKey


class _APIKeyRepository:
    def __init__(self, api_key: APIKey | None = None) -> None:
        self.api_key = api_key
        self.find_hashes: list[str] = []
        self.last_used_updates: list[tuple[str, datetime]] = []

    async def save(self, api_key: APIKey) -> APIKey:
        self.api_key = api_key
        return api_key

    async def find_by_id(self, key_id: str) -> APIKey | None:
        if self.api_key and self.api_key.id == key_id:
            return self.api_key
        return None

    async def find_by_hash(self, key_hash: str) -> APIKey | None:
        self.find_hashes.append(key_hash)
        if self.api_key and self.api_key.key_hash == key_hash:
            return self.api_key
        return None

    async def find_by_user(
        self, user_id: str, limit: int = 50, offset: int = 0
    ) -> list[APIKey]:
        if self.api_key and self.api_key.user_id == user_id:
            return [self.api_key]
        return []

    async def delete(self, key_id: str) -> bool:
        return False

    async def update_last_used(self, key_id: str, timestamp: datetime) -> None:
        self.last_used_updates.append((key_id, timestamp))


class _UserRepository:
    pass


def _make_api_key(
    plain_key: str = "ms_sk_valid",
    *,
    is_active: bool = True,
    expires_at: datetime | None = None,
) -> APIKey:
    return APIKey(
        id="key-1",
        user_id="user-1",
        key_hash=AuthService.hash_api_key(plain_key),
        name="Test key",
        permissions=["read"],
        is_active=is_active,
        expires_at=expires_at,
    )


@pytest.mark.asyncio
async def test_verify_api_key_updates_last_used_at_on_success() -> None:
    plain_key = "ms_sk_valid"
    api_key = _make_api_key(plain_key)
    api_key_repo = _APIKeyRepository(api_key)
    service = AuthService(user_repository=_UserRepository(), api_key_repository=api_key_repo)

    before = datetime.now(UTC)
    result = await service.verify_api_key(plain_key)
    after = datetime.now(UTC)

    assert result is api_key
    assert len(api_key_repo.last_used_updates) == 1
    updated_key_id, updated_at = api_key_repo.last_used_updates[0]
    assert updated_key_id == "key-1"
    assert before <= updated_at <= after
    assert result.last_used_at == updated_at


@pytest.mark.asyncio
async def test_verify_api_key_read_only_does_not_update_last_used_at() -> None:
    plain_key = "ms_sk_valid"
    api_key = _make_api_key(plain_key)
    api_key_repo = _APIKeyRepository(api_key)
    service = AuthService(user_repository=_UserRepository(), api_key_repository=api_key_repo)

    result = await service.verify_api_key_read_only(plain_key)

    assert result is api_key
    assert api_key_repo.last_used_updates == []
    assert result.last_used_at is None


@pytest.mark.asyncio
async def test_verify_api_key_does_not_update_inactive_key() -> None:
    plain_key = "ms_sk_inactive"
    api_key_repo = _APIKeyRepository(_make_api_key(plain_key, is_active=False))
    service = AuthService(user_repository=_UserRepository(), api_key_repository=api_key_repo)

    with pytest.raises(ValueError, match="deactivated"):
        await service.verify_api_key(plain_key)

    assert api_key_repo.last_used_updates == []


@pytest.mark.asyncio
async def test_verify_api_key_does_not_update_expired_key() -> None:
    plain_key = "ms_sk_expired"
    api_key_repo = _APIKeyRepository(
        _make_api_key(plain_key, expires_at=datetime.now(UTC) - timedelta(seconds=1))
    )
    service = AuthService(user_repository=_UserRepository(), api_key_repository=api_key_repo)

    with pytest.raises(ValueError, match="expired"):
        await service.verify_api_key(plain_key)

    assert api_key_repo.last_used_updates == []
