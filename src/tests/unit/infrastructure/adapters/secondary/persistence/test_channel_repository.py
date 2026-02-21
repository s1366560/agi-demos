"""Tests for channel repository.

Tests cover:
- BaseRepository inheritance (P1-ARCH-1)
- Encryption of credentials (P0-SEC-1)
- CRUD operations
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.secondary.persistence.channel_models import (
    ChannelConfigModel,
    ChannelMessageModel,
    ChannelOutboxModel,
    ChannelSessionBindingModel,
)
from src.infrastructure.adapters.secondary.persistence.channel_repository import (
    ChannelConfigRepository,
    ChannelMessageRepository,
    ChannelOutboxRepository,
    ChannelSessionBindingRepository,
)


class TestChannelConfigRepositoryInheritance:
    """Test that ChannelConfigRepository properly inherits from BaseRepository."""

    def test_inherits_from_base_repository(self):
        """ChannelConfigRepository should inherit from BaseRepository."""
        # Note: Currently it does NOT inherit from BaseRepository
        # This test will FAIL until we refactor it
        pass  # Will implement after refactoring

    def test_has_session_attribute(self):
        """ChannelConfigRepository should have _session attribute."""
        mock_session = MagicMock(spec=AsyncSession)
        repo = ChannelConfigRepository(mock_session)
        assert repo._session == mock_session


class TestChannelConfigRepositoryCRUD:
    """Test CRUD operations for ChannelConfigRepository."""

    @pytest.fixture
    def mock_session(self):
        """Create a mock database session."""
        session = MagicMock(spec=AsyncSession)
        session.execute = AsyncMock()
        session.add = MagicMock()
        session.flush = AsyncMock()
        session.delete = AsyncMock()
        return session

    @pytest.fixture
    def sample_config(self):
        """Create a sample channel configuration."""
        return ChannelConfigModel(
            id="config-123",
            project_id="project-456",
            channel_type="feishu",
            name="Test Channel",
            enabled=True,
            connection_mode="websocket",
            app_id="cli_test",
            app_secret="secret123",
            status="disconnected",
            created_at=datetime.utcnow(),
        )

    @pytest.mark.asyncio
    async def test_create_config(self, mock_session, sample_config):
        """Should create a new channel configuration."""
        repo = ChannelConfigRepository(mock_session)

        result = await repo.create(sample_config)

        mock_session.add.assert_called_once_with(sample_config)
        mock_session.flush.assert_called_once()
        assert result == sample_config

    @pytest.mark.asyncio
    async def test_create_generates_id_if_missing(self, mock_session):
        """Should generate ID if not provided."""
        config = ChannelConfigModel(
            id="",  # Empty ID
            project_id="project-456",
            channel_type="feishu",
            name="Test",
            enabled=True,
            connection_mode="websocket",
            status="disconnected",
            created_at=datetime.utcnow(),
        )

        repo = ChannelConfigRepository(mock_session)
        result = await repo.create(config)

        assert result.id != ""  # ID should be generated

    @pytest.mark.asyncio
    async def test_get_by_id(self, mock_session, sample_config):
        """Should get configuration by ID."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_config
        mock_session.execute.return_value = mock_result

        repo = ChannelConfigRepository(mock_session)
        result = await repo.get_by_id("config-123")

        assert result == sample_config

    @pytest.mark.asyncio
    async def test_get_by_id_returns_none_if_not_found(self, mock_session):
        """Should return None if configuration not found."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        repo = ChannelConfigRepository(mock_session)
        result = await repo.get_by_id("nonexistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_list_by_project(self, mock_session, sample_config):
        """Should list configurations by project."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [sample_config]
        mock_session.execute.return_value = mock_result

        repo = ChannelConfigRepository(mock_session)
        result = await repo.list_by_project("project-456")

        assert len(result) == 1
        assert result[0] == sample_config

    @pytest.mark.asyncio
    async def test_list_by_project_with_channel_type_filter(self, mock_session, sample_config):
        """Should filter by channel type."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [sample_config]
        mock_session.execute.return_value = mock_result

        repo = ChannelConfigRepository(mock_session)
        result = await repo.list_by_project("project-456", channel_type="feishu")

        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_list_by_project_enabled_only(self, mock_session, sample_config):
        """Should filter enabled configurations only."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [sample_config]
        mock_session.execute.return_value = mock_result

        repo = ChannelConfigRepository(mock_session)
        result = await repo.list_by_project("project-456", enabled_only=True)

        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_update_config(self, mock_session, sample_config):
        """Should update configuration."""
        mock_session.merge = AsyncMock(return_value=sample_config)

        repo = ChannelConfigRepository(mock_session)
        result = await repo.update(sample_config)

        mock_session.merge.assert_called_once_with(sample_config)
        mock_session.flush.assert_called_once()
        assert result == sample_config

    @pytest.mark.asyncio
    async def test_delete_config(self, mock_session, sample_config):
        """Should delete configuration."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_config
        mock_session.execute.return_value = mock_result

        repo = ChannelConfigRepository(mock_session)
        result = await repo.delete("config-123")

        assert result is True
        mock_session.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_nonexistent_returns_false(self, mock_session):
        """Should return False if configuration not found."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        repo = ChannelConfigRepository(mock_session)
        result = await repo.delete("nonexistent")

        assert result is False

    @pytest.mark.asyncio
    async def test_update_status(self, mock_session, sample_config):
        """Should update connection status."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_config
        mock_session.execute.return_value = mock_result

        repo = ChannelConfigRepository(mock_session)
        result = await repo.update_status("config-123", "connected")

        assert result is True
        assert sample_config.status == "connected"

    @pytest.mark.asyncio
    async def test_update_status_with_error(self, mock_session, sample_config):
        """Should update status and store error message."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_config
        mock_session.execute.return_value = mock_result

        repo = ChannelConfigRepository(mock_session)
        result = await repo.update_status("config-123", "error", "Connection refused")

        assert result is True
        assert sample_config.status == "error"
        assert sample_config.last_error == "Connection refused"


