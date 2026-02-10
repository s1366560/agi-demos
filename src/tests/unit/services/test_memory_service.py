"""
Unit tests for MemoryService.
Tests memory CRUD operations, version handling, and share functionality.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock

import pytest

from src.application.services.memory_service import MemoryService
from src.infrastructure.adapters.secondary.persistence.models import Memory


@pytest.mark.asyncio
class TestMemoryService:
    """Test MemoryService business logic."""

    @pytest.mark.skip(
        reason="Legacy interface diverges from current MemoryService; covered by use case tests"
    )
    async def test_create_memory_success(
        self, mock_memory_repo, mock_graphiti_client, mock_queue_service
    ):
        """Test successful memory creation."""
        # Arrange
        service = MemoryService(mock_memory_repo, mock_graphiti_client, mock_queue_service)

        mock_memory_repo.create.return_value = Memory(
            id="memory-1",
            title="Test Memory",
            content="Test content",
            project_id="project-1",
            author_id="user-1",
            created_at=datetime.now(timezone.utc),
        )

        # Act - call with individual parameters, not a dict
        result = await service.create_memory(
            title="Test Memory",
            content="Test content",
            project_id="project-1",
            user_id="user-1",
            tenant_id="tenant-1",
        )

        # Assert
        assert result.title == "Test Memory"
        assert result.content == "Test content"
        mock_memory_repo.create.assert_called_once()

    @pytest.mark.skip(
        reason="Legacy interface diverges from current MemoryService; covered by use case tests"
    )
    async def test_update_memory_success(self, mock_memory_repo, mock_queue_service):
        """Test successful memory update."""
        # Arrange
        service = MemoryService(mock_memory_repo, Mock(), mock_queue_service)
        memory_id = "memory-1"

        existing_memory = Memory(
            id=memory_id,
            title="Old Title",
            content="Old Content",
            version=1,
            project_id="project-1",
            author_id="user-1",
            created_at=datetime.now(timezone.utc),
        )

        mock_memory_repo.find_by_id.return_value = existing_memory
        mock_memory_repo.update.return_value = Memory(
            id=memory_id,
            title="New Title",
            content="New Content",
            version=2,  # Version incremented
            project_id="project-1",
            author_id="user-1",
            created_at=datetime.now(timezone.utc),
        )

        # Act - use kwargs for individual parameters
        result = await service.update_memory(
            memory_id=memory_id, title="New Title", content="New Content"
        )

        # Assert
        assert result.title == "New Title"
        mock_memory_repo.update.assert_called_once()

    @pytest.mark.skip(
        reason="Legacy interface diverges from current MemoryService; covered by use case tests"
    )
    async def test_update_memory_version_conflict(self, mock_memory_repo, mock_queue_service):
        """Test update with version mismatch raises error."""
        # Arrange
        service = MemoryService(mock_memory_repo, Mock(), mock_queue_service)
        memory_id = "memory-1"

        existing_memory = Memory(
            id=memory_id,
            title="Title",
            content="Content",
            version=2,  # Current version is 2
            project_id="project-1",
            author_id="user-1",
            created_at=datetime.now(timezone.utc),
        )

        mock_memory_repo.find_by_id.return_value = existing_memory

        # Act & Assert
        with pytest.raises(ValueError, match="Version mismatch"):
            await service.update_memory(
                memory_id,
                {"title": "New Title"},
                version=1,  # Trying to update with version 1
            )

    async def test_delete_memory_success(self, mock_memory_repo, mock_graphiti_client):
        """Test successful memory deletion with proper graph cleanup."""
        # Arrange
        service = MemoryService(mock_memory_repo, mock_graphiti_client)
        memory_id = "memory-1"

        mock_memory_repo.find_by_id.return_value = Memory(
            id=memory_id,
            title="Title",
            content="Content",
            version=1,
            project_id="project-1",
            author_id="user-1",
            created_at=datetime.now(timezone.utc),
        )

        # Mock the remove_episode method (new proper cleanup method)
        mock_graphiti_client.remove_episode = AsyncMock(return_value=True)

        # Act
        await service.delete_memory(memory_id)

        # Assert
        # Should call remove_episode (the proper cleanup method), not delete_episode_by_memory_id
        mock_graphiti_client.remove_episode.assert_called_once_with(memory_id)
        mock_memory_repo.delete.assert_called_once_with(memory_id)

    async def test_delete_memory_continues_on_graph_error(
        self, mock_memory_repo, mock_graphiti_client
    ):
        """Test that memory deletion continues even if graph deletion fails."""
        # Arrange
        service = MemoryService(mock_memory_repo, mock_graphiti_client)
        memory_id = "memory-1"

        mock_memory_repo.find_by_id.return_value = Memory(
            id=memory_id,
            title="Title",
            content="Content",
            version=1,
            project_id="project-1",
            author_id="user-1",
            created_at=datetime.now(timezone.utc),
        )

        # Mock remove_episode to raise an error
        mock_graphiti_client.remove_episode = AsyncMock(
            side_effect=Exception("Graph deletion failed")
        )

        # Act - should not raise, should continue with DB deletion
        await service.delete_memory(memory_id)

        # Assert - DB deletion should still happen
        mock_memory_repo.delete.assert_called_once_with(memory_id)

    async def test_delete_memory_not_found(self, mock_memory_repo, mock_graphiti_client):
        """Test deletion of non-existent memory raises error."""
        # Arrange
        service = MemoryService(mock_memory_repo, mock_graphiti_client)
        memory_id = "non-existent"

        mock_memory_repo.find_by_id.return_value = None

        # Act & Assert
        with pytest.raises(ValueError, match="not found"):
            await service.delete_memory(memory_id)

    async def test_get_memory_by_id(self, mock_memory_repo):
        """Test retrieving memory by ID."""
        # Arrange
        service = MemoryService(mock_memory_repo, Mock())
        memory_id = "memory-1"

        expected_memory = Memory(
            id=memory_id,
            title="Test Memory",
            content="Content",
            version=1,
            project_id="project-1",
            author_id="user-1",
            created_at=datetime.now(timezone.utc),
        )

        mock_memory_repo.find_by_id.return_value = expected_memory

        # Act
        result = await service.get_memory(memory_id)

        # Assert
        assert result.id == memory_id
        assert result.title == "Test Memory"
        mock_memory_repo.find_by_id.assert_called_once_with(memory_id)

    async def test_search_memories(self, mock_memory_repo, mock_graphiti_client):
        """Test searching memories by query."""
        # Arrange
        service = MemoryService(mock_memory_repo, mock_graphiti_client)

        # Mock graph_service.search to return async results using AsyncMock
        from unittest.mock import AsyncMock

        mock_graphiti_client.search = AsyncMock(
            return_value=[
                {"type": "episode", "title": "Memory 1", "content": "Content 1"},
                {"type": "episode", "title": "Memory 2", "content": "Content 2"},
            ]
        )

        # Act - parameters are (query, project_id, limit), not (project_id, query)
        results = await service.search_memories(
            query="test query", project_id="project-1", limit=10
        )

        # Assert - returns SearchResults object with memories and entities
        assert len(results.memories) == 2
        mock_graphiti_client.search.assert_called_once()

    async def test_share_memory_with_user(self, mock_memory_repo):
        """Test sharing memory with a user."""
        # Arrange
        service = MemoryService(mock_memory_repo, Mock())
        memory_id = "memory-1"
        user_id = "user-2"

        mock_memory_repo.find_by_id.return_value = Memory(
            id=memory_id,
            title="Memory",
            content="Content",
            version=1,
            project_id="project-1",
            author_id="user-1",
            collaborators=[],  # Initialize collaborators
            created_at=datetime.now(timezone.utc),
        )

        # Act - signature is (memory_id, collaborators)
        await service.share_memory(memory_id=memory_id, collaborators=[user_id])

        # Assert - calls save() not update()
        mock_memory_repo.save.assert_called_once()

    async def test_share_memory_with_project(self, mock_memory_repo):
        """Test sharing memory with a project."""
        # Arrange
        service = MemoryService(mock_memory_repo, Mock())
        memory_id = "memory-1"
        project_id = "project-2"

        mock_memory_repo.find_by_id.return_value = Memory(
            id=memory_id,
            title="Memory",
            content="Content",
            version=1,
            project_id="project-1",
            author_id="user-1",
            collaborators=[],  # Initialize collaborators
            created_at=datetime.now(timezone.utc),
        )

        # Act - signature is (memory_id, collaborators)
        await service.share_memory(memory_id=memory_id, collaborators=[project_id])

        # Assert - calls save() not update()
        mock_memory_repo.save.assert_called_once()


@pytest.mark.asyncio
class TestMemoryServicePermissions:
    """Test permission checks in MemoryService."""

    async def test_user_with_edit_share_can_update(self, mock_memory_repo):
        """Test that user with edit share can update memory."""
        # This would require mock share repository setup
        # For now, we'll test the basic logic
        pass

    async def test_user_without_permission_cannot_update(self):
        """Test that user without permission cannot update memory."""
        # This would require full mock setup of shares and permissions
        # For now, we'll test the basic logic
        pass
