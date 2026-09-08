"""Closed schema storage foundation; legacy tables remain the only current authority.

The legacy-only head constraint must be replaced by a later reviewed migration
when an atomic command authority and its database write guards actually exist.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.adapters.secondary.persistence.models import Base


class ProjectSchemaHeadModel(Base):
    """An inactive slot, not a second current-document payload or activation API."""

    __tablename__ = "project_schema_heads"
    project_id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False, server_default="legacy")
    schema_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    format_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    revision: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    sequence: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "tenant_id"],
            ["projects.id", "projects.tenant_id"],
            name="fk_project_schema_head_scope",
            ondelete="CASCADE",
        ),
        UniqueConstraint("schema_id", name="uq_project_schema_head_identity"),
        UniqueConstraint(
            "tenant_id", "project_id", "schema_id", name="uq_project_schema_head_scope"
        ),
        CheckConstraint("format_version = 1", name="ck_project_schema_head_format"),
        CheckConstraint(
            "mode = 'legacy' AND schema_id IS NULL AND revision IS NULL "
            "AND sequence = 0 AND NOT deleted",
            name="ck_project_schema_head_closed",
        ),
    )


class ProjectSchemaTombstoneModel(Base):
    """Future immutable member reservations; no writer is supplied in this batch."""

    __tablename__ = "project_schema_tombstones"
    schema_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    member_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False)
    project_id: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    deleted_revision: Mapped[int] = mapped_column(BigInteger, nullable=False)
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "project_id", "schema_id"],
            [
                "project_schema_heads.tenant_id",
                "project_schema_heads.project_id",
                "project_schema_heads.schema_id",
            ],
            name="fk_project_schema_tombstone_head",
        ),
        CheckConstraint(
            "kind IN ('entity_type', 'edge_type', 'mapping')",
            name="ck_project_schema_tombstone_kind",
        ),
        CheckConstraint(
            "deleted_revision BETWEEN 1 AND 2147483647", name="ck_project_schema_tombstone_revision"
        ),
    )


class ProjectSchemaChangeModel(Base):
    """Future immutable journal snapshots, never a writable current-document copy."""

    __tablename__ = "project_schema_changes"
    tenant_id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, primary_key=True)
    sequence: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    schema_id: Mapped[str] = mapped_column(String(36), nullable=False)
    revision: Mapped[int] = mapped_column(BigInteger, nullable=False)
    actor_id: Mapped[str] = mapped_column(String, nullable=False)
    change_id: Mapped[str] = mapped_column(String(36), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    transaction_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "project_id", "schema_id"],
            [
                "project_schema_heads.tenant_id",
                "project_schema_heads.project_id",
                "project_schema_heads.schema_id",
            ],
            name="fk_project_schema_change_head",
        ),
        UniqueConstraint("schema_id", "revision", name="uq_project_schema_change_revision"),
        UniqueConstraint(
            "tenant_id",
            "project_id",
            "actor_id",
            "change_id",
            name="uq_project_schema_change_request",
        ),
        CheckConstraint(
            "sequence > 0 AND revision BETWEEN 1 AND 2147483647",
            name="ck_project_schema_change_version",
        ),
        CheckConstraint(
            "source_kind IN ('bootstrap', 'mutation')", name="ck_project_schema_change_source"
        ),
    )


class ProjectSchemaReceiptModel(Base):
    """Future exact request/response bytes scoped to the initiator and schema."""

    __tablename__ = "project_schema_receipts"
    tenant_id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, primary_key=True)
    schema_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    actor_id: Mapped[str] = mapped_column(String, primary_key=True)
    change_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    request_json: Mapped[str] = mapped_column(Text, nullable=False)
    receipt_json: Mapped[str] = mapped_column(Text, nullable=False)
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "project_id", "schema_id"],
            [
                "project_schema_heads.tenant_id",
                "project_schema_heads.project_id",
                "project_schema_heads.schema_id",
            ],
            name="fk_project_schema_receipt_head",
        ),
    )


class ProjectSchemaMigrationFindingModel(Base):
    """Storage reserved for structural findings; this batch has no persistence command."""

    __tablename__ = "project_schema_migration_findings"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    inspection_id: Mapped[str] = mapped_column(String(36), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False)
    project_id: Mapped[str] = mapped_column(String, nullable=False)
    record_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    record_id: Mapped[str] = mapped_column(String, nullable=False)
    code: Mapped[str] = mapped_column(String(128), nullable=False)
    field: Mapped[str | None] = mapped_column(String(64), nullable=True)
    related_records: Mapped[list[dict[str, str]]] = mapped_column(JSON, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "tenant_id"],
            ["projects.id", "projects.tenant_id"],
            name="fk_project_schema_finding_scope",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "record_kind IN ('project', 'entity_type', 'edge_type', 'mapping')",
            name="ck_project_schema_finding_kind",
        ),
        Index("ix_project_schema_finding_scan", "tenant_id", "project_id", "inspection_id"),
    )
