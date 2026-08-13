"""add task session saga journal

Revision ID: f0a1b2c3d4e6
Revises: e9f0a1b2c3d5
Create Date: 2026-08-13 00:00:00

"""

from collections.abc import Sequence

from alembic import op

revision: str = "f0a1b2c3d4e6"
down_revision: str | Sequence[str] | None = "e9f0a1b2c3d5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DROP_LEGACY_RECEIPT_FOREIGN_KEYS_SQL = """
DO $$
DECLARE
    relation record;
    source_attribute smallint;
    target_attribute smallint;
    relevant_names text[];
    candidate_names text[];
BEGIN
    FOR relation IN
        SELECT *
        FROM (
            VALUES
                (
                    'workspace_id'::text,
                    'workspaces'::text,
                    'id'::text,
                    'c'::"char",
                    ARRAY[
                        'fk_task_session_receipts_workspace_id',
                        'task_session_creation_receipts_workspace_id_fkey'
                    ]::text[]
                ),
                (
                    'initial_message_id'::text,
                    'workspace_messages'::text,
                    'id'::text,
                    'n'::"char",
                    ARRAY[
                        'fk_task_session_receipts_initial_message_id',
                        'task_session_creation_receipts_initial_message_id_fkey'
                    ]::text[]
                )
        ) AS expected(
            source_column,
            target_table,
            target_column,
            delete_action,
            allowed_names
        )
    LOOP
        SELECT attnum
        INTO STRICT source_attribute
        FROM pg_attribute
        WHERE attrelid = 'task_session_creation_receipts'::regclass
          AND attname = relation.source_column
          AND NOT attisdropped;

        SELECT attnum
        INTO target_attribute
        FROM pg_attribute
        WHERE attrelid = to_regclass(format('%I', relation.target_table))
          AND attname = relation.target_column
          AND NOT attisdropped;

        SELECT coalesce(array_agg(constraint_record.conname ORDER BY constraint_record.conname), '{}')
        INTO relevant_names
        FROM pg_constraint constraint_record
        WHERE constraint_record.conrelid = 'task_session_creation_receipts'::regclass
          AND constraint_record.contype = 'f'
          AND source_attribute = ANY(constraint_record.conkey);

        IF EXISTS (
            SELECT 1
            FROM unnest(relevant_names) AS relevant_name
            WHERE NOT relevant_name = ANY(relation.allowed_names)
        ) THEN
            RAISE EXCEPTION
                'unexpected legacy task-session receipt FK for column %: %',
                relation.source_column,
                relevant_names;
        END IF;

        SELECT coalesce(array_agg(constraint_record.conname ORDER BY constraint_record.conname), '{}')
        INTO candidate_names
        FROM pg_constraint constraint_record
        WHERE constraint_record.conrelid = 'task_session_creation_receipts'::regclass
          AND constraint_record.contype = 'f'
          AND constraint_record.conname = ANY(relation.allowed_names)
          AND constraint_record.conkey = ARRAY[source_attribute]::smallint[]
          AND constraint_record.confrelid = to_regclass(format('%I', relation.target_table))
          AND constraint_record.confkey = ARRAY[target_attribute]::smallint[]
          AND constraint_record.confdeltype = relation.delete_action;

        IF cardinality(relevant_names) > 1 OR cardinality(candidate_names) > 1 THEN
            RAISE EXCEPTION
                'ambiguous legacy task-session receipt FK for column %; found=% valid=%',
                relation.source_column,
                relevant_names,
                candidate_names;
        END IF;

        IF cardinality(candidate_names) = 1 THEN
            EXECUTE format(
                'ALTER TABLE task_session_creation_receipts DROP CONSTRAINT %I',
                candidate_names[1]
            );
        ELSIF cardinality(relevant_names) <> 0 THEN
            RAISE EXCEPTION
                'invalid legacy task-session receipt FK for column %; found=% valid=%',
                relation.source_column,
                relevant_names,
                candidate_names;
        END IF;
    END LOOP;