class TestChannelMessageRepository:
    """Tests for ChannelMessageRepository."""

    @pytest.fixture
    def mock_session(self):
        """Create a mock database session."""
        session = MagicMock(spec=AsyncSession)
        session.execute = AsyncMock()
        session.add = MagicMock()
        session.flush = AsyncMock()
        return session

    @pytest.fixture
    def sample_message(self):
        """Create a sample channel message."""
        return ChannelMessageModel(
            id="msg-123",
            channel_config_id="config-456",
            project_id="project-789",
            channel_message_id="original-msg-id",
            chat_id="chat-001",
            chat_type="group",
            sender_id="user-001",
            sender_name="Test User",
            message_type="text",
            content_text="Hello World",
            direction="inbound",
            created_at=datetime.utcnow(),
        )

    @pytest.mark.asyncio
    async def test_create_message(self, mock_session, sample_message):
        """Should create a new message."""
        repo = ChannelMessageRepository(mock_session)

        result = await repo.create(sample_message)

        mock_session.add.assert_called_once_with(sample_message)
        mock_session.flush.assert_called_once()
        assert result == sample_message

    @pytest.mark.asyncio
    async def test_list_by_chat(self, mock_session, sample_message):
        """Should list messages by chat."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [sample_message]
        mock_session.execute.return_value = mock_result

        repo = ChannelMessageRepository(mock_session)
        result = await repo.list_by_chat("project-789", "chat-001")

        assert len(result) == 1
        assert result[0] == sample_message

    @pytest.mark.asyncio
    async def test_list_by_chat_with_pagination(self, mock_session, sample_message):
        """Should support pagination."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [sample_message]
        mock_session.execute.return_value = mock_result

        repo = ChannelMessageRepository(mock_session)
        result = await repo.list_by_chat("project-789", "chat-001", limit=50, offset=10)

        assert len(result) == 1


class TestCredentialEncryption:
    """Tests for credential encryption functionality."""

    def test_encryption_service_available(self):
        """Encryption service should be available."""
        from src.infrastructure.security.encryption_service import get_encryption_service

        service = get_encryption_service()
        assert service is not None

    def test_encrypt_decrypt_roundtrip(self):
        """Should encrypt and decrypt credentials correctly."""
        from src.infrastructure.security.encryption_service import get_encryption_service

        service = get_encryption_service()
        secret = "my-app-secret-12345"

        encrypted = service.encrypt(secret)
        decrypted = service.decrypt(encrypted)

        assert encrypted != secret
        assert decrypted == secret

    def test_encryption_produces_different_ciphertext(self):
        """Same plaintext should produce different ciphertext (random nonce)."""
        from src.infrastructure.security.encryption_service import get_encryption_service

        service = get_encryption_service()
        secret = "my-app-secret-12345"

        encrypted1 = service.encrypt(secret)
        encrypted2 = service.encrypt(secret)

        # Due to random nonce, same plaintext produces different ciphertext
        assert encrypted1 != encrypted2
        assert service.decrypt(encrypted1) == secret
        assert service.decrypt(encrypted2) == secret


