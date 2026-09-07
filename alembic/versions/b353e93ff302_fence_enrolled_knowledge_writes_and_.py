"""fence enrolled knowledge writes and bootstrap journals

Revision ID: b353e93ff302
Revises: a931fc278146
Create Date: 2026-09-07 15:50:15.457547

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b353e93ff302"
down_revision: str | Sequence[str] | None = "a931fc278146"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SNAPSHOT_SQL = r"""
CREATE FUNCTION knowledge_sync_snapshot(row_value memories, revision_value integer, deleted_value boolean)
RETURNS jsonb LANGUAGE sql IMMUTABLE AS $$
    SELECT jsonb_build_object(
        'memory_id', row_value.id, 'revision', revision_value, 'deleted', deleted_value,
        'author_id', row_value.author_id,
        'created_at_ms', floor(extract(epoch FROM row_value.created_at) * 1000)::bigint,
        'content', jsonb_build_object(
            'title', row_value.title, 'content', row_value.content,
            'content_type', row_value.content_type,
            'tags', coalesce(row_value.tags::jsonb, '[]'::jsonb),
            'metadata', coalesce(row_value.meta::jsonb, '{}'::jsonb),
            'status', row_value.status))
$$;
"""

PROJECT_FENCE_SQL = r"""
CREATE FUNCTION knowledge_sync_project_fence() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE active boolean;
BEGIN
    IF TG_OP = 'UPDATE' AND OLD.tenant_id IS DISTINCT FROM NEW.tenant_id THEN
        SELECT enabled INTO active FROM knowledge_sync_enrollments
            WHERE project_id = OLD.id FOR UPDATE;
        IF active THEN
            RAISE EXCEPTION USING MESSAGE = 'knowledge_sync_scope_immutable', ERRCODE = '23514';
        END IF;
        UPDATE knowledge_sync_enrollments SET tenant_id = NEW.tenant_id WHERE project_id = NEW.id;
    ELSIF TG_OP = 'INSERT' THEN
        INSERT INTO knowledge_sync_enrollments(project_id, tenant_id, enabled)
            VALUES(NEW.id, NEW.tenant_id, false);
    END IF;
    RETURN NEW;
END
$$;
"""

WRITE_GUARD_SQL = r"""
CREATE FUNCTION knowledge_sync_guard_write() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    project_value text;
    memory_value text;
    tenant_value text;
    active boolean;
    intent jsonb;
    reserved knowledge_sync_tombstones%ROWTYPE;
    old_revision integer;
    operation_value text;
    moved_fence record;
