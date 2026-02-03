"""
Tests for V2 SqlConversationRepository using BaseRepository.

TDD Approach: RED -> GREEN -> REFACTOR

These tests verify that the migrated repository maintains 100% compatibility
with the original implementation while leveraging the BaseRepository.

Key features tested:
- Upsert operations (PostgreSQL ON CONFLICT)
- save_and_commit for SSE streaming
- List by project/user with filters
- Count operations
- Delete operations
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent import Conversation, ConversationStatus
from src.domain.model.agent.agent_mode import AgentMode
from src.infrastructure.adapters.secondary.persistence.models import Conversation as DBConversation
from src.infrastructure.adapters.secondary.persistence.v2_sql_conversation_repository import (
    V2SqlConversationRepository,
)


@pytest.fixture
async def v2_conversation_repo(db_session: AsyncSession) -> V2SqlConversationRepository:
    """Create a V2 conversation repository for testing."""
    return V2SqlConversationRepository(db_session)


class TestV2SqlConversationRepositorySave:
    """Tests for save/upsert operations."""

    @pytest.mark.asyncio
    async def test_save_new_conversation(self, v2_conversation_repo: V2SqlConversationRepository):
        """Test saving a new conversation."""
        conversation = Conversation(
            id="conv-test-1",
            project_id="proj-1",
            tenant_id="tenant-1",
            user_id="user-1",
            title="Test Conversation",
            status=ConversationStatus.ACTIVE,
            agent_config={"model": "gpt-4"},
            metadata={"key": "value"},
            message_count=0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            current_mode=AgentMode.BUILD,
        )

        await v2_conversation_repo.save(conversation)

        # Verify conversation was saved
        retrieved = await v2_conversation_repo.find_by_id("conv-test-1")
        assert retrieved is not None
        assert retrieved.id == "conv-test-1"
        assert retrieved.title == "Test Conversation"
        assert retrieved.status == ConversationStatus.ACTIVE
        assert retrieved.current_mode == AgentMode.BUILD

    @pytest.mark.asyncio
    async def test_save_upsert_existing_conversation(self, v2_conversation_repo: V2SqlConversationRepository):
        """Test upserting an existing conversation."""
        # Create initial conversation
        conversation = Conversation(
            id="conv-upsert-1",
            project_id="proj-1",
            tenant_id="tenant-1",
            user_id="user-1",
            title="Original Title",
            status=ConversationStatus.ACTIVE,
            agent_config={},
            metadata={},
            message_count=0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            current_mode=AgentMode.BUILD,
        )
        await v2_conversation_repo.save(conversation)

        # Upsert with updated data
        updated_conversation = Conversation(
            id="conv-upsert-1",
            project_id="proj-1",
            tenant_id="tenant-1",
            user_id="user-1",
            title="Updated Title",
            status=ConversationStatus.ARCHIVED,
            agent_config={"new": True},
            metadata={"updated": True},
            message_count=5,
            created_at=conversation.created_at,
            updated_at=datetime.now(timezone.utc),
            current_mode=AgentMode.PLAN,
        )
        await v2_conversation_repo.save(updated_conversation)

        # Verify updates
        retrieved = await v2_conversation_repo.find_by_id("conv-upsert-1")
        assert retrieved.title == "Updated Title"
        assert retrieved.status == ConversationStatus.ARCHIVED
        assert retrieved.message_count == 5
        assert retrieved.current_mode == AgentMode.PLAN

    @pytest.mark.asyncio
    async def test_save_and_commit(self, v2_conversation_repo: V2SqlConversationRepository):
        """Test save_and_commit immediately commits to database."""
        conversation = Conversation(
            id="conv-commit-1",
            project_id="proj-1",
            tenant_id="tenant-1",
            user_id="user-1",
            title="Commit Test",
            status=ConversationStatus.ACTIVE,
            agent_config={},
            metadata={},
            message_count=0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            current_mode=AgentMode.BUILD,
        )

        await v2_conversation_repo.save_and_commit(conversation)

        # Verify committed (new query should find it)
        retrieved = await v2_conversation_repo.find_by_id("conv-commit-1")
        assert retrieved is not None
        assert retrieved.title == "Commit Test"


class TestV2SqlConversationRepositoryFind:
    """Tests for finding conversations."""

    @pytest.mark.asyncio
    async def test_find_by_id_existing(self, v2_conversation_repo: V2SqlConversationRepository):
        """Test finding an existing conversation by ID."""
        conversation = Conversation(
            id="conv-find-1",
            project_id="proj-1",
            tenant_id="tenant-1",
            user_id="user-1",
            title="Find Me",
            status=ConversationStatus.ACTIVE,
            agent_config={},
            metadata={},
            message_count=0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            current_mode=AgentMode.BUILD,
        )
        await v2_conversation_repo.save(conversation)

        retrieved = await v2_conversation_repo.find_by_id("conv-find-1")
        assert retrieved is not None
        assert retrieved.id == "conv-find-1"
        assert retrieved.title == "Find Me"

    @pytest.mark.asyncio
    async def test_find_by_id_not_found(self, v2_conversation_repo: V2SqlConversationRepository):
        """Test finding a non-existent conversation returns None."""
        retrieved = await v2_conversation_repo.find_by_id("non-existent")
        assert retrieved is None


class TestV2SqlConversationRepositoryList:
    """Tests for listing conversations."""

    @pytest.mark.asyncio
    async def test_list_by_project(self, v2_conversation_repo: V2SqlConversationRepository):
        """Test listing conversations by project."""
        # Create conversations for different projects
        for i in range(3):
            conversation = Conversation(
                id=f"conv-proj-1-{i}",
                project_id="proj-1",
                tenant_id="tenant-1",
                user_id="user-1",
                title=f"Project 1 Conv {i}",
                status=ConversationStatus.ACTIVE,
                agent_config={},
                metadata={},
                message_count=0,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
                current_mode=AgentMode.BUILD,
            )
            await v2_conversation_repo.save(conversation)

        # Add conversation for different project
        other_conv = Conversation(
            id="conv-proj-2",
            project_id="proj-2",
            tenant_id="tenant-1",
            user_id="user-1",
            title="Other Project",
            status=ConversationStatus.ACTIVE,
            agent_config={},
            metadata={},
            message_count=0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            current_mode=AgentMode.BUILD,
        )
        await v2_conversation_repo.save(other_conv)

        # List proj-1 conversations
        conversations = await v2_conversation_repo.list_by_project("proj-1")
        assert len(conversations) == 3
        assert all(c.project_id == "proj-1" for c in conversations)

    @pytest.mark.asyncio
    async def test_list_by_project_with_status_filter(self, v2_conversation_repo: V2SqlConversationRepository):
        """Test listing conversations by project with status filter."""
        # Create conversations with different statuses
        active_conv = Conversation(
            id="conv-active",
            project_id="proj-filter",
            tenant_id="tenant-1",
            user_id="user-1",
            title="Active",
            status=ConversationStatus.ACTIVE,
            agent_config={},
            metadata={},
            message_count=0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            current_mode=AgentMode.BUILD,
        )
        await v2_conversation_repo.save(active_conv)

        archived_conv = Conversation(
            id="conv-archived",
            project_id="proj-filter",
            tenant_id="tenant-1",
            user_id="user-1",
            title="Archived",
            status=ConversationStatus.ARCHIVED,
            agent_config={},
            metadata={},
            message_count=0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            current_mode=AgentMode.BUILD,
        )
        await v2_conversation_repo.save(archived_conv)

        # List only active conversations
        active_convs = await v2_conversation_repo.list_by_project(
            "proj-filter", status=ConversationStatus.ACTIVE
        )
        assert len(active_convs) == 1
        assert active_convs[0].status == ConversationStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_list_by_project_with_pagination(self, v2_conversation_repo: V2SqlConversationRepository):
        """Test listing conversations by project with pagination."""
        # Create 5 conversations
        for i in range(5):
            conversation = Conversation(
                id=f"conv-page-{i}",
                project_id="proj-page",
                tenant_id="tenant-1",
                user_id="user-1",
                title=f"Conv {i}",
                status=ConversationStatus.ACTIVE,
                agent_config={},
                metadata={},
                message_count=0,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
                current_mode=AgentMode.BUILD,
            )
            await v2_conversation_repo.save(conversation)

        # Get first page
        page1 = await v2_conversation_repo.list_by_project("proj-page", limit=2, offset=0)
        assert len(page1) == 2

        # Get second page
        page2 = await v2_conversation_repo.list_by_project("proj-page", limit=2, offset=2)
        assert len(page2) == 2

    @pytest.mark.asyncio
    async def test_list_by_user(self, v2_conversation_repo: V2SqlConversationRepository):
        """Test listing conversations by user."""
        # Create conversations for different users
        for i in range(3):
            conversation = Conversation(
                id=f"conv-user-1-{i}",
                project_id="proj-1",
                tenant_id="tenant-1",
                user_id="user-1",
                title=f"User 1 Conv {i}",
                status=ConversationStatus.ACTIVE,
                agent_config={},
                metadata={},
                message_count=0,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
                current_mode=AgentMode.BUILD,
            )
            await v2_conversation_repo.save(conversation)

        # Add conversation for different user
        other_conv = Conversation(
            id="conv-user-2",
            project_id="proj-1",
            tenant_id="tenant-1",
            user_id="user-2",
            title="Other User",
            status=ConversationStatus.ACTIVE,
            agent_config={},
            metadata={},
            message_count=0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            current_mode=AgentMode.BUILD,
        )
        await v2_conversation_repo.save(other_conv)

        # List user-1 conversations
        conversations = await v2_conversation_repo.list_by_user("user-1")
        assert len(conversations) == 3
        assert all(c.user_id == "user-1" for c in conversations)

    @pytest.mark.asyncio
    async def test_list_by_user_with_project_filter(self, v2_conversation_repo: V2SqlConversationRepository):
        """Test listing conversations by user with project filter."""
        # Create conversations for different projects
        conv1 = Conversation(
            id="conv-user-proj-1",
            project_id="proj-A",
            tenant_id="tenant-1",
            user_id="user-filter",
            title="User Proj A",
            status=ConversationStatus.ACTIVE,
            agent_config={},
            metadata={},
            message_count=0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            current_mode=AgentMode.BUILD,
        )
        await v2_conversation_repo.save(conv1)

        conv2 = Conversation(
            id="conv-user-proj-2",
            project_id="proj-B",
            tenant_id="tenant-1",
            user_id="user-filter",
            title="User Proj B",
            status=ConversationStatus.ACTIVE,
            agent_config={},
            metadata={},
            message_count=0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            current_mode=AgentMode.BUILD,
        )
        await v2_conversation_repo.save(conv2)

        # List only for proj-A
        conversations = await v2_conversation_repo.list_by_user("user-filter", project_id="proj-A")
        assert len(conversations) == 1
        assert conversations[0].project_id == "proj-A"


class TestV2SqlConversationRepositoryDelete:
    """Tests for deleting conversations."""

    @pytest.mark.asyncio
    async def test_delete_conversation(self, v2_conversation_repo: V2SqlConversationRepository):
        """Test deleting a conversation by ID."""
        conversation = Conversation(
            id="conv-delete-1",
            project_id="proj-1",
            tenant_id="tenant-1",
            user_id="user-1",
            title="Delete Me",
            status=ConversationStatus.ACTIVE,
            agent_config={},
            metadata={},
            message_count=0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            current_mode=AgentMode.BUILD,
        )
        await v2_conversation_repo.save(conversation)

        # Delete
        await v2_conversation_repo.delete("conv-delete-1")

        # Verify deleted
        retrieved = await v2_conversation_repo.find_by_id("conv-delete-1")
        assert retrieved is None


class TestV2SqlConversationRepositoryCount:
    """Tests for counting conversations."""

    @pytest.mark.asyncio
    async def test_count_by_project(self, v2_conversation_repo: V2SqlConversationRepository):
        """Test counting conversations by project."""
        # Initially empty
        count = await v2_conversation_repo.count_by_project("proj-count")
        assert count == 0

        # Add conversations
        for i in range(3):
            conversation = Conversation(
                id=f"conv-count-{i}",
                project_id="proj-count",
                tenant_id="tenant-1",
                user_id="user-1",
                title=f"Count {i}",
                status=ConversationStatus.ACTIVE,
                agent_config={},
                metadata={},
                message_count=0,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
                current_mode=AgentMode.BUILD,
            )
            await v2_conversation_repo.save(conversation)

        count = await v2_conversation_repo.count_by_project("proj-count")
        assert count == 3


class TestV2SqlConversationRepositoryToDomain:
    """Tests for _to_domain conversion."""

    @pytest.mark.asyncio
    async def test_to_domain_converts_all_fields(self, v2_conversation_repo: V2SqlConversationRepository):
        """Test that _to_domain correctly converts all DB fields."""
        conversation = Conversation(
            id="conv-domain",
            project_id="proj-1",
            tenant_id="tenant-1",
            user_id="user-1",
            title="Domain Test",
            status=ConversationStatus.ACTIVE,
            agent_config={"model": "gpt-4"},
            metadata={"test": True},
            message_count=5,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            current_mode=AgentMode.PLAN,
            current_plan_id="plan-123",
        )
        await v2_conversation_repo.save(conversation)

        retrieved = await v2_conversation_repo.find_by_id("conv-domain")
        assert retrieved.id == "conv-domain"
        assert retrieved.project_id == "proj-1"
        assert retrieved.title == "Domain Test"
        assert retrieved.status == ConversationStatus.ACTIVE
        assert retrieved.agent_config == {"model": "gpt-4"}
        assert retrieved.metadata == {"test": True}
        assert retrieved.message_count == 5
        assert retrieved.current_mode == AgentMode.PLAN
        assert retrieved.current_plan_id == "plan-123"

    @pytest.mark.asyncio
    async def test_to_domain_with_none_db_model(self, v2_conversation_repo: V2SqlConversationRepository):
        """Test that _to_domain returns None for None input."""
        result = v2_conversation_repo._to_domain(None)
        assert result is None


class TestV2SqlConversationRepositoryToDb:
    """Tests for _to_db conversion."""

    def test_to_db_creates_db_model(self, v2_conversation_repo: V2SqlConversationRepository):
        """Test that _to_db creates a valid DB model."""
        conversation = Conversation(
            id="conv-todb",
            project_id="proj-1",
            tenant_id="tenant-1",
            user_id="user-1",
            title="To DB Test",
            status=ConversationStatus.ACTIVE,
            agent_config={},
            metadata={},
            message_count=0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            current_mode=AgentMode.BUILD,
        )

        db_model = v2_conversation_repo._to_db(conversation)
        assert isinstance(db_model, DBConversation)
        assert db_model.id == "conv-todb"
        assert db_model.project_id == "proj-1"
        assert db_model.title == "To DB Test"


class TestV2SqlConversationRepositoryTransaction:
    """Tests for transaction support."""

    @pytest.mark.asyncio
    async def test_transaction_context_manager(self, v2_conversation_repo: V2SqlConversationRepository):
        """Test using transaction context manager."""
        async with v2_conversation_repo.transaction():
            conv1 = Conversation(
                id="conv-tx-1",
                project_id="proj-1",
                tenant_id="tenant-1",
                user_id="user-1",
                title="TX 1",
                status=ConversationStatus.ACTIVE,
                agent_config={},
                metadata={},
                message_count=0,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
                current_mode=AgentMode.BUILD,
            )
            await v2_conversation_repo.save(conv1)

            conv2 = Conversation(
                id="conv-tx-2",
                project_id="proj-1",
                tenant_id="tenant-1",
                user_id="user-1",
                title="TX 2",
                status=ConversationStatus.ACTIVE,
                agent_config={},
                metadata={},
                message_count=0,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
                current_mode=AgentMode.BUILD,
            )
            await v2_conversation_repo.save(conv2)

        # Verify both were saved
        c1 = await v2_conversation_repo.find_by_id("conv-tx-1")
        c2 = await v2_conversation_repo.find_by_id("conv-tx-2")
        assert c1 is not None
        assert c2 is not None