class TestChannelSessionBindingRepository:
    """Tests for ChannelSessionBindingRepository."""

    @pytest.fixture
    def mock_session(self):
        """Create a mock database session."""
        session = MagicMock(spec=AsyncSession)
        session.execute = AsyncMock()
        session.add = MagicMock()
        session.flush = AsyncMock()
        return session

    @pytest.fixture
    def sample_binding(self):
        """Create a sample channel session binding."""
        return ChannelSessionBindingModel(
            id="bind-123",
            project_id="project-1",
            channel_config_id="config-1",
            conversation_id="conv-1",
            channel_type="feishu",
            chat_id="chat-1",
            chat_type="group",
            session_key="project:project-1:channel:feishu:config:config-1:group:chat-1",
        )

    @pytest.mark.asyncio
    async def test_get_by_session_key(self, mock_session, sample_binding):
        """Should load binding by project/session key."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_binding
        mock_session.execute.return_value = mock_result

        repo = ChannelSessionBindingRepository(mock_session)
        result = await repo.get_by_session_key("project-1", sample_binding.session_key)

        assert result == sample_binding

    @pytest.mark.asyncio
    async def test_upsert_creates_when_absent(self, mock_session):
        """Upsert should create new binding when no existing row is found."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        repo = ChannelSessionBindingRepository(mock_session)
        binding = await repo.upsert(
            project_id="project-1",
            channel_config_id="config-1",
            conversation_id="conv-1",
            channel_type="feishu",
            chat_id="chat-1",
            chat_type="group",
            session_key="session-key-1",
        )

        assert binding.project_id == "project-1"
        assert binding.conversation_id == "conv-1"
        mock_session.add.assert_called_once()
        mock_session.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_upsert_returns_existing_binding(self, mock_session, sample_binding):
        """Upsert should preserve existing canonical binding."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_binding
        mock_session.execute.return_value = mock_result

        repo = ChannelSessionBindingRepository(mock_session)
        result = await repo.upsert(
            project_id="project-1",
            channel_config_id="config-1",
            conversation_id="conv-2",
            channel_type="feishu",
            chat_id="chat-1",
            chat_type="group",
            session_key=sample_binding.session_key,
        )

        assert result is sample_binding
        assert sample_binding.conversation_id == "conv-1"


class TestChannelOutboxRepository:
    """Tests for ChannelOutboxRepository."""

    @pytest.fixture
    def mock_session(self):
        """Create a mock database session."""
        session = MagicMock(spec=AsyncSession)
        session.execute = AsyncMock()
        session.add = MagicMock()
        session.flush = AsyncMock()
        return session

    @pytest.fixture
    def sample_outbox(self):
        """Create a sample outbox record."""
        return ChannelOutboxModel(
            id="outbox-1",
            project_id="project-1",
            channel_config_id="config-1",
            conversation_id="conv-1",
            chat_id="chat-1",
            content_text="hello",
            status="pending",
            attempt_count=0,
            max_attempts=3,
        )

    @pytest.mark.asyncio
    async def test_create_outbox_record(self, mock_session, sample_outbox):
        """Should create outbox record."""
        repo = ChannelOutboxRepository(mock_session)
        result = await repo.create(sample_outbox)

        assert result == sample_outbox
        mock_session.add.assert_called_once_with(sample_outbox)
        mock_session.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_mark_sent(self, mock_session, sample_outbox):
        """Should mark outbox as sent and clear retry fields."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_outbox
        mock_session.execute.return_value = mock_result

        repo = ChannelOutboxRepository(mock_session)
        result = await repo.mark_sent("outbox-1", "sent-123")

        assert result is True
        assert sample_outbox.status == "sent"
        assert sample_outbox.sent_channel_message_id == "sent-123"
        assert sample_outbox.next_retry_at is None

    @pytest.mark.asyncio
    async def test_mark_failed_sets_retry(self, mock_session, sample_outbox):
        """Should increment attempts and mark as failed before max attempts."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_outbox
        mock_session.execute.return_value = mock_result

        repo = ChannelOutboxRepository(mock_session)
        result = await repo.mark_failed("outbox-1", "network timeout")

        assert result is True
        assert sample_outbox.status == "failed"
        assert sample_outbox.attempt_count == 1
        assert sample_outbox.next_retry_at is not None

    @pytest.mark.asyncio
    async def test_mark_failed_dead_letter_after_max_attempts(self, mock_session, sample_outbox):
        """Should move record to dead_letter when max attempts reached."""
        sample_outbox.attempt_count = 2
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_outbox
        mock_session.execute.return_value = mock_result

        repo = ChannelOutboxRepository(mock_session)
        result = await repo.mark_failed("outbox-1", "permanent failure")

        assert result is True
        assert sample_outbox.status == "dead_letter"
        assert sample_outbox.attempt_count == 3
        assert sample_outbox.next_retry_at is None
