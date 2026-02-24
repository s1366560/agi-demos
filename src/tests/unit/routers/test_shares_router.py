"""Unit tests for memory sharing API endpoints."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from src.infrastructure.adapters.secondary.persistence.models import (
    Memory,
    MemoryShare,
    Project,
    User,
)


class TestCreateShare:
    """Tests for POST /memories/{memory_id}/shares"""

    @pytest.mark.asyncio
    async def test_create_share_success(self, test_db, client, test_memory_with_project):
        """Test successful share creation."""
        share_data = {"permissions": {"view": True, "edit": False}, "expires_in_days": 7}

        response = client.post(
            f"/api/v1/memories/{test_memory_with_project.id}/shares", json=share_data
        )

        assert response.status_code == 201
        data = response.json()
        assert "id" in data
        assert "share_token" in data
        assert data["permissions"] == share_data["permissions"]
        assert "expires_at" in data
        assert data["access_count"] == 0

    @pytest.mark.asyncio
    async def test_create_share_with_expires_at(self, test_db, client, test_memory_with_project):
        """Test share creation with specific expiration date."""
        expires_at = (datetime.now(UTC) + timedelta(days=14)).isoformat()
        share_data = {"permissions": {"view": True, "edit": True}, "expires_at": expires_at}

        response = client.post(
            f"/api/v1/memories/{test_memory_with_project.id}/shares", json=share_data
        )

        assert response.status_code == 201
        data = response.json()
        assert data["permissions"]["edit"] is True
        assert data["expires_at"] is not None

    @pytest.mark.asyncio
    async def test_create_share_without_expiration(self, test_db, client, test_memory_with_project):
        """Test share creation without expiration (permanent link)."""
        share_data = {"permissions": {"view": True}}

        response = client.post(
            f"/api/v1/memories/{test_memory_with_project.id}/shares", json=share_data
        )

        assert response.status_code == 201
        data = response.json()
        assert data["expires_at"] is None

    @pytest.mark.asyncio
    async def test_create_share_invalid_expires_at_defaults_to_7_days(
        self, test_db, client, test_memory_with_project
    ):
        """Test that invalid expires_at format defaults to 7 days."""
        share_data = {"permissions": {"view": True}, "expires_at": "invalid-date-format"}

        response = client.post(
            f"/api/v1/memories/{test_memory_with_project.id}/shares", json=share_data
        )

        assert response.status_code == 201
        data = response.json()
        # Should default to 7 days
        assert data["expires_at"] is not None

    @pytest.mark.asyncio
    async def test_create_share_memory_not_found(self, test_db, client):
        """Test creating share for non-existent memory."""
        share_data = {"permissions": {"view": True}}
        # Use a valid UUID that doesn't exist
        non_existent_id = "00000000-0000-0000-0000-000000000000"

        response = client.post(f"/api/v1/memories/{non_existent_id}/shares", json=share_data)

        assert response.status_code == 404
        assert "Memory not found" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_create_share_access_denied(self, test_db, client, test_user):
        """Test that non-author cannot create share."""
        # Create memory owned by different user
        other_user_id = "other_user_123"
        project = Project(
            id="proj_other",
            tenant_id="tenant_123",
            name="Other Project",
            description="Owned by other user",
            owner_id=other_user_id,
            is_public=False,
        )
        test_db.add(project)

        memory = Memory(
            id="mem_other",
            project_id=project.id,
            title="Other Memory",
            content="Other content",
            author_id=other_user_id,
            content_type="text",
            is_public=False,
        )
        test_db.add(memory)
        await test_db.commit()

        share_data = {"permissions": {"view": True}}

        response = client.post(f"/api/v1/memories/{memory.id}/shares", json=share_data)

        assert response.status_code == 403
        assert "Access denied" in response.json()["detail"]


class TestListShares:
    """Tests for GET /memories/{memory_id}/shares"""

    @pytest.mark.asyncio
    async def test_list_shares_success(
        self, test_db, client, test_memory_with_project, test_memory_share
    ):
        """Test successful listing of shares."""
        response = client.get(f"/api/v1/memories/{test_memory_with_project.id}/shares")

        assert response.status_code == 200
        data = response.json()
        assert "shares" in data
        assert len(data["shares"]) >= 1

        # Verify share structure
        share = data["shares"][0]
        assert "id" in share
        assert "share_token" in share
        assert "permissions" in share
        assert "created_at" in share
        assert "access_count" in share

    @pytest.mark.asyncio
    async def test_list_shares_empty(self, test_db, client, test_memory_with_project):
        """Test listing shares when no shares exist."""
        response = client.get(f"/api/v1/memories/{test_memory_with_project.id}/shares")

        assert response.status_code == 200
        data = response.json()
        assert data["shares"] == []

    @pytest.mark.asyncio
    async def test_list_shares_memory_not_found(self, test_db, client):
        """Test listing shares for non-existent memory."""
        # Use a valid UUID that doesn't exist
        non_existent_id = "00000000-0000-0000-0000-000000000000"
        response = client.get(f"/api/v1/memories/{non_existent_id}/shares")

        assert response.status_code == 404
        assert "Memory not found" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_list_shares_access_denied(self, test_db, client):
        """Test that non-author cannot list shares."""
        other_user_id = "other_user_456"
        project = Project(
            id="proj_other_2",
            tenant_id="tenant_123",
            name="Other Project 2",
            description="Owned by other user",
            owner_id=other_user_id,
            is_public=False,
        )
        test_db.add(project)

        memory = Memory(
            id="mem_other_2",
            project_id=project.id,
            title="Other Memory 2",
            content="Other content",
            author_id=other_user_id,
            content_type="text",
            is_public=False,
        )
        test_db.add(memory)
        await test_db.commit()

        response = client.get(f"/api/v1/memories/{memory.id}/shares")

        assert response.status_code == 403
        assert "Access denied" in response.json()["detail"]


class TestDeleteShare:
    """Tests for DELETE /memories/{memory_id}/shares/{share_id}"""

    @pytest.mark.asyncio
    async def test_delete_share_success(
        self, test_db, client, test_memory_with_project, test_memory_share
    ):
        """Test successful share deletion."""
        response = client.delete(
            f"/api/v1/memories/{test_memory_with_project.id}/shares/{test_memory_share.id}"
        )

        assert response.status_code == 200
        assert response.json()["success"] is True

        # Verify share is deleted
        result = await test_db.execute(
            select(MemoryShare).where(MemoryShare.id == test_memory_share.id)
        )
        assert result.scalar_one_or_none() is None

    @pytest.mark.asyncio
    async def test_delete_share_memory_not_found(self, test_db, client, test_memory_share):
        """Test deleting share for non-existent memory."""
        # Use a valid UUID that doesn't exist
        non_existent_id = "00000000-0000-0000-0000-000000000000"
        response = client.delete(
            f"/api/v1/memories/{non_existent_id}/shares/{test_memory_share.id}"
        )

        assert response.status_code == 404
        assert "Memory not found" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_delete_share_not_found(self, test_db, client, test_memory_with_project):
        """Test deleting non-existent share."""
        response = client.delete(
            f"/api/v1/memories/{test_memory_with_project.id}/shares/nonexistent_share"
        )

        assert response.status_code == 404
        assert "Share not found" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_delete_share_access_denied(self, test_db, client, test_user):
        """Test that non-author cannot delete share."""
        other_user_id = "other_user_789"
        project = Project(
            id="proj_other_3",
            tenant_id="tenant_123",
            name="Other Project 3",
            description="Owned by other user",
            owner_id=other_user_id,
            is_public=False,
        )
        test_db.add(project)

        memory = Memory(
            id="mem_other_3",
            project_id=project.id,
            title="Other Memory 3",
            content="Other content",
            author_id=other_user_id,
            content_type="text",
            is_public=False,
        )
        test_db.add(memory)

        share = MemoryShare(
            id=str(uuid.uuid4()),
            memory_id=memory.id,
            share_token="other_token",
            shared_by=other_user_id,
            permissions={"view": True},
        )
        test_db.add(share)
        await test_db.commit()

        response = client.delete(f"/api/v1/memories/{memory.id}/shares/{share.id}")

        assert response.status_code == 403
        assert "Access denied" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_delete_share_wrong_memory(
        self, test_db, client, test_memory_with_project, test_memory_share
    ):
        """Test deleting share that belongs to different memory."""
        other_memory = Memory(
            id="mem_other_4",
            project_id=test_memory_with_project.project_id,
            title="Other Memory 4",
            content="Other content",
            author_id=test_memory_with_project.author_id,
            content_type="text",
            is_public=False,
        )
        test_db.add(other_memory)
        await test_db.commit()

        response = client.delete(
            f"/api/v1/memories/{other_memory.id}/shares/{test_memory_share.id}"
        )

        assert response.status_code == 400
        assert "does not belong to this memory" in response.json()["detail"]


class TestGetSharedMemory:
    """Tests for GET /shared/{share_token}"""

    @pytest.mark.asyncio
    async def test_get_shared_memory_success(self, client, test_memory_share):
        """Test successful access to shared memory."""
        response = client.get(f"/api/v1/shared/{test_memory_share.share_token}")

        assert response.status_code == 200
        data = response.json()
        assert "memory" in data
        assert "share" in data

        # Verify memory data
        memory = data["memory"]
        assert "id" in memory
        assert "title" in memory
        assert "content" in memory

        # Verify share info
        share = data["share"]
        assert "permissions" in share

    @pytest.mark.asyncio
    async def test_get_shared_memory_increments_access_count(
        self, test_db, client, test_memory_share
    ):
        """Test that accessing shared memory increments access count."""
        initial_count = test_memory_share.access_count

        client.get(f"/api/v1/shared/{test_memory_share.share_token}")

        # Refresh from database
        await test_db.refresh(test_memory_share)
        assert test_memory_share.access_count == initial_count + 1

    @pytest.mark.asyncio
    async def test_get_shared_memory_token_not_found(self, client):
        """Test accessing with invalid share token."""
        response = client.get("/api/v1/shared/invalid_token_12345")

        assert response.status_code == 404
        assert "Share link not found" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_get_shared_memory_expired(self, test_db, client):
        """Test accessing expired share link."""
        # Create expired share
        user = User(
            id="user_expired", email="expired@test.com", hashed_password="hash", full_name="Expired"
        )
        test_db.add(user)

        project = Project(
            id="proj_expired",
            tenant_id="tenant_123",
            name="Expired Project",
            description="Expired",
            owner_id=user.id,
            is_public=False,
        )
        test_db.add(project)

        memory = Memory(
            id="mem_expired",
            project_id=project.id,
            title="Expired Memory",
            content="Expired content",
            author_id=user.id,
            content_type="text",
            is_public=False,
        )
        test_db.add(memory)

        expired_share = MemoryShare(
            id=str(uuid.uuid4()),
            memory_id=memory.id,
            share_token="expired_token",
            shared_by=user.id,
            permissions={"view": True},
            expires_at=datetime.now(UTC) - timedelta(days=1),  # Expired yesterday
        )
        test_db.add(expired_share)
        await test_db.commit()

        response = client.get("/api/v1/shared/expired_token")

        assert response.status_code == 403
        assert "has expired" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_get_shared_memory_memory_not_found(self, test_db, client):
        """Test accessing share when memory has been deleted."""
        # Create share for non-existent memory
        orphan_share = MemoryShare(
            id=str(uuid.uuid4()),
            memory_id="deleted_memory_id",
            share_token="orphan_token",
            shared_by="user_123",
            permissions={"view": True},
        )
        test_db.add(orphan_share)
        await test_db.commit()

        response = client.get("/api/v1/shared/orphan_token")

        assert response.status_code == 404
        assert "Memory not found" in response.json()["detail"]
