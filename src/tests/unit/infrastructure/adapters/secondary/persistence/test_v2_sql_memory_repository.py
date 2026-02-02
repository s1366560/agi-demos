"""
Tests for V2 SqlMemoryRepository using BaseRepository.
"""

import pytest
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.memory.memory import Memory
from src.infrastructure.adapters.secondary.persistence.models import Memory as DBMemory
from src.infrastructure.adapters.secondary.persistence.v2_sql_memory_repository import (
    V2SqlMemoryRepository,
)


@pytest.fixture
async def v2_memory_repo(v2_db_session: AsyncSession) -> V2SqlMemoryRepository:
    """Create a V2 memory repository for testing."""
    return V2SqlMemoryRepository(v2_db_session)


class TestV2SqlMemoryRepositoryCreate:
    """Tests for creating memories."""

    @pytest.mark.asyncio
    async def test_save_new_memory(self, v2_memory_repo: V2SqlMemoryRepository):
        """Test saving a new memory."""
        memory = Memory(
            id="mem-test-1",
            project_id="proj-1",
            title="Test Memory",
            content="Test content",
            author_id="user-1",
            content_type="text",
            tags=[],
            entities=[],
            relationships=[],
            version=1,
            collaborators=[],
            is_public=False,
            status="enabled",
            processing_status="pending",
            metadata={},
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        await v2_memory_repo.save(memory)

        # Verify memory was saved
        retrieved = await v2_memory_repo.find_by_id("mem-test-1")
        assert retrieved is not None
        assert retrieved.id == "mem-test-1"
        assert retrieved.title == "Test Memory"
        assert retrieved.content == "Test content"

    @pytest.mark.asyncio
    async def test_save_with_tags_and_entities(self, v2_memory_repo: V2SqlMemoryRepository):
        """Test saving a memory with tags and entities."""
        memory = Memory(
            id="mem-tags-1",
            project_id="proj-1",
            title="Tagged Memory",
            content="Content with tags",
            author_id="user-1",
            content_type="text",
            tags=["tag1", "tag2"],
            entities=[{"name": "Entity1", "type": "Person"}],
            relationships=[],
            version=1,
            collaborators=[],
            is_public=False,
            status="enabled",
            processing_status="pending",
            metadata={},
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        await v2_memory_repo.save(memory)

        retrieved = await v2_memory_repo.find_by_id("mem-tags-1")
        assert retrieved.tags == ["tag1", "tag2"]
        assert retrieved.entities == [{"name": "Entity1", "type": "Person"}]


class TestV2SqlMemoryRepositoryUpdate:
    """Tests for updating memories."""

    @pytest.mark.asyncio
    async def test_update_existing_memory(self, v2_memory_repo: V2SqlMemoryRepository):
        """Test updating an existing memory."""
        memory = Memory(
            id="mem-update-1",
            project_id="proj-1",
            title="Original Title",
            content="Original content",
            author_id="user-1",
            content_type="text",
            tags=[],
            entities=[],
            relationships=[],
            version=1,
            collaborators=[],
            is_public=False,
            status="enabled",
            processing_status="pending",
            metadata={},
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await v2_memory_repo.save(memory)

        # Update
        updated = Memory(
            id="mem-update-1",
            project_id="proj-1",
            title="Updated Title",
            content="Updated content",
            author_id="user-1",
            content_type="text",
            tags=["new-tag"],
            entities=[],
            relationships=[],
            version=2,
            collaborators=[],
            is_public=True,
            status="enabled",
            processing_status="completed",
            metadata={"updated": True},
            created_at=memory.created_at,
            updated_at=datetime.now(timezone.utc),
        )
        await v2_memory_repo.save(updated)

        retrieved = await v2_memory_repo.find_by_id("mem-update-1")
        assert retrieved.title == "Updated Title"
        assert retrieved.version == 2
        assert retrieved.is_public is True


class TestV2SqlMemoryRepositoryFind:
    """Tests for finding memories."""

    @pytest.mark.asyncio
    async def test_find_by_id_existing(self, v2_memory_repo: V2SqlMemoryRepository):
        """Test finding an existing memory by ID."""
        memory = Memory(
            id="mem-find-1",
            project_id="proj-1",
            title="Find Me",
            content="Content",
            author_id="user-1",
            content_type="text",
            tags=[],
            entities=[],
            relationships=[],
            version=1,
            collaborators=[],
            is_public=False,
            status="enabled",
            processing_status="pending",
            metadata={},
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await v2_memory_repo.save(memory)

        retrieved = await v2_memory_repo.find_by_id("mem-find-1")
        assert retrieved is not None
        assert retrieved.title == "Find Me"

    @pytest.mark.asyncio
    async def test_find_by_id_not_found(self, v2_memory_repo: V2SqlMemoryRepository):
        """Test finding a non-existent memory returns None."""
        retrieved = await v2_memory_repo.find_by_id("non-existent")
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_list_by_project(self, v2_memory_repo: V2SqlMemoryRepository):
        """Test listing memories for a project."""
        for i in range(3):
            memory = Memory(
                id=f"mem-proj-{i}",
                project_id="proj-list",
                title=f"Memory {i}",
                content=f"Content {i}",
                author_id="user-1",
                content_type="text",
                tags=[],
                entities=[],
                relationships=[],
                version=1,
                collaborators=[],
                is_public=False,
                status="enabled",
                processing_status="pending",
                metadata={},
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            await v2_memory_repo.save(memory)

        memories = await v2_memory_repo.list_by_project("proj-list")
        assert len(memories) == 3

    @pytest.mark.asyncio
    async def test_list_by_project_with_pagination(self, v2_memory_repo: V2SqlMemoryRepository):
        """Test listing memories with pagination."""
        for i in range(5):
            memory = Memory(
                id=f"mem-page-{i}",
                project_id="proj-page",
                title=f"Memory {i}",
                content=f"Content {i}",
                author_id="user-1",
                content_type="text",
                tags=[],
                entities=[],
                relationships=[],
                version=1,
                collaborators=[],
                is_public=False,
                status="enabled",
                processing_status="pending",
                metadata={},
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            await v2_memory_repo.save(memory)

        page1 = await v2_memory_repo.list_by_project("proj-page", limit=2, offset=0)
        assert len(page1) == 2

        page2 = await v2_memory_repo.list_by_project("proj-page", limit=2, offset=2)
        assert len(page2) == 2

        page3 = await v2_memory_repo.list_by_project("proj-page", limit=2, offset=4)
        assert len(page3) == 1


class TestV2SqlMemoryRepositoryDelete:
    """Tests for deleting memories."""

    @pytest.mark.asyncio
    async def test_delete_existing_memory(self, v2_memory_repo: V2SqlMemoryRepository):
        """Test deleting an existing memory."""
        memory = Memory(
            id="mem-delete-1",
            project_id="proj-1",
            title="Delete Me",
            content="Content",
            author_id="user-1",
            content_type="text",
            tags=[],
            entities=[],
            relationships=[],
            version=1,
            collaborators=[],
            is_public=False,
            status="enabled",
            processing_status="pending",
            metadata={},
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await v2_memory_repo.save(memory)

        await v2_memory_repo.delete("mem-delete-1")

        retrieved = await v2_memory_repo.find_by_id("mem-delete-1")
        assert retrieved is None


class TestV2SqlMemoryRepositoryToDomain:
    """Tests for _to_domain conversion."""

    def test_to_domain_with_none(self, v2_memory_repo: V2SqlMemoryRepository):
        """Test that _to_domain returns None for None input."""
        result = v2_memory_repo._to_domain(None)
        assert result is None


class TestV2SqlMemoryRepositoryToDb:
    """Tests for _to_db conversion."""

    def test_to_db_creates_db_model(self, v2_memory_repo: V2SqlMemoryRepository):
        """Test that _to_db creates a valid DB model."""
        memory = Memory(
            id="mem-todb-1",
            project_id="proj-1",
            title="To DB",
            content="Content",
            author_id="user-1",
            content_type="text",
            tags=[],
            entities=[],
            relationships=[],
            version=1,
            collaborators=[],
            is_public=False,
            status="enabled",
            processing_status="pending",
            metadata={},
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        db_model = v2_memory_repo._to_db(memory)
        assert isinstance(db_model, DBMemory)
        assert db_model.id == "mem-todb-1"
        assert db_model.title == "To DB"
