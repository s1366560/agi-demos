"""
Unit tests for MemoryService.
Tests memory CRUD operations, version handling, and share functionality.
"""

import logging
from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock

import pytest

from src.application.services.memory_service import MemoryService
from src.domain.model.enums import ProcessingStatus
from src.domain.model.memory.memory import Memory


@pytest.mark.asyncio
class TestMemoryService:
    """Test MemoryService business logic."""

    async def test_create_memory_success(self, mock_memory_repo, mock_graphiti_client):
        """Test successful memory creation."""
        # Arrange
        service = MemoryService(mock_memory_repo, mock_graphiti_client)

        result = await service.create_memory(
            title="Test Memory",
            content="Test content",
            project_id="project-1",
            user_id="user-1",
            tenant_id="tenant-1",
            tags=["research"],
            is_public=True,
            metadata={"source": "test"},
        )

        assert result.title == "Test Memory"
        assert result.content == "Test content"
        assert result.project_id == "project-1"
        assert result.author_id == "user-1"
        assert result.tags == ["research"]
        assert result.is_public is True
        assert result.processing_status == ProcessingStatus.PENDING.value
        assert result.metadata == {
            "source": "test",
            "tenant_id": "tenant-1",
            "project_id": "project-1",
            "user_id": "user-1",
        }
        mock_memory_repo.save.assert_awaited_once_with(result)

        mock_graphiti_client.add_episode.assert_awaited_once()
        episode = mock_graphiti_client.add_episode.call_args.args[0]
        assert episode.name == "Test Memory"
        assert episode.content == "Test content"
        assert episode.metadata["memory_id"] == result.id
        assert episode.tenant_id == "tenant-1"
        assert episode.project_id == "project-1"
        assert episode.user_id == "user-1"

    async def test_create_memory_logs_do_not_include_identifiers_or_content(
        self,
        mock_memory_repo,
        mock_graphiti_client,
        caplog,
    ):
        """Memory creation logs must not expose IDs, title, or content."""
        secret_title = "Customer private memory title"
        secret_content = "The memory contains secret token alpha-1357"
        secret_project_id = "project-secret-memory-create"
        secret_user_id = "user-secret-memory-create"
        secret_tenant_id = "tenant-secret-memory-create"
        service = MemoryService(mock_memory_repo, mock_graphiti_client)
        caplog.set_level(logging.INFO, logger="src.application.services.memory_service")

        memory = await service.create_memory(
            title=secret_title,
            content=secret_content,
            project_id=secret_project_id,
            user_id=secret_user_id,
            tenant_id=secret_tenant_id,
            tags=["private", "incident"],
            is_public=False,
        )
        episode = mock_graphiti_client.add_episode.call_args.args[0]

        assert memory.id not in caplog.text
        assert episode.id not in caplog.text
        assert secret_title not in caplog.text
        assert secret_content not in caplog.text
        assert secret_project_id not in caplog.text
        assert secret_user_id not in caplog.text
        assert secret_tenant_id not in caplog.text
        assert "tag_count=2" in caplog.text
        assert "is_public=False" in caplog.text

    async def test_create_memory_graph_failure_logs_do_not_include_identifiers_or_exception(
        self,
        mock_memory_repo,
        mock_graphiti_client,
        caplog,
    ):
        """Graph enqueue failure logs must not expose IDs, content, or backend error text."""
        secret_title = "Graph failure private title"
        secret_content = "Graph failure secret body beta-2468"
        exception_detail = "graph backend leaked episode payload gamma-9753"
        service = MemoryService(mock_memory_repo, mock_graphiti_client)
        mock_graphiti_client.add_episode = AsyncMock(side_effect=RuntimeError(exception_detail))
        caplog.set_level(logging.ERROR, logger="src.application.services.memory_service")

        with pytest.raises(RuntimeError):
            await service.create_memory(
                title=secret_title,
                content=secret_content,
                project_id="project-secret-graph-failure",
                user_id="user-secret-graph-failure",
                tenant_id="tenant-secret-graph-failure",
            )

        saved_memory = mock_memory_repo.save.await_args_list[0].args[0]
        assert saved_memory.id not in caplog.text
        assert secret_title not in caplog.text
        assert secret_content not in caplog.text
        assert exception_detail not in caplog.text
        assert "error_type=RuntimeError" in caplog.text

    async def test_create_memory_can_skip_graph_enqueue(
        self, mock_memory_repo, mock_graphiti_client
    ):
        """Agent tools can use a fast commit path and queue graph work separately."""
        service = MemoryService(mock_memory_repo, mock_graphiti_client)

        result = await service.create_memory(
            title="Fast Memory",
            content="Fast content",
            project_id="project-1",
            user_id="user-1",
            tenant_id="tenant-1",
            enqueue_graph=False,
        )

        assert result.title == "Fast Memory"
        assert result.processing_status == ProcessingStatus.PENDING.value
        mock_memory_repo.save.assert_awaited_once_with(result)
        mock_graphiti_client.add_episode.assert_not_awaited()

    async def test_update_memory_success(self, mock_memory_repo, mock_graphiti_client):
        """Test successful memory update."""
        # Arrange
        service = MemoryService(mock_memory_repo, mock_graphiti_client)
        memory_id = "memory-1"

        existing_memory = Memory(
            id=memory_id,
            title="Old Title",
            content="Old Content",
            version=1,
            project_id="project-1",
            author_id="user-1",
            metadata={"tenant_id": "tenant-1", "source": "original"},
            created_at=datetime.now(UTC),
        )

        mock_memory_repo.find_by_id.return_value = existing_memory

        result = await service.update_memory(
            memory_id=memory_id,
            title="New Title",
            content="New Content",
            tags=["updated"],
            is_public=True,
            metadata={"source": "edited"},
        )

        assert result.title == "New Title"
        assert result.content == "New Content"
        assert result.tags == ["updated"]
        assert result.is_public is True
        assert result.metadata["source"] == "edited"
        assert result.updated_at is not None
        assert result.processing_status == ProcessingStatus.PENDING.value
        mock_memory_repo.save.assert_awaited_once_with(existing_memory)

        mock_graphiti_client.delete_episode_by_memory_id.assert_awaited_once_with(memory_id)
        mock_graphiti_client.add_episode.assert_awaited_once()
        episode = mock_graphiti_client.add_episode.call_args.args[0]
        assert episode.content == "New Content"
        assert episode.metadata["memory_id"] == memory_id
        assert episode.metadata["tenant_id"] == "tenant-1"
        assert episode.metadata["reprocess"] is True

    async def test_update_memory_logs_do_not_include_identifiers_or_content(
        self,
        mock_memory_repo,
        mock_graphiti_client,
        caplog,
    ):
        """Memory update logs must not expose IDs, title, or content."""
        secret_memory_id = "memory-secret-update"
        secret_title = "Updated private memory title"
        secret_content = "Updated body has secret token delta-8642"
        existing_memory = Memory(
            id=secret_memory_id,
            title="Old private title",
            content="Old private content",
            version=1,
            project_id="project-secret-update",
            author_id="user-secret-update",
            metadata={"tenant_id": "tenant-secret-update"},
            created_at=datetime.now(UTC),
        )
        mock_memory_repo.find_by_id.return_value = existing_memory
        service = MemoryService(mock_memory_repo, mock_graphiti_client)
        caplog.set_level(logging.INFO, logger="src.application.services.memory_service")

        result = await service.update_memory(
            memory_id=secret_memory_id,
            title=secret_title,
            content=secret_content,
            tags=["private"],
        )

        assert result.title == secret_title
        assert secret_memory_id not in caplog.text
        assert secret_title not in caplog.text
        assert secret_content not in caplog.text
        assert "content_changed=True" in caplog.text
        assert "tag_count=1" in caplog.text

    async def test_update_memory_reprocess_failure_logs_do_not_include_exception_content(
        self,
        mock_memory_repo,
        mock_graphiti_client,
        caplog,
    ):
        """Memory reprocess failure logs must not expose IDs, content, or backend error text."""
        secret_memory_id = "memory-secret-reprocess"
        secret_content = "Reprocess secret content epsilon-7531"
        exception_detail = "graph enqueue leaked memory body zeta-1597"
        existing_memory = Memory(
            id=secret_memory_id,
            title="Reprocess private title",
            content="Old reprocess content",
            version=1,
            project_id="project-secret-reprocess",
            author_id="user-secret-reprocess",
            metadata={"tenant_id": "tenant-secret-reprocess"},
            created_at=datetime.now(UTC),
        )
        mock_memory_repo.find_by_id.return_value = existing_memory
        mock_graphiti_client.add_episode = AsyncMock(side_effect=RuntimeError(exception_detail))
        service = MemoryService(mock_memory_repo, mock_graphiti_client)
        caplog.set_level(logging.ERROR, logger="src.application.services.memory_service")

        with pytest.raises(RuntimeError):
            await service.update_memory(memory_id=secret_memory_id, content=secret_content)

        assert secret_memory_id not in caplog.text
        assert secret_content not in caplog.text
        assert exception_detail not in caplog.text
        assert "error_type=RuntimeError" in caplog.text

    async def test_update_memory_content_unchanged_does_not_reprocess(
        self, mock_memory_repo, mock_graphiti_client
    ):
        """Test metadata-only updates skip graph reprocessing."""
        # Arrange
        service = MemoryService(mock_memory_repo, mock_graphiti_client)
        memory_id = "memory-1"

        existing_memory = Memory(
            id=memory_id,
            title="Title",
            content="Content",
            project_id="project-1",
            author_id="user-1",
            processing_status=ProcessingStatus.COMPLETED.value,
            metadata={"tenant_id": "tenant-1"},
            created_at=datetime.now(UTC),
        )

        mock_memory_repo.find_by_id.return_value = existing_memory

        result = await service.update_memory(memory_id=memory_id, metadata={"category": "note"})

        assert result.metadata["category"] == "note"
        assert result.processing_status == ProcessingStatus.COMPLETED.value
        mock_memory_repo.save.assert_awaited_once_with(existing_memory)
        mock_graphiti_client.add_episode.assert_not_awaited()
        mock_graphiti_client.delete_episode_by_memory_id.assert_not_awaited()

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
            created_at=datetime.now(UTC),
        )

        # Mock the canonical memory-id cleanup method.
        mock_graphiti_client.delete_episode_by_memory_id = AsyncMock(return_value=True)

        # Act
        await service.delete_memory(memory_id)

        # Assert
        mock_graphiti_client.delete_episode_by_memory_id.assert_called_once_with(memory_id)
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
            created_at=datetime.now(UTC),
        )

        # Mock canonical graph cleanup to raise an error
        mock_graphiti_client.delete_episode_by_memory_id = AsyncMock(
            side_effect=Exception("Graph deletion failed")
        )

        # Act - should not raise, should continue with DB deletion
        await service.delete_memory(memory_id)

        # Assert - DB deletion should still happen
        mock_memory_repo.delete.assert_called_once_with(memory_id)

    async def test_delete_memory_logs_do_not_include_identifier_on_success(
        self,
        mock_memory_repo,
        mock_graphiti_client,
        caplog,
    ):
        """Successful deletion logs must not expose memory IDs."""
        service = MemoryService(mock_memory_repo, mock_graphiti_client)
        secret_memory_id = "memory-delete-secret-alpha"
        mock_memory_repo.find_by_id.return_value = Memory(
            id=secret_memory_id,
            title="Private title",
            content="Private content",
            version=1,
            project_id="project-delete-secret",
            author_id="user-delete-secret",
            created_at=datetime.now(UTC),
        )
        mock_graphiti_client.delete_episode_by_memory_id = AsyncMock(return_value=True)
        caplog.set_level(logging.INFO, logger="src.application.services.memory_service")

        await service.delete_memory(secret_memory_id)

        assert secret_memory_id not in caplog.text
        assert "Removed graph state with proper cleanup" in caplog.text
        assert "Deleted memory" in caplog.text

    async def test_delete_memory_graph_failure_logs_do_not_include_identifier_or_error_text(
        self,
        mock_memory_repo,
        mock_graphiti_client,
        caplog,
    ):
        """Graph cleanup failure logs must not expose memory IDs or backend error text."""
        service = MemoryService(mock_memory_repo, mock_graphiti_client)
        secret_memory_id = "memory-delete-secret-beta"
        exception_detail = "neo4j delete failed for hidden memory theta-4912"
        mock_memory_repo.find_by_id.return_value = Memory(
            id=secret_memory_id,
            title="Private title",
            content="Private content",
            version=1,
            project_id="project-delete-secret",
            author_id="user-delete-secret",
            created_at=datetime.now(UTC),
        )
        mock_graphiti_client.delete_episode_by_memory_id = AsyncMock(
            side_effect=RuntimeError(exception_detail)
        )
        caplog.set_level(logging.WARNING, logger="src.application.services.memory_service")

        await service.delete_memory(secret_memory_id)

        assert secret_memory_id not in caplog.text
        assert exception_detail not in caplog.text
        assert "error_type=RuntimeError" in caplog.text
        mock_memory_repo.delete.assert_called_once_with(secret_memory_id)

    async def test_create_memory_persists_system_metadata(
        self, mock_memory_repo, mock_graphiti_client
    ):
        """Service-created memories should retain routing metadata for later reprocessing."""
        service = MemoryService(mock_memory_repo, mock_graphiti_client)
        mock_memory_repo.save = AsyncMock()
        mock_graphiti_client.add_episode = AsyncMock()

        memory = await service.create_memory(
            title="Test Memory",
            content="Remember this",
            project_id="project-1",
            user_id="user-1",
            tenant_id="tenant-1",
            metadata={"category": "fact"},
        )

        assert memory.metadata["tenant_id"] == "tenant-1"
        assert memory.metadata["project_id"] == "project-1"
        assert memory.metadata["user_id"] == "user-1"
        assert memory.metadata["category"] == "fact"

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
            created_at=datetime.now(UTC),
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

    async def test_search_memories_failure_logs_do_not_include_query_or_exception_content(
        self,
        mock_memory_repo,
        mock_graphiti_client,
        caplog,
    ):
        """Search failure logs must not expose query or backend exception text."""
        secret_query = "find customer memory token alpha-2468"
        exception_detail = "graph search leaked private payload beta-1357"
        service = MemoryService(mock_memory_repo, mock_graphiti_client)
        mock_graphiti_client.search = AsyncMock(side_effect=RuntimeError(exception_detail))
        caplog.set_level(logging.ERROR, logger="src.application.services.memory_service")

        with pytest.raises(RuntimeError):
            await service.search_memories(query=secret_query, project_id="project-1", limit=7)

        assert secret_query not in caplog.text
        assert exception_detail not in caplog.text
        assert "query_len=37" in caplog.text
        assert "limit=7" in caplog.text
        assert "error_type=RuntimeError" in caplog.text

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
            created_at=datetime.now(UTC),
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
            created_at=datetime.now(UTC),
        )

        # Act - signature is (memory_id, collaborators)
        await service.share_memory(memory_id=memory_id, collaborators=[project_id])

        # Assert - calls save() not update()
        mock_memory_repo.save.assert_called_once()

    async def test_share_memory_skips_duplicate_collaborators(self, mock_memory_repo):
        """Test sharing memory does not duplicate existing collaborators."""
        service = MemoryService(mock_memory_repo, Mock())
        memory_id = "memory-1"

        existing_memory = Memory(
            id=memory_id,
            title="Memory",
            content="Content",
            version=1,
            project_id="project-1",
            author_id="user-1",
            collaborators=["user-2"],
            created_at=datetime.now(UTC),
        )
        mock_memory_repo.find_by_id.return_value = existing_memory

        result = await service.share_memory(memory_id=memory_id, collaborators=["user-2", "user-3"])

        assert result.collaborators == ["user-2", "user-3"]
        assert result.updated_at is not None
        mock_memory_repo.save.assert_called_once_with(existing_memory)

    async def test_share_memory_logs_do_not_include_identifiers(
        self,
        mock_memory_repo,
        caplog,
    ):
        """Share logs must not expose memory or collaborator IDs."""
        service = MemoryService(mock_memory_repo, Mock())
        secret_memory_id = "memory-share-secret"
        secret_collaborator_id = "user-share-secret"
        existing_memory = Memory(
            id=secret_memory_id,
            title="Memory",
            content="Content",
            version=1,
            project_id="project-share-secret",
            author_id="user-share-author",
            collaborators=[],
            created_at=datetime.now(UTC),
        )
        mock_memory_repo.find_by_id.return_value = existing_memory
        caplog.set_level(logging.INFO, logger="src.application.services.memory_service")

        result = await service.share_memory(
            memory_id=secret_memory_id,
            collaborators=[secret_collaborator_id],
        )

        assert result.collaborators == [secret_collaborator_id]
        assert secret_memory_id not in caplog.text
        assert secret_collaborator_id not in caplog.text
        assert "collaborator_count=1" in caplog.text

    async def test_share_memory_not_found(self, mock_memory_repo):
        """Test sharing a missing memory raises a clear error."""
        service = MemoryService(mock_memory_repo, Mock())
        mock_memory_repo.find_by_id.return_value = None

        with pytest.raises(ValueError, match="Memory memory-1 not found"):
            await service.share_memory(memory_id="memory-1", collaborators=["user-2"])

        mock_memory_repo.save.assert_not_called()
