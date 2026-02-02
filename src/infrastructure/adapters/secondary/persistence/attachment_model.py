"""Attachment database model for file uploads.

This model represents file attachments in conversations, supporting:
- Simple and multipart uploads
- Multiple purposes (LLM context, sandbox input, or both)
- Upload progress tracking
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from src.infrastructure.adapters.secondary.persistence.models import Base


class AttachmentModel(Base):
    """
    File attachment for conversation messages.

    Stores metadata about uploaded files, supporting both simple
    and multipart uploads for large files.
    """

    __tablename__ = "attachments"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # File information
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    object_key: Mapped[str] = mapped_column(String(500), nullable=False)

    # Purpose: llm_context, sandbox_input, or both
    purpose: Mapped[str] = mapped_column(String(20), nullable=False)

    # Status: pending, uploaded, processing, ready, failed, expired
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)

    # Multipart upload tracking
    upload_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    total_parts: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    uploaded_parts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Sandbox integration
    sandbox_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Additional metadata (dimensions for images, page count for docs, etc.)
    # Note: Use 'file_metadata' to avoid conflict with SQLAlchemy's reserved 'metadata'
    file_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=True)

    # Error tracking
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Relationships
    conversation: Mapped["Conversation"] = relationship(  # noqa: F821
        foreign_keys=[conversation_id],
    )
    project: Mapped["Project"] = relationship(  # noqa: F821
        foreign_keys=[project_id],
    )
    tenant: Mapped["Tenant"] = relationship(  # noqa: F821
        foreign_keys=[tenant_id],
    )

    __table_args__ = (
        Index("ix_attachments_status", "status"),
        Index("ix_attachments_expires_at", "expires_at"),
        Index("ix_attachments_conv_status", "conversation_id", "status"),
    )

    def __repr__(self) -> str:
        return (
            f"Attachment(id={self.id!r}, filename={self.filename!r}, "
            f"status={self.status!r}, size_bytes={self.size_bytes})"
        )
