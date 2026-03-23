"""add_agent_graph_tables

Revision ID: ff587f7ed717
Revises: j2b3c4d5e6f7
Create Date: 2026-03-23 10:40:41.871562

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "ff587f7ed717"
down_revision: Union[str, Sequence[str], None] = "j2b3c4d5e6f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = inspector.get_table_names()

    if "agent_graphs" not in existing_tables:
        op.create_table(
            "agent_graphs",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("tenant_id", sa.String(), nullable=False),
            sa.Column("project_id", sa.String(), nullable=False),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("pattern", sa.String(length=30), nullable=False),
            sa.Column("nodes_json", sa.JSON(), nullable=False),
            sa.Column("edges_json", sa.JSON(), nullable=False),
            sa.Column("shared_context_keys", sa.JSON(), nullable=False),
            sa.Column("max_total_steps", sa.Integer(), nullable=False),
            sa.Column("metadata_json", sa.JSON(), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(
                ["project_id"],
                ["projects.id"],
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "tenant_id", "project_id", "name", name="uq_agent_graphs_tenant_project_name"
            ),
        )
        op.create_index(
            "ix_agent_graphs_project_active",
            "agent_graphs",
            ["project_id", "is_active"],
            unique=False,
        )
        op.create_index(
            op.f("ix_agent_graphs_project_id"), "agent_graphs", ["project_id"], unique=False
        )
        op.create_index(
            op.f("ix_agent_graphs_tenant_id"), "agent_graphs", ["tenant_id"], unique=False
        )

    if "graph_runs" not in existing_tables:
        op.create_table(
            "graph_runs",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("graph_id", sa.String(), nullable=False),
            sa.Column("conversation_id", sa.String(), nullable=False),
            sa.Column("tenant_id", sa.String(), nullable=False),
            sa.Column("project_id", sa.String(), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("shared_context", sa.JSON(), nullable=False),
            sa.Column("current_node_ids", sa.JSON(), nullable=False),
            sa.Column("total_steps", sa.Integer(), nullable=False),
            sa.Column("max_total_steps", sa.Integer(), nullable=False),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(
                ["conversation_id"],
                ["conversations.id"],
            ),
            sa.ForeignKeyConstraint(["graph_id"], ["agent_graphs.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            op.f("ix_graph_runs_conversation_id"), "graph_runs", ["conversation_id"], unique=False
        )
        op.create_index(
            "ix_graph_runs_conversation_status",
            "graph_runs",
            ["conversation_id", "status"],
            unique=False,
        )
        op.create_index(op.f("ix_graph_runs_graph_id"), "graph_runs", ["graph_id"], unique=False)
        op.create_index(
            "ix_graph_runs_graph_status", "graph_runs", ["graph_id", "status"], unique=False
        )
        op.create_index(op.f("ix_graph_runs_tenant_id"), "graph_runs", ["tenant_id"], unique=False)

    if "node_executions" not in existing_tables:
        op.create_table(
            "node_executions",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("graph_run_id", sa.String(), nullable=False),
            sa.Column("node_id", sa.String(), nullable=False),
            sa.Column("agent_session_id", sa.String(), nullable=True),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("input_context", sa.JSON(), nullable=False),
            sa.Column("output_context", sa.JSON(), nullable=False),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["graph_run_id"], ["graph_runs.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            op.f("ix_node_executions_graph_run_id"),
            "node_executions",
            ["graph_run_id"],
            unique=False,
        )
        op.create_index(
            "ix_node_executions_run_node",
            "node_executions",
            ["graph_run_id", "node_id"],
            unique=False,
        )
        op.create_index(
            "ix_node_executions_status", "node_executions", ["graph_run_id", "status"], unique=False
        )


def downgrade() -> None:
    op.drop_index("ix_node_executions_status", table_name="node_executions")
    op.drop_index("ix_node_executions_run_node", table_name="node_executions")
    op.drop_index(op.f("ix_node_executions_graph_run_id"), table_name="node_executions")
    op.drop_table("node_executions")
    op.drop_index(op.f("ix_graph_runs_tenant_id"), table_name="graph_runs")
    op.drop_index("ix_graph_runs_graph_status", table_name="graph_runs")
    op.drop_index(op.f("ix_graph_runs_graph_id"), table_name="graph_runs")
    op.drop_index("ix_graph_runs_conversation_status", table_name="graph_runs")
    op.drop_index(op.f("ix_graph_runs_conversation_id"), table_name="graph_runs")
    op.drop_table("graph_runs")
    op.drop_index(op.f("ix_agent_graphs_tenant_id"), table_name="agent_graphs")
    op.drop_index(op.f("ix_agent_graphs_project_id"), table_name="agent_graphs")
    op.drop_index("ix_agent_graphs_project_active", table_name="agent_graphs")
    op.drop_table("agent_graphs")
