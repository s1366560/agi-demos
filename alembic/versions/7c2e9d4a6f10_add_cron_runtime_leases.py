"""Add durable cron Agent runtime leases and deadlines.

Revision ID: 7c2e9d4a6f10
Revises: 4e4afcbe9600
Create Date: 2026-07-14 16:20:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "7c2e9d4a6f10"
down_revision: str | Sequence[str] | None = "4e4afcbe9600"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add fenced runtime ownership and timeout recovery fields."""
    op.add_column(
        "cron_job_runs",
        sa.Column(
            "runtime_revision",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.add_column(
        "cron_job_runs",
        sa.Column("runtime_lease_owner", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "cron_job_runs",
        sa.Column("runtime_lease_token", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "cron_job_runs",
        sa.Column("runtime_lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "cron_job_runs",
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "cron_job_runs",
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_cron_job_runs_runtime_dispatch",
        "cron_job_runs",
        ["status", "runtime_lease_expires_at", "accepted_at"],
        unique=False,
    )
    op.create_index(
        "ix_cron_job_runs_runtime_deadline",
        "cron_job_runs",
        ["deadline_at"],
        unique=False,
        postgresql_where=sa.text("status IN ('running', 'waiting_human')"),
    )


def downgrade() -> None:
    """Remove fenced runtime ownership and timeout recovery fields."""
    op.drop_index("ix_cron_job_runs_runtime_deadline", table_name="cron_job_runs")
    op.drop_index("ix_cron_job_runs_runtime_dispatch", table_name="cron_job_runs")
    op.drop_column("cron_job_runs", "last_heartbeat_at")
    op.drop_column("cron_job_runs", "deadline_at")
    op.drop_column("cron_job_runs", "runtime_lease_expires_at")
    op.drop_column("cron_job_runs", "runtime_lease_token")
    op.drop_column("cron_job_runs", "runtime_lease_owner")
    op.drop_column("cron_job_runs", "runtime_revision")
