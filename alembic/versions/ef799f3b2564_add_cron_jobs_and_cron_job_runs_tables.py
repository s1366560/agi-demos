"""add cron_jobs and cron_job_runs tables

Revision ID: ef799f3b2564
Revises: 6716678957ce
Create Date: 2026-03-06 00:08:35.197964

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "ef799f3b2564"
down_revision: Union[str, Sequence[str], None] = "6716678957ce"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "cron_jobs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "delete_after_run", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("schedule_type", sa.String(length=50), nullable=False),
        sa.Column("schedule_config", sa.JSON(), nullable=False),
        sa.Column("payload_type", sa.String(length=50), nullable=False),
        sa.Column("payload_config", sa.JSON(), nullable=False),
        sa.Column("delivery_type", sa.String(length=50), nullable=False, server_default="none"),
        sa.Column("delivery_config", sa.JSON(), nullable=True),
        sa.Column("conversation_mode", sa.String(length=50), nullable=True, server_default="reuse"),
        sa.Column("conversation_id", sa.String(), nullable=True),
        sa.Column("timezone", sa.String(length=100), nullable=True, server_default="UTC"),
        sa.Column("stagger_seconds", sa.Integer(), nullable=True, server_default=sa.text("0")),
        sa.Column("timeout_seconds", sa.Integer(), nullable=True, server_default=sa.text("300")),
        sa.Column("max_retries", sa.Integer(), nullable=True, server_default=sa.text("3")),
        sa.Column("state", sa.JSON(), nullable=True),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_cron_jobs_project_enabled",
        "cron_jobs",
        ["project_id", "enabled"],
    )

    op.create_table(
        "cron_job_runs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("trigger_type", sa.String(length=50), nullable=True, server_default="scheduled"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("result_summary", sa.JSON(), nullable=True),
        sa.Column("conversation_id", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["cron_jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_cron_job_runs_job_status", "cron_job_runs", ["job_id", "status"])
    op.create_index(
        "ix_cron_job_runs_project_started", "cron_job_runs", ["project_id", "started_at"]
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_cron_job_runs_project_started", table_name="cron_job_runs")
    op.drop_index("ix_cron_job_runs_job_status", table_name="cron_job_runs")
    op.drop_table("cron_job_runs")
    op.drop_index("ix_cron_jobs_project_enabled", table_name="cron_jobs")
    op.drop_table("cron_jobs")
