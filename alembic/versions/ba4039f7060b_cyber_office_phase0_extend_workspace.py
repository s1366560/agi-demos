"""cyber_office_phase0_extend_workspace

Revision ID: ba4039f7060b
Revises: k3c4d5e6f7a8
Create Date: 2026-03-26 00:09:32.561148

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "ba4039f7060b"
down_revision: Union[str, Sequence[str], None] = "k3c4d5e6f7a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "cyber_objectives",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("workspace_id", sa.String(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("obj_type", sa.String(length=20), nullable=False),
        sa.Column("parent_id", sa.String(), nullable=True),
        sa.Column("progress", sa.Float(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(["parent_id"], ["cyber_objectives.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_cyber_objectives_parent", "cyber_objectives", ["parent_id"], unique=False)
    op.create_index(
        "ix_cyber_objectives_workspace", "cyber_objectives", ["workspace_id"], unique=False
    )
    op.create_index(
        "ix_cyber_objectives_workspace_type",
        "cyber_objectives",
        ["workspace_id", "obj_type"],
        unique=False,
    )

    op.add_column("topology_edges", sa.Column("source_hex_q", sa.Integer(), nullable=True))
    op.add_column("topology_edges", sa.Column("source_hex_r", sa.Integer(), nullable=True))
    op.add_column("topology_edges", sa.Column("target_hex_q", sa.Integer(), nullable=True))
    op.add_column("topology_edges", sa.Column("target_hex_r", sa.Integer(), nullable=True))
    op.add_column("topology_edges", sa.Column("direction", sa.String(length=20), nullable=True))
    op.add_column(
        "topology_edges",
        sa.Column("auto_created", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )

    op.add_column("topology_nodes", sa.Column("hex_q", sa.Integer(), nullable=True))
    op.add_column("topology_nodes", sa.Column("hex_r", sa.Integer(), nullable=True))
    op.add_column(
        "topology_nodes",
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default=sa.text("'active'")
        ),
    )
    op.add_column(
        "topology_nodes",
        sa.Column("tags_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
    )

    op.add_column("workspace_agents", sa.Column("hex_q", sa.Integer(), nullable=True))
    op.add_column("workspace_agents", sa.Column("hex_r", sa.Integer(), nullable=True))
    op.add_column("workspace_agents", sa.Column("theme_color", sa.String(length=20), nullable=True))
    op.add_column("workspace_agents", sa.Column("label", sa.String(length=100), nullable=True))
    op.add_column(
        "workspace_agents",
        sa.Column("status", sa.String(length=20), nullable=False, server_default=sa.text("'idle'")),
    )

    op.add_column(
        "workspace_tasks",
        sa.Column("priority", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "workspace_tasks", sa.Column("estimated_effort", sa.String(length=50), nullable=True)
    )
    op.add_column("workspace_tasks", sa.Column("blocker_reason", sa.Text(), nullable=True))
    op.add_column(
        "workspace_tasks", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "workspace_tasks", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True)
    )

    op.add_column(
        "workspaces",
        sa.Column(
            "office_status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'inactive'"),
        ),
    )
    op.add_column(
        "workspaces",
        sa.Column(
            "hex_layout_config_json",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
    )


def downgrade() -> None:
    op.drop_column("workspaces", "hex_layout_config_json")
    op.drop_column("workspaces", "office_status")

    op.drop_column("workspace_tasks", "archived_at")
    op.drop_column("workspace_tasks", "completed_at")
    op.drop_column("workspace_tasks", "blocker_reason")
    op.drop_column("workspace_tasks", "estimated_effort")
    op.drop_column("workspace_tasks", "priority")

    op.drop_column("workspace_agents", "status")
    op.drop_column("workspace_agents", "label")
    op.drop_column("workspace_agents", "theme_color")
    op.drop_column("workspace_agents", "hex_r")
    op.drop_column("workspace_agents", "hex_q")

    op.drop_column("topology_nodes", "tags_json")
    op.drop_column("topology_nodes", "status")
    op.drop_column("topology_nodes", "hex_r")
    op.drop_column("topology_nodes", "hex_q")

    op.drop_column("topology_edges", "auto_created")
    op.drop_column("topology_edges", "direction")
    op.drop_column("topology_edges", "target_hex_r")
    op.drop_column("topology_edges", "target_hex_q")
    op.drop_column("topology_edges", "source_hex_r")
    op.drop_column("topology_edges", "source_hex_q")

    op.drop_index("ix_cyber_objectives_workspace_type", table_name="cyber_objectives")
    op.drop_index("ix_cyber_objectives_workspace", table_name="cyber_objectives")
    op.drop_index("ix_cyber_objectives_parent", table_name="cyber_objectives")
    op.drop_table("cyber_objectives")
