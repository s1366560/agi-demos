"""
Tests for V2 SqlTenantRepository using BaseRepository.
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.tenant.tenant import Tenant
from src.infrastructure.adapters.secondary.persistence.models import User as DBUser
from src.infrastructure.adapters.secondary.persistence.v2_sql_tenant_repository import (
    V2SqlTenantRepository,
)


@pytest.fixture
async def v2_tenant_repo(db_session: AsyncSession, test_owner_db: DBUser) -> V2SqlTenantRepository:
    """Create a V2 tenant repository for testing."""
    return V2SqlTenantRepository(db_session)


@pytest.fixture
async def test_owner_db(db_session: AsyncSession) -> DBUser:
    """Create a test user (owner) in the database."""
    user = DBUser(
        id="user-owner-1",
        email="owner@example.com",
        full_name="Owner User",
        hashed_password="hash",
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    return user


class TestV2SqlTenantRepositorySave:
    """Tests for saving tenants."""

    @pytest.mark.asyncio
    async def test_save_new_tenant(self, v2_tenant_repo: V2SqlTenantRepository):
        """Test saving a new tenant."""
        tenant = Tenant(
            id="tenant-test-1",
            name="Test Tenant",
            owner_id="user-owner-1",
            description="A test tenant",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        await v2_tenant_repo.save(tenant)

        # Verify tenant was saved
        retrieved = await v2_tenant_repo.find_by_id("tenant-test-1")
        assert retrieved is not None
        assert retrieved.id == "tenant-test-1"
        assert retrieved.name == "Test Tenant"

    @pytest.mark.asyncio
    async def test_update_existing_tenant(self, v2_tenant_repo: V2SqlTenantRepository):
        """Test updating an existing tenant."""
        # Create initial tenant
        tenant = Tenant(
            id="tenant-update-1",
            name="Original Name",
            owner_id="user-owner-1",
            description="Original description",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await v2_tenant_repo.save(tenant)

        # Update the tenant
        updated_tenant = Tenant(
            id="tenant-update-1",
            name="Updated Name",
            owner_id="user-owner-1",
            description="Updated description",
            created_at=tenant.created_at,
            updated_at=datetime.now(timezone.utc),
        )
        await v2_tenant_repo.save(updated_tenant)

        # Verify updates
        retrieved = await v2_tenant_repo.find_by_id("tenant-update-1")
        assert retrieved.name == "Updated Name"
        assert retrieved.description == "Updated description"


class TestV2SqlTenantRepositoryFind:
    """Tests for finding tenants."""

    @pytest.mark.asyncio
    async def test_find_by_id_existing(self, v2_tenant_repo: V2SqlTenantRepository):
        """Test finding an existing tenant by ID."""
        tenant = Tenant(
            id="tenant-find-1",
            name="Find Me",
            owner_id="user-owner-1",
            description="Find test",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await v2_tenant_repo.save(tenant)

        retrieved = await v2_tenant_repo.find_by_id("tenant-find-1")
        assert retrieved is not None
        assert retrieved.id == "tenant-find-1"

    @pytest.mark.asyncio
    async def test_find_by_id_not_found(self, v2_tenant_repo: V2SqlTenantRepository):
        """Test finding a non-existent tenant returns None."""
        retrieved = await v2_tenant_repo.find_by_id("non-existent")
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_find_by_name_existing(self, v2_tenant_repo: V2SqlTenantRepository):
        """Test finding a tenant by name."""
        tenant = Tenant(
            id="tenant-name-1",
            name="Unique Tenant Name",
            owner_id="user-owner-1",
            description="Name test",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await v2_tenant_repo.save(tenant)

        retrieved = await v2_tenant_repo.find_by_name("Unique Tenant Name")
        assert retrieved is not None
        assert retrieved.id == "tenant-name-1"

    @pytest.mark.asyncio
    async def test_find_by_name_not_found(self, v2_tenant_repo: V2SqlTenantRepository):
        """Test finding by non-existent name returns None."""
        retrieved = await v2_tenant_repo.find_by_name("non-existent-name")
        assert retrieved is None


class TestV2SqlTenantRepositoryList:
    """Tests for listing tenants."""

    @pytest.mark.asyncio
    async def test_list_all(self, v2_tenant_repo: V2SqlTenantRepository):
        """Test listing all tenants."""
        # Create multiple tenants
        for i in range(3):
            tenant = Tenant(
                id=f"tenant-list-{i}",
                name=f"Tenant {i}",
                owner_id="user-owner-1",
                description=f"Description {i}",
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            await v2_tenant_repo.save(tenant)

        # List all tenants
        tenants = await v2_tenant_repo.list_all()
        assert len(tenants) == 3

    @pytest.mark.asyncio
    async def test_list_all_with_pagination(self, v2_tenant_repo: V2SqlTenantRepository):
        """Test listing tenants with pagination."""
        # Create 5 tenants
        for i in range(5):
            tenant = Tenant(
                id=f"tenant-page-{i}",
                name=f"Page Tenant {i}",
                owner_id="user-owner-1",
                description=f"Page {i}",
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            await v2_tenant_repo.save(tenant)

        # Get first page
        page1 = await v2_tenant_repo.list_all(limit=2, offset=0)
        assert len(page1) == 2

        # Get second page
        page2 = await v2_tenant_repo.list_all(limit=2, offset=2)
        assert len(page2) == 2

    @pytest.mark.asyncio
    async def test_find_by_owner(self, v2_tenant_repo: V2SqlTenantRepository):
        """Test listing tenants owned by a user."""
        # Create tenants for the owner
        for i in range(3):
            tenant = Tenant(
                id=f"tenant-owner-{i}",
                name=f"Owner Tenant {i}",
                owner_id="user-owner-1",
                description=f"Owned {i}",
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            await v2_tenant_repo.save(tenant)

        # List by owner
        tenants = await v2_tenant_repo.find_by_owner("user-owner-1")
        assert len(tenants) == 3


class TestV2SqlTenantRepositoryDelete:
    """Tests for deleting tenants."""

    @pytest.mark.asyncio
    async def test_delete_existing_tenant(self, v2_tenant_repo: V2SqlTenantRepository):
        """Test deleting an existing tenant."""
        tenant = Tenant(
            id="tenant-delete-1",
            name="Delete Me",
            owner_id="user-owner-1",
            description="Delete test",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await v2_tenant_repo.save(tenant)

        # Delete
        await v2_tenant_repo.delete("tenant-delete-1")

        # Verify deleted
        retrieved = await v2_tenant_repo.find_by_id("tenant-delete-1")
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_tenant(self, v2_tenant_repo: V2SqlTenantRepository):
        """Test deleting a non-existent tenant does not raise error."""
        # Should not raise error
        await v2_tenant_repo.delete("non-existent")


class TestV2SqlTenantRepositoryToDomain:
    """Tests for _to_domain conversion."""

    @pytest.mark.asyncio
    async def test_to_domain_converts_all_fields(self, v2_tenant_repo: V2SqlTenantRepository):
        """Test that _to_domain correctly converts all DB fields."""
        tenant = Tenant(
            id="tenant-domain-1",
            name="Domain Test",
            owner_id="user-owner-1",
            description="Domain conversion test",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await v2_tenant_repo.save(tenant)

        retrieved = await v2_tenant_repo.find_by_id("tenant-domain-1")
        assert retrieved.id == "tenant-domain-1"
        assert retrieved.name == "Domain Test"
        assert retrieved.owner_id == "user-owner-1"
        assert retrieved.description == "Domain conversion test"

    @pytest.mark.asyncio
    async def test_to_domain_with_none_db_model(self, v2_tenant_repo: V2SqlTenantRepository):
        """Test that _to_domain returns None for None input."""
        result = v2_tenant_repo._to_domain(None)
        assert result is None
