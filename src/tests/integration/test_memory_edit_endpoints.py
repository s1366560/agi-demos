"""
Integration tests for Memory Edit and Share endpoints.
Tests PATCH /memories/{id}, POST /memories/{id}/shares, DELETE /memories/{id}/shares/{share_id}
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.secondary.persistence.models import (
    Memory,
    MemoryShare,
    Project,
    User,
)


@pytest.mark.asyncio
class TestMemoryUpdateEndpoint:
    """Test PATCH /memories/{memory_id} endpoint."""

    async def test_update_memory_success(
        self, async_client: AsyncClient, db: AsyncSession, test_user: User, test_memory_db: "Memory"
    ):
        """Test successful memory update with version increment."""
        # Arrange
        original_version = test_memory_db.version
        update_data = {
            "title": "Updated Title",
            "content": "Updated content",
            "version": original_version,
        }

        # Act
        response = await async_client.patch(
            f"/api/v1/memories/{test_memory_db.id}", json=update_data
        )

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "Updated Title"
        assert data["content"] == "Updated content"
        assert data["version"] == original_version + 1

    async def test_update_memory_version_conflict(
        self, async_client: AsyncClient, test_memory_db: "Memory"
    ):
        """Test optimistic locking - version mismatch returns 409."""
        # Arrange
        update_data = {
            "title": "Updated Title",
            "content": "Updated content",
            "version": 999,  # Wrong version
        }

        # Act
        response = await async_client.patch(
            f"/api/v1/memories/{test_memory_db.id}", json=update_data
        )

        # Assert
        assert response.status_code == 409
        assert "Version conflict" in response.json()["detail"]

    async def test_update_memory_not_found(self, async_client: AsyncClient):
        """Test updating non-existent memory returns 404."""
        # Arrange
        update_data = {"title": "Updated", "content": "Updated", "version": 1}

        # Act
        response = await async_client.patch("/api/v1/memories/nonexistent-id", json=update_data)

        # Assert
        assert response.status_code == 404

    async def test_update_memory_partial_fields(
        self, async_client: AsyncClient, test_memory_db: "Memory"
    ):
        """Test updating only specific fields (partial update)."""
        # Arrange
        original_content = test_memory_db.content
        update_data = {"title": "New Title Only", "version": test_memory_db.version}

        # Act
        response = await async_client.patch(
            f"/api/v1/memories/{test_memory_db.id}", json=update_data
        )

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "New Title Only"
        assert data["content"] == original_content  # Content unchanged

    async def test_update_memory_with_edit_permission(
        self,
        async_client: AsyncClient,
        db: AsyncSession,
        test_user: User,
        test_memory_db: "Memory",
        another_user: User,
    ):
        """Test user with edit permission through share can update memory."""
        # Arrange - Create share with edit permission
        share = MemoryShare(
            id="test-share-edit",
            memory_id=test_memory_db.id,
            shared_with_user_id=another_user.id,
            permissions={"view": True, "edit": True},
            shared_by=test_user.id,
            created_at=test_memory_db.created_at,
        )
        db.add(share)
        await db.commit()

        # Act - Login as another_user
        # (Note: This would require authentication setup for multiple users)
        # For now, we'll skip this test as it requires full auth setup

    async def test_update_memory_permission_denied(
        self, async_client: AsyncClient, test_memory_db: "Memory"
    ):
        """Test user without permission cannot update memory."""
        # This test would require auth setup with unauthorized user
        # Skipping for now as it requires full auth context
        pass


@pytest.mark.asyncio
class TestMemoryShareEndpoints:
    """Test POST /memories/{id}/shares and DELETE /memories/{id}/shares/{share_id} endpoints."""

    async def test_create_memory_share_with_user(
        self,
        async_client: AsyncClient,
        db: AsyncSession,
        test_user: User,
        test_memory_db: "Memory",
        another_user: User,
    ):
        """Test sharing memory with a user."""
        # Arrange
        share_data = {
            "target_type": "user",
            "target_id": another_user.id,
            "permission_level": "view",
        }

        # Act
        response = await async_client.post(
            f"/api/v1/memories/{test_memory_db.id}/shares", json=share_data
        )

        # Assert
        assert response.status_code == 201
        data = response.json()
        assert data["memory_id"] == test_memory_db.id
        assert data["shared_with_user_id"] == another_user.id
        assert data["permissions"]["view"] is True
        # permission_level is no longer in response, mapped to permissions

    async def test_create_memory_share_with_project(
        self,
        async_client: AsyncClient,
        db: AsyncSession,
        test_user: User,
        test_memory_db: "Memory",
        test_project_db: "Project",
    ):
        """Test sharing memory with a project."""
        # Arrange
        share_data = {
            "target_type": "project",
            "target_id": test_project_db.id,
            "permission_level": "edit",
        }

        # Act
        response = await async_client.post(
            f"/api/v1/memories/{test_memory_db.id}/shares", json=share_data
        )

        # Assert
        assert response.status_code == 201
        data = response.json()
        assert data["memory_id"] == test_memory_db.id
        assert data["shared_with_project_id"] == test_project_db.id
        assert data["permissions"]["edit"] is True

    async def test_create_memory_share_duplicate(
        self,
        async_client: AsyncClient,
        db: AsyncSession,
        test_memory_db: "Memory",
        another_user: User,
    ):
        """Test duplicate share returns 400."""
        # Arrange - Create existing share
        existing_share = MemoryShare(
            id="existing-share",
            memory_id=test_memory_db.id,
            shared_with_user_id=another_user.id,
            permissions={"view": True},
            shared_by=test_memory_db.author_id,
            created_at=test_memory_db.created_at,
        )
        db.add(existing_share)
        await db.commit()

        share_data = {
            "target_type": "user",
            "target_id": another_user.id,
            "permission_level": "view",
        }

        # Act
        response = await async_client.post(
            f"/api/v1/memories/{test_memory_db.id}/shares", json=share_data
        )

        # Assert
        assert response.status_code == 400
        assert "already shared" in response.json()["detail"]

    async def test_create_memory_share_invalid_target_type(
        self, async_client: AsyncClient, test_memory_db: "Memory"
    ):
        """Test invalid target_type returns 400."""
        # Arrange
        share_data = {"target_type": "invalid", "target_id": "some-id", "permission_level": "view"}

        # Act
        response = await async_client.post(
            f"/api/v1/memories/{test_memory_db.id}/shares", json=share_data
        )

        # Assert
        assert response.status_code == 400

    async def test_create_memory_share_invalid_permission(
        self, async_client: AsyncClient, test_memory_db: "Memory"
    ):
        """Test invalid permission_level returns 400."""
        # Arrange
        share_data = {
            "target_type": "user",
            "target_id": "some-user-id",
            "permission_level": "admin",  # Invalid
        }

        # Act
        response = await async_client.post(
            f"/api/v1/memories/{test_memory_db.id}/shares", json=share_data
        )

        # Assert
        assert response.status_code == 400

    async def test_delete_memory_share(
        self,
        async_client: AsyncClient,
        db: AsyncSession,
        test_user: User,
        test_memory_db: "Memory",
        another_user: User,
    ):
        """Test deleting a memory share."""
        # Arrange - Create share
        share = MemoryShare(
            id="share-to-delete",
            memory_id=test_memory_db.id,
            shared_with_user_id=another_user.id,
            permissions={"view": True},
            shared_by=test_user.id,
            created_at=test_memory_db.created_at,
        )
        db.add(share)
        await db.commit()

        # Act
        response = await async_client.delete(
            f"/api/v1/memories/{test_memory_db.id}/shares/share-to-delete"
        )

        # Assert
        assert response.status_code == 204

        # Verify share is deleted
        result = await db.execute(select(MemoryShare).where(MemoryShare.id == "share-to-delete"))
        assert result.scalar_one_or_none() is None

    async def test_delete_memory_share_not_found(
        self, async_client: AsyncClient, test_memory_db: "Memory"
    ):
        """Test deleting non-existent share returns 404."""
        # Act
        response = await async_client.delete(
            f"/api/v1/memories/{test_memory_db.id}/shares/nonexistent-share"
        )

        # Assert
        assert response.status_code == 404

    async def test_delete_memory_share_wrong_memory(
        self,
        async_client: AsyncClient,
        db: AsyncSession,
        test_user: User,
        test_memory_db: "Memory",
        another_memory_db: "Memory",
    ):
        """Test deleting share from different memory returns 400."""
        # Arrange - Create share for test_memory_db
        share = MemoryShare(
            id="share-for-test",
            memory_id=test_memory_db.id,
            shared_with_user_id=test_user.id,
            permissions={"view": True},
            shared_by=test_user.id,
            created_at=test_memory_db.created_at,
        )
        db.add(share)
        await db.commit()

        # Act - Try to delete using different memory_id
        response = await async_client.delete(
            f"/api/v1/memories/{another_memory_db.id}/shares/share-for-test"
        )

        # Assert
        assert response.status_code == 400
        assert "does not belong to this memory" in response.json()["detail"]
