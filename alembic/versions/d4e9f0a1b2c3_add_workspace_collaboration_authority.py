"""add workspace collaboration mutation authority

Revision ID: d4e9f0a1b2c3
Revises: c3d8e9f0a1b2
Create Date: 2026-07-28
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d4e9f0a1b2c3"
down_revision: str | Sequence[str] | None = "c3d8e9f0a1b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_WORKSPACE_CHILD_TABLES = (
    "workspace_members",
    "workspace_agents",
    "workspace_tasks",
    "cyber_objectives",
    "blackboard_posts",
    "blackboard_replies",
    "blackboard_files",
    "cyber_genes",
    "topology_nodes",
    "topology_edges",
)


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

    if op.get_bind().dialect.name != "postgresql":
        return

    op.execute(
        sa.text(
            """
            CREATE FUNCTION bump_workspace_collaboration_authority()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            DECLARE
                target_workspace_id text;
                target_tenant_id text;
                target_project_id text;
            BEGIN
                IF TG_TABLE_NAME = 'workspaces' THEN
                    target_workspace_id := COALESCE(NEW.id, OLD.id);
                    target_tenant_id := COALESCE(NEW.tenant_id, OLD.tenant_id);
                    target_project_id := COALESCE(NEW.project_id, OLD.project_id);
                ELSE
                    target_workspace_id := COALESCE(NEW.workspace_id, OLD.workspace_id);
                    SELECT tenant_id, project_id
                    INTO target_tenant_id, target_project_id
                    FROM workspaces
                    WHERE id = target_workspace_id;
                END IF;

                IF target_workspace_id IS NOT NULL
                   AND target_tenant_id IS NOT NULL
                   AND target_project_id IS NOT NULL THEN
                    INSERT INTO workspace_collaboration_authorities (
                        workspace_id,
                        tenant_id,
                        project_id,
                        revision,
                        created_at,
                        updated_at
                    )
                    VALUES (
                        target_workspace_id,
                        target_tenant_id,
                        target_project_id,
                        1,
                        now(),
                        now()
                    )
                    ON CONFLICT (workspace_id) DO UPDATE
                    SET revision =
                            workspace_collaboration_authorities.revision + 1,
                        tenant_id = EXCLUDED.tenant_id,
                        project_id = EXCLUDED.project_id,
                        updated_at = now();
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
            AFTER UPDATE ON workspaces
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


def downgrade() -> None:
    """Remove Workspace Collaboration authority and legacy-route triggers."""
    if op.get_bind().dialect.name == "postgresql":
        for table_name in reversed(_WORKSPACE_CHILD_TABLES):
            op.execute(
                sa.text(f"DROP TRIGGER IF EXISTS {_trigger_name(table_name)} ON {table_name}")
            )
        op.execute(sa.text(f"DROP TRIGGER IF EXISTS {_trigger_name('workspaces')} ON workspaces"))
        op.execute(sa.text("DROP FUNCTION IF EXISTS bump_workspace_collaboration_authority()"))

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
