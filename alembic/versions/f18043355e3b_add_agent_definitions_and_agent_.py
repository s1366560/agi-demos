"""add agent_definitions and agent_bindings tables

Revision ID: f18043355e3b
Revises: d5e6f7a8b9c0
Create Date: 2026-03-17 11:32:05.446129

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "f18043355e3b"
down_revision: Union[str, Sequence[str], None] = "d5e6f7a8b9c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "agent_definitions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("system_prompt", sa.Text(), nullable=False),
        sa.Column("trigger_description", sa.Text(), nullable=True),
        sa.Column("trigger_examples", sa.JSON(), nullable=True),
        sa.Column("trigger_keywords", sa.JSON(), nullable=True),
        sa.Column("model", sa.String(length=50), nullable=False),
        sa.Column("persona_files", sa.JSON(), nullable=True),
        sa.Column("allowed_tools", sa.JSON(), nullable=False),
        sa.Column("allowed_skills", sa.JSON(), nullable=False),
        sa.Column("allowed_mcp_servers", sa.JSON(), nullable=False),
        sa.Column("max_tokens", sa.Integer(), nullable=False),
        sa.Column("temperature", sa.Float(), nullable=False),
        sa.Column("max_iterations", sa.Integer(), nullable=False),
        sa.Column("workspace_dir", sa.String(), nullable=True),
        sa.Column("workspace_config", sa.JSON(), nullable=True),
        sa.Column("can_spawn", sa.Boolean(), nullable=False),
        sa.Column("max_spawn_depth", sa.Integer(), nullable=False),
        sa.Column("agent_to_agent_enabled", sa.Boolean(), nullable=False),
        sa.Column("discoverable", sa.Boolean(), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("max_retries", sa.Integer(), nullable=False),
        sa.Column("fallback_models", sa.JSON(), nullable=True),
        sa.Column("total_invocations", sa.Integer(), nullable=False),
        sa.Column("avg_execution_time_ms", sa.Float(), nullable=False),
        sa.Column("success_rate", sa.Float(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index(
        op.f("ix_agent_definitions_project_id"), "agent_definitions", ["project_id"], unique=False
    )
    op.create_index(
        op.f("ix_agent_definitions_tenant_id"), "agent_definitions", ["tenant_id"], unique=False
    )

    op.create_table(
        "agent_bindings",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("agent_id", sa.String(), nullable=False),
        sa.Column("channel_type", sa.String(length=50), nullable=True),
        sa.Column("channel_id", sa.String(), nullable=True),
        sa.Column("account_id", sa.String(), nullable=True),
        sa.Column("peer_id", sa.String(), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agent_definitions.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_agent_bindings_agent_id"), "agent_bindings", ["agent_id"], unique=False
    )
    op.create_index(
        "ix_agent_bindings_routing",
        "agent_bindings",
        ["tenant_id", "channel_type", "channel_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_agent_bindings_tenant_id"), "agent_bindings", ["tenant_id"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_agent_bindings_tenant_id"), table_name="agent_bindings")
    op.drop_index("ix_agent_bindings_routing", table_name="agent_bindings")
    op.drop_index(op.f("ix_agent_bindings_agent_id"), table_name="agent_bindings")
    op.drop_table("agent_bindings")
    op.drop_index(op.f("ix_agent_definitions_tenant_id"), table_name="agent_definitions")
    op.drop_index(op.f("ix_agent_definitions_project_id"), table_name="agent_definitions")
    op.drop_table("agent_definitions")
