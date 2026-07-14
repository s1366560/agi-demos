"""Add automation command run correlation.

Revision ID: 4e4afcbe9600
Revises: aa98102469b3
Create Date: 2026-07-14 02:56:53.436619

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "4e4afcbe9600"
down_revision: str | Sequence[str] | None = "aa98102469b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add replay-safe receipt authority and Agent runtime correlation."""
    op.add_column(
        "agistack_cron_request_receipts",
        sa.Column("actor_api_key_id", sa.String(), nullable=True),
    )

    op.add_column(
        "cron_job_runs",
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "cron_job_runs",
        sa.Column("job_revision", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "cron_job_runs",
        sa.Column("schedule_revision", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "cron_job_runs",
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "cron_job_runs",
        sa.Column("runtime_execution_id", sa.String(), nullable=True),
    )
    op.add_column(
        "cron_job_runs",
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "cron_job_runs",
        sa.Column("request_receipt_id", sa.String(), nullable=True),
    )

    op.execute(
        """
        UPDATE cron_job_runs
        SET accepted_at = COALESCE(started_at, now())
        WHERE accepted_at IS NULL
        """
    )
    op.execute(
        """
        UPDATE cron_job_runs AS run
        SET job_revision = job.revision,
            schedule_revision = job.schedule_revision
        FROM cron_jobs AS job
        WHERE job.id = run.job_id
          AND run.job_revision IS NULL
        """
    )
    op.execute(
        """
        UPDATE cron_job_runs
        SET job_revision = 1
        WHERE job_revision IS NULL
        """
    )
    op.alter_column(
        "cron_job_runs",
        "accepted_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )
    op.alter_column(
        "cron_job_runs",
        "job_revision",
        existing_type=sa.BigInteger(),
        nullable=False,
        server_default=sa.text("1"),
    )
    op.create_index(
        "uq_cron_job_runs_runtime_execution",
        "cron_job_runs",
        ["runtime_execution_id"],
        unique=True,
        postgresql_where=sa.text("runtime_execution_id IS NOT NULL"),
    )


def downgrade() -> None:
    """Remove command receipt and runtime correlation fields."""
    op.drop_index("uq_cron_job_runs_runtime_execution", table_name="cron_job_runs")
    op.drop_column("cron_job_runs", "request_receipt_id")
    op.drop_column("cron_job_runs", "idempotency_key")
    op.drop_column("cron_job_runs", "runtime_execution_id")
    op.drop_column("cron_job_runs", "scheduled_for")
    op.drop_column("cron_job_runs", "schedule_revision")
    op.drop_column("cron_job_runs", "job_revision")
    op.drop_column("cron_job_runs", "accepted_at")
    op.drop_column("agistack_cron_request_receipts", "actor_api_key_id")
