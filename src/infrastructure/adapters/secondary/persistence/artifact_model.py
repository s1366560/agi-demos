"""Artifact database model for tool execution outputs.

This model represents file artifacts produced by sandbox/MCP tool executions,
supporting storage, retrieval, and lifecycle management of generated files.
"""

from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.infrastructure.adapters.secondary.persistence.models import (
        Conversation,
        Project,
        Tenant,
    )

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from src.infrastructure.adapters.secondary.persistence.models import Base


class ArtifactModel(Base):
    """
    File artifact produced by tool execution.

    Stores metadata about artifacts generated during sandbox/MCP tool
    executions, including storage references and lifecycle status.
    """

    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)

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
    sandbox_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tool_execution_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    conversation_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("conversations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    workspace_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("workspaces.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)

    object_key: Mapped[str] = mapped_column(String(500), nullable=False)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    preview_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    source_tool: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_path: Mapped[str | None] = mapped_column(String(500), nullable=True)

    artifact_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    project: Mapped["Project"] = relationship(
        foreign_keys=[project_id],
    )
    tenant: Mapped["Tenant"] = relationship(
        foreign_keys=[tenant_id],
    )
    conversation: Mapped["Conversation | None"] = relationship(
        foreign_keys=[conversation_id],
    )

    __table_args__ = (
        Index("ix_artifacts_status", "status"),
        Index("ix_artifacts_tool_execution", "tool_execution_id"),
        Index("ix_artifacts_project_status", "project_id", "status"),
        Index("ix_artifacts_project_category", "project_id", "category"),
        Index("ix_artifacts_workspace_status", "workspace_id", "status"),
    )

    def __repr__(self) -> str:
        return (
            f"Artifact(id={self.id!r}, filename={self.filename!r}, "
            f"status={self.status!r}, size_bytes={self.size_bytes})"
        )
