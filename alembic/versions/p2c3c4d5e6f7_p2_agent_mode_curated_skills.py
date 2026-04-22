"""p2 add agent_conversation_mode and curated skills tables

Revision ID: p2c3c4d5e6f7
Revises: n1a2b3c4d5e6
Create Date: 2026-04-22

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "p2c3c4d5e6f7"
down_revision: str | Sequence[str] | None = "n1a2b3c4d5e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # --- P2-3: agent_conversation_mode on projects ---
    op.add_column(
        "projects",
        sa.Column(
            "agent_conversation_mode",
            sa.String(length=32),
            nullable=False,
            server_default="single_agent",
        ),
    )

    # --- P2-4: curated skills registry ---
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
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="active",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_curated_skills_status", "curated_skills", ["status"])
    op.create_unique_constraint("uq_curated_skills_hash", "curated_skills", ["revision_hash"])

    # --- P2-4: submissions queue ---
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
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="pending",
        ),
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

    # --- P2-4: skills fork / version metadata ---
    op.add_column(
        "skills",
        sa.Column(
            "parent_curated_id",
            sa.String(),
            sa.ForeignKey("curated_skills.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "skills",
        sa.Column("semver", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "skills",
        sa.Column("revision_hash", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("skills", "revision_hash")
    op.drop_column("skills", "semver")
    op.drop_column("skills", "parent_curated_id")

    op.drop_index("ix_skill_submissions_status", table_name="skill_submissions")
    op.drop_table("skill_submissions")

    op.drop_constraint("uq_curated_skills_hash", "curated_skills", type_="unique")
    op.drop_index("ix_curated_skills_status", table_name="curated_skills")
    op.drop_table("curated_skills")

    op.drop_column("projects", "agent_conversation_mode")
