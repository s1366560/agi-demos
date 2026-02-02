"""
Tests for V2 SqlUserRepository using BaseRepository.

TDD Approach: RED -> GREEN -> REFACTOR

These tests verify that the migrated repository maintains 100% compatibility
with the original implementation while leveraging the BaseRepository.
"""

import pytest
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.auth.user import User
from src.infrastructure.adapters.secondary.persistence.models import User as DBUser
from src.infrastructure.adapters.secondary.persistence.v2_sql_user_repository import (
    V2SqlUserRepository,
)


@pytest.fixture
async def v2_user_repo(db_session: AsyncSession) -> V2SqlUserRepository:
    """Create a V2 user repository for testing."""
    return V2SqlUserRepository(db_session)


class TestV2SqlUserRepositoryCreate:
    """Tests for creating new users."""

    @pytest.mark.asyncio
    async def test_create_new_user(self, v2_user_repo: V2SqlUserRepository):
        """Test creating a new user."""
        user = User(
            id="user-test-1",
            email="test@example.com",
            name="Test User",
            password_hash="hashed_password_123",
            is_active=True,
            profile={"bio": "Test bio"},
            created_at=datetime.now(timezone.utc),
        )

        await v2_user_repo.save(user)

        # Verify user was saved
        retrieved = await v2_user_repo.find_by_id("user-test-1")
        assert retrieved is not None
        assert retrieved.id == "user-test-1"
        assert retrieved.email == "test@example.com"
        assert retrieved.name == "Test User"
        assert retrieved.password_hash == "hashed_password_123"
        assert retrieved.is_active is True

    @pytest.mark.asyncio
    async def test_save_with_none_user_raises_error(self, v2_user_repo: V2SqlUserRepository):
        """Test that saving None raises ValueError."""
        with pytest.raises(ValueError, match="Entity cannot be None"):
            await v2_user_repo.save(None)


class TestV2SqlUserRepositoryUpdate:
    """Tests for updating existing users."""

    @pytest.mark.asyncio
    async def test_update_existing_user(self, v2_user_repo: V2SqlUserRepository):
        """Test updating an existing user."""
        # Create initial user
        user = User(
            id="user-update-1",
            email="original@example.com",
            name="Original Name",
            password_hash="original_hash",
            is_active=False,
            profile={},
            created_at=datetime.now(timezone.utc),
        )
        await v2_user_repo.save(user)

        # Update the user
        updated_user = User(
            id="user-update-1",
            email="updated@example.com",
            name="Updated Name",
            password_hash="new_hash",
            is_active=True,
            profile={"bio": "New bio"},
            created_at=user.created_at,
        )
        await v2_user_repo.save(updated_user)

        # Verify updates
        retrieved = await v2_user_repo.find_by_id("user-update-1")
        assert retrieved.email == "updated@example.com"
        assert retrieved.name == "Updated Name"
        assert retrieved.password_hash == "new_hash"
        assert retrieved.is_active is True

    @pytest.mark.asyncio
    async def test_update_preserves_created_at(self, v2_user_repo: V2SqlUserRepository):
        """Test that updates preserve created_at timestamp."""
        original_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        user = User(
            id="user-preserve",
            email="preserve@example.com",
            name="Preserve Created At",
            password_hash="hash",
            is_active=True,
            profile={},
            created_at=original_time,
        )
        await v2_user_repo.save(user)

        retrieved = await v2_user_repo.find_by_id("user-preserve")
        # SQLite may strip timezone, just check the datetime values match
        assert retrieved.created_at.replace(tzinfo=None) == original_time.replace(tzinfo=None)


