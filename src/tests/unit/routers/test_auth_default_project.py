"""
Tests for automatic default project creation on first login.
"""

from unittest.mock import MagicMock

import pytest
from sqlalchemy import select

from src.infrastructure.adapters.primary.web.routers.auth import _ensure_default_project
from src.infrastructure.adapters.secondary.persistence.models import (
    Project,
    Tenant,
    UserProject,
    UserTenant,
)


@pytest.mark.unit
class TestEnsureDefaultProject:
    """Test cases for _ensure_default_project function."""

    async def test_creates_default_project_when_user_has_no_projects(self, db_session):
        """Test that default project is created when user has no projects."""
        # Arrange
        user = MagicMock()
        user.id = "user-123"
        user.full_name = "Test User"
        user.email = "test@example.com"

        # Create a tenant for the user
        tenant = Tenant(
            id="tenant-123",
            name="Test Tenant",
            slug="test-tenant",
            owner_id=user.id,
        )
        db_session.add(tenant)
        await db_session.flush()

        # Create user-tenant relationship
        user_tenant = UserTenant(
            id="ut-123",
            user_id=user.id,
            tenant_id=tenant.id,
            role="owner",
        )
        db_session.add(user_tenant)
        await db_session.commit()

        # Act
        await _ensure_default_project(db_session, user)
        await db_session.commit()

        # Assert
        result = await db_session.execute(
            select(UserProject).where(UserProject.user_id == user.id)
        )
        user_projects = result.scalars().all()
        assert len(user_projects) == 1

        result = await db_session.execute(
            select(Project).where(Project.id == user_projects[0].project_id)
        )
        project = result.scalar_one()
        assert project.name == "默认项目"
        assert project.owner_id == user.id
        assert project.tenant_id == tenant.id

    async def test_does_not_create_project_if_user_already_has_projects(self, db_session):
        """Test that no project is created if user already has projects."""
        # Arrange
        user = MagicMock()
        user.id = "user-456"
        user.full_name = "Test User 2"
        user.email = "test2@example.com"

        # Create tenant
        tenant = Tenant(
            id="tenant-456",
            name="Test Tenant 2",
            slug="test-tenant-2",
            owner_id=user.id,
        )
        db_session.add(tenant)
        await db_session.flush()

        # Create user-tenant relationship
        user_tenant = UserTenant(
            id="ut-456",
            user_id=user.id,
            tenant_id=tenant.id,
            role="owner",
        )
        db_session.add(user_tenant)

        # Create existing project
        existing_project = Project(
            id="project-456",
            tenant_id=tenant.id,
            name="Existing Project",
            owner_id=user.id,
        )
        db_session.add(existing_project)

        # Create user-project relationship
        user_project = UserProject(
            id="up-456",
            user_id=user.id,
            project_id=existing_project.id,
            role="owner",
        )
        db_session.add(user_project)
        await db_session.commit()

        # Act
        await _ensure_default_project(db_session, user)
        await db_session.commit()

        # Assert
        result = await db_session.execute(
            select(Project).where(Project.owner_id == user.id)
        )
        projects = result.scalars().all()
        assert len(projects) == 1
        assert projects[0].name == "Existing Project"

    async def test_does_nothing_if_user_has_no_tenant(self, db_session):
        """Test that no project is created if user has no tenant."""
        # Arrange
        user = MagicMock()
        user.id = "user-789"
        user.full_name = "Test User 3"
        user.email = "test3@example.com"

        # Act
        await _ensure_default_project(db_session, user)
        await db_session.commit()

        # Assert
        result = await db_session.execute(
            select(UserProject).where(UserProject.user_id == user.id)
        )
        user_projects = result.scalars().all()
        assert len(user_projects) == 0

    async def test_uses_email_when_full_name_is_none(self, db_session):
        """Test that email is used in description when full_name is None."""
        # Arrange
        user = MagicMock()
        user.id = "user-abc"
        user.full_name = None
        user.email = "testuser@example.com"

        # Create tenant
        tenant = Tenant(
            id="tenant-abc",
            name="Test Tenant 3",
            slug="test-tenant-3",
            owner_id=user.id,
        )
        db_session.add(tenant)
        await db_session.flush()

        # Create user-tenant relationship
        user_tenant = UserTenant(
            id="ut-abc",
            user_id=user.id,
            tenant_id=tenant.id,
            role="owner",
        )
        db_session.add(user_tenant)
        await db_session.commit()

        # Act
        await _ensure_default_project(db_session, user)
        await db_session.commit()

        # Assert
        result = await db_session.execute(
            select(Project).where(Project.owner_id == user.id)
        )
        project = result.scalar_one()
        assert user.email in project.description
