"""add workspace collaboration tables

Revision ID: k3c4d5e6f7a8
Revises: 43b727f54251
Create Date: 2026-03-25 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "k3c4d5e6f7a8"
down_revision: str | Sequence[str] | None = "43b727f54251"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workspaces",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("is_archived", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "name", name="uq_workspaces_project_name"),
    )
    op.create_index("ix_workspaces_tenant_project", "workspaces", ["tenant_id", "project_id"])

    op.create_table(
        "workspace_members",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("workspace_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False, server_default="viewer"),
        sa.Column("invited_by", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["invited_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "user_id", name="uq_workspace_members_workspace_user"),
    )
    op.create_index(
        "ix_workspace_members_workspace_role",
        "workspace_members",
        ["workspace_id", "role"],
    )

    op.create_table(
        "workspace_agents",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("workspace_id", sa.String(), nullable=False),
        sa.Column("agent_id", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("config_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["agent_id"], ["agent_definitions.id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "agent_id", name="uq_workspace_agents_workspace_agent"),
    )
    op.create_index("ix_workspace_agents_agent_id", "workspace_agents", ["agent_id"])
    op.create_index(
        "ix_workspace_agents_workspace_active",
        "workspace_agents",
        ["workspace_id", "is_active"],
    )

    op.create_table(
        "blackboard_posts",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("workspace_id", sa.String(), nullable=False),
        sa.Column("author_id", sa.String(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="open"),
        sa.Column("is_pinned", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["author_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_blackboard_posts_workspace_created",
        "blackboard_posts",
        ["workspace_id", "created_at"],
    )
    op.create_index(
        "ix_blackboard_posts_workspace_pinned_status",
        "blackboard_posts",
        ["workspace_id", "is_pinned", "status"],
    )

    op.create_table(
        "workspace_tasks",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("workspace_id", sa.String(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("assignee_user_id", sa.String(), nullable=True),
        sa.Column("assignee_agent_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="todo"),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["assignee_agent_id"], ["agent_definitions.id"]),
        sa.ForeignKeyConstraint(["assignee_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_workspace_tasks_workspace_created",
        "workspace_tasks",
        ["workspace_id", "created_at"],
    )
    op.create_index(
        "ix_workspace_tasks_workspace_status",
        "workspace_tasks",
        ["workspace_id", "status"],
    )

    op.create_table(
        "topology_nodes",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("workspace_id", sa.String(), nullable=False),
        sa.Column("node_type", sa.String(length=20), nullable=False),
        sa.Column("ref_id", sa.String(), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("position_x", sa.Float(), nullable=False, server_default="0"),
        sa.Column("position_y", sa.Float(), nullable=False, server_default="0"),
        sa.Column("data_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_topology_nodes_workspace_ref",
        "topology_nodes",
        ["workspace_id", "ref_id"],
    )
    op.create_index(
        "ix_topology_nodes_workspace_type",
        "topology_nodes",
        ["workspace_id", "node_type"],
    )

    op.create_table(
        "blackboard_replies",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("post_id", sa.String(), nullable=False),
        sa.Column("workspace_id", sa.String(), nullable=False),
        sa.Column("author_id", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["author_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["post_id"], ["blackboard_posts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_blackboard_replies_post_created",
        "blackboard_replies",
        ["post_id", "created_at"],
    )

    op.create_table(
        "topology_edges",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("workspace_id", sa.String(), nullable=False),
        sa.Column("source_node_id", sa.String(), nullable=False),
        sa.Column("target_node_id", sa.String(), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=True),
        sa.Column("data_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["source_node_id"], ["topology_nodes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_node_id"], ["topology_nodes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_topology_edges_workspace", "topology_edges", ["workspace_id"])
    op.create_index(
        "ix_topology_edges_source_target",
        "topology_edges",
        ["source_node_id", "target_node_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_topology_edges_source_target", table_name="topology_edges")
    op.drop_index("ix_topology_edges_workspace", table_name="topology_edges")
    op.drop_table("topology_edges")

    op.drop_index("ix_blackboard_replies_post_created", table_name="blackboard_replies")
    op.drop_table("blackboard_replies")

    op.drop_index("ix_topology_nodes_workspace_type", table_name="topology_nodes")
    op.drop_index("ix_topology_nodes_workspace_ref", table_name="topology_nodes")
    op.drop_table("topology_nodes")

    op.drop_index("ix_workspace_tasks_workspace_status", table_name="workspace_tasks")
    op.drop_index("ix_workspace_tasks_workspace_created", table_name="workspace_tasks")
    op.drop_table("workspace_tasks")

    op.drop_index(
        "ix_blackboard_posts_workspace_pinned_status",
        table_name="blackboard_posts",
    )
    op.drop_index("ix_blackboard_posts_workspace_created", table_name="blackboard_posts")
    op.drop_table("blackboard_posts")

    op.drop_index("ix_workspace_agents_workspace_active", table_name="workspace_agents")
    op.drop_index("ix_workspace_agents_agent_id", table_name="workspace_agents")
    op.drop_table("workspace_agents")

    op.drop_index("ix_workspace_members_workspace_role", table_name="workspace_members")
    op.drop_table("workspace_members")

    op.drop_index("ix_workspaces_tenant_project", table_name="workspaces")
    op.drop_table("workspaces")
