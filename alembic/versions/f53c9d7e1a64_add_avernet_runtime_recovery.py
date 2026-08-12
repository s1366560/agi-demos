"""Add durable Avernet Agent Runtime recovery and callback acknowledgement fields.

Revision ID: f53c9d7e1a64
Revises: e42b8c6d0f53
Create Date: 2026-08-10
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "f53c9d7e1a64"
down_revision: str | Sequence[str] | None = "e42b8c6d0f53"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE_DDL: tuple[str, ...] = (
    """
    ALTER TABLE avernet.workspace_agent_runtime_correlations
        ADD COLUMN user_id VARCHAR(128),
        ADD COLUMN bcs_group_id VARCHAR(128),
        ADD COLUMN provider_id VARCHAR(128),
        ADD COLUMN provider_bot_ref VARCHAR(191),
        ADD COLUMN recovery_lease_owner VARCHAR(191),
        ADD COLUMN recovery_lease_expires_at TIMESTAMPTZ,
        ADD COLUMN recovery_attempt_count INTEGER NOT NULL DEFAULT 0,
        ADD COLUMN recovery_disposition VARCHAR(32),
        ADD COLUMN callback_completed_at TIMESTAMPTZ,
        ADD COLUMN callback_attempt_count INTEGER NOT NULL DEFAULT 0,
        ADD CONSTRAINT ck_workspace_runtime_recovery_attempts
            CHECK (recovery_attempt_count >= 0),
        ADD CONSTRAINT ck_workspace_runtime_callback_attempts
            CHECK (callback_attempt_count >= 0)
    """,
    """
    CREATE INDEX ix_avn_ws_runtime_recovery_ready
        ON avernet.workspace_agent_runtime_correlations
        (status, callback_completed_at, recovery_lease_expires_at, updated_at)
    """,
)

_DOWNGRADE_DDL: tuple[str, ...] = (
    "DROP INDEX IF EXISTS avernet.ix_avn_ws_runtime_recovery_ready",
    """
    ALTER TABLE avernet.workspace_agent_runtime_correlations
        DROP CONSTRAINT IF EXISTS ck_workspace_runtime_callback_attempts,
        DROP CONSTRAINT IF EXISTS ck_workspace_runtime_recovery_attempts,
        DROP COLUMN IF EXISTS callback_attempt_count,
        DROP COLUMN IF EXISTS callback_completed_at,
        DROP COLUMN IF EXISTS recovery_disposition,
        DROP COLUMN IF EXISTS recovery_attempt_count,
        DROP COLUMN IF EXISTS recovery_lease_expires_at,
        DROP COLUMN IF EXISTS recovery_lease_owner,
        DROP COLUMN IF EXISTS provider_bot_ref,
        DROP COLUMN IF EXISTS provider_id,
        DROP COLUMN IF EXISTS bcs_group_id,
        DROP COLUMN IF EXISTS user_id
    """,
)


def upgrade() -> None:
    for statement in _UPGRADE_DDL:
        op.execute(statement)


def downgrade() -> None:
    for statement in _DOWNGRADE_DDL:
        op.execute(statement)
