"""add skill evolution sessions and jobs tables

Revision ID: p3a4b5c6d7e8
Revises: p2c3c4d5e6f7
Create Date: 2026-04-29

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "p3a4b5c6d7e8"
down_revision: str | Sequence[str] | None = "p2c3c4d5e6f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create skill evolution sessions and jobs tables."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "skill_evolution_sessions" not in tables:
        op.create_table(
            "skill_evolution_sessions",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column(
                "skill_name",
                sa.String(length=200),
                nullable=False,
                index=True,
            ),
            sa.Column("tenant_id", sa.String(), nullable=False, index=True),
            sa.Column("project_id", sa.String(), nullable=True, index=True),
            sa.Column("conversation_id", sa.String(), nullable=False),
            sa.Column("user_query", sa.Text(), nullable=False),
            sa.Column("trajectory", sa.JSON(), nullable=True),
            sa.Column("summary", sa.Text(), nullable=True),
            sa.Column("judge_scores", sa.JSON(), nullable=True),
            sa.Column("overall_score", sa.Float(), nullable=True),
            sa.Column(
                "success",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
            sa.Column(
                "execution_time_ms",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column(
                "tool_call_count",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column(
                "processed",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
                index=True,
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
        )

    session_indexes = {
        index["name"] for index in inspector.get_indexes("skill_evolution_sessions")
    }
    if "ix_skill_evolution_sessions_skill_tenant" not in session_indexes:
        op.create_index(
            "ix_skill_evolution_sessions_skill_tenant",
            "skill_evolution_sessions",
            ["skill_name", "tenant_id"],
        )

    if "skill_evolution_jobs" not in tables:
        op.create_table(
            "skill_evolution_jobs",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column(
                "skill_name",
                sa.String(length=200),
                nullable=False,
                index=True,
            ),
            sa.Column("tenant_id", sa.String(), nullable=False, index=True),
            sa.Column("action", sa.String(length=30), nullable=False),
            sa.Column("candidate_content", sa.Text(), nullable=True),
            sa.Column("rationale", sa.Text(), nullable=True),
            sa.Column("session_ids", sa.JSON(), nullable=True),
            sa.Column(
                "status",
                sa.String(length=30),
                nullable=False,
                server_default="pending_review",
                index=True,
            ),
            sa.Column("skill_version_id", sa.String(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "applied_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
        )

    job_indexes = {index["name"] for index in inspector.get_indexes("skill_evolution_jobs")}
    if "ix_skill_evolution_jobs_skill_tenant" not in job_indexes:
        op.create_index(
            "ix_skill_evolution_jobs_skill_tenant",
            "skill_evolution_jobs",
            ["skill_name", "tenant_id"],
        )


def downgrade() -> None:
    """Drop skill evolution tables."""
    op.drop_index(
        "ix_skill_evolution_jobs_skill_tenant",
        table_name="skill_evolution_jobs",
    )
    op.drop_table("skill_evolution_jobs")

    op.drop_index(
        "ix_skill_evolution_sessions_skill_tenant",
        table_name="skill_evolution_sessions",
    )
    op.drop_table("skill_evolution_sessions")
