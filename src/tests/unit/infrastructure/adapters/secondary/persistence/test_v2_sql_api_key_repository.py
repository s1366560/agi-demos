"""
Tests for V2 SqlAPIKeyRepository using BaseRepository.
"""

import pytest
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.auth.api_key import APIKey
from src.infrastructure.adapters.secondary.persistence.models import APIKey as DBAPIKey, User as DBUser
from src.infrastructure.adapters.secondary.persistence.v2_sql_api_key_repository import (
    V2SqlAPIKeyRepository,
)


@pytest.fixture
async def v2_api_key_repo(db_session: AsyncSession, test_user_db: DBUser) -> V2SqlAPIKeyRepository:
    """Create a V2 API key repository for testing."""
    return V2SqlAPIKeyRepository(db_session)


@pytest.fixture
async def test_user_db(db_session: AsyncSession) -> DBUser:
    """Create a test user in the database."""
    user = DBUser(
        id="user-test-1",
        email="test@example.com",
        full_name="Test User",
        hashed_password="hash",
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    return user


class TestV2SqlAPIKeyRepositorySave:
    """Tests for saving API keys."""

    @pytest.mark.asyncio
    async def test_save_new_api_key(self, v2_api_key_repo: V2SqlAPIKeyRepository):
        """Test saving a new API key."""
        api_key = APIKey(
            id="key-test-1",
            user_id="user-test-1",
            key_hash="hash123",
            name="Test Key",
            is_active=True,
            permissions=["read", "write"],
            created_at=datetime.now(timezone.utc),
        )

        await v2_api_key_repo.save(api_key)

        # Verify API key was saved
        retrieved = await v2_api_key_repo.find_by_id("key-test-1")
        assert retrieved is not None
        assert retrieved.id == "key-test-1"
        assert retrieved.name == "Test Key"

    @pytest.mark.asyncio
    async def test_update_existing_api_key(self, v2_api_key_repo: V2SqlAPIKeyRepository):
        """Test updating an existing API key."""
        # Create initial API key
        api_key = APIKey(
            id="key-update-1",
            user_id="user-test-1",
            key_hash="hash123",
            name="Original Name",
            is_active=True,
            permissions=["read"],
            created_at=datetime.now(timezone.utc),
        )
        await v2_api_key_repo.save(api_key)

        # Update the API key
        updated_key = APIKey(
            id="key-update-1",
            user_id="user-test-1",
            key_hash="hash456",
            name="Updated Name",
            is_active=False,
            permissions=["read", "write", "delete"],
            created_at=api_key.created_at,
            last_used_at=datetime.now(timezone.utc),
        )
        await v2_api_key_repo.save(updated_key)

        # Verify updates
        retrieved = await v2_api_key_repo.find_by_id("key-update-1")
        assert retrieved.name == "Updated Name"
        assert retrieved.is_active is False
        assert "write" in retrieved.permissions


class TestV2SqlAPIKeyRepositoryFind:
    """Tests for finding API keys."""

    @pytest.mark.asyncio
    async def test_find_by_id_existing(self, v2_api_key_repo: V2SqlAPIKeyRepository):
        """Test finding an existing API key by ID."""
        api_key = APIKey(
            id="key-find-1",
            user_id="user-test-1",
            key_hash="hash123",
            name="Find Me",
            is_active=True,
            permissions=["read"],
            created_at=datetime.now(timezone.utc),
        )
        await v2_api_key_repo.save(api_key)

        retrieved = await v2_api_key_repo.find_by_id("key-find-1")
        assert retrieved is not None
        assert retrieved.id == "key-find-1"

    @pytest.mark.asyncio
    async def test_find_by_id_not_found(self, v2_api_key_repo: V2SqlAPIKeyRepository):
        """Test finding a non-existent API key returns None."""
        retrieved = await v2_api_key_repo.find_by_id("non-existent")
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_find_by_hash_existing(self, v2_api_key_repo: V2SqlAPIKeyRepository):
        """Test finding an API key by hash."""
        api_key = APIKey(
            id="key-hash-1",
            user_id="user-test-1",
            key_hash="unique_hash_123",
            name="Hash Test",
            is_active=True,
            permissions=["read"],
            created_at=datetime.now(timezone.utc),
        )
        await v2_api_key_repo.save(api_key)

        retrieved = await v2_api_key_repo.find_by_hash("unique_hash_123")
        assert retrieved is not None
        assert retrieved.id == "key-hash-1"

    @pytest.mark.asyncio
    async def test_find_by_hash_not_found(self, v2_api_key_repo: V2SqlAPIKeyRepository):
        """Test finding by non-existent hash returns None."""
        retrieved = await v2_api_key_repo.find_by_hash("nonexistent_hash")
        assert retrieved is None


class TestV2SqlAPIKeyRepositoryList:
    """Tests for listing API keys."""

    @pytest.mark.asyncio
    async def test_find_by_user(self, v2_api_key_repo: V2SqlAPIKeyRepository):
        """Test listing API keys for a user."""
        # Create multiple API keys
        for i in range(3):
            api_key = APIKey(
                id=f"key-user-{i}",
                user_id="user-test-1",
                key_hash=f"hash{i}",
                name=f"Key {i}",
                is_active=True,
                permissions=["read"],
                created_at=datetime.now(timezone.utc),
            )
            await v2_api_key_repo.save(api_key)

        # List by user
        keys = await v2_api_key_repo.find_by_user("user-test-1")
        assert len(keys) == 3

    @pytest.mark.asyncio
    async def test_find_by_user_with_pagination(self, v2_api_key_repo: V2SqlAPIKeyRepository):
        """Test listing API keys with pagination."""
        # Create 5 API keys
        for i in range(5):
            api_key = APIKey(
                id=f"key-page-{i}",
                user_id="user-test-1",
                key_hash=f"hash{i}",
                name=f"Page Key {i}",
                is_active=True,
                permissions=["read"],
                created_at=datetime.now(timezone.utc),
            )
            await v2_api_key_repo.save(api_key)

        # Get first page
        page1 = await v2_api_key_repo.find_by_user("user-test-1", limit=2, offset=0)
        assert len(page1) == 2

        # Get second page
        page2 = await v2_api_key_repo.find_by_user("user-test-1", limit=2, offset=2)
        assert len(page2) == 2


class TestV2SqlAPIKeyRepositoryDelete:
    """Tests for deleting API keys."""

    @pytest.mark.asyncio
    async def test_delete_existing_key(self, v2_api_key_repo: V2SqlAPIKeyRepository):
        """Test deleting an existing API key."""
        api_key = APIKey(
            id="key-delete-1",
            user_id="user-test-1",
            key_hash="hash123",
            name="Delete Me",
            is_active=True,
            permissions=["read"],
            created_at=datetime.now(timezone.utc),
        )
        await v2_api_key_repo.save(api_key)

        # Delete
        await v2_api_key_repo.delete("key-delete-1")

        # Verify deleted
        retrieved = await v2_api_key_repo.find_by_id("key-delete-1")
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_key(self, v2_api_key_repo: V2SqlAPIKeyRepository):
        """Test deleting a non-existent API key does not raise error."""
        # Should not raise error
        await v2_api_key_repo.delete("non-existent")


class TestV2SqlAPIKeyRepositoryUpdateLastUsed:
    """Tests for updating last_used_at."""

    @pytest.mark.asyncio
    async def test_update_last_used(self, v2_api_key_repo: V2SqlAPIKeyRepository):
        """Test updating the last_used_at timestamp."""
        api_key = APIKey(
            id="key-lastused-1",
            user_id="user-test-1",
            key_hash="hash123",
            name="Last Used Test",
            is_active=True,
            permissions=["read"],
            created_at=datetime.now(timezone.utc),
        )
        await v2_api_key_repo.save(api_key)

        # Update last used
        timestamp = datetime.now(timezone.utc)
        await v2_api_key_repo.update_last_used("key-lastused-1", timestamp)

        # Verify updated
        retrieved = await v2_api_key_repo.find_by_id("key-lastused-1")
        assert retrieved.last_used_at is not None


class TestV2SqlAPIKeyRepositoryToDomain:
    """Tests for _to_domain conversion."""

    @pytest.mark.asyncio
    async def test_to_domain_converts_all_fields(self, v2_api_key_repo: V2SqlAPIKeyRepository):
        """Test that _to_domain correctly converts all DB fields."""
        api_key = APIKey(
            id="key-domain-1",
            user_id="user-test-1",
            key_hash="hash123",
            name="Domain Test",
            is_active=True,
            permissions=["read", "write", "delete"],
            created_at=datetime.now(timezone.utc),
            expires_at=datetime(2025, 12, 31, 23, 59, 59, tzinfo=timezone.utc),
        )
        await v2_api_key_repo.save(api_key)

        retrieved = await v2_api_key_repo.find_by_id("key-domain-1")
        assert retrieved.id == "key-domain-1"
        assert retrieved.permissions == ["read", "write", "delete"]
        assert retrieved.expires_at is not None

    @pytest.mark.asyncio
    async def test_to_domain_with_none_db_model(self, v2_api_key_repo: V2SqlAPIKeyRepository):
        """Test that _to_domain returns None for None input."""
        result = v2_api_key_repo._to_domain(None)
        assert result is None
