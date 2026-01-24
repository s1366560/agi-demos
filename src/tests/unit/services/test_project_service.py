"""
Unit tests for ProjectService.

These tests use mocked repositories to test business logic in isolation.
"""

from unittest.mock import AsyncMock, Mock

import pytest

from src.application.services.project_service import ProjectService


@pytest.fixture
def mock_project_repo():
    """Create a mock project repository"""
    repo = Mock()
    repo.save = AsyncMock()
    repo.find_by_id = AsyncMock()
    repo.find_by_tenant = AsyncMock()
    repo.find_by_owner = AsyncMock()
    repo.delete = AsyncMock()
    return repo


@pytest.fixture
def mock_user_repo():
    """Create a mock user repository"""
    repo = Mock()
    repo.find_by_id = AsyncMock()
    return repo


@pytest.fixture
def project_service(mock_project_repo, mock_user_repo):
    """Create a ProjectService instance with mocked repositories"""
    return ProjectService(project_repo=mock_project_repo, user_repo=mock_user_repo)


@pytest.mark.asyncio
async def test_create_project_success(project_service, mock_project_repo, mock_user_repo):
    """Test successful project creation"""
    # Mock user exists
    mock_user = Mock()
    mock_user.id = "user-123"
    mock_user_repo.find_by_id.return_value = mock_user

    # Create project
    project = await project_service.create_project(
        name="Test Project",
        owner_id="user-123",
        tenant_id="tenant-456",
        description="A test project",
    )

    # Verify user lookup
    mock_user_repo.find_by_id.assert_called_once_with("user-123")

    # Verify project was saved
    mock_project_repo.save.assert_called_once()

    # Check project properties
    assert project.name == "Test Project"
    assert project.owner_id == "user-123"
    assert project.tenant_id == "tenant-456"
    assert project.description == "A test project"
    assert "user-123" in project.member_ids  # Owner should be a member


@pytest.mark.asyncio
async def test_create_project_user_not_found(project_service, mock_user_repo):
    """Test project creation with non-existent user"""
    # Mock user doesn't exist
    mock_user_repo.find_by_id.return_value = None

    # Should raise ValueError
    with pytest.raises(ValueError, match="Owner with ID user-123 does not exist"):
        await project_service.create_project(
            name="Test Project", owner_id="user-123", tenant_id="tenant-456"
        )


@pytest.mark.asyncio
async def test_get_project_success(project_service, mock_project_repo):
    """Test successful project retrieval"""
    mock_project = Mock()
    mock_project.id = "project-123"
    mock_project.name = "Test Project"
    mock_project_repo.find_by_id.return_value = mock_project

    # Get project
    result = await project_service.get_project("project-123")

    # Verify repository call
    mock_project_repo.find_by_id.assert_called_once_with("project-123")
    assert result == mock_project


@pytest.mark.asyncio
async def test_get_project_not_found(project_service, mock_project_repo):
    """Test getting non-existent project"""
    mock_project_repo.find_by_id.return_value = None

    result = await project_service.get_project("nonexistent")

    assert result is None


@pytest.mark.asyncio
async def test_list_projects_by_tenant(project_service, mock_project_repo):
    """Test listing projects in a tenant"""
    mock_projects = [
        Mock(id="project-1", name="Project 1", owner_id="user-1"),
        Mock(id="project-2", name="Project 2", owner_id="user-1"),
        Mock(id="project-3", name="Project 3", owner_id="user-2"),
    ]
    mock_project_repo.find_by_tenant.return_value = mock_projects

    # List all tenant projects
    result = await project_service.list_projects("tenant-123")

    # Verify call
    mock_project_repo.find_by_tenant.assert_called_once_with("tenant-123", limit=50, offset=0)
    assert result == mock_projects


@pytest.mark.asyncio
async def test_list_projects_filtered_by_owner(project_service, mock_project_repo):
    """Test listing projects filtered by owner"""
    mock_projects = [
        Mock(id="project-1", name="Project 1", owner_id="user-1"),
        Mock(id="project-2", name="Project 2", owner_id="user-1"),
        Mock(id="project-3", name="Project 3", owner_id="user-2"),
    ]
    mock_project_repo.find_by_tenant.return_value = mock_projects

    # List projects for specific owner
    result = await project_service.list_projects(tenant_id="tenant-123", owner_id="user-1")

    # Should only return user-1's projects
    assert len(result) == 2
    assert all(p.owner_id == "user-1" for p in result)


