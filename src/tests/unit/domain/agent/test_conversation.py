"""Unit tests for the Conversation domain entity."""

from datetime import datetime

from src.domain.model.agent import (
    Conversation,
    ConversationStatus,
)


class TestConversation:
    """Test Conversation domain entity behavior."""

    def test_create_conversation_with_defaults(self):
        """Test creating a conversation with default values."""
        conversation = Conversation(
            id="conv-1",
            project_id="proj-1",
            tenant_id="tenant-1",
            user_id="user-1",
            title="New Conversation",
        )

        assert conversation.id == "conv-1"
        assert conversation.project_id == "proj-1"
        assert conversation.tenant_id == "tenant-1"
        assert conversation.user_id == "user-1"
        assert conversation.title == "New Conversation"
        assert conversation.status == ConversationStatus.ACTIVE
        assert conversation.agent_config == {}
        assert conversation.metadata == {}
        assert conversation.message_count == 0
        assert isinstance(conversation.created_at, datetime)

    def test_create_conversation_with_custom_values(self):
        """Test creating a conversation with custom values."""
        custom_config = {"model": "gpt-4", "temperature": 0.7}
        custom_meta = {"source": "web"}
        conversation = Conversation(
            id="conv-1",
            project_id="proj-1",
            tenant_id="tenant-1",
            user_id="user-1",
            title="My Conversation",
            status=ConversationStatus.ACTIVE,
            agent_config=custom_config,
            metadata=custom_meta,
            message_count=5,
        )

        assert conversation.title == "My Conversation"
        assert conversation.status == ConversationStatus.ACTIVE
        assert conversation.agent_config == custom_config
        assert conversation.metadata == custom_meta
        assert conversation.message_count == 5

    def test_archive_conversation(self):
        """Test archiving a conversation."""
        conversation = Conversation(
            id="conv-1",
            project_id="proj-1",
            tenant_id="tenant-1",
            user_id="user-1",
            title="Test",
            status=ConversationStatus.ACTIVE,
        )

        conversation.archive()

        assert conversation.status == ConversationStatus.ARCHIVED
        assert conversation.updated_at is not None

    def test_delete_conversation(self):
        """Test deleting a conversation."""
        conversation = Conversation(
            id="conv-1",
            project_id="proj-1",
            tenant_id="tenant-1",
            user_id="user-1",
            title="Test",
            status=ConversationStatus.ACTIVE,
        )

        conversation.delete()
        assert conversation.status == ConversationStatus.DELETED

    def test_increment_message_count(self):
        """Test incrementing message count."""
        conversation = Conversation(
            id="conv-1",
            project_id="proj-1",
            tenant_id="tenant-1",
            user_id="user-1",
            title="Test",
            message_count=0,
        )

        conversation.increment_message_count()
        assert conversation.message_count == 1

        conversation.increment_message_count()
        assert conversation.message_count == 2

    def test_update_agent_config(self):
        """Test updating agent configuration."""
        conversation = Conversation(
            id="conv-1",
            project_id="proj-1",
            tenant_id="tenant-1",
            user_id="user-1",
            title="Test",
            agent_config={"model": "gpt-3.5"},
        )

        new_config = {"temperature": 0.5}
        conversation.update_agent_config(new_config)

        assert conversation.agent_config == {"model": "gpt-3.5", "temperature": 0.5}
        assert conversation.updated_at is not None
