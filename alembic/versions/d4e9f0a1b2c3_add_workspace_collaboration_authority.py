"""add workspace collaboration mutation authority

Revision ID: d4e9f0a1b2c3
Revises: c3d8e9f0a1b2
Create Date: 2026-07-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from alembic import op

revision: str = "d4e9f0a1b2c3"
down_revision: str | Sequence[str] | None = "c3d8e9f0a1b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_WORKSPACE_CHILD_TABLES = (
    "workspace_members",
    "workspace_agents",
    "workspace_tasks",
    "workspace_task_session_attempts",
    "cyber_objectives",
    "blackboard_posts",
    "blackboard_replies",
    "blackboard_files",
    "cyber_genes",
    "topology_nodes",
    "topology_edges",
    "workspace_plans",
    "workspace_plan_outbox",
)
_PLAN_SCOPED_TABLES = ("workspace_plan_nodes",)
_CONVERSATION_SCOPED_TABLES = ("tool_execution_records",)


def _trigger_name(table_name: str) -> str:
    return f"trg_{table_name}_collaboration_authority"


def upgrade() -> None:
    """Create durable revisions, receipts, and PostgreSQL legacy-route triggers."""
    op.create_table(
        "workspace_collaboration_authorities",
        sa.Column("workspace_id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column(
            "revision",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "revision >= 0",
            name="ck_workspace_collaboration_authority_revision",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("workspace_id"),
    )
    op.create_index(
        "ix_workspace_collaboration_authorities_scope",
        "workspace_collaboration_authorities",
        ["tenant_id", "project_id"],
    )
    op.create_table(
        "workspace_collaboration_mutation_receipts",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("workspace_id", sa.String(), nullable=False),
        sa.Column("actor_user_id", sa.String(), nullable=False),
        sa.Column("contract_version", sa.String(length=20), nullable=False),
        sa.Column("surface", sa.String(length=32), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=256), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("expected_revision", sa.BigInteger(), nullable=False),
        sa.Column("committed_revision", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "expected_revision >= 0",
            name="ck_workspace_collaboration_receipt_expected_revision",
        ),
        sa.CheckConstraint(
            "committed_revision IS NULL OR committed_revision >= expected_revision",
            name="ck_workspace_collaboration_receipt_committed_revision",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_workspace_collaboration_receipt_intent",
        "workspace_collaboration_mutation_receipts",
        ["workspace_id", "actor_user_id", "idempotency_key"],
        unique=True,
    )
    op.create_index(
        "ix_workspace_collaboration_receipts_scope_revision",
        "workspace_collaboration_mutation_receipts",
        ["tenant_id", "project_id", "workspace_id", "committed_revision"],
    )
    workspace_table = sa.table(
        "workspaces",
        sa.column("id", sa.String()),
        sa.column("tenant_id", sa.String()),
        sa.column("project_id", sa.String()),
    )
    authority_table = sa.table(
        "workspace_collaboration_authorities",
        sa.column("workspace_id", sa.String()),
        sa.column("tenant_id", sa.String()),
        sa.column("project_id", sa.String()),
        sa.column("revision", sa.BigInteger()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    authority_columns = [
        "workspace_id",
        "tenant_id",
        "project_id",
        "revision",
        "created_at",
        "updated_at",
    ]
    authority_rows = sa.select(
        workspace_table.c.id,
        workspace_table.c.tenant_id,
        workspace_table.c.project_id,
        sa.literal(0),
        sa.func.now(),
        sa.func.now(),
    )
    dialect_name = op.get_bind().dialect.name
    if dialect_name == "postgresql":
        op.execute(
            postgresql_insert(authority_table)
            .from_select(authority_columns, authority_rows)
            .on_conflict_do_nothing(index_elements=["workspace_id"])
        )
    elif dialect_name == "sqlite":
        op.execute(
            sqlite_insert(authority_table)
            .from_select(authority_columns, authority_rows)
            .on_conflict_do_nothing(index_elements=["workspace_id"])
        )
    else:
        op.execute(authority_table.insert().from_select(authority_columns, authority_rows))

    if dialect_name != "postgresql":
        return

    op.execute(
        sa.text(
            """
            CREATE FUNCTION bump_workspace_collaboration_authority_for_workspace(
                target_workspace_id text
            )
            RETURNS void
            LANGUAGE plpgsql
            AS $$
            BEGIN
                IF target_workspace_id IS NULL THEN
                    RETURN;
                END IF;
                INSERT INTO workspace_collaboration_authorities (
                    workspace_id,
                    tenant_id,
                    project_id,
                    revision,
                    created_at,
                    updated_at
                )
                SELECT
                    workspaces.id,
                    workspaces.tenant_id,
                    workspaces.project_id,
                    1,
                    now(),
                    now()
                FROM workspaces
                WHERE workspaces.id = target_workspace_id
                ON CONFLICT (workspace_id) DO UPDATE
                SET revision =
                        workspace_collaboration_authorities.revision + 1,
                    tenant_id = EXCLUDED.tenant_id,
                    project_id = EXCLUDED.project_id,
                    updated_at = now();
            END;
            $$
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE FUNCTION bump_workspace_collaboration_authority()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            DECLARE
                old_workspace_id text;
                new_workspace_id text;
            BEGIN
                IF TG_TABLE_NAME = 'workspaces' THEN
                    IF TG_OP <> 'DELETE' THEN
                        new_workspace_id := NEW.id;
                    END IF;
                    IF TG_OP <> 'INSERT' THEN
                        old_workspace_id := OLD.id;
                    END IF;
                ELSIF TG_TABLE_NAME = 'workspace_plan_nodes' THEN
                    IF TG_OP <> 'DELETE' THEN
                        SELECT workspace_plans.workspace_id
                        INTO new_workspace_id
                        FROM workspace_plans
                        WHERE workspace_plans.id = NEW.plan_id;
                    END IF;
                    IF TG_OP <> 'INSERT' THEN
                        SELECT workspace_plans.workspace_id
                        INTO old_workspace_id
                        FROM workspace_plans
                        WHERE workspace_plans.id = OLD.plan_id;
                    END IF;
                ELSIF TG_TABLE_NAME = 'tool_execution_records' THEN
                    IF TG_OP <> 'DELETE' THEN
                        SELECT workspaces.id
                        INTO new_workspace_id
                        FROM conversations
                        JOIN workspaces
                          ON conversations.workspace_id = workspaces.id
                         AND conversations.tenant_id = workspaces.tenant_id
                         AND conversations.project_id = workspaces.project_id
                        WHERE conversations.id = NEW.conversation_id
                          AND EXISTS (
                              SELECT 1
                              FROM workspace_task_session_attempts
                              WHERE workspace_task_session_attempts.conversation_id =
                                    conversations.id
                                AND workspace_task_session_attempts.workspace_id =
                                    workspaces.id
                          );
                    END IF;
                    IF TG_OP <> 'INSERT' THEN
                        SELECT workspaces.id
                        INTO old_workspace_id
                        FROM conversations
                        JOIN workspaces
                          ON conversations.workspace_id = workspaces.id
                         AND conversations.tenant_id = workspaces.tenant_id
                         AND conversations.project_id = workspaces.project_id
                        WHERE conversations.id = OLD.conversation_id
                          AND EXISTS (
                              SELECT 1
                              FROM workspace_task_session_attempts
                              WHERE workspace_task_session_attempts.conversation_id =
                                    conversations.id
                                AND workspace_task_session_attempts.workspace_id =
                                    workspaces.id
                          );
                    END IF;
                ELSE
                    IF TG_OP <> 'DELETE' THEN
                        new_workspace_id := NEW.workspace_id;
                    END IF;
                    IF TG_OP <> 'INSERT' THEN
                        old_workspace_id := OLD.workspace_id;
                    END IF;
                END IF;

                IF TG_OP = 'DELETE' THEN
                    PERFORM bump_workspace_collaboration_authority_for_workspace(
                        old_workspace_id
                    );
                ELSIF TG_OP = 'INSERT' THEN
                    PERFORM bump_workspace_collaboration_authority_for_workspace(
                        new_workspace_id
                    );
                ELSE
                    IF old_workspace_id IS DISTINCT FROM new_workspace_id THEN
                        PERFORM bump_workspace_collaboration_authority_for_workspace(
                            old_workspace_id
                        );
                    END IF;
                    PERFORM bump_workspace_collaboration_authority_for_workspace(
                        new_workspace_id
                    );
                END IF;

                IF TG_OP = 'DELETE' THEN
                    RETURN OLD;
                END IF;
                RETURN NEW;
            END;
            $$
            """
        )
    )
    op.execute(
        sa.text(
            f"""
            CREATE TRIGGER {_trigger_name("workspaces")}
            AFTER INSERT OR UPDATE ON workspaces
            FOR EACH ROW
            EXECUTE FUNCTION bump_workspace_collaboration_authority()
            """
        )
    )
    for table_name in _WORKSPACE_CHILD_TABLES:
        op.execute(
            sa.text(
                f"""
                CREATE TRIGGER {_trigger_name(table_name)}
                AFTER INSERT OR UPDATE OR DELETE ON {table_name}
                FOR EACH ROW
                EXECUTE FUNCTION bump_workspace_collaboration_authority()
                """
            )
        )
    for table_name in (*_PLAN_SCOPED_TABLES, *_CONVERSATION_SCOPED_TABLES):
        op.execute(
            sa.text(
                f"""
                CREATE TRIGGER {_trigger_name(table_name)}
                AFTER INSERT OR UPDATE OR DELETE ON {table_name}
                FOR EACH ROW
                EXECUTE FUNCTION bump_workspace_collaboration_authority()
                """
            )
        )


def downgrade() -> None:
    """Remove Workspace Collaboration authority and legacy-route triggers."""
    if op.get_bind().dialect.name == "postgresql":
        for table_name in reversed((*_PLAN_SCOPED_TABLES, *_CONVERSATION_SCOPED_TABLES)):
            op.execute(
                sa.text(f"DROP TRIGGER IF EXISTS {_trigger_name(table_name)} ON {table_name}")
            )
        for table_name in reversed(_WORKSPACE_CHILD_TABLES):
            op.execute(
                sa.text(f"DROP TRIGGER IF EXISTS {_trigger_name(table_name)} ON {table_name}")
            )
        op.execute(sa.text(f"DROP TRIGGER IF EXISTS {_trigger_name('workspaces')} ON workspaces"))
        op.execute(sa.text("DROP FUNCTION IF EXISTS bump_workspace_collaboration_authority()"))
        op.execute(
            sa.text(
                "DROP FUNCTION IF EXISTS bump_workspace_collaboration_authority_for_workspace(text)"
            )
        )

    op.drop_index(
        "ix_workspace_collaboration_receipts_scope_revision",
        table_name="workspace_collaboration_mutation_receipts",
    )
    op.drop_index(
        "uq_workspace_collaboration_receipt_intent",
        table_name="workspace_collaboration_mutation_receipts",
    )
    op.drop_table("workspace_collaboration_mutation_receipts")
    op.drop_index(
        "ix_workspace_collaboration_authorities_scope",
        table_name="workspace_collaboration_authorities",
    )
    op.drop_table("workspace_collaboration_authorities")