BEGIN
    IF TG_OP = 'UPDATE' AND NEW.project_id IS DISTINCT FROM OLD.project_id THEN
        FOR moved_fence IN SELECT enabled FROM knowledge_sync_enrollments
            WHERE project_id IN (OLD.project_id, NEW.project_id) ORDER BY project_id FOR SHARE LOOP
            IF moved_fence.enabled THEN
                RAISE EXCEPTION USING MESSAGE = 'knowledge_sync_scope_immutable', ERRCODE = '23514';
            END IF;
        END LOOP;
    END IF;
    IF TG_OP = 'DELETE' THEN
        project_value := OLD.project_id;
        memory_value := OLD.id;
        -- Parent deletion retires the entire scope, including its journal and
        -- fence. FK cascade trigger order must not require a per-Memory intent.
        -- A missing fence alone is insufficient: the parent must be gone too.
        IF NOT EXISTS (SELECT 1 FROM projects WHERE id = project_value) THEN
            RETURN OLD;
        END IF;
    ELSE
        project_value := NEW.project_id;
        memory_value := NEW.id;
    END IF;
    -- The row exists before any Memory write, including projects created later.
    -- SHARE permits concurrent legacy writes. Activation takes UPDATE on this
    -- same fence and reads Memory without taking Memory row locks.
    SELECT enabled, tenant_id INTO active, tenant_value
        FROM knowledge_sync_enrollments WHERE project_id = project_value FOR SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION USING MESSAGE = 'knowledge_sync_fence_missing', ERRCODE = '23514';
    END IF;
    IF TG_OP = 'INSERT' OR (TG_OP = 'UPDATE' AND NEW.id IS DISTINCT FROM OLD.id) THEN
        SELECT tomb.* INTO reserved FROM knowledge_sync_tombstones tomb
            JOIN knowledge_sync_enrollments fence ON fence.project_id = tomb.project_id
            WHERE tomb.memory_id = memory_value AND fence.enabled;
        IF FOUND AND (reserved.project_id <> project_value OR reserved.tenant_id <> tenant_value) THEN
            RAISE EXCEPTION USING MESSAGE = 'knowledge_sync_id_collision', ERRCODE = '23514';
        END IF;
    END IF;
    IF NOT active THEN
        RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
    END IF;
    IF TG_OP = 'UPDATE' THEN
        IF (NEW.id, NEW.project_id, NEW.author_id, NEW.created_at)
            IS DISTINCT FROM (OLD.id, OLD.project_id, OLD.author_id, OLD.created_at) THEN
            RAISE EXCEPTION USING MESSAGE = 'knowledge_sync_identity_immutable', ERRCODE = '23514';
        END IF;
        IF knowledge_sync_snapshot(NEW, NEW.version, false)
            = knowledge_sync_snapshot(OLD, OLD.version, false) THEN
            -- Processing status, entities, embeddings and other derived columns
            -- do not create a second content revision.
            RETURN NEW;
        END IF;
    END IF;
    intent := nullif(current_setting('memstack.knowledge_sync_intent', true), '')::jsonb;
    IF intent IS NULL OR intent->>'project_id' IS DISTINCT FROM project_value
        OR intent->>'tenant_id' IS DISTINCT FROM tenant_value
        OR intent->>'memory_id' IS DISTINCT FROM memory_value THEN
        RAISE EXCEPTION USING MESSAGE = 'knowledge_sync_write_intent_required', ERRCODE = '23514';
    END IF;
    IF TG_OP = 'INSERT' THEN
        IF reserved.memory_id IS NOT NULL THEN
            operation_value := 'restore';
            old_revision := reserved.revision;
        ELSE
            operation_value := 'create';
            old_revision := 0;
        END IF;
    ELSE
        old_revision := OLD.version;
        operation_value := CASE WHEN TG_OP = 'DELETE' THEN 'delete' ELSE 'update' END;
    END IF;
    IF intent->>'operation' IS DISTINCT FROM operation_value
        OR intent->>'expected_revision' IS DISTINCT FROM old_revision::text
        OR old_revision < 0 OR old_revision >= 2147483647 THEN
        RAISE EXCEPTION USING MESSAGE = 'knowledge_sync_revision_invalid', ERRCODE = '23514';
    END IF;
    IF TG_OP <> 'DELETE' AND NEW.version <> old_revision + 1 THEN
        RAISE EXCEPTION USING MESSAGE = 'knowledge_sync_revision_invalid', ERRCODE = '23514';
    END IF;
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END
$$;
"""

JOURNAL_GUARD_SQL = r"""
CREATE FUNCTION knowledge_sync_guard_journal() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    project_value text;
    memory_value text;
    tenant_value text;
    active boolean;
    expected jsonb;
    terminal jsonb;
    final_memory memories%ROWTYPE;
    final_tombstone knowledge_sync_tombstones%ROWTYPE;
    transaction_value bigint;
BEGIN
    IF TG_OP = 'DELETE' THEN
        project_value := OLD.project_id;
        memory_value := OLD.id;
        expected := knowledge_sync_snapshot(OLD, OLD.version + 1, true);
    ELSE
        project_value := NEW.project_id;
        memory_value := NEW.id;
        expected := knowledge_sync_snapshot(NEW, NEW.version, false);
    END IF;
    SELECT enabled, tenant_id INTO active, tenant_value FROM knowledge_sync_enrollments
        WHERE project_id = project_value;
    IF NOT coalesce(active, false) THEN
        RETURN NULL;
    END IF;
    IF TG_OP = 'UPDATE' AND expected = knowledge_sync_snapshot(OLD, OLD.version, false) THEN
        RETURN NULL;
    END IF;
    -- The DB default records the root XID even when INSERT occurs inside a
    -- savepoint. Tuple xmin is a subtransaction XID and is unsuitable here.
    transaction_value := txid_current();
    PERFORM 1 FROM knowledge_sync_changes change
        WHERE change.tenant_id = tenant_value AND change.project_id = project_value
        AND change.memory_id = memory_value AND change.revision = (expected->>'revision')::bigint
        AND change.source_kind = 'mutation' AND change.snapshot::jsonb = expected
        AND change.transaction_id = transaction_value;
    IF NOT FOUND THEN
        RAISE EXCEPTION USING MESSAGE = 'knowledge_sync_journal_required', ERRCODE = '23514';
    END IF;
    -- Check the terminal event as well: several consecutive revisions may be
    -- written in one transaction, including an explicit delete then restore.
    SELECT change.snapshot::jsonb INTO terminal FROM knowledge_sync_changes change
        WHERE change.tenant_id = tenant_value AND change.project_id = project_value
        AND change.memory_id = memory_value AND change.source_kind = 'mutation'
        AND change.transaction_id = transaction_value ORDER BY change.revision DESC LIMIT 1;
    SELECT * INTO final_memory FROM memories WHERE id = memory_value;
    SELECT * INTO final_tombstone FROM knowledge_sync_tombstones WHERE memory_id = memory_value;
    IF (terminal->>'deleted')::boolean THEN
        IF final_memory.id IS NOT NULL OR final_tombstone.memory_id IS NULL
            OR final_tombstone.tenant_id <> tenant_value
            OR final_tombstone.project_id <> project_value
            OR final_tombstone.snapshot::jsonb <> terminal THEN
            RAISE EXCEPTION USING MESSAGE = 'knowledge_sync_tombstone_required', ERRCODE = '23514';
        END IF;
    ELSE
        IF final_tombstone.memory_id IS NOT NULL OR final_memory.id IS NULL
            OR final_memory.project_id <> project_value
            OR knowledge_sync_snapshot(final_memory, final_memory.version, false) <> terminal THEN
            RAISE EXCEPTION USING MESSAGE = 'knowledge_sync_journal_terminal_mismatch', ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NULL;
