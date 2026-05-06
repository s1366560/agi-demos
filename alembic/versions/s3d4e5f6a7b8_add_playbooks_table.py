"""add playbooks table

Revision ID: s3d4e5f6a7b8
Revises: r2c3d4e5f6a7
Create Date: 2026-05-06
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "s3d4e5f6a7b8"
down_revision: str | Sequence[str] | None = "r2c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def upgrade() -> None:
    if _has_table("playbooks"):
        return

    op.create_table(
        "playbooks",
        sa.Column("id", sa.String(), primary_key=True, nullable=False),
        sa.Column(
            "project_id",
            sa.String(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("trigger", sa.JSON(), nullable=False),
        sa.Column("steps", sa.JSON(), nullable=False),
        sa.Column(
            "hit_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_playbooks_project_status",
        "playbooks",
        ["project_id", "status"],
    )
    op.create_index(
        "ix_playbooks_project_created",
        "playbooks",
        ["project_id", "created_at"],
    )


def downgrade() -> None:
    if not _has_table("playbooks"):
        return
    op.drop_index("ix_playbooks_project_created", table_name="playbooks")
    op.drop_index("ix_playbooks_project_status", table_name="playbooks")
    op.drop_table("playbooks")
