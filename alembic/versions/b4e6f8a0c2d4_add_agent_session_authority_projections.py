"""add agent session authority projections

Revision ID: b4e6f8a0c2d4
Revises: a3d5f7b9c1e2
Create Date: 2026-08-04 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b4e6f8a0c2d4"
down_revision: str | None = "a3d5f7b9c1e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_AUTHORITY_TABLE = "agent_run_authorities"
_LEGACY_PROJECTION_TABLES = frozenset(
    {"agent_run_inputs", "agent_run_summaries", "activity_read_receipts"}
)
_RUN_INPUT_BASE_COLUMNS = frozenset(
    {
        "id",
        "tenant_id",
        "project_id",
        "conversation_id",
        "run_id",
        "actor_user_id",
        "expected_run_revision",
        "message",
        "message_id",
        "idempotency_key",
        "payload_hash",
        "delivery",
        "references_json",
        "context_items_json",
        "status",
        "sequence",
        "queue_position",
        "applied_round",
        "applied_at",
        "injected_via",
        "promoted_run_id",
        "promotion_key",
        "promoted_at",
        "created_at",
        "updated_at",
    }
)
_RUN_SUMMARY_REQUIRED_COLUMNS = frozenset(
    {
        "id",
        "tenant_id",
        "project_id",
        "conversation_id",
        "run_id",
        "status",
        "revision",
        "summary_state",
        "model_breakdown_json",
        "evidence_references_json",
        "created_at",
        "updated_at",
    }
)
_ACTIVITY_REQUIRED_COLUMNS = frozenset(
    {
        "id",
        "tenant_id",
        "project_id",
        "user_id",
        "entry_id",
        "entry_revision",
        "revision",
        "read_at",
        "created_at",
        "updated_at",
    }
)


def _column_names(inspector: sa.Inspector, table_name: str) -> set[str]:
    return {str(column["name"]) for column in inspector.get_columns(table_name)}


def _check_names(inspector: sa.Inspector, table_name: str) -> set[str]:
    return {
        str(constraint["name"])
        for constraint in inspector.get_check_constraints(table_name)
        if constraint.get("name")
    }


def _require_columns(
    inspector: sa.Inspector,
    table_name: str,
    required_columns: frozenset[str],
) -> set[str]:
    columns = _column_names(inspector, table_name)
    missing = required_columns.difference(columns)
    if missing:
        raise RuntimeError(
            f"existing {table_name} is missing required columns: {', '.join(sorted(missing))}"
        )
    return columns


def _require_checks(
    inspector: sa.Inspector,
    table_name: str,
    required_checks: frozenset[str],
) -> set[str]:
    checks = _check_names(inspector, table_name)
    missing = required_checks.difference(checks)
    if missing:
        raise RuntimeError(
            f"existing {table_name} is missing required checks: {', '.join(sorted(missing))}"
        )
    return checks


def _ensure_index(
    inspector: sa.Inspector,
    table_name: str,
    index_name: str,
    columns: list[str],
) -> None:
    existing = {
        str(index["name"]) for index in inspector.get_indexes(table_name) if index.get("name")
    }
    if index_name not in existing:
        op.create_index(index_name, table_name, columns, unique=False)


def _rebind_run_authority_foreign_key(inspector: sa.Inspector, table_name: str) -> None:
    run_foreign_keys = [
        foreign_key
        for foreign_key in inspector.get_foreign_keys(table_name)
        if foreign_key.get("constrained_columns") == ["run_id"]
    ]
    if any(
        foreign_key.get("referred_table") == _AUTHORITY_TABLE for foreign_key in run_foreign_keys
    ):
        return
    for foreign_key in run_foreign_keys:
        if foreign_key.get("referred_table") != "agent_plan_runs":
            raise RuntimeError(f"existing {table_name}.run_id has an unsupported authority")
        constraint_name = foreign_key.get("name")
        if not constraint_name:
            raise RuntimeError(f"existing {table_name}.run_id foreign key is unnamed")
        op.drop_constraint(str(constraint_name), table_name, type_="foreignkey")
    op.create_foreign_key(
        f"{table_name}_run_id_fkey",
        table_name,
        _AUTHORITY_TABLE,
        ["run_id"],
        ["id"],
        ondelete="CASCADE",
    )


def _adopt_legacy_projection_tables(inspector: sa.Inspector) -> None:
    _require_columns(inspector, "agent_run_inputs", _RUN_INPUT_BASE_COLUMNS)
    input_checks = _require_checks(
        inspector,
        "agent_run_inputs",
        frozenset(
            {
                "ck_agent_run_inputs_delivery",
                "ck_agent_run_inputs_expected_revision_positive",
                "ck_agent_run_inputs_status",
            }
        ),
    )
    input_columns = _column_names(inspector, "agent_run_inputs")
    dispatch_columns = (
        sa.Column(
            "dispatch_status",
            sa.String(length=20),
            server_default="not_required",
            nullable=False,
        ),
        sa.Column(
            "dispatch_attempts",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("dispatch_lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dispatch_error_code", sa.String(length=80), nullable=True),
    )
    for column in dispatch_columns:
        if column.name not in input_columns:
            op.add_column("agent_run_inputs", column)
    if "ck_agent_run_inputs_dispatch_status" not in input_checks:
        op.create_check_constraint(
            "ck_agent_run_inputs_dispatch_status",
            "agent_run_inputs",
            "dispatch_status IN ('not_required', 'dispatching', 'dispatched', 'failed')",
        )
    if "ck_agent_run_inputs_dispatch_attempts_nonnegative" not in input_checks:
        op.create_check_constraint(
            "ck_agent_run_inputs_dispatch_attempts_nonnegative",
            "agent_run_inputs",
            "dispatch_attempts >= 0",
        )
    _rebind_run_authority_foreign_key(inspector, "agent_run_inputs")
    _ensure_index(
        inspector,
        "agent_run_inputs",
        "ix_agent_run_inputs_scope_status",
        ["tenant_id", "project_id", "conversation_id", "run_id", "status"],
    )

    _require_columns(inspector, "agent_run_summaries", _RUN_SUMMARY_REQUIRED_COLUMNS)
    _require_checks(
        inspector,
        "agent_run_summaries",
        frozenset(
            {
                "ck_agent_run_summaries_revision_positive",
                "ck_agent_run_summaries_state",
            }
        ),
    )
    _rebind_run_authority_foreign_key(inspector, "agent_run_summaries")
    _ensure_index(
        inspector,
        "agent_run_summaries",
        "ix_agent_run_summaries_scope",
        ["tenant_id", "project_id", "conversation_id", "run_id"],
    )

    _require_columns(inspector, "activity_read_receipts", _ACTIVITY_REQUIRED_COLUMNS)
    _require_checks(
        inspector,
        "activity_read_receipts",
        frozenset(
            {
                "ck_activity_read_receipts_entry_revision",
                "ck_activity_read_receipts_revision_positive",
            }
        ),
    )
    _ensure_index(
        inspector,
        "activity_read_receipts",
        "ix_activity_read_receipts_scope_revision",
        ["tenant_id", "project_id", "user_id", "revision"],
    )


def _create_agent_run_authorities() -> None:
    op.create_table(
        "agent_run_authorities",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("conversation_id", sa.String(), nullable=False),
        sa.Column("run_kind", sa.String(length=20), nullable=False),
        sa.Column("plan_run_id", sa.String(), nullable=True),
        sa.Column("plan_version_id", sa.String(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("message_id", sa.String(length=255), nullable=False),
        sa.Column("request_message", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("permission_profile", sa.String(length=30), nullable=False),
        sa.Column("authorization_snapshot", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "run_kind IN ('chat', 'plan')",
            name="ck_agent_run_authorities_kind",
        ),
        sa.CheckConstraint(
            "revision >= 1",
            name="ck_agent_run_authorities_revision_positive",
        ),
        sa.CheckConstraint(
            "permission_profile IN ('read_only', 'workspace_write', 'full_access')",
            name="ck_agent_run_authorities_permission_profile",
        ),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["plan_run_id"], ["agent_plan_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["plan_version_id"], ["agent_plan_versions.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("plan_run_id"),
        sa.UniqueConstraint(
            "conversation_id",
            "idempotency_key",
            name="uq_agent_run_authorities_conversation_idempotency",
        ),
    )
    op.create_index(
        "ix_agent_run_authorities_scope_status",
        "agent_run_authorities",
        ["tenant_id", "project_id", "conversation_id", "status", "created_at"],
        unique=False,
    )


def _backfill_plan_run_authorities() -> None:
    op.execute(
        sa.text(
            """
            INSERT INTO agent_run_authorities (
                id, tenant_id, project_id, conversation_id, run_kind,
                plan_run_id, plan_version_id, idempotency_key, message_id,
                request_message, status, revision, permission_profile,
                authorization_snapshot, created_at, started_at, updated_at,
                completed_at, error
            )
            SELECT
                run.id, conversation.tenant_id, run.project_id,
                run.conversation_id, 'plan', run.id, run.plan_version_id,
                run.idempotency_key, run.message_id, run.request_message,
                run.status, run.revision, run.permission_profile,
                run.authorization_snapshot, run.created_at, NULL, run.updated_at,
                run.completed_at, run.error
            FROM agent_plan_runs AS run
            JOIN conversations AS conversation ON conversation.id = run.conversation_id
            WHERE NOT EXISTS (
                SELECT 1 FROM agent_run_authorities AS authority
                WHERE authority.id = run.id
            )
            """
        )
    )


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing_tables = set(inspector.get_table_names())
    existing_legacy_tables = existing_tables.intersection(_LEGACY_PROJECTION_TABLES)
    if existing_legacy_tables and existing_legacy_tables != _LEGACY_PROJECTION_TABLES:
        raise RuntimeError(
            "legacy Agent authority projection tables are only partially present: "
            + ", ".join(sorted(existing_legacy_tables))
        )
    if _AUTHORITY_TABLE in existing_tables:
        _require_columns(
            inspector,
            _AUTHORITY_TABLE,
            frozenset(
                {
                    "id",
                    "tenant_id",
                    "project_id",
                    "conversation_id",
                    "run_kind",
                    "idempotency_key",
                    "message_id",
                    "status",
                    "revision",
                    "authorization_snapshot",
                }
            ),
        )
    else:
        _create_agent_run_authorities()
    _backfill_plan_run_authorities()
    if existing_legacy_tables:
        _adopt_legacy_projection_tables(inspector)
        return

    op.create_table(
        "agent_run_inputs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("conversation_id", sa.String(), nullable=False),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("actor_user_id", sa.String(), nullable=False),
        sa.Column("expected_run_revision", sa.Integer(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("message_id", sa.String(length=255), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("delivery", sa.String(length=20), nullable=False),
        sa.Column("references_json", sa.JSON(), nullable=False),
        sa.Column("context_items_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("queue_position", sa.BigInteger(), nullable=True),
        sa.Column("applied_round", sa.BigInteger(), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("injected_via", sa.String(length=50), nullable=True),
        sa.Column(
            "dispatch_status",
            sa.String(length=20),
            server_default="not_required",
            nullable=False,
        ),
        sa.Column(
            "dispatch_attempts",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("dispatch_lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dispatch_error_code", sa.String(length=80), nullable=True),
        sa.Column("promoted_run_id", sa.String(), nullable=True),
        sa.Column("promotion_key", sa.String(length=255), nullable=True),
        sa.Column("promoted_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint(
            "delivery IN ('steer_now', 'queue_next')",
            name="ck_agent_run_inputs_delivery",
        ),
        sa.CheckConstraint(
            "expected_run_revision >= 1",
            name="ck_agent_run_inputs_expected_revision_positive",
        ),
        sa.CheckConstraint(
            "status IN "
            "('pending_boundary', 'queued', 'applied', 'ready', 'blocked', "
            "'promoted_to_plan')",
            name="ck_agent_run_inputs_status",
        ),
        sa.CheckConstraint(
            "dispatch_status IN ('not_required', 'dispatching', 'dispatched', 'failed')",
            name="ck_agent_run_inputs_dispatch_status",
        ),
        sa.CheckConstraint(
            "dispatch_attempts >= 0",
            name="ck_agent_run_inputs_dispatch_attempts_nonnegative",
        ),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["promoted_run_id"],
            ["agent_plan_runs.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["run_id"], ["agent_run_authorities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "run_id",
            "idempotency_key",
            name="uq_agent_run_inputs_run_idempotency",
        ),
        sa.UniqueConstraint(
            "run_id",
            "message_id",
            name="uq_agent_run_inputs_run_message",
        ),
    )
    op.create_index(
        "ix_agent_run_inputs_scope_status",
        "agent_run_inputs",
        ["tenant_id", "project_id", "conversation_id", "run_id", "status"],
        unique=False,
    )

    op.create_table(
        "agent_run_summaries",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("conversation_id", sa.String(), nullable=False),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("summary_state", sa.String(length=30), nullable=False),
        sa.Column("reason_code", sa.String(length=80), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.BigInteger(), nullable=True),
        sa.Column("input_tokens", sa.BigInteger(), nullable=True),
        sa.Column("output_tokens", sa.BigInteger(), nullable=True),
        sa.Column("cost_usd", sa.Float(), nullable=True),
        sa.Column("model_breakdown_json", sa.JSON(), nullable=False),
        sa.Column("completion_summary", sa.Text(), nullable=True),
        sa.Column("artifact_count", sa.Integer(), nullable=True),
        sa.Column("checks_passed", sa.Integer(), nullable=True),
        sa.Column("checks_failed", sa.Integer(), nullable=True),
        sa.Column("files_changed", sa.Integer(), nullable=True),
        sa.Column("lines_added", sa.Integer(), nullable=True),
        sa.Column("lines_deleted", sa.Integer(), nullable=True),
        sa.Column("evidence_references_json", sa.JSON(), nullable=False),
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
        sa.CheckConstraint(
            "revision >= 1",
            name="ck_agent_run_summaries_revision_positive",
        ),
        sa.CheckConstraint(
            "summary_state IN ('recorded', 'partial')",
            name="ck_agent_run_summaries_state",
        ),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["agent_run_authorities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id"),
    )
    op.create_index(
        "ix_agent_run_summaries_scope",
        "agent_run_summaries",
        ["tenant_id", "project_id", "conversation_id", "run_id"],
        unique=False,
    )

    op.create_table(
        "activity_read_receipts",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("entry_id", sa.String(length=255), nullable=False),
        sa.Column("entry_revision", sa.BigInteger(), nullable=False),
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=False),
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
        sa.CheckConstraint(
            "entry_revision >= 0",
            name="ck_activity_read_receipts_entry_revision",
        ),
        sa.CheckConstraint(
            "revision >= 1",
            name="ck_activity_read_receipts_revision_positive",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "project_id",
            "user_id",
            "entry_id",
            name="uq_activity_read_receipts_scope_entry",
        ),
    )
    op.create_index(
        "ix_activity_read_receipts_scope_revision",
        "activity_read_receipts",
        ["tenant_id", "project_id", "user_id", "revision"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_activity_read_receipts_scope_revision",
        table_name="activity_read_receipts",
    )
    op.drop_table("activity_read_receipts")
    op.drop_index("ix_agent_run_summaries_scope", table_name="agent_run_summaries")
    op.drop_table("agent_run_summaries")
    op.drop_index("ix_agent_run_inputs_scope_status", table_name="agent_run_inputs")
    op.drop_table("agent_run_inputs")
    op.drop_index(
        "ix_agent_run_authorities_scope_status",
        table_name="agent_run_authorities",
    )
    op.drop_table("agent_run_authorities")
