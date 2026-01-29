"""
Session SQLAlchemy ORM Models

This module contains SQLAlchemy ORM models for session management.
These models map to the database tables created in Alembic migrations.
"""

from datetime import datetime
from typing import List

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.infrastructure.adapters.secondary.persistence.models import Base


class SessionModel(Base):
    """
    Session ORM model.

    Represents an isolated conversation context for agent interactions.
    """

    __tablename__ = "sessions"

    # Primary key
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )

    # Session identification
    session_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    agent_id: Mapped[str] = mapped_column(String(255), nullable=False)

    # Session classification
    kind: Mapped[str] = mapped_column(String(50), nullable=False, default="main")

    # Model override (optional)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Status
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active")

    # Flexible metadata
    metadata: Mapped[dict] = mapped_column(
        JSONB, default=dict, nullable=False
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=func.now(), nullable=False
    )
    last_active_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    messages: Mapped[List["SessionMessageModel"]] = relationship(
        "SessionMessageModel", back_populates="session", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("length(trim(session_key)) > 0", name="sessions_key_not_empty"),
        CheckConstraint("length(trim(agent_id)) > 0", name="sessions_agent_not_empty"),
        CheckConstraint(
            "kind IN ('main', 'sub_agent', 'background', 'one_shot')",
            name="sessions_valid_kind",
        ),
        CheckConstraint(
            "status IN ('active', 'inactive', 'terminated', 'error')",
            name="sessions_valid_status",
        ),
        UniqueConstraint("session_key", name="uq_sessions_session_key"),
        Index("idx_sessions_session_key", "session_key"),
        Index("idx_sessions_agent_id", "agent_id"),
        Index("idx_sessions_kind", "kind"),
        Index("idx_sessions_status", "status"),
        Index("idx_sessions_last_active", "last_active_at"),
        Index("idx_sessions_agent_kind", "agent_id", "kind"),
        Index("idx_sessions_agent_status", "agent_id", "status"),
    )

    def __repr__(self) -> str:
        return f"<SessionModel(id={self.id}, key='{self.session_key}', agent='{self.agent_id}', status='{self.status}')>"


class SessionMessageModel(Base):
    """
    Session Message ORM model.

    Represents a single message within a session.
    """

    __tablename__ = "session_messages"

    # Primary key
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )

    # Session reference
    session_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )

    # Message role
    role: Mapped[str] = mapped_column(String(50), nullable=False)

    # Message content
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # Flexible metadata
    metadata: Mapped[dict] = mapped_column(
        JSONB, default=dict, nullable=False
    )

    # Timestamp
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=func.now(), nullable=False
    )

    # Relationships
    session: Mapped["SessionModel"] = relationship("SessionModel", back_populates="messages")

    __table_args__ = (
        CheckConstraint("length(trim(content)) > 0", name="session_messages_content_not_empty"),
        CheckConstraint(
            "role IN ('user', 'assistant', 'system', 'tool')",
            name="session_messages_valid_role",
        ),
        Index("idx_session_messages_session_id", "session_id"),
        Index("idx_session_messages_created_at", "created_at"),
        Index("idx_session_messages_session_created", "session_id", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<SessionMessageModel(id={self.id}, session_id={self.session_id}, role='{self.role}')>"