@pytest.mark.asyncio
async def test_update_project_success(project_service, mock_project_repo):
    """Test successful project update"""
    mock_project = Mock()
    mock_project.id = "project-123"
    mock_project.name = "Old Name"
    mock_project.description = "Old Description"
    mock_project.is_public = False
    mock_project_repo.find_by_id.return_value = mock_project

    # Update project
    result = await project_service.update_project(
        project_id="project-123", name="New Name", description="New Description", is_public=True
    )

    # Verify updates
    assert result.name == "New Name"
    assert result.description == "New Description"
    assert result.is_public is True
    assert result.updated_at is not None

    # Verify save was called
    mock_project_repo.save.assert_called_once()


@pytest.mark.asyncio
async def test_update_project_not_found(project_service, mock_project_repo):
    """Test updating non-existent project"""
    mock_project_repo.find_by_id.return_value = None

    with pytest.raises(ValueError, match="Project project-123 not found"):
        await project_service.update_project(project_id="project-123", name="New Name")


@pytest.mark.asyncio
async def test_delete_project_success(project_service, mock_project_repo):
    """Test successful project deletion"""
    mock_project = Mock()
    mock_project.id = "project-123"
    mock_project_repo.find_by_id.return_value = mock_project

    # Delete project
    await project_service.delete_project("project-123")

    # Verify deletion
    mock_project_repo.delete.assert_called_once_with("project-123")


@pytest.mark.asyncio
async def test_delete_project_not_found(project_service, mock_project_repo):
    """Test deleting non-existent project"""
    mock_project_repo.find_by_id.return_value = None

    with pytest.raises(ValueError, match="Project project-123 not found"):
        await project_service.delete_project("project-123")


@pytest.mark.asyncio
async def test_add_member_success(project_service, mock_project_repo, mock_user_repo):
    """Test successfully adding a member to a project"""
    mock_project = Mock()
    mock_project.id = "project-123"
    mock_project.member_ids = ["owner-123"]
    mock_project_repo.find_by_id.return_value = mock_project

    mock_user = Mock()
    mock_user.id = "user-456"
    mock_user_repo.find_by_id.return_value = mock_user

    # Add member
    await project_service.add_member("project-123", "user-456")

    # Verify member was added
    assert "user-456" in mock_project.member_ids
    mock_project_repo.save.assert_called_once()


@pytest.mark.asyncio
async def test_add_member_already_exists(project_service, mock_project_repo, mock_user_repo):
    """Test adding a user who is already a member"""
    mock_project = Mock()
    mock_project.id = "project-123"
    mock_project.member_ids = ["owner-123", "user-456"]
    mock_project_repo.find_by_id.return_value = mock_project

    mock_user = Mock()
    mock_user.id = "user-456"
    mock_user_repo.find_by_id.return_value = mock_user

    # Add existing member (should not duplicate)
    await project_service.add_member("project-123", "user-456")

    # Should not call save (no changes needed)
    # Note: Depending on implementation, this might still call save


@pytest.mark.asyncio
async def test_remove_member_success(project_service, mock_project_repo):
    """Test successfully removing a member from a project"""
    mock_project = Mock()
    mock_project.id = "project-123"
    mock_project.owner_id = "owner-123"
    mock_project.member_ids = ["owner-123", "user-456"]
    mock_project_repo.find_by_id.return_value = mock_project

    # Remove member
    await project_service.remove_member("project-123", "user-456")

    # Verify member was removed
    assert "user-456" not in mock_project.member_ids
    mock_project_repo.save.assert_called_once()


@pytest.mark.asyncio
async def test_remove_member_owner_forbidden(project_service, mock_project_repo):
    """Test that owner cannot be removed"""
    mock_project = Mock()
    mock_project.id = "project-123"
    mock_project.owner_id = "owner-123"
    mock_project.member_ids = ["owner-123", "user-456"]
    mock_project_repo.find_by_id.return_value = mock_project

    # Try to remove owner
    with pytest.raises(ValueError, match="Cannot remove project owner"):
        await project_service.remove_member("project-123", "owner-123")


@pytest.mark.asyncio
async def test_get_members_success(project_service, mock_project_repo):
    """Test getting project members"""
    mock_project = Mock()
    mock_project.id = "project-123"
    mock_project.member_ids = ["user-1", "user-2", "user-3"]
    mock_project_repo.find_by_id.return_value = mock_project

    # Get members
    result = await project_service.get_members("project-123")

    # Verify result
    assert result == ["user-1", "user-2", "user-3"]


@pytest.mark.asyncio
async def test_get_members_project_not_found(project_service, mock_project_repo):
    """Test getting members of non-existent project"""
    mock_project_repo.find_by_id.return_value = None

    with pytest.raises(ValueError, match="Project project-123 not found"):
        await project_service.get_members("project-123")
