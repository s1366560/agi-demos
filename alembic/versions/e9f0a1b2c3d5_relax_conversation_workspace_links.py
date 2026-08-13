"""Relax conversation links for Avernet-owned workspaces.

Revision ID: e9f0a1b2c3d5
Revises: 727ce1982b0f
Create Date: 2026-08-12
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "e9f0a1b2c3d5"
down_revision: str | Sequence[str] | None = "727ce1982b0f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DROP_WORKSPACE_LINK_FOREIGN_KEYS_SQL = """
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
                    ARRAY[
                        'fk_conversations_workspace_id',
                        'conversations_workspace_id_fkey'
                    ]::text[]
                ),
                (
                    'linked_workspace_task_id'::text,
                    'workspace_tasks'::text,
                    'id'::text,
                    ARRAY[
                        'fk_conversations_linked_workspace_task_id',
                        'conversations_linked_workspace_task_id_fkey'
                    ]::text[]
                )
        ) AS expected(source_column, target_table, target_column, allowed_names)
    LOOP
        SELECT attnum
        INTO STRICT source_attribute
        FROM pg_attribute
        WHERE attrelid = 'conversations'::regclass
          AND attname = relation.source_column
          AND NOT attisdropped;

        SELECT attnum
        INTO STRICT target_attribute
        FROM pg_attribute
        WHERE attrelid = format('%I', relation.target_table)::regclass
          AND attname = relation.target_column
          AND NOT attisdropped;

        SELECT coalesce(array_agg(constraint_record.conname ORDER BY constraint_record.conname), '{}')
        INTO relevant_names
        FROM pg_constraint constraint_record
        WHERE constraint_record.conrelid = 'conversations'::regclass
          AND constraint_record.contype = 'f'
          AND source_attribute = ANY(constraint_record.conkey);

        IF EXISTS (
            SELECT 1
            FROM unnest(relevant_names) AS relevant_name
            WHERE NOT relevant_name = ANY(relation.allowed_names)
        ) THEN
            RAISE EXCEPTION
                'unexpected legacy conversation Workspace FK for column %: %',
                relation.source_column,
                relevant_names;
        END IF;

        SELECT coalesce(array_agg(constraint_record.conname ORDER BY constraint_record.conname), '{}')
        INTO candidate_names
        FROM pg_constraint constraint_record
        WHERE constraint_record.conrelid = 'conversations'::regclass
          AND constraint_record.contype = 'f'
          AND constraint_record.conname = ANY(relation.allowed_names)
          AND constraint_record.conkey = ARRAY[source_attribute]::smallint[]
          AND constraint_record.confrelid = format('%I', relation.target_table)::regclass
          AND constraint_record.confkey = ARRAY[target_attribute]::smallint[]
          AND constraint_record.confdeltype = 'n';

        IF cardinality(relevant_names) <> 1 OR cardinality(candidate_names) <> 1 THEN
            RAISE EXCEPTION
                'missing legacy conversation Workspace FK for column %; found=% valid=%',
                relation.source_column,
                relevant_names,
                candidate_names;
        END IF;

        EXECUTE format(
            'ALTER TABLE conversations DROP CONSTRAINT %I',
            candidate_names[1]
        );
    END LOOP;
END
$$
"""

_RESTORE_WORKSPACE_LINK_FOREIGN_KEYS_SQL = (
    "ALTER TABLE conversations ADD CONSTRAINT fk_conversations_workspace_id "
    "FOREIGN KEY (workspace_id) REFERENCES workspaces (id) ON DELETE SET NULL",
    "ALTER TABLE conversations ADD CONSTRAINT fk_conversations_linked_workspace_task_id "
    "FOREIGN KEY (linked_workspace_task_id) REFERENCES workspace_tasks (id) ON DELETE SET NULL",
)


def upgrade() -> None:
    """Turn legacy Workspace FKs into external authority correlations."""
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(_DROP_WORKSPACE_LINK_FOREIGN_KEYS_SQL)


def downgrade() -> None:
    """Restore legacy FKs after rejecting correlations absent from legacy tables."""
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM conversations conversation
                LEFT JOIN workspaces workspace ON workspace.id = conversation.workspace_id
                WHERE conversation.workspace_id IS NOT NULL AND workspace.id IS NULL
            ) OR EXISTS (
                SELECT 1
                FROM conversations conversation
                LEFT JOIN workspace_tasks task
                    ON task.id = conversation.linked_workspace_task_id
                WHERE conversation.linked_workspace_task_id IS NOT NULL AND task.id IS NULL
            ) THEN
                RAISE EXCEPTION
                    'cannot restore legacy conversation Workspace FKs while Avernet correlations exist';
            END IF;
        END
        $$
        """
    )
    for statement in _RESTORE_WORKSPACE_LINK_FOREIGN_KEYS_SQL:
        op.execute(statement)
