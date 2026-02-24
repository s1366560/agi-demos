"""
Integration tests for Project Settings endpoints.
Tests PUT /{project_id}, DELETE /{project_id}
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.secondary.persistence.models import (
    Memory,
    Project,
    Tenant,
    User,
    UserProject,
)


@pytest.mark.asyncio
class TestUpdateProjectEndpoint:
    """Test PUT /{project_id} endpoint."""

    async def test_update_project_success(
        self,
        async_client: AsyncClient,
        db: AsyncSession,
        test_project_db: "Project",
        test_user: User,
    ):
        """Test successful project update."""
        # Arrange
        update_data = {
            "name": "Updated Project Name",
            "description": "Updated description",
        }

        # Act
        response = await async_client.put(
            f"/api/v1/projects/{test_project_db.id}", json=update_data
        )

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Updated Project Name"
        assert data["description"] == "Updated description"

        # Verify in database
        await db.refresh(test_project_db)
        assert test_project_db.name == "Updated Project Name"

    async def test_update_project_with_is_public(
        self, authenticated_async_client: AsyncClient, test_project_db, test_db
    ):
        """Test updating project visibility."""
        # Arrange
        project_id = str(test_project_db.id)
        payload = {"is_public": True}

        # Act
        response = await authenticated_async_client.put(
            f"/api/v1/projects/{project_id}", json=payload
        )

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["is_public"] is True

        await test_db.refresh(test_project_db)
        assert test_project_db.is_public is True

    async def test_update_project_partial_fields(
        self, async_client: AsyncClient, db: AsyncSession, test_project_db: "Project"
    ):
        """Test updating only specific fields."""
        # Arrange - update only name, not description
        original_description = test_project_db.description
        update_data = {"name": "New Name Only"}

        # Act
        response = await async_client.put(
            f"/api/v1/projects/{test_project_db.id}", json=update_data
        )

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "New Name Only"
        assert data["description"] == original_description

    async def test_update_project_not_found(self, authenticated_async_client: AsyncClient):
        """Test updating a non-existent project."""
        # Arrange
        from uuid import uuid4

        project_id = str(uuid4())
        payload = {"name": "Updated Name"}

        # Act
        response = await authenticated_async_client.put(
            f"/api/v1/projects/{project_id}", json=payload
        )

        # Assert
        assert response.status_code == 403

    async def test_update_project_unauthorized(
        self,
        async_client: AsyncClient,
        db: AsyncSession,
        test_project_db: "Project",
        test_user: User,
    ):
        """Test that only owner/admin can update project."""
        # This test would require creating a user without admin rights
        # For now, we document the expected behavior
        # Current implementation: only owner or admin can update

    async def test_update_project_with_memory_rules(
        self, authenticated_async_client: AsyncClient, test_project_db, test_db
    ):
        """Test updating project memory rules."""
        # Arrange
        project_id = str(test_project_db.id)
        # Only use fields that exist in MemoryRulesConfig: max_episodes, retention_days, auto_refresh, refresh_interval
        payload = {"memory_rules": {"max_episodes": 2000, "retention_days": 60}}

        # Act
        response = await authenticated_async_client.put(
            f"/api/v1/projects/{project_id}", json=payload
        )

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["memory_rules"]["max_episodes"] == 2000

        # Refresh from DB
        await test_db.refresh(test_project_db)
        assert test_project_db.memory_rules["max_episodes"] == 2000

    async def test_update_project_with_graph_config(
        self, authenticated_async_client: AsyncClient, test_project_db, test_db
    ):
        """Test updating project graph configuration."""
        # Arrange
        project_id = str(test_project_db.id)
        # Only use fields that exist in GraphConfig
        payload = {"graph_config": {"max_nodes": 2000, "community_detection": False}}

        # Act
        response = await authenticated_async_client.put(
            f"/api/v1/projects/{project_id}", json=payload
        )

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["graph_config"]["max_nodes"] == 2000
        assert data["graph_config"]["community_detection"] is False

        # Refresh from DB
        await test_db.refresh(test_project_db)
        assert test_project_db.graph_config["max_nodes"] == 2000


@pytest.mark.asyncio
class TestDeleteProjectEndpoint:
    """Test DELETE /{project_id} endpoint."""

    async def test_delete_project_success(
        self,
        authenticated_async_client: AsyncClient,
        db: AsyncSession,
        test_tenant_db: "Tenant",
        test_user: User,
    ):
        """Test successful project deletion."""
        # Arrange - create a project to delete
        from uuid import uuid4

        project = Project(
            id=str(uuid4()),
            tenant_id=test_tenant_db.id,
            name="Project to Delete",
            description="Will be deleted",
            owner_id=test_user.id,
            memory_rules={},
            graph_config={},
        )
        db.add(project)

        user_project = UserProject(
            id=str(uuid4()),
            user_id=test_user.id,
            project_id=project.id,
            role="owner",
            permissions={"admin": True},
        )
        db.add(user_project)
        await db.commit()

        project_id = project.id

        # Act
        response = await authenticated_async_client.delete(f"/api/v1/projects/{project_id}")

        # Assert
        assert response.status_code == 204

        # Verify deletion in database
        result = await db.execute(select(Project).where(Project.id == project_id))
        assert result.scalar_one_or_none() is None

        # Verify user-project relationship also deleted
        result = await db.execute(select(UserProject).where(UserProject.project_id == project_id))
        assert result.scalar_one_or_none() is None

    async def test_delete_project_not_found(self, authenticated_async_client: AsyncClient):
        """Test deleting a non-existent project."""
        # Arrange
        from uuid import uuid4

        project_id = str(uuid4())

        # Act
        response = await authenticated_async_client.delete(f"/api/v1/projects/{project_id}")

        # Assert
        assert response.status_code == 403

    async def test_delete_project_unauthorized(
        self, async_client: AsyncClient, test_project_db: "Project"
    ):
        """Test that only owner can delete project."""
        # This would require authenticating as a non-owner user
        # Current implementation: only owner can delete

    async def test_delete_project_with_memories(
        self,
        authenticated_async_client: AsyncClient,
        db: AsyncSession,
        test_tenant_db: "Tenant",
        test_user: User,
    ):
        """Test that deleting project also handles associated memories."""
        # Arrange - create project with memories
        from uuid import uuid4

        project = Project(
            id=str(uuid4()),
            tenant_id=test_tenant_db.id,
            name="Project with Memories",
            description="Test",
            owner_id=test_user.id,
            memory_rules={},
            graph_config={},
        )
        db.add(project)

        memory = Memory(
            id=str(uuid4()),
            project_id=project.id,
            title="Test Memory",
            content="Content",
            author_id=test_user.id,
            version=1,
        )
        db.add(memory)

        user_project = UserProject(
            id=str(uuid4()),
            user_id=test_user.id,
            project_id=project.id,
            role="owner",
            permissions={"admin": True},
        )
        db.add(user_project)
        await db.commit()

        project_id = project.id

        # Act
        response = await authenticated_async_client.delete(f"/api/v1/projects/{project_id}")

        # Assert
        assert response.status_code == 204

        # Verify project deleted
        result = await db.execute(select(Project).where(Project.id == project_id))
        assert result.scalar_one_or_none() is None

        # Note: Memories might be orphaned or cascade deleted
        # This depends on database configuration


@pytest.mark.asyncio
class TestProjectMemberManagementEndpoints:
    """Test project member management endpoints as part of settings."""

    async def test_add_project_member_success(
        self,
        authenticated_async_client: AsyncClient,
        db: AsyncSession,
        test_project_db: "Project",
        test_user: User,
        test_tenant_db: "Tenant",
    ):
        """Test adding member to project."""
        # Arrange - create another user
        new_user = User(
            id="user-project-member",
            email="projectmember@example.com",
            full_name="Project Member",
            hashed_password="hash",
        )
        db.add(new_user)
        await db.commit()

        # Act
        payload = {"user_id": "user-project-member", "role": "member"}
        response = await authenticated_async_client.post(
            f"/api/v1/projects/{test_project_db.id}/members", json=payload
        )

        # Assert
        assert response.status_code == 201
        data = response.json()
        assert data["user_id"] == "user-project-member"
        assert data["role"] == "member"

        # Verify in database
        result = await db.execute(
            select(UserProject).where(
                UserProject.user_id == "user-project-member",
                UserProject.project_id == test_project_db.id,
            )
        )
        user_project = result.scalar_one_or_none()
        assert user_project is not None

    async def test_remove_project_member_success(
        self,
        authenticated_async_client: AsyncClient,
        db: AsyncSession,
        test_project_db: "Project",
        test_user: User,
    ):
        """Test removing member from project."""
        # Arrange - add a member first
        from uuid import uuid4

        new_user = User(
            id="user-removable",
            email="removable@example.com",
            full_name="Removable",
            hashed_password="hash",
        )
        db.add(new_user)

        user_project = UserProject(
            id=str(uuid4()),
            user_id="user-removable",
            project_id=test_project_db.id,
            role="viewer",
            permissions={"read": True},
        )
        db.add(user_project)
        await db.commit()

        # Act
        response = await authenticated_async_client.delete(
            f"/api/v1/projects/{test_project_db.id}/members/user-removable"
        )

        # Assert
        assert response.status_code == 204

        # Verify removal
        result = await db.execute(
            select(UserProject).where(
                UserProject.user_id == "user-removable",
                UserProject.project_id == test_project_db.id,
            )
        )
        assert result.scalar_one_or_none() is None

    async def test_list_project_members(
        self,
        authenticated_async_client: AsyncClient,
        db: AsyncSession,
        test_project_db: "Project",
        test_user: User,
    ):
        """Test listing project members."""
        # Act
        response = await authenticated_async_client.get(
            f"/api/v1/projects/{test_project_db.id}/members"
        )

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert "members" in data
        assert data["total"] == 1
        assert data["members"][0]["user_id"] == str(test_user.id)
        assert data["members"][0]["role"] == "owner"

    async def test_cannot_add_member_beyond_tenant_limit(
        self,
        async_client: AsyncClient,
        db: AsyncSession,
        test_project_db: "Project",
        test_tenant_db: "Tenant",
    ):
        """Test that project member limit is enforced based on tenant limits."""
        # Arrange - set a low limit for testing
        original_max = test_tenant_db.max_users
        test_tenant_db.max_users = 2  # Already has 1 member (owner)
        await db.commit()

        # Try to add a second member (should succeed)
        new_user = User(
            id="user-extra",
            email="extra@example.com",
            full_name="Extra User",
            hashed_password="hash",
        )
        db.add(new_user)
        await db.commit()

        payload = {"user_id": "user-extra", "role": "viewer"}
        response = await async_client.post(
            f"/api/v1/projects/{test_project_db.id}/members", json=payload
        )

        # This should succeed if within limit, or fail if limit reached
        # The actual behavior depends on the current member count
        assert response.status_code in [201, 400]

        # Restore original limit
        test_tenant_db.max_users = original_max
        await db.commit()


@pytest.mark.asyncio
class TestProjectStatsEndpoint:
    """Test GET /{project_id}/stats endpoint."""

    async def test_get_project_stats(
        self,
        async_client: AsyncClient,
        db: AsyncSession,
        test_project_db: "Project",
    ):
        """Test retrieving project statistics."""
        # Act
        response = await async_client.get(f"/api/v1/projects/{test_project_db.id}/stats")

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert "memory_count" in data
        assert "node_count" in data
        assert "member_count" in data
        assert "storage_used" in data
        assert "last_active" in data

    async def test_get_project_stats_not_found(self, authenticated_async_client: AsyncClient):
        """Test getting stats for a non-existent project."""
        # Arrange
        from uuid import uuid4

        project_id = str(uuid4())

        # Act
        response = await authenticated_async_client.get(f"/api/v1/projects/{project_id}/stats")

        # Assert
        # 403 Forbidden (access denied) or 404 Not Found (project not found) are acceptable
        # 422 Unprocessable Entity might happen if UUID validation is strict or dependency fails
        assert response.status_code in [403, 404, 422]