END
$$
"""

_UPGRADE_STATEMENTS = (
    "SET LOCAL lock_timeout = '10s'",
    _DROP_LEGACY_RECEIPT_FOREIGN_KEYS_SQL,
    "DROP TRIGGER IF EXISTS trg_task_session_receipt_message_delete ON workspace_messages",
    """
    CREATE OR REPLACE FUNCTION tombstone_task_session_creation_receipt()
    RETURNS trigger
    LANGUAGE plpgsql
    AS $$
    BEGIN
        UPDATE task_session_creation_receipts
        SET conversation_id = NULL,
            initial_message_id = NULL,
            response_json = json_build_object('tombstone', true)
        WHERE conversation_id = OLD.id;
        RETURN OLD;
    END;
    $$
    """,
    """
    ALTER TABLE task_session_creation_receipts
        ADD COLUMN core_receipt_id VARCHAR(128),
        ADD COLUMN status VARCHAR(32) NOT NULL DEFAULT 'pending',
        ADD COLUMN last_error TEXT,
        ADD COLUMN updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        ADD CONSTRAINT ck_task_session_receipts_status
            CHECK (status IN ('pending', 'core_committed', 'completed', 'retryable_error'))
    """,
    """
    CREATE INDEX ix_task_session_receipts_status_updated
    ON task_session_creation_receipts (tenant_id, project_id, status, updated_at)
    """,
    """
    CREATE UNIQUE INDEX uq_avn_workspace_task_receipts_task_session_scope
    ON avernet.workspace_task_receipts (tenant_id, project_id, actor_id, idempotency_key)
    WHERE action = 'create_task_session'
    """,
)

_RESTORE_LEGACY_RECEIPT_FOREIGN_KEYS_SQL = """
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM task_session_creation_receipts receipt
        LEFT JOIN workspaces workspace ON workspace.id = receipt.workspace_id
        WHERE workspace.id IS NULL
    ) OR EXISTS (
        SELECT 1
        FROM task_session_creation_receipts receipt
        LEFT JOIN workspace_messages message ON message.id = receipt.initial_message_id
        WHERE receipt.initial_message_id IS NOT NULL
          AND message.id IS NULL
    ) THEN
        RAISE EXCEPTION
            'cannot restore legacy task-session receipt FKs while external correlations exist';
    END IF;
END
$$
"""

_DOWNGRADE_STATEMENTS = (
    "SET LOCAL lock_timeout = '10s'",
    _RESTORE_LEGACY_RECEIPT_FOREIGN_KEYS_SQL,
    """
    ALTER TABLE task_session_creation_receipts
        ADD CONSTRAINT fk_task_session_receipts_workspace_id
            FOREIGN KEY (workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE,
        ADD CONSTRAINT fk_task_session_receipts_initial_message_id
            FOREIGN KEY (initial_message_id)
            REFERENCES workspace_messages (id) ON DELETE SET NULL
    """,
    """
    CREATE OR REPLACE FUNCTION tombstone_task_session_creation_receipt()
    RETURNS trigger
    LANGUAGE plpgsql
    AS $$
    BEGIN
        IF TG_TABLE_NAME = 'conversations' THEN
            UPDATE task_session_creation_receipts
            SET conversation_id = NULL,
                initial_message_id = NULL,
                response_json = json_build_object('tombstone', true)
            WHERE conversation_id = OLD.id;
        ELSIF TG_TABLE_NAME = 'workspace_messages' THEN
            UPDATE task_session_creation_receipts
            SET conversation_id = NULL,
                initial_message_id = NULL,
                response_json = json_build_object('tombstone', true)
            WHERE initial_message_id = OLD.id;
        END IF;
        RETURN OLD;
    END;
    $$
    """,
    """
    CREATE TRIGGER trg_task_session_receipt_message_delete
    BEFORE DELETE ON workspace_messages
    FOR EACH ROW
    EXECUTE FUNCTION tombstone_task_session_creation_receipt()
    """,
    "DROP INDEX avernet.uq_avn_workspace_task_receipts_task_session_scope",
    "DROP INDEX ix_task_session_receipts_status_updated",
    """
    ALTER TABLE task_session_creation_receipts
        DROP CONSTRAINT ck_task_session_receipts_status,
        DROP COLUMN updated_at,
        DROP COLUMN last_error,
        DROP COLUMN status,
        DROP COLUMN core_receipt_id
    """,
)


def upgrade() -> None:
    """Turn the legacy task-session receipt into a Core saga journal."""
    for statement in _UPGRADE_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    """Restore the legacy receipt relations when all correlations still exist."""
    for statement in _DOWNGRADE_STATEMENTS:
        op.execute(statement)
