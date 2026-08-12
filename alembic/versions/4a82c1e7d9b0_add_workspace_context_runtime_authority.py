"""Add durable Workspace Context runtime authority.

Revision ID: 4a82c1e7d9b0
Revises: 3f971b85c2da
Create Date: 2026-08-11

Context routes remain fail-closed until their request hash, Agent judgment
scope, and dedicated durable outbox can be persisted atomically. Existing
Context events are rejected during upgrade because they predate the replay
hash contract and cannot be reconstructed without changing idempotency
semantics.
"""

from collections.abc import Iterable

import sqlalchemy as sa

from alembic import op

revision = "4a82c1e7d9b0"
down_revision = "3f971b85c2da"
branch_labels = None
depends_on = None

_TABLE_DDL: tuple[str, ...] = (
    """
    CREATE TABLE avernet.workspace_context_outbox (
        outbox_id VARCHAR(128) PRIMARY KEY,
        user_id VARCHAR(128) NOT NULL,
        tenant_id VARCHAR(128) NOT NULL,
        project_id VARCHAR(128) NOT NULL,
        event_type VARCHAR(80) NOT NULL,
        stream_name VARCHAR(256) NOT NULL,
        event_sequence BIGINT NOT NULL,
        payload_json JSONB NOT NULL,
        metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        actor_api_key_id VARCHAR(128),
        idempotency_key VARCHAR(256) NOT NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'pending',
        attempt_count INTEGER NOT NULL DEFAULT 0,
        max_attempts INTEGER NOT NULL DEFAULT 12,
        next_attempt_at TIMESTAMPTZ,
        lease_owner VARCHAR(255),
        lease_expires_at TIMESTAMPTZ,
        dispatched_at TIMESTAMPTZ,
        last_error TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT uq_workspace_context_outbox_intent
            UNIQUE (user_id, idempotency_key),
        CONSTRAINT uq_workspace_context_outbox_sequence
            UNIQUE (user_id, event_sequence),
        CONSTRAINT ck_workspace_context_outbox_status
            CHECK (status IN ('pending', 'dispatching', 'retry', 'dispatched', 'dead_letter')),
        CONSTRAINT ck_workspace_context_outbox_attempts
            CHECK (attempt_count >= 0 AND max_attempts > 0),
        CONSTRAINT ck_workspace_context_outbox_sequence
            CHECK (event_sequence >= 0),
        CONSTRAINT ck_workspace_context_outbox_lease
            CHECK (
                (status = 'dispatching') =
                (lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)
            ),
        CONSTRAINT ck_workspace_context_outbox_dispatched
            CHECK (dispatched_at IS NULL OR status = 'dispatched')
    )
    """,
)

_UPGRADE_DDL: tuple[str, ...] = (
    """
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM avernet.workspace_context_events) THEN
            RAISE EXCEPTION
                'workspace_context_events must be empty before request_hash authority is enabled';
        END IF;
    END
    $$
    """,
    """
    ALTER TABLE avernet.workspace_context_events
        ADD COLUMN request_hash CHAR(64) NOT NULL,
        ADD CONSTRAINT ck_workspace_context_events_request_hash
            CHECK (request_hash ~ '^[0-9a-f]{64}$')
    """,
    """
    ALTER TABLE avernet.workspace_judge_audits
        ALTER COLUMN tenant_id DROP NOT NULL,
        ALTER COLUMN project_id DROP NOT NULL,
        ADD COLUMN user_id VARCHAR(128),
        ADD CONSTRAINT ck_workspace_judge_audits_scope_pair
            CHECK ((tenant_id IS NULL) = (project_id IS NULL)),
        ADD CONSTRAINT ck_workspace_judge_audits_scope
            CHECK (tenant_id IS NOT NULL OR user_id IS NOT NULL)
    """,
    *_TABLE_DDL,
    """
    CREATE INDEX ix_avn_ws_judge_audits_user_created
        ON avernet.workspace_judge_audits (user_id, created_at DESC)
        WHERE user_id IS NOT NULL
    """,
    """
    CREATE INDEX ix_avn_ws_context_outbox_ready
        ON avernet.workspace_context_outbox
            (status, next_attempt_at, created_at, outbox_id)
        WHERE status IN ('pending', 'retry')
    """,
    """
    CREATE INDEX ix_avn_ws_context_outbox_reclaim
        ON avernet.workspace_context_outbox (lease_expires_at, outbox_id)
        WHERE status = 'dispatching'
    """,
    """
    CREATE TRIGGER trg_workspace_context_outbox_touch_updated_at
    BEFORE UPDATE ON avernet.workspace_context_outbox
    FOR EACH ROW EXECUTE FUNCTION avernet.touch_updated_at()
    """,
)

_DOWNGRADE_DDL: tuple[str, ...] = (
    "DROP TABLE IF EXISTS avernet.workspace_context_outbox",
    "DROP INDEX IF EXISTS avernet.ix_avn_ws_judge_audits_user_created",
    """
    DO $$
    BEGIN
        IF EXISTS (
            SELECT 1
            FROM avernet.workspace_judge_audits
            WHERE tenant_id IS NULL OR project_id IS NULL
        ) THEN
            RAISE EXCEPTION
                'Context-scoped Judge audits must be exported before downgrade';
        END IF;
    END
    $$
    """,
    """
    ALTER TABLE avernet.workspace_judge_audits
        DROP CONSTRAINT ck_workspace_judge_audits_scope,
        DROP CONSTRAINT ck_workspace_judge_audits_scope_pair,
        DROP COLUMN user_id,
        ALTER COLUMN project_id SET NOT NULL,
        ALTER COLUMN tenant_id SET NOT NULL
    """,
    """
    ALTER TABLE avernet.workspace_context_events
        DROP CONSTRAINT ck_workspace_context_events_request_hash,
        DROP COLUMN request_hash
    """,
)


def _execute_all(statements: Iterable[str]) -> None:
    for statement in statements:
        op.execute(sa.text(statement))


def upgrade() -> None:
    _execute_all(_UPGRADE_DDL)


def downgrade() -> None:
    _execute_all(_DOWNGRADE_DDL)