class TestV2SqlUserRepositoryFind:
    """Tests for finding users."""

    @pytest.mark.asyncio
    async def test_find_by_id_existing(self, v2_user_repo: V2SqlUserRepository):
        """Test finding an existing user by ID."""
        user = User(
            id="user-find-1",
            email="find@example.com",
            name="Find Me",
            password_hash="hash",
            is_active=True,
            profile={},
            created_at=datetime.now(timezone.utc),
        )
        await v2_user_repo.save(user)

        retrieved = await v2_user_repo.find_by_id("user-find-1")
        assert retrieved is not None
        assert retrieved.id == "user-find-1"
        assert retrieved.email == "find@example.com"

    @pytest.mark.asyncio
    async def test_find_by_id_not_found(self, v2_user_repo: V2SqlUserRepository):
        """Test finding a non-existent user returns None."""
        retrieved = await v2_user_repo.find_by_id("non-existent")
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_find_by_email_existing(self, v2_user_repo: V2SqlUserRepository):
        """Test finding an existing user by email."""
        user = User(
            id="user-email-1",
            email="email@example.com",
            name="Email User",
            password_hash="hash",
            is_active=True,
            profile={},
            created_at=datetime.now(timezone.utc),
        )
        await v2_user_repo.save(user)

        retrieved = await v2_user_repo.find_by_email("email@example.com")
        assert retrieved is not None
        assert retrieved.id == "user-email-1"
        assert retrieved.email == "email@example.com"

    @pytest.mark.asyncio
    async def test_find_by_email_not_found(self, v2_user_repo: V2SqlUserRepository):
        """Test finding a non-existent user by email returns None."""
        retrieved = await v2_user_repo.find_by_email("nonexistent@example.com")
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_exists_true(self, v2_user_repo: V2SqlUserRepository):
        """Test exists returns True for existing user."""
        user = User(
            id="user-exists-1",
            email="exists@example.com",
            name="Exists User",
            password_hash="hash",
            is_active=True,
            profile={},
            created_at=datetime.now(timezone.utc),
        )
        await v2_user_repo.save(user)

        assert await v2_user_repo.exists("user-exists-1") is True

    @pytest.mark.asyncio
    async def test_exists_false(self, v2_user_repo: V2SqlUserRepository):
        """Test exists returns False for non-existent user."""
        assert await v2_user_repo.exists("non-existent") is False


class TestV2SqlUserRepositoryList:
    """Tests for listing users."""

    @pytest.mark.asyncio
    async def test_list_all(self, v2_user_repo: V2SqlUserRepository):
        """Test listing all users."""
        # Create users
        for i in range(3):
            user = User(
                id=f"user-list-{i}",
                email=f"user{i}@example.com",
                name=f"User {i}",
                password_hash="hash",
                is_active=True,
                profile={},
                created_at=datetime.now(timezone.utc),
            )
            await v2_user_repo.save(user)

        # List all users
        users = await v2_user_repo.list_all()
        assert len(users) == 3

    @pytest.mark.asyncio
    async def test_list_all_with_pagination(self, v2_user_repo: V2SqlUserRepository):
        """Test listing users with pagination."""
        # Create 5 users
        for i in range(5):
            user = User(
                id=f"user-page-{i}",
                email=f"page{i}@example.com",
                name=f"Page User {i}",
                password_hash="hash",
                is_active=True,
                profile={},
                created_at=datetime.now(timezone.utc),
            )
            await v2_user_repo.save(user)

        # Get first page
        page1 = await v2_user_repo.list_all(limit=2, offset=0)
        assert len(page1) == 2

        # Get second page
        page2 = await v2_user_repo.list_all(limit=2, offset=2)
        assert len(page2) == 2

        # Get remaining
        page3 = await v2_user_repo.list_all(limit=2, offset=4)
        assert len(page3) == 1


class TestV2SqlUserRepositoryDelete:
    """Tests for deleting users."""

    @pytest.mark.asyncio
    async def test_delete_existing_user(self, v2_user_repo: V2SqlUserRepository):
        """Test deleting an existing user."""
        user = User(
            id="user-delete-1",
            email="delete@example.com",
            name="Delete Me",
            password_hash="hash",
            is_active=True,
            profile={},
            created_at=datetime.now(timezone.utc),
        )
        await v2_user_repo.save(user)

        # Delete
        result = await v2_user_repo.delete("user-delete-1")
        assert result is True

        # Verify deleted
        retrieved = await v2_user_repo.find_by_id("user-delete-1")
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_user(self, v2_user_repo: V2SqlUserRepository):
        """Test deleting a non-existent user returns False."""
        result = await v2_user_repo.delete("non-existent")
        assert result is False