END
$$;
"""


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "knowledge_sync_enrollments",
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("bootstrap_actor_id", sa.String(), nullable=True),
        sa.Column("bootstrap_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("bootstrap_count", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("bootstrap_cursor", sa.BigInteger(), server_default="0", nullable=False),
        sa.CheckConstraint(
            "bootstrap_count >= 0 AND bootstrap_cursor >= 0",
            name="ck_knowledge_sync_bootstrap_nonnegative",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("project_id"),
    )
    op.add_column(
        "knowledge_sync_changes",
        sa.Column("source_kind", sa.String(length=16), server_default="mutation", nullable=False),
    )

    op.add_column(
        "knowledge_sync_changes",
        sa.Column(
            "transaction_id",
            sa.BigInteger(),
            nullable=True,
        ),
    )
    # Keep pre-migration events untagged; only new inserts acquire a root XID.
    op.alter_column(
        "knowledge_sync_changes", "transaction_id", server_default=sa.text("txid_current()")
    )
    op.create_check_constraint(
        "ck_knowledge_sync_change_source",
        "knowledge_sync_changes",
        "source_kind IN ('mutation', 'bootstrap')",
    )
    # Fence project creation between the seed and installation of its trigger.
    op.execute("LOCK TABLE projects IN SHARE ROW EXCLUSIVE MODE")
    op.execute(
        "INSERT INTO knowledge_sync_enrollments(project_id, tenant_id, enabled) SELECT id, tenant_id, false FROM projects"
    )
    op.execute(SNAPSHOT_SQL)
    op.execute(PROJECT_FENCE_SQL)
    op.execute(WRITE_GUARD_SQL)
    op.execute(JOURNAL_GUARD_SQL)
    op.execute(
        "CREATE TRIGGER knowledge_sync_project_fence AFTER INSERT OR UPDATE OF tenant_id ON projects FOR EACH ROW EXECUTE FUNCTION knowledge_sync_project_fence()"
    )
    op.execute(
        "CREATE TRIGGER knowledge_sync_write_guard BEFORE INSERT OR UPDATE OR DELETE ON memories FOR EACH ROW EXECUTE FUNCTION knowledge_sync_guard_write()"
    )
    op.execute(
        "CREATE CONSTRAINT TRIGGER knowledge_sync_journal_guard AFTER INSERT OR UPDATE OR DELETE ON memories DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION knowledge_sync_guard_journal()"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP TRIGGER knowledge_sync_journal_guard ON memories")
    op.execute("DROP TRIGGER knowledge_sync_write_guard ON memories")
    op.execute("DROP TRIGGER knowledge_sync_project_fence ON projects")
    op.execute("DROP FUNCTION knowledge_sync_guard_journal()")
    op.execute("DROP FUNCTION knowledge_sync_guard_write()")
    op.execute("DROP FUNCTION knowledge_sync_project_fence()")
    op.execute("DROP FUNCTION knowledge_sync_snapshot(memories, integer, boolean)")
    op.drop_constraint("ck_knowledge_sync_change_source", "knowledge_sync_changes", type_="check")
    op.drop_column("knowledge_sync_changes", "transaction_id")
    op.drop_column("knowledge_sync_changes", "source_kind")
    op.drop_table("knowledge_sync_enrollments")
