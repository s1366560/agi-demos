"""Split Workspace outbox publication attempts from Plan runtime dispatch.

Revision ID: 8e26a5c9d0f4
Revises: 7d15f4b8c9e3
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "8e26a5c9d0f4"
down_revision: str | Sequence[str] | None = "7d15f4b8c9e3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PLAN_RUNTIME_EVENT_TYPES = (
    "operator_stale_attempt_recovery_requested",
    "operator_iteration_next_requested",
    "workspace_pipeline_run_requested",
    "delivery_contract_regeneration_requested",
)

_PLAN_RUNTIME_EVENTS_SQL = ", ".join(f"'{event_type}'" for event_type in _PLAN_RUNTIME_EVENT_TYPES)

_UPGRADE_DDL: tuple[str, ...] = (
    """
    ALTER TABLE avernet.workspace_outbox
        ADD COLUMN publication_attempt_count INTEGER NOT NULL DEFAULT 0,
        ADD COLUMN publication_max_attempts INTEGER NOT NULL DEFAULT 10,
        ADD CONSTRAINT ck_workspace_outbox_publication_attempts
            CHECK (
                publication_attempt_count >= 0
                AND publication_max_attempts > 0
            )
    """,
    f"""
    UPDATE avernet.workspace_outbox
    SET publication_attempt_count = attempt_count,
        publication_max_attempts = max_attempts
    WHERE event_type NOT IN ({_PLAN_RUNTIME_EVENTS_SQL})
    """,
    """
    CREATE INDEX ix_avn_ws_outbox_publication_ready
        ON avernet.workspace_outbox (
            status,
            next_attempt_at,
            publication_attempt_count,
            created_at,
            outbox_id
        )
    """,
)

_DOWNGRADE_DDL: tuple[str, ...] = (
    "DROP INDEX IF EXISTS avernet.ix_avn_ws_outbox_publication_ready",
    """
    ALTER TABLE avernet.workspace_outbox
        DROP CONSTRAINT IF EXISTS ck_workspace_outbox_publication_attempts,
        DROP COLUMN IF EXISTS publication_max_attempts,
        DROP COLUMN IF EXISTS publication_attempt_count
    """,
)


def upgrade() -> None:
    for statement in _UPGRADE_DDL:
        op.execute(statement)


def downgrade() -> None:
    for statement in _DOWNGRADE_DDL:
        op.execute(statement)
