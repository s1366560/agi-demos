"""add task session creation receipts

Revision ID: a1f6e8c2d4b7
Revises: f9d99e5695ec
Create Date: 2026-07-19 00:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a1f6e8c2d4b7"
down_revision: str | Sequence[str] | None = "f9d99e5695ec"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the durable atomic task-session idempotency ledger."""
    op.create_table(
        "task_session_creation_receipts",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("actor_user_id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("workspace_id", sa.String(), nullable=False),
        sa.Column("conversation_id", sa.String(), nullable=True),
        sa.Column("initial_message_id", sa.String(), nullable=True),
        sa.Column("response_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["initial_message_id"],
            ["workspace_messages.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "actor_user_id",
            "tenant_id",
            "project_id",
            "idempotency_key",
            name="uq_task_session_receipts_scope_key",
        ),
        sa.UniqueConstraint(
            "conversation_id",
            name="uq_task_session_receipts_conversation",
        ),
        sa.UniqueConstraint(
            "initial_message_id",
            name="uq_task_session_receipts_initial_message",
        ),
    )
    op.create_index(
        "ix_task_session_receipts_scope_created",
        "task_session_creation_receipts",
        ["tenant_id", "project_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_task_session_receipts_actor_user_id",
        "task_session_creation_receipts",
        ["actor_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_task_session_receipts_project_id",
        "task_session_creation_receipts",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        "ix_task_session_receipts_workspace_id",
        "task_session_creation_receipts",
        ["workspace_id"],
        unique=False,
    )
    op.execute(
        """
        CREATE FUNCTION tombstone_task_session_creation_receipt()
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
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_task_session_receipt_conversation_delete
        BEFORE DELETE ON conversations
        FOR EACH ROW
        EXECUTE FUNCTION tombstone_task_session_creation_receipt()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_task_session_receipt_message_delete
        BEFORE DELETE ON workspace_messages
        FOR EACH ROW
        EXECUTE FUNCTION tombstone_task_session_creation_receipt()
        """
    )


def downgrade() -> None:
    """Drop the atomic task-session idempotency ledger."""
    op.execute(
        "DROP TRIGGER IF EXISTS trg_task_session_receipt_message_delete ON workspace_messages"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_task_session_receipt_conversation_delete ON conversations"
    )
    op.execute("DROP FUNCTION IF EXISTS tombstone_task_session_creation_receipt()")
    op.drop_index(
        "ix_task_session_receipts_workspace_id",
        table_name="task_session_creation_receipts",
    )
    op.drop_index(
        "ix_task_session_receipts_project_id",
        table_name="task_session_creation_receipts",
    )
    op.drop_index(
        "ix_task_session_receipts_actor_user_id",
        table_name="task_session_creation_receipts",
    )
    op.drop_index(
        "ix_task_session_receipts_scope_created",
        table_name="task_session_creation_receipts",
    )
    op.drop_table("task_session_creation_receipts")
