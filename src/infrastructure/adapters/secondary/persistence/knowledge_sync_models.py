"""Durable sync metadata; active content remains in the existing memories table."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.adapters.secondary.persistence.models import Base


class KnowledgeSyncCursorModel(Base):
    __tablename__ = "knowledge_sync_cursors"
    tenant_id: Mapped[str] = mapped_column(
        String, ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    project_id: Mapped[str] = mapped_column(
        String, ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    sequence: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    __table_args__ = (
        CheckConstraint("sequence >= 0", name="ck_knowledge_sync_cursor_nonnegative"),
    )


class KnowledgeSyncChangeModel(Base):
    __tablename__ = "knowledge_sync_changes"
    tenant_id: Mapped[str] = mapped_column(
        String, ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    project_id: Mapped[str] = mapped_column(
        String, ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    sequence: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    actor_id: Mapped[str] = mapped_column(String, nullable=False)
    change_id: Mapped[str] = mapped_column(String(36), nullable=False)
    memory_id: Mapped[str] = mapped_column(String, nullable=False)
    revision: Mapped[int] = mapped_column(BigInteger, nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    # PostgreSQL's migration installs txid_current(); SQLite has no deferred
    # guard and uses NULL. The database records the root transaction, including
    # changes inserted inside SQLAlchemy savepoints.
    transaction_id: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, server_default=text("NULL")
    )
    source_kind: Mapped[str] = mapped_column(
        String(16), nullable=False, default="mutation", server_default="mutation"
    )
    __table_args__ = (
        CheckConstraint(
            "source_kind IN ('mutation', 'bootstrap')", name="ck_knowledge_sync_change_source"
        ),
        UniqueConstraint(
            "tenant_id",
            "project_id",
            "actor_id",
            "change_id",
            name="uq_knowledge_sync_change_request",
        ),
        UniqueConstraint(
            "tenant_id",
            "project_id",
            "memory_id",
            "revision",
            name="uq_knowledge_sync_object_revision",
        ),
        CheckConstraint("sequence > 0 AND revision > 0", name="ck_knowledge_sync_change_positive"),
    )


class KnowledgeSyncReceiptModel(Base):
    __tablename__ = "knowledge_sync_receipts"
    tenant_id: Mapped[str] = mapped_column(
        String, ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    project_id: Mapped[str] = mapped_column(
        String, ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    actor_id: Mapped[str] = mapped_column(String, primary_key=True)
    change_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    request_json: Mapped[str] = mapped_column(Text, nullable=False)
    receipt_json: Mapped[str] = mapped_column(Text, nullable=False)


class KnowledgeSyncTombstoneModel(Base):
    __tablename__ = "knowledge_sync_tombstones"
    # Memory IDs are globally reserved, including after deletion, just like memories.id.
    memory_id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[str] = mapped_column(
        String, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    revision: Mapped[int] = mapped_column(BigInteger, nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    __table_args__ = (
        CheckConstraint("revision > 0", name="ck_knowledge_sync_tombstone_positive"),
        Index("ix_knowledge_sync_tombstone_scope", "tenant_id", "project_id"),
    )


class KnowledgeSyncConflictModel(Base):
    __tablename__ = "knowledge_sync_conflicts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[str] = mapped_column(
        String, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    actor_id: Mapped[str] = mapped_column(String, nullable=False)
    memory_id: Mapped[str] = mapped_column(String, nullable=False)
    change_id: Mapped[str] = mapped_column(String(36), nullable=False)
    proposed: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    current: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    resolved_change_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "project_id",
            "actor_id",
            "change_id",
            name="uq_knowledge_sync_conflict_request",
        ),
        Index(
            "ix_knowledge_sync_pending_conflict",
            "tenant_id",
            "project_id",
            "actor_id",
            "memory_id",
            "resolved_change_id",
        ),
    )


class KnowledgeGraphSyncObjectModel(Base):
    """Current derived projection records; the durable journal form, never Neo4j."""

    __tablename__ = "knowledge_sync_graph_objects"
    tenant_id: Mapped[str] = mapped_column(
        String, ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    project_id: Mapped[str] = mapped_column(
        String, ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    object_id: Mapped[str] = mapped_column(String, primary_key=True)
    revision: Mapped[int] = mapped_column(BigInteger, nullable=False)
    deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    author_id: Mapped[str] = mapped_column(String, nullable=False)
    created_at_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    __table_args__ = (
        CheckConstraint("revision > 0", name="ck_knowledge_sync_graph_object_positive"),
    )


class KnowledgeGraphSyncCursorModel(Base):
    __tablename__ = "knowledge_sync_graph_cursors"
    tenant_id: Mapped[str] = mapped_column(
        String, ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    project_id: Mapped[str] = mapped_column(
        String, ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    sequence: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    __table_args__ = (
        CheckConstraint("sequence >= 0", name="ck_knowledge_sync_graph_cursor_nonnegative"),
    )


class KnowledgeGraphSyncChangeModel(Base):
    __tablename__ = "knowledge_sync_graph_changes"
    tenant_id: Mapped[str] = mapped_column(
        String, ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    project_id: Mapped[str] = mapped_column(
        String, ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    sequence: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    actor_id: Mapped[str] = mapped_column(String, nullable=False)
    change_id: Mapped[str] = mapped_column(String(36), nullable=False)
    object_id: Mapped[str] = mapped_column(String, nullable=False)
    revision: Mapped[int] = mapped_column(BigInteger, nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "project_id",
            "actor_id",
            "change_id",
            name="uq_knowledge_sync_graph_change_request",
        ),
        UniqueConstraint(
            "tenant_id",
            "project_id",
            "object_id",
            "revision",
            name="uq_knowledge_sync_graph_object_revision",
        ),
        CheckConstraint(
            "sequence > 0 AND revision > 0", name="ck_knowledge_sync_graph_change_positive"
        ),
    )


class KnowledgeGraphSyncReceiptModel(Base):
    __tablename__ = "knowledge_sync_graph_receipts"
    tenant_id: Mapped[str] = mapped_column(
        String, ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    project_id: Mapped[str] = mapped_column(
        String, ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    actor_id: Mapped[str] = mapped_column(String, primary_key=True)
    change_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    request_json: Mapped[str] = mapped_column(Text, nullable=False)
    receipt_json: Mapped[str] = mapped_column(Text, nullable=False)


class KnowledgeGraphSyncTombstoneModel(Base):
    __tablename__ = "knowledge_sync_graph_tombstones"
    # Graph object IDs are globally reserved, including after deletion.
    object_id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[str] = mapped_column(
        String, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    revision: Mapped[int] = mapped_column(BigInteger, nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    __table_args__ = (
        CheckConstraint("revision > 0", name="ck_knowledge_sync_graph_tombstone_positive"),
        Index("ix_knowledge_sync_graph_tombstone_scope", "tenant_id", "project_id"),
    )


class KnowledgeGraphSyncConflictModel(Base):
    __tablename__ = "knowledge_sync_graph_conflicts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[str] = mapped_column(
        String, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    actor_id: Mapped[str] = mapped_column(String, nullable=False)
    object_id: Mapped[str] = mapped_column(String, nullable=False)
    change_id: Mapped[str] = mapped_column(String(36), nullable=False)
    proposed: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    current: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    resolved_change_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "project_id",
            "actor_id",
            "change_id",
            name="uq_knowledge_sync_graph_conflict_request",
        ),
        Index(
            "ix_knowledge_sync_graph_pending_conflict",
            "tenant_id",
            "project_id",
            "actor_id",
            "object_id",
            "resolved_change_id",
        ),
    )


class KnowledgeSyncEnrollmentModel(Base):
    """A per-project fence separating enrolled and unchanged legacy writers."""

    __tablename__ = "knowledge_sync_enrollments"
    project_id: Mapped[str] = mapped_column(
        String, ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    tenant_id: Mapped[str] = mapped_column(
        String, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    bootstrap_actor_id: Mapped[str | None] = mapped_column(String, nullable=True)
    bootstrap_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    bootstrap_count: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    bootstrap_cursor: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    __table_args__ = (
        CheckConstraint(
            "bootstrap_count >= 0 AND bootstrap_cursor >= 0",
            name="ck_knowledge_sync_bootstrap_nonnegative",
        ),
    )
