"""Tests for channel database models.

Tests cover:
- Model definitions (P0-IMPL-2)
- Foreign key relationships
- Index constraints
"""

from sqlalchemy import inspect

from src.infrastructure.adapters.secondary.persistence.channel_models import (
    ChannelConfigModel,
    ChannelMessageModel,
    ChannelOutboxModel,
    ChannelSessionBindingModel,
)


class TestChannelConfigModel:
    """Tests for ChannelConfigModel."""

    def test_table_name(self):
        """ChannelConfigModel should have correct table name."""
        assert ChannelConfigModel.__tablename__ == "channel_configs"

    def test_primary_key(self):
        """ChannelConfigModel should have id as primary key."""
        mapper = inspect(ChannelConfigModel)
        pk_columns = [col.key for col in mapper.primary_key]
        assert "id" in pk_columns

    def test_required_fields(self):
        """ChannelConfigModel should have required fields."""
        mapper = inspect(ChannelConfigModel)
        column_names = {col.key for col in mapper.columns}

        required_fields = {
            "id",
            "project_id",
            "channel_type",
            "name",
            "enabled",
            "connection_mode",
            "status",
        }

        for field in required_fields:
            assert field in column_names, f"Missing required field: {field}"

    def test_credential_fields(self):
        """ChannelConfigModel should have credential fields for encryption."""
        mapper = inspect(ChannelConfigModel)
        column_names = {col.key for col in mapper.columns}

        credential_fields = {"app_id", "app_secret", "encrypt_key", "verification_token"}

        for field in credential_fields:
            assert field in column_names, f"Missing credential field: {field}"

    def test_webhook_fields(self):
        """ChannelConfigModel should have webhook configuration fields."""
        mapper = inspect(ChannelConfigModel)
        column_names = {col.key for col in mapper.columns}

        webhook_fields = {"webhook_url", "webhook_port", "webhook_path"}

        for field in webhook_fields:
            assert field in column_names, f"Missing webhook field: {field}"

    def test_has_project_foreign_key(self):
        """ChannelConfigModel should have foreign key to projects."""

        mapper = inspect(ChannelConfigModel)
        fk_columns = []
        for col in mapper.columns:
            for fk in col.foreign_keys:
                fk_columns.append((col.key, fk.target_fullname))

        assert any(
            col == "project_id" and "projects.id" in target
            for col, target in fk_columns
        ), "Missing foreign key to projects.id"

    def test_has_user_foreign_key(self):
        """ChannelConfigModel should have foreign key to users for created_by."""
        mapper = inspect(ChannelConfigModel)
        fk_columns = []
        for col in mapper.columns:
            for fk in col.foreign_keys:
                fk_columns.append((col.key, fk.target_fullname))

        assert any(
            col == "created_by" and "users.id" in target for col, target in fk_columns
        ), "Missing foreign key to users.id"


class TestChannelMessageModel:
    """Tests for ChannelMessageModel."""

    def test_table_name(self):
        """ChannelMessageModel should have correct table name."""
        assert ChannelMessageModel.__tablename__ == "channel_messages"

    def test_primary_key(self):
        """ChannelMessageModel should have id as primary key."""
        mapper = inspect(ChannelMessageModel)
        pk_columns = [col.key for col in mapper.primary_key]
        assert "id" in pk_columns

    def test_required_fields(self):
        """ChannelMessageModel should have required fields."""
        mapper = inspect(ChannelMessageModel)
        column_names = {col.key for col in mapper.columns}

        required_fields = {
            "id",
            "channel_config_id",
            "project_id",
            "channel_message_id",
            "chat_id",
            "chat_type",
            "sender_id",
            "message_type",
            "direction",
        }

        for field in required_fields:
            assert field in column_names, f"Missing required field: {field}"

    def test_has_channel_config_foreign_key(self):
        """ChannelMessageModel should have foreign key to channel_configs."""
        mapper = inspect(ChannelMessageModel)
        fk_columns = []
        for col in mapper.columns:
            for fk in col.foreign_keys:
                fk_columns.append((col.key, fk.target_fullname))

        assert any(
            col == "channel_config_id" and "channel_configs.id" in target
            for col, target in fk_columns
        ), "Missing foreign key to channel_configs.id"

    def test_has_project_foreign_key(self):
        """ChannelMessageModel should have foreign key to projects."""
        mapper = inspect(ChannelMessageModel)
        fk_columns = []
        for col in mapper.columns:
            for fk in col.foreign_keys:
                fk_columns.append((col.key, fk.target_fullname))

        assert any(
            col == "project_id" and "projects.id" in target
            for col, target in fk_columns
        ), "Missing foreign key to projects.id"


