"""remove curated skill library tables

Revision ID: g4b5c6d7e8f9
Revises: f3a4b5c6d7e8
Create Date: 2026-05-28

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "g4b5c6d7e8f9"
down_revision: str | Sequence[str] | None = "f3a4b5c6d7e8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Drop curated-skill state after removing its API and UI."""
    bind = op.get_bind()
    bind.exec_driver_sql("SET LOCAL lock_timeout = '10s'")

    op.drop_column("skills", "revision_hash")
    op.drop_column("skills", "semver")
    op.drop_column("skills", "parent_curated_id")

    op.drop_index("ix_skill_submissions_status", table_name="skill_submissions")
    op.drop_table("skill_submissions")

    op.drop_constraint("uq_curated_skills_hash", "curated_skills", type_="unique")
    op.drop_index("ix_curated_skills_status", table_name="curated_skills")
    op.drop_table("curated_skills")


def downgrade() -> None:
    """Recreate the removed curated-skill tables and lineage columns."""
    bind = op.get_bind()
    bind.exec_driver_sql("SET LOCAL lock_timeout = '10s'")

    op.create_table(
        "curated_skills",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("semver", sa.String(length=32), nullable=False),
        sa.Column("revision_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "source_skill_id",
            sa.String(),
            sa.ForeignKey("skills.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("source_tenant_id", sa.String(), nullable=True, index=True),
        sa.Column(
            "approved_by",
            sa.String(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="active", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_curated_skills_status", "curated_skills", ["status"])
    op.create_unique_constraint("uq_curated_skills_hash", "curated_skills", ["revision_hash"])

    op.create_table(
        "skill_submissions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("submitter_tenant_id", sa.String(), nullable=False, index=True),
        sa.Column(
            "submitter_user_id",
            sa.String(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("source_skill_id", sa.String(), nullable=True),
        sa.Column("skill_snapshot", sa.JSON(), nullable=False),
        sa.Column("proposed_semver", sa.String(length=32), nullable=False),
        sa.Column("submission_note", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column(
            "reviewer_id",
            sa.String(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_skill_submissions_status", "skill_submissions", ["status"])

    op.add_column(
        "skills",
        sa.Column(
            "parent_curated_id",
            sa.String(),
            sa.ForeignKey("curated_skills.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column("skills", sa.Column("semver", sa.String(length=32), nullable=True))
    op.add_column("skills", sa.Column("revision_hash", sa.String(length=64), nullable=True))
