"""add ordinary chat cicd tables

Revision ID: f3a4b5c6d7e8
Revises: e2f3a4b5c6d7
Create Date: 2026-05-26

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f3a4b5c6d7e8"
down_revision: str | Sequence[str] | None = "e2f3a4b5c6d7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create tenant/project-scoped CI/CD run tables."""
    op.create_table(
        "cicd_pipeline_runs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("conversation_id", sa.String(), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("repository", sa.String(length=255), nullable=False),
        sa.Column("branch", sa.String(), nullable=True),
        sa.Column("commit_ref", sa.String(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("external_id", sa.String(), nullable=True),
        sa.Column("external_url", sa.String(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_cicd_pipeline_runs_tenant_project_created",
        "cicd_pipeline_runs",
        ["tenant_id", "project_id", "created_at"],
    )
    op.create_index(
        "ix_cicd_pipeline_runs_conversation_created",
        "cicd_pipeline_runs",
        ["conversation_id", "created_at"],
    )
    op.create_index(
        "ix_cicd_pipeline_runs_repository_created",
        "cicd_pipeline_runs",
        ["repository", "created_at"],
    )
    op.create_index("ix_cicd_pipeline_runs_status", "cicd_pipeline_runs", ["status"])

    op.create_table(
        "cicd_pipeline_stage_runs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("stage", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("command", sa.Text(), nullable=True),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column("stdout_preview", sa.Text(), nullable=True),
        sa.Column("stderr_preview", sa.Text(), nullable=True),
        sa.Column("log_ref", sa.String(), nullable=True),
        sa.Column(
            "artifact_refs_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["cicd_pipeline_runs.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_cicd_pipeline_stage_runs_run", "cicd_pipeline_stage_runs", ["run_id"])
    op.create_index("ix_cicd_pipeline_stage_runs_status", "cicd_pipeline_stage_runs", ["status"])


def downgrade() -> None:
    """Drop tenant/project-scoped CI/CD run tables."""
    op.drop_index("ix_cicd_pipeline_stage_runs_status", table_name="cicd_pipeline_stage_runs")
    op.drop_index("ix_cicd_pipeline_stage_runs_run", table_name="cicd_pipeline_stage_runs")
    op.drop_table("cicd_pipeline_stage_runs")
    op.drop_index("ix_cicd_pipeline_runs_status", table_name="cicd_pipeline_runs")
    op.drop_index("ix_cicd_pipeline_runs_repository_created", table_name="cicd_pipeline_runs")
    op.drop_index("ix_cicd_pipeline_runs_conversation_created", table_name="cicd_pipeline_runs")
    op.drop_index("ix_cicd_pipeline_runs_tenant_project_created", table_name="cicd_pipeline_runs")
    op.drop_table("cicd_pipeline_runs")
