"""Pin project graph projection work and its replayable input."""

import sqlalchemy as sa

from alembic import op

revision = "8de32c54a61f"
down_revision = "7ca467e31a9a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "graph_projection_jobs",
        sa.Column("task_id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("memory_id", sa.String(), nullable=False),
        sa.Column("source_revision", sa.Integer(), nullable=False),
        sa.Column("actor_id", sa.String(), nullable=False),
        sa.Column("author_id", sa.String(), nullable=False),
        sa.Column("pin", sa.JSON(), nullable=False),
        sa.Column("tool", sa.String(), nullable=False),
        sa.Column("phase", sa.String(), nullable=False),
        sa.Column("snapshot", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("summary", sa.JSON(none_as_null=True), nullable=True),
        sa.Column(
            "retry_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["memory_id"], ["memories.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["task_logs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("task_id"),
    )
    op.create_index(
        "ix_graph_projection_retry", "graph_projection_jobs", ["phase", "retry_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_graph_projection_retry", table_name="graph_projection_jobs")
    op.drop_table("graph_projection_jobs")
