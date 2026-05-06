"""add reflection_verdicts table

Revision ID: t4e5f6a7b8c9
Revises: s3d4e5f6a7b8
Create Date: 2026-05-07
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "t4e5f6a7b8c9"
down_revision: str | Sequence[str] | None = "s3d4e5f6a7b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def upgrade() -> None:
    if _has_table("reflection_verdicts"):
        return

    op.create_table(
        "reflection_verdicts",
        sa.Column("id", sa.String(), primary_key=True, nullable=False),
        sa.Column(
            "project_id",
            sa.String(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column(
            "playbook_id",
            sa.String(),
            sa.ForeignKey("playbooks.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "rationale",
            sa.Text(),
            nullable=False,
            server_default="",
        ),
        sa.Column("proposed_payload", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_reflection_verdicts_project_created",
        "reflection_verdicts",
        ["project_id", "created_at"],
    )


def downgrade() -> None:
    if not _has_table("reflection_verdicts"):
        return
    op.drop_index(
        "ix_reflection_verdicts_project_created",
        table_name="reflection_verdicts",
    )
    op.drop_table("reflection_verdicts")
