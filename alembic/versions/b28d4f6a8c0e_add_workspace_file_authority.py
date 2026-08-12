"""Add durable Workspace File object and compensation authority.

Revision ID: b28d4f6a8c0e
Revises: a17c3e5f7b9d
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "b28d4f6a8c0e"
down_revision: str | Sequence[str] | None = "a17c3e5f7b9d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UPGRADE_DDL: tuple[str, ...] = (
    """
    ALTER TABLE avernet.workspace_files
        ADD COLUMN object_state VARCHAR(16) NOT NULL DEFAULT 'ready',
        ADD COLUMN revision BIGINT NOT NULL DEFAULT 1,
        ADD COLUMN updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        ADD CONSTRAINT ck_workspace_files_object_state
            CHECK (object_state IN ('staging', 'ready')),
        ADD CONSTRAINT ck_workspace_files_revision CHECK (revision > 0)
    """,
    """
    CREATE TABLE avernet.workspace_file_operations (
        operation_id VARCHAR(128) PRIMARY KEY,
        tenant_id VARCHAR(128) NOT NULL,
        project_id VARCHAR(128) NOT NULL,
        workspace_id VARCHAR(128) NOT NULL,
        file_id VARCHAR(128) NOT NULL,
        actor_id VARCHAR(256) NOT NULL,
        action VARCHAR(64) NOT NULL,
        idempotency_key VARCHAR(256) NOT NULL,
        request_hash CHAR(64) NOT NULL,
        state VARCHAR(24) NOT NULL,
        staged_handle_json JSONB,
        ready_handle_json JSONB,
        checksum_sha256 CHAR(64),
        size_bytes BIGINT,
        last_error TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        completed_at TIMESTAMPTZ,
        CONSTRAINT fk_workspace_file_operations_profile
            FOREIGN KEY (tenant_id, project_id, workspace_id)
            REFERENCES avernet.workspace_profiles (tenant_id, project_id, workspace_id)
            ON DELETE CASCADE,
        CONSTRAINT uq_workspace_file_operations_intent
            UNIQUE (workspace_id, actor_id, idempotency_key),
        CONSTRAINT uq_workspace_file_operations_file UNIQUE (workspace_id, file_id),
        CONSTRAINT ck_workspace_file_operations_state
            CHECK (state IN ('staged', 'finalized', 'completed', 'failed')),
        CONSTRAINT ck_workspace_file_operations_hash
            CHECK (request_hash ~ '^[0-9a-f]{64}$'),
        CONSTRAINT ck_workspace_file_operations_checksum
            CHECK (checksum_sha256 IS NULL OR checksum_sha256 ~ '^[0-9a-f]{64}$'),
        CONSTRAINT ck_workspace_file_operations_size
            CHECK (size_bytes IS NULL OR size_bytes >= 0),
        CONSTRAINT ck_workspace_file_operations_handles
            CHECK (
                (state = 'staged' AND staged_handle_json IS NOT NULL)
                OR (state = 'finalized' AND ready_handle_json IS NOT NULL)
                OR state IN ('completed', 'failed')
            )
    )
    """,
    """
    CREATE TABLE avernet.workspace_file_compensations (
        compensation_id VARCHAR(128) PRIMARY KEY,
        operation_id VARCHAR(128) NOT NULL,
        tenant_id VARCHAR(128) NOT NULL,
        project_id VARCHAR(128) NOT NULL,
        workspace_id VARCHAR(128) NOT NULL,
        file_id VARCHAR(128) NOT NULL,
        compensation_kind VARCHAR(32) NOT NULL,
        object_handle_json JSONB NOT NULL,
        status VARCHAR(16) NOT NULL DEFAULT 'pending',
        attempt_count INTEGER NOT NULL DEFAULT 0,
        max_attempts INTEGER NOT NULL DEFAULT 20,
        next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        lease_owner VARCHAR(255),
        lease_expires_at TIMESTAMPTZ,
        last_error TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        completed_at TIMESTAMPTZ,
        CONSTRAINT fk_workspace_file_compensations_profile
            FOREIGN KEY (tenant_id, project_id, workspace_id)
            REFERENCES avernet.workspace_profiles (tenant_id, project_id, workspace_id)
            ON DELETE CASCADE,
        CONSTRAINT uq_workspace_file_compensations_intent
            UNIQUE (operation_id, compensation_kind),
        CONSTRAINT ck_workspace_file_compensations_kind
            CHECK (compensation_kind IN (
                'abort_stage', 'delete_ready', 'persist_finalize', 'activate_metadata'
            )),
        CONSTRAINT ck_workspace_file_compensations_status
            CHECK (status IN ('pending', 'leased', 'completed', 'dead_letter')),
        CONSTRAINT ck_workspace_file_compensations_attempts
            CHECK (attempt_count >= 0 AND max_attempts > 0 AND attempt_count <= max_attempts),
        CONSTRAINT ck_workspace_file_compensations_lease
            CHECK (
                (status = 'leased' AND lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)
                OR (status <> 'leased' AND lease_owner IS NULL AND lease_expires_at IS NULL)
            ),
        CONSTRAINT ck_workspace_file_compensations_completed
            CHECK ((status = 'completed') = (completed_at IS NOT NULL))
    )
    """,
    """
    CREATE INDEX ix_avn_workspace_file_operations_state
        ON avernet.workspace_file_operations (state, updated_at)
    """,
    """
    CREATE INDEX ix_avn_workspace_file_compensations_ready
        ON avernet.workspace_file_compensations (status, next_attempt_at)
        WHERE status IN ('pending', 'leased')
    """,
    """
    CREATE TRIGGER trg_workspace_files_touch_updated_at
    BEFORE UPDATE ON avernet.workspace_files
    FOR EACH ROW EXECUTE FUNCTION avernet.touch_updated_at()
    """,
    """
    CREATE TRIGGER trg_workspace_file_operations_touch_updated_at
    BEFORE UPDATE ON avernet.workspace_file_operations
    FOR EACH ROW EXECUTE FUNCTION avernet.touch_updated_at()
    """,
    """
    CREATE TRIGGER trg_workspace_file_compensations_touch_updated_at
    BEFORE UPDATE ON avernet.workspace_file_compensations
    FOR EACH ROW EXECUTE FUNCTION avernet.touch_updated_at()
    """,
    """
    REVOKE ALL ON TABLE avernet.workspace_file_operations FROM PUBLIC
    """,
    """
    REVOKE ALL ON TABLE avernet.workspace_file_compensations FROM PUBLIC
    """,
)

_DOWNGRADE_DDL: tuple[str, ...] = (
    """
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM avernet.workspace_file_operations)
            OR EXISTS (SELECT 1 FROM avernet.workspace_file_compensations)
        THEN
            RAISE EXCEPTION
                'Workspace File authority contains durable operation or compensation data';
        END IF;
        IF EXISTS (
            SELECT 1 FROM avernet.workspace_files
            WHERE object_state <> 'ready' OR revision <> 1
        ) THEN
            RAISE EXCEPTION
                'workspace_files contains new authority state that cannot be downgraded';
        END IF;
    END
    $$
    """,
    "DROP TRIGGER IF EXISTS trg_workspace_file_compensations_touch_updated_at ON avernet.workspace_file_compensations",
    "DROP TRIGGER IF EXISTS trg_workspace_file_operations_touch_updated_at ON avernet.workspace_file_operations",
    "DROP TRIGGER IF EXISTS trg_workspace_files_touch_updated_at ON avernet.workspace_files",
    "DROP INDEX IF EXISTS avernet.ix_avn_workspace_file_compensations_ready",
    "DROP INDEX IF EXISTS avernet.ix_avn_workspace_file_operations_state",
    "DROP TABLE avernet.workspace_file_compensations",
    "DROP TABLE avernet.workspace_file_operations",
    """
    ALTER TABLE avernet.workspace_files
        DROP CONSTRAINT ck_workspace_files_revision,
        DROP CONSTRAINT ck_workspace_files_object_state,
        DROP COLUMN updated_at,
        DROP COLUMN revision,
        DROP COLUMN object_state
    """,
)


def upgrade() -> None:
    for statement in _UPGRADE_DDL:
        op.execute(statement)


def downgrade() -> None:
    for statement in _DOWNGRADE_DDL:
        op.execute(statement)
