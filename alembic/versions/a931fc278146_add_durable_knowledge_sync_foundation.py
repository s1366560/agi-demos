"""add durable knowledge sync foundation

Revision ID: a931fc278146
Revises: ce113f52d916
Create Date: 2026-09-07 15:27:15.865213

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a931fc278146"
down_revision: str | Sequence[str] | None = "ce113f52d916"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "knowledge_sync_changes",
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("sequence", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("actor_id", sa.String(), nullable=False),
        sa.Column("change_id", sa.String(length=36), nullable=False),
        sa.Column("memory_id", sa.String(), nullable=False),
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.CheckConstraint(
            "sequence > 0 AND revision > 0", name="ck_knowledge_sync_change_positive"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("tenant_id", "project_id", "sequence"),
        sa.UniqueConstraint(
            "tenant_id",
            "project_id",
            "actor_id",
            "change_id",
            name="uq_knowledge_sync_change_request",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "project_id",
            "memory_id",
            "revision",
            name="uq_knowledge_sync_object_revision",
        ),
    )
    op.create_table(
        "knowledge_sync_conflicts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("actor_id", sa.String(), nullable=False),
        sa.Column("memory_id", sa.String(), nullable=False),
        sa.Column("change_id", sa.String(length=36), nullable=False),
        sa.Column("proposed", sa.JSON(), nullable=False),
        sa.Column("current", sa.JSON(), nullable=True),
        sa.Column("resolved_change_id", sa.String(length=36), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "project_id",
            "actor_id",
            "change_id",
            name="uq_knowledge_sync_conflict_request",
        ),
    )
    op.create_index(
        "ix_knowledge_sync_pending_conflict",
        "knowledge_sync_conflicts",
        ["tenant_id", "project_id", "actor_id", "memory_id", "resolved_change_id"],
        unique=False,
    )
    op.create_table(
        "knowledge_sync_cursors",
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.CheckConstraint("sequence >= 0", name="ck_knowledge_sync_cursor_nonnegative"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("tenant_id", "project_id"),
    )
    op.create_table(
        "knowledge_sync_receipts",
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("actor_id", sa.String(), nullable=False),
        sa.Column("change_id", sa.String(length=36), nullable=False),
        sa.Column("request_json", sa.Text(), nullable=False),
        sa.Column("receipt_json", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("tenant_id", "project_id", "actor_id", "change_id"),
    )
    op.create_table(
        "knowledge_sync_tombstones",
        sa.Column("memory_id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.CheckConstraint("revision > 0", name="ck_knowledge_sync_tombstone_positive"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("memory_id"),
    )
    op.create_index(
        "ix_knowledge_sync_tombstone_scope",
        "knowledge_sync_tombstones",
        ["tenant_id", "project_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("knowledge_sync_tombstones")
    op.drop_table("knowledge_sync_receipts")
    op.drop_table("knowledge_sync_cursors")
    op.drop_table("knowledge_sync_conflicts")
    op.drop_table("knowledge_sync_changes")
