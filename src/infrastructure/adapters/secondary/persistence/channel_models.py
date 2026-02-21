"""Channel configuration database models."""

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from src.infrastructure.adapters.secondary.persistence.models import Base, IdGeneratorMixin


class ChannelConfigModel(IdGeneratorMixin, Base):
    """Channel configuration database model.
    
    Stores configuration for IM channel integrations (Feishu, DingTalk, WeCom, etc.)
    Supports multi-tenancy via project_id.
    """
    
    __tablename__ = "channel_configs"
    
    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String, 
        ForeignKey("projects.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    
    # Channel identification
    channel_type: Mapped[str] = mapped_column(
        String, 
        index=True,
        nullable=False,
        comment="Channel type: feishu, dingtalk, wecom, etc."
    )
    name: Mapped[str] = mapped_column(
        String, 
        nullable=False,
        comment="Display name for this channel configuration"
    )
    
    # Connection settings
    enabled: Mapped[bool] = mapped_column(
        Boolean, 
        default=True,
        comment="Whether this channel is enabled"
    )
    connection_mode: Mapped[str] = mapped_column(
        String,
        default="websocket",
        comment="Connection mode: websocket or webhook"
    )
    
    # Credentials (should be encrypted in production)
    app_id: Mapped[Optional[str]] = mapped_column(
        String, 
        nullable=True,
        comment="App ID for the channel"
    )
    app_secret: Mapped[Optional[str]] = mapped_column(
        String, 
        nullable=True,
        comment="App secret (encrypted)"
    )
    encrypt_key: Mapped[Optional[str]] = mapped_column(
        String, 
        nullable=True,
        comment="Encrypt key for webhook verification"
    )
    verification_token: Mapped[Optional[str]] = mapped_column(
        String, 
        nullable=True,
        comment="Verification token for webhook"
    )
    
    # Webhook settings
    webhook_url: Mapped[Optional[str]] = mapped_column(
        String, 
        nullable=True,
        comment="Webhook URL for receiving events"
    )
    webhook_port: Mapped[Optional[int]] = mapped_column(
        nullable=True,
        comment="Webhook server port"
    )
    webhook_path: Mapped[Optional[str]] = mapped_column(
        String, 
        nullable=True,
        comment="Webhook endpoint path"
    )
    
    # Channel-specific settings
    domain: Mapped[Optional[str]] = mapped_column(
        String,
        default="feishu",
        comment="Domain: feishu, lark, or custom"
    )
    extra_settings: Mapped[Optional[dict]] = mapped_column(
        JSON,
        nullable=True,
        comment="Additional channel-specific settings"
    )
    
    # Status
    status: Mapped[str] = mapped_column(
        String,
        default="disconnected",
        comment="Connection status: connected, disconnected, error"
    )
    last_error: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Last error message if any"
    )
    
    # Metadata
    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Optional description"
    )
    created_by: Mapped[Optional[str]] = mapped_column(
        String,
        ForeignKey("users.id"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        server_default=func.now()
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), 
        onupdate=func.now(),
        nullable=True
    )
    
    # Relationships
    project = relationship("Project", back_populates="channel_configs")
    creator = relationship("User")
    
    __table_args__ = (
        Index(
            "ix_channel_configs_project_type", 
            "project_id", 
            "channel_type"
        ),
        Index(
            "ix_channel_configs_project_enabled",
            "project_id",
            "enabled",
        ),
    )


class ChannelMessageModel(IdGeneratorMixin, Base):
    """Channel message history model.
    
    Stores message history for audit and context.
    """
    
    __tablename__ = "channel_messages"
    
    id: Mapped[str] = mapped_column(String, primary_key=True)
    
    # Channel reference
    channel_config_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("channel_configs.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    project_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("projects.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    
    # Message metadata
    channel_message_id: Mapped[str] = mapped_column(
        String,
        index=True,
        nullable=False,
        comment="Original message ID from channel"
    )
    chat_id: Mapped[str] = mapped_column(
        String,
        index=True,
        nullable=False,
    )
    chat_type: Mapped[str] = mapped_column(
        String,
        nullable=False,
        comment="p2p or group"
    )
    sender_id: Mapped[str] = mapped_column(
        String,
        index=True,
        nullable=False,
    )
    sender_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    
    # Content
    message_type: Mapped[str] = mapped_column(
        String,
        nullable=False,
        comment="text, image, file, card, etc."
    )
    content_text: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    content_data: Mapped[Optional[dict]] = mapped_column(
        JSON,
        nullable=True,
        comment="Structured content data"
    )
    
    # Reply info
    reply_to: Mapped[Optional[str]] = mapped_column(
        String,
        nullable=True,
        comment="ID of message being replied to"
    )
    mentions: Mapped[Optional[list]] = mapped_column(
        JSON,
        nullable=True,
        comment="List of mentioned user IDs"
    )
    
    # Direction
    direction: Mapped[str] = mapped_column(
        String,
        nullable=False,
        comment="inbound or outbound"
    )
    
    # Raw data for debugging
    raw_data: Mapped[Optional[dict]] = mapped_column(
        JSON,
        nullable=True,
        comment="Original message data from channel"
    )
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now()
    )
    
    __table_args__ = (
        Index(
            "ix_channel_messages_project_chat",
            "project_id",
            "chat_id",
        ),
        Index(
            "ix_channel_messages_config_time",
            "channel_config_id",
            "created_at",
        ),
    )


class ChannelSessionBindingModel(IdGeneratorMixin, Base):
    """Channel session key to conversation binding.

    Provides deterministic routing from channel session identity to a stable
    agent conversation without scanning conversation metadata.
    """

    __tablename__ = "channel_session_bindings"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("projects.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    channel_config_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("channel_configs.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    conversation_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    channel_type: Mapped[str] = mapped_column(String, nullable=False)
    chat_id: Mapped[str] = mapped_column(String, nullable=False)
    chat_type: Mapped[str] = mapped_column(String, nullable=False)
    thread_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    topic_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    session_key: Mapped[str] = mapped_column(String(512), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        onupdate=func.now(),
        nullable=True,
    )

    project = relationship("Project")
    channel_config = relationship("ChannelConfigModel")
    conversation = relationship("Conversation")

    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "session_key",
            name="uq_channel_session_bindings_project_session_key",
        ),
        UniqueConstraint(
            "conversation_id",
            name="uq_channel_session_bindings_conversation_id",
        ),
        Index(
            "ix_channel_session_bindings_project_chat",
            "project_id",
            "chat_id",
        ),
        Index(
            "ix_channel_session_bindings_config_chat",
            "channel_config_id",
            "chat_id",
        ),
    )


class ChannelOutboxModel(IdGeneratorMixin, Base):
    """Outbound message queue for reliable channel delivery."""

    __tablename__ = "channel_outbox"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("projects.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    channel_config_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("channel_configs.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    conversation_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("conversations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    chat_id: Mapped[str] = mapped_column(String, nullable=False)
    reply_to_channel_message_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    content_text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20),
        default="pending",
        nullable=False,
        comment="pending | sent | failed | dead_letter",
    )
    attempt_count: Mapped[int] = mapped_column(default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(default=3, nullable=False)
    sent_channel_message_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    next_retry_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        onupdate=func.now(),
        nullable=True,
    )

    project = relationship("Project")
    channel_config = relationship("ChannelConfigModel")
    conversation = relationship("Conversation")

    __table_args__ = (
        Index(
            "ix_channel_outbox_status_retry",
            "status",
            "next_retry_at",
        ),
        Index(
            "ix_channel_outbox_project_created",
            "project_id",
            "created_at",
        ),
    )