class TestModelIndexes:
    """Tests for model indexes."""

    def test_channel_config_has_project_type_index(self):
        """ChannelConfigModel should have composite index on (project_id, channel_type)."""
        table_args = ChannelConfigModel.__table_args__
        index_names = []
        for arg in table_args:
            if hasattr(arg, "name"):
                index_names.append(arg.name)

        assert (
            "ix_channel_configs_project_type" in index_names
        ), "Missing composite index on (project_id, channel_type)"

    def test_channel_config_has_project_enabled_index(self):
        """ChannelConfigModel should have composite index on (project_id, enabled)."""
        table_args = ChannelConfigModel.__table_args__
        index_names = []
        for arg in table_args:
            if hasattr(arg, "name"):
                index_names.append(arg.name)

        assert (
            "ix_channel_configs_project_enabled" in index_names
        ), "Missing composite index on (project_id, enabled)"

    def test_channel_message_has_project_chat_index(self):
        """ChannelMessageModel should have composite index on (project_id, chat_id)."""
        table_args = ChannelMessageModel.__table_args__
        index_names = []
        for arg in table_args:
            if hasattr(arg, "name"):
                index_names.append(arg.name)

        assert (
            "ix_channel_messages_project_chat" in index_names
        ), "Missing composite index on (project_id, chat_id)"


class TestChannelSessionBindingModel:
    """Tests for ChannelSessionBindingModel."""

    def test_table_name(self):
        """ChannelSessionBindingModel should have correct table name."""
        assert ChannelSessionBindingModel.__tablename__ == "channel_session_bindings"

    def test_required_fields(self):
        """ChannelSessionBindingModel should have required fields."""
        mapper = inspect(ChannelSessionBindingModel)
        column_names = {col.key for col in mapper.columns}
        required_fields = {
            "id",
            "project_id",
            "channel_config_id",
            "conversation_id",
            "channel_type",
            "chat_id",
            "chat_type",
            "session_key",
        }
        for field in required_fields:
            assert field in column_names, f"Missing required field: {field}"

    def test_unique_constraints(self):
        """ChannelSessionBindingModel should define expected unique constraints."""
        table_args = ChannelSessionBindingModel.__table_args__
        constraint_names = [getattr(arg, "name", None) for arg in table_args]
        assert "uq_channel_session_bindings_project_session_key" in constraint_names
        assert "uq_channel_session_bindings_conversation_id" in constraint_names

    def test_indexes(self):
        """ChannelSessionBindingModel should define project/chat and config/chat indexes."""
        table_args = ChannelSessionBindingModel.__table_args__
        index_names = [arg.name for arg in table_args if hasattr(arg, "name")]
        assert "ix_channel_session_bindings_project_chat" in index_names
        assert "ix_channel_session_bindings_config_chat" in index_names


class TestChannelOutboxModel:
    """Tests for ChannelOutboxModel."""

    def test_table_name(self):
        """ChannelOutboxModel should have correct table name."""
        assert ChannelOutboxModel.__tablename__ == "channel_outbox"

    def test_required_fields(self):
        """ChannelOutboxModel should have required delivery fields."""
        mapper = inspect(ChannelOutboxModel)
        column_names = {col.key for col in mapper.columns}
        required_fields = {
            "id",
            "project_id",
            "channel_config_id",
            "conversation_id",
            "chat_id",
            "content_text",
            "status",
            "attempt_count",
            "max_attempts",
        }
        for field in required_fields:
            assert field in column_names, f"Missing required field: {field}"

    def test_indexes(self):
        """ChannelOutboxModel should define retry and project-time indexes."""
        table_args = ChannelOutboxModel.__table_args__
        index_names = [arg.name for arg in table_args if hasattr(arg, "name")]
        assert "ix_channel_outbox_status_retry" in index_names
        assert "ix_channel_outbox_project_created" in index_names
