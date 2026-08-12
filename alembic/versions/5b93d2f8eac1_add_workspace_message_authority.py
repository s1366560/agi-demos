"""Add idempotent Workspace message authority fields.

Revision ID: 5b93d2f8eac1
Revises: 4a82c1e7d9b0
Create Date: 2026-08-11
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "5b93d2f8eac1"
down_revision: str | Sequence[str] | None = "4a82c1e7d9b0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE_DDL: tuple[str, ...] = (
    """
    ALTER TABLE avernet.workspace_message_correlations
        ADD COLUMN idempotency_key VARCHAR(255),
        ADD COLUMN request_hash CHAR(64),
        ADD COLUMN event_outbox_id VARCHAR(128)
    """,
    """
    ALTER TABLE avernet.workspace_message_correlations
        ADD CONSTRAINT ck_workspace_message_correlations_authority_triplet
            CHECK (
                (idempotency_key IS NULL AND request_hash IS NULL AND event_outbox_id IS NULL)
                OR
                (idempotency_key IS NOT NULL AND request_hash IS NOT NULL
                    AND event_outbox_id IS NOT NULL)
            ),
        ADD CONSTRAINT ck_workspace_message_correlations_request_hash
            CHECK (request_hash IS NULL OR request_hash ~ '^[0-9a-f]{64}$'),
        ADD CONSTRAINT uq_workspace_message_correlations_idempotency
            UNIQUE (workspace_id, idempotency_key),
        ADD CONSTRAINT fk_workspace_message_correlations_outbox
            FOREIGN KEY (event_outbox_id)
            REFERENCES avernet.workspace_outbox (outbox_id)
    """,
    """
    CREATE INDEX ix_avn_bcs_messages_mentions_gin
        ON avernet.bcs_messages USING GIN (mentions_json)
    """,
)

_DOWNGRADE_DDL: tuple[str, ...] = (
    """
    DO $$
    BEGIN
        IF EXISTS (
            SELECT 1
            FROM avernet.workspace_message_correlations
            WHERE idempotency_key IS NOT NULL
               OR request_hash IS NOT NULL
               OR event_outbox_id IS NOT NULL
        ) THEN
            RAISE EXCEPTION
                'workspace_message_correlations contains new message authority data';
        END IF;
    END
    $$
    """,
    "DROP INDEX IF EXISTS avernet.ix_avn_bcs_messages_mentions_gin",
    """
    ALTER TABLE avernet.workspace_message_correlations
        DROP CONSTRAINT IF EXISTS fk_workspace_message_correlations_outbox,
        DROP CONSTRAINT IF EXISTS uq_workspace_message_correlations_idempotency,
        DROP CONSTRAINT IF EXISTS ck_workspace_message_correlations_request_hash,
        DROP CONSTRAINT IF EXISTS ck_workspace_message_correlations_authority_triplet,
        DROP COLUMN IF EXISTS event_outbox_id,
        DROP COLUMN IF EXISTS request_hash,
        DROP COLUMN IF EXISTS idempotency_key
    """,
)


def _execute_all(statements: Sequence[str]) -> None:
    for statement in statements:
        op.execute(sa.text(statement))


def upgrade() -> None:
    _execute_all(_UPGRADE_DDL)


def downgrade() -> None:
    _execute_all(_DOWNGRADE_DDL)