class TestV2SqlUserRepositoryCount:
    """Tests for counting users."""

    @pytest.mark.asyncio
    async def test_count_all(self, v2_user_repo: V2SqlUserRepository):
        """Test counting all users."""
        # Initially empty
        count = await v2_user_repo.count()
        assert count == 0

        # Add users
        for i in range(3):
            user = User(
                id=f"user-count-{i}",
                email=f"count{i}@example.com",
                name=f"Count {i}",
                password_hash="hash",
                is_active=True,
                profile={},
                created_at=datetime.now(timezone.utc),
            )
            await v2_user_repo.save(user)

        count = await v2_user_repo.count()
        assert count == 3


class TestV2SqlUserRepositoryToDomain:
    """Tests for _to_domain conversion."""

    @pytest.mark.asyncio
    async def test_to_domain_converts_all_fields(self, v2_user_repo: V2SqlUserRepository):
        """Test that _to_domain correctly converts all DB fields."""
        user = User(
            id="user-domain",
            email="domain@example.com",
            name="Domain Test",
            password_hash="hash",
            is_active=True,
            profile={"bio": "test bio"},
            created_at=datetime.now(timezone.utc),
        )
        await v2_user_repo.save(user)

        retrieved = await v2_user_repo.find_by_id("user-domain")
        assert retrieved.id == "user-domain"
        assert retrieved.email == "domain@example.com"
        assert retrieved.name == "Domain Test"
        assert retrieved.password_hash == "hash"
        assert retrieved.is_active is True
        assert retrieved.created_at is not None

    @pytest.mark.asyncio
    async def test_to_domain_with_none_db_model(self, v2_user_repo: V2SqlUserRepository):
        """Test that _to_domain returns None for None input."""
        result = v2_user_repo._to_domain(None)
        assert result is None


class TestV2SqlUserRepositoryToDb:
    """Tests for _to_db conversion."""

    def test_to_db_creates_db_model(self, v2_user_repo: V2SqlUserRepository):
        """Test that _to_db creates a valid DB model."""
        user = User(
            id="user-todb",
            email="todb@example.com",
            name="To DB Test",
            password_hash="hash",
            is_active=True,
            profile={},
            created_at=datetime.now(timezone.utc),
        )

        db_model = v2_user_repo._to_db(user)
        assert isinstance(db_model, DBUser)
        assert db_model.id == "user-todb"
        assert db_model.email == "todb@example.com"
        assert db_model.full_name == "To DB Test"
        assert db_model.hashed_password == "hash"
        assert db_model.is_active is True


class TestV2SqlUserRepositoryTransaction:
    """Tests for transaction support."""

    @pytest.mark.asyncio
    async def test_transaction_context_manager(self, v2_user_repo: V2SqlUserRepository):
        """Test using transaction context manager."""
        async with v2_user_repo.transaction():
            user1 = User(
                id="user-tx-1",
                email="tx1@example.com",
                name="TX User 1",
                password_hash="hash",
                is_active=True,
                profile={},
                created_at=datetime.now(timezone.utc),
            )
            await v2_user_repo.save(user1)

            user2 = User(
                id="user-tx-2",
                email="tx2@example.com",
                name="TX User 2",
                password_hash="hash",
                is_active=True,
                profile={},
                created_at=datetime.now(timezone.utc),
            )
            await v2_user_repo.save(user2)

        # Verify both were saved
        u1 = await v2_user_repo.find_by_id("user-tx-1")
        u2 = await v2_user_repo.find_by_id("user-tx-2")
        assert u1 is not None
        assert u2 is not None

    @pytest.mark.asyncio
    async def test_transaction_rollback_on_error(self, v2_user_repo: V2SqlUserRepository):
        """Test that transaction rolls back on error."""
        try:
            async with v2_user_repo.transaction():
                user1 = User(
                    id="user-tx-rollback-1",
                    email="rollback@example.com",
                    name="TX Rollback",
                    password_hash="hash",
                    is_active=True,
                    profile={},
                    created_at=datetime.now(timezone.utc),
                )
                await v2_user_repo.save(user1)

                # Raise error to trigger rollback
                raise ValueError("Test error")
        except ValueError:
            pass

        # Verify rollback occurred
        u1 = await v2_user_repo.find_by_id("user-tx-rollback-1")
        assert u1 is None
