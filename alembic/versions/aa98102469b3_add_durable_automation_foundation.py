"""Add durable automation foundation.

Revision ID: aa98102469b3
Revises: b1039849ef6d
Create Date: 2026-07-14 02:11:56.012499

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "aa98102469b3"
down_revision: str | Sequence[str] | None = "b1039849ef6d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create revision fencing, durable operation, receipt, and owner records."""
    op.add_column(
        "cron_jobs",
        sa.Column("revision", sa.BigInteger(), server_default=sa.text("1"), nullable=False),
    )
    op.add_column(
        "cron_jobs",
        sa.Column(
            "schedule_revision",
            sa.BigInteger(),
            server_default=sa.text("1"),
            nullable=False,
        ),
    )

    op.create_table(
        "agistack_cron_operations",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("job_revision", sa.BigInteger(), nullable=False),
        sa.Column("schedule_revision", sa.BigInteger(), nullable=True),
        sa.Column("operation_kind", sa.String(length=40), nullable=False),
        sa.Column("run_id", sa.String(), nullable=True),
        sa.Column("trigger_type", sa.String(length=40), nullable=True),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "input_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("attempt_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default=sa.text("5"), nullable=False),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column("lease_owner", sa.String(length=255), nullable=True),
        sa.Column("lease_token", sa.String(length=255), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actor_user_id", sa.String(), nullable=True),
        sa.Column("actor_api_key_id", sa.String(), nullable=True),
        sa.Column("request_receipt_id", sa.String(), nullable=True),
        sa.Column(
            "result_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("last_error_code", sa.String(length=100), nullable=True),
        sa.Column("last_error_redacted", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_agistack_cron_operations_claim",
        "agistack_cron_operations",
        ["status", "next_attempt_at", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_agistack_cron_operations_lease",
        "agistack_cron_operations",
        ["status", "lease_expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_agistack_cron_operations_project_job",
        "agistack_cron_operations",
        ["project_id", "job_id"],
        unique=False,
    )
    op.create_index(
        "uq_agistack_cron_operations_reconcile",
        "agistack_cron_operations",
        ["job_id", "operation_kind", "schedule_revision"],
        unique=True,
        postgresql_where=sa.text("operation_kind = 'reconcile_schedule'"),
    )
    op.create_index(
        "uq_agistack_cron_operations_run",
        "agistack_cron_operations",
        ["run_id"],
        unique=True,
        postgresql_where=sa.text("run_id IS NOT NULL"),
    )
    op.create_index(
        "uq_agistack_cron_operations_scheduled_fire",
        "agistack_cron_operations",
        ["job_id", "scheduled_for"],
        unique=True,
        postgresql_where=sa.text("operation_kind = 'execute_run' AND trigger_type = 'scheduled'"),
    )

    op.create_table(
        "agistack_cron_request_receipts",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("actor_user_id", sa.String(), nullable=False),
        sa.Column("operation", sa.String(length=40), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("request_hash", sa.String(length=128), nullable=False),
        sa.Column("resource_kind", sa.String(length=40), nullable=False),
        sa.Column("resource_id", sa.String(), nullable=True),
        sa.Column("operation_id", sa.String(), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column(
            "response_json_redacted",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_agistack_cron_request_receipts_expiry",
        "agistack_cron_request_receipts",
        ["expires_at"],
        unique=False,
    )
    op.create_index(
        "uq_agistack_cron_request_receipts_intent",
        "agistack_cron_request_receipts",
        ["project_id", "actor_user_id", "operation", "idempotency_key"],
        unique=True,
    )

    op.create_table(
        "agistack_cron_scheduler_owners",
        sa.Column("scope_id", sa.String(length=100), nullable=False),
        sa.Column(
            "owner_kind",
            sa.String(length=20),
            server_default=sa.text("'off'"),
            nullable=False,
        ),
        sa.Column("owner_id", sa.String(length=255), nullable=True),
        sa.Column("owner_epoch", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("lease_token", sa.String(length=255), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("scope_id"),
    )

    op.create_table(
        "agistack_cron_schedule_state",
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("schedule_revision", sa.BigInteger(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default=sa.text("'active'"),
            nullable=False,
        ),
        sa.Column("schedule_fingerprint", sa.String(length=128), nullable=False),
        sa.Column("next_fire_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_fire_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=100), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["job_id"], ["cron_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("job_id"),
    )
    op.create_index(
        "ix_agistack_cron_schedule_state_due",
        "agistack_cron_schedule_state",
        ["status", "next_fire_at"],
        unique=False,
    )
    op.create_index(
        "ix_agistack_cron_schedule_state_project",
        "agistack_cron_schedule_state",
        ["project_id", "status"],
        unique=False,
    )

    op.execute(
        """
        CREATE FUNCTION agistack_bump_cron_job_revisions()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            NEW.revision := OLD.revision + 1;
            IF ROW(
                NEW.enabled,
                NEW.schedule_type,
                NEW.schedule_config::jsonb,
                NEW.timezone,
                NEW.stagger_seconds
            ) IS DISTINCT FROM ROW(
                OLD.enabled,
                OLD.schedule_type,
                OLD.schedule_config::jsonb,
                OLD.timezone,
                OLD.stagger_seconds
            ) THEN
                NEW.schedule_revision := OLD.schedule_revision + 1;
            ELSE
                NEW.schedule_revision := OLD.schedule_revision;
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_agistack_bump_cron_job_revisions
        BEFORE UPDATE ON cron_jobs
        FOR EACH ROW
        EXECUTE FUNCTION agistack_bump_cron_job_revisions()
        """
    )


def downgrade() -> None:
    """Remove durable automation foundation records and revision fencing."""
    op.execute("DROP TRIGGER IF EXISTS trg_agistack_bump_cron_job_revisions ON cron_jobs")
    op.execute("DROP FUNCTION IF EXISTS agistack_bump_cron_job_revisions()")

    op.drop_table("agistack_cron_schedule_state")
    op.drop_table("agistack_cron_scheduler_owners")
    op.drop_table("agistack_cron_request_receipts")
    op.drop_table("agistack_cron_operations")

    op.drop_column("cron_jobs", "schedule_revision")
    op.drop_column("cron_jobs", "revision")
