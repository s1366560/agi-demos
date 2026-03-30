"""add observability tables

Revision ID: c6d7e8f9a0b1
Revises: b5c6d7e8f9a0
Create Date: 2026-03-27 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c6d7e8f9a0b1"
down_revision: str | Sequence[str] | None = "b5c6d7e8f9a0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # -- event_logs --
    op.create_table(
        "event_logs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("workspace_id", sa.String(), nullable=False),
        sa.Column("trace_id", sa.String(), nullable=True),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("source_node_id", sa.String(), nullable=True),
        sa.Column("target_node_id", sa.String(), nullable=True),
        sa.Column("message_id", sa.String(), nullable=True),
        sa.Column(
            "payload",
            sa.JSON(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column(
            "deleted_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_event_logs_tenant_id",
        "event_logs",
        ["tenant_id"],
    )
    op.create_index(
        "ix_event_logs_workspace_id",
        "event_logs",
        ["workspace_id"],
    )
    op.create_index(
        "ix_event_logs_trace_id",
        "event_logs",
        ["trace_id"],
    )
    op.create_index(
        "ix_event_logs_event_type",
        "event_logs",
        ["event_type"],
    )
    op.create_index(
        "ix_event_logs_message_id",
        "event_logs",
        ["message_id"],
    )

    # -- observability_dead_letters --
    op.create_table(
        "observability_dead_letters",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("workspace_id", sa.String(), nullable=False),
        sa.Column(
            "original_message_id",
            sa.String(),
            nullable=True,
        ),
        sa.Column("source_node_id", sa.String(), nullable=True),
        sa.Column("target_node_id", sa.String(), nullable=True),
        sa.Column("error_reason", sa.Text(), nullable=True),
        sa.Column(
            "payload",
            sa.JSON(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "retry_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "status",
            sa.String(),
            nullable=False,
            server_default="'pending'",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column(
            "retried_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "deleted_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_obs_dead_letters_tenant_id",
        "observability_dead_letters",
        ["tenant_id"],
    )
    op.create_index(
        "ix_obs_dead_letters_workspace_id",
        "observability_dead_letters",
        ["workspace_id"],
    )

    # -- circuit_states --
    op.create_table(
        "circuit_states",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("workspace_id", sa.String(), nullable=False),
        sa.Column("node_id", sa.String(), nullable=False),
        sa.Column(
            "state",
            sa.String(),
            nullable=False,
            server_default="'closed'",
        ),
        sa.Column(
            "failure_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "last_failure_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "last_success_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "deleted_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_circuit_states_tenant_id",
        "circuit_states",
        ["tenant_id"],
    )
    op.create_index(
        "ix_circuit_states_workspace_id",
        "circuit_states",
        ["workspace_id"],
    )
    op.create_index(
        "ix_circuit_states_node_id",
        "circuit_states",
        ["node_id"],
    )

    # -- message_queue_items --
    op.create_table(
        "message_queue_items",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("workspace_id", sa.String(), nullable=False),
        sa.Column("message_id", sa.String(), nullable=False),
        sa.Column("source_node_id", sa.String(), nullable=True),
        sa.Column("target_node_id", sa.String(), nullable=True),
        sa.Column(
            "status",
            sa.String(),
            nullable=False,
            server_default="'queued'",
        ),
        sa.Column(
            "priority",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "payload",
            sa.JSON(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column(
            "processed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "deleted_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_mq_items_tenant_id",
        "message_queue_items",
        ["tenant_id"],
    )
    op.create_index(
        "ix_mq_items_workspace_id",
        "message_queue_items",
        ["workspace_id"],
    )
    op.create_index(
        "ix_mq_items_message_id",
        "message_queue_items",
        ["message_id"],
    )

    # -- node_cards --
    op.create_table(
        "node_cards",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("workspace_id", sa.String(), nullable=False),
        sa.Column("node_id", sa.String(), nullable=False),
        sa.Column("node_type", sa.String(), nullable=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "tags",
            sa.JSON(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "status",
            sa.String(),
            nullable=False,
            server_default="'active'",
        ),
        sa.Column(
            "metadata",
            sa.JSON(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "deleted_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_node_cards_tenant_id",
        "node_cards",
        ["tenant_id"],
    )
    op.create_index(
        "ix_node_cards_workspace_id",
        "node_cards",
        ["workspace_id"],
    )
    op.create_index(
        "ix_node_cards_node_id",
        "node_cards",
        ["node_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_node_cards_node_id", table_name="node_cards")
    op.drop_index(
        "ix_node_cards_workspace_id",
        table_name="node_cards",
    )
    op.drop_index(
        "ix_node_cards_tenant_id",
        table_name="node_cards",
    )
    op.drop_table("node_cards")

    op.drop_index(
        "ix_mq_items_message_id",
        table_name="message_queue_items",
    )
    op.drop_index(
        "ix_mq_items_workspace_id",
        table_name="message_queue_items",
    )
    op.drop_index(
        "ix_mq_items_tenant_id",
        table_name="message_queue_items",
    )
    op.drop_table("message_queue_items")

    op.drop_index(
        "ix_circuit_states_node_id",
        table_name="circuit_states",
    )
    op.drop_index(
        "ix_circuit_states_workspace_id",
        table_name="circuit_states",
    )
    op.drop_index(
        "ix_circuit_states_tenant_id",
        table_name="circuit_states",
    )
    op.drop_table("circuit_states")

    op.drop_index(
        "ix_obs_dead_letters_workspace_id",
        table_name="observability_dead_letters",
    )
    op.drop_index(
        "ix_obs_dead_letters_tenant_id",
        table_name="observability_dead_letters",
    )
    op.drop_table("observability_dead_letters")

    op.drop_index(
        "ix_event_logs_message_id",
        table_name="event_logs",
    )
    op.drop_index(
        "ix_event_logs_event_type",
        table_name="event_logs",
    )
    op.drop_index(
        "ix_event_logs_trace_id",
        table_name="event_logs",
    )
    op.drop_index(
        "ix_event_logs_workspace_id",
        table_name="event_logs",
    )
    op.drop_index(
        "ix_event_logs_tenant_id",
        table_name="event_logs",
    )
    op.drop_table("event_logs")
