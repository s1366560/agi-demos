"""add observability trust invitation smtp registry gene-policy models

Revision ID: 1a64269ebc77
Revises: fa8dab0f9da1
Create Date: 2026-03-28 00:05:20.748129

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "1a64269ebc77"
down_revision: Union[str, Sequence[str], None] = "fa8dab0f9da1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create new tables for gene_market and observability (new naming)."""
    # 1. gene_market — new table (replaces genes_market for ORM, old table kept)
    op.create_table(
        "gene_market",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("short_description", sa.String(length=300), nullable=True),
        sa.Column("category", sa.String(length=50), nullable=True),
        sa.Column("tags", sa.JSON(), nullable=True),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("source_ref", sa.String(length=200), nullable=True),
        sa.Column("icon", sa.String(length=200), nullable=True),
        sa.Column("version", sa.String(length=20), nullable=False),
        sa.Column("manifest", sa.JSON(), nullable=True),
        sa.Column("dependencies", sa.JSON(), nullable=True),
        sa.Column("synergies", sa.JSON(), nullable=True),
        sa.Column("parent_gene_id", sa.String(length=36), nullable=True),
        sa.Column("created_by_instance_id", sa.String(length=36), nullable=True),
        sa.Column("install_count", sa.Integer(), nullable=False),
        sa.Column("avg_rating", sa.Float(), nullable=False),
        sa.Column("effectiveness_score", sa.Float(), nullable=False),
        sa.Column("is_featured", sa.Boolean(), nullable=False),
        sa.Column("review_status", sa.String(length=20), nullable=False),
        sa.Column("is_published", sa.Boolean(), nullable=False),
        sa.Column("visibility", sa.String(length=20), nullable=False),
        sa.Column("created_by", sa.String(length=100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )

    # 2. observability_circuit_states — new table (replaces circuit_states for ORM)
    op.create_table(
        "observability_circuit_states",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("node_id", sa.String(length=36), nullable=False),
        sa.Column("state", sa.String(length=30), nullable=False),
        sa.Column("failure_count", sa.Integer(), nullable=False),
        sa.Column("last_failure_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_circuit_states_tenant_ws",
        "observability_circuit_states",
        ["tenant_id", "workspace_id"],
        unique=False,
    )

    # 3. observability_event_logs — new table (replaces event_logs for ORM)
    op.create_table(
        "observability_event_logs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("trace_id", sa.String(length=64), nullable=True),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("source_node_id", sa.String(length=36), nullable=True),
        sa.Column("target_node_id", sa.String(length=36), nullable=True),
        sa.Column("message_id", sa.String(length=36), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_event_logs_tenant_ws",
        "observability_event_logs",
        ["tenant_id", "workspace_id"],
        unique=False,
    )

    # 4. observability_message_queue — new table (replaces message_queue_items for ORM)
    op.create_table(
        "observability_message_queue",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("message_id", sa.String(length=36), nullable=True),
        sa.Column("source_node_id", sa.String(length=36), nullable=True),
        sa.Column("target_node_id", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_mq_items_tenant_ws",
        "observability_message_queue",
        ["tenant_id", "workspace_id"],
        unique=False,
    )

    # 5. observability_node_cards — new table (replaces node_cards for ORM)
    op.create_table(
        "observability_node_cards",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("node_id", sa.String(length=36), nullable=False),
        sa.Column("node_type", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("tags", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_node_cards_tenant_ws",
        "observability_node_cards",
        ["tenant_id", "workspace_id"],
        unique=False,
    )

    # NOTE: Autogenerate also detected differences on existing tables:
    # - index renames (ix_clusters_tenant -> ix_clusters_tenant_id, etc.)
    # - FK constraint recreation (adding ondelete='CASCADE')
    # - column type narrowing (VARCHAR -> Text, TEXT -> String(500))
    # - column drops (users.must_change_password)
    # - drops of old tables (circuit_states, event_logs, node_cards, etc.)
    # - drops of unrelated tables (schedules, jobs, llm_providers, etc.)
    # These are intentionally excluded from this migration to avoid
    # data loss and breaking changes. They should be addressed in
    # separate, focused migrations after careful review.


def downgrade() -> None:
    """Drop the newly created tables."""
    op.drop_index("ix_node_cards_tenant_ws", table_name="observability_node_cards")
    op.drop_table("observability_node_cards")
    op.drop_index("ix_mq_items_tenant_ws", table_name="observability_message_queue")
    op.drop_table("observability_message_queue")
    op.drop_index("ix_event_logs_tenant_ws", table_name="observability_event_logs")
    op.drop_table("observability_event_logs")
    op.drop_index("ix_circuit_states_tenant_ws", table_name="observability_circuit_states")
    op.drop_table("observability_circuit_states")
    op.drop_table("gene_market")
