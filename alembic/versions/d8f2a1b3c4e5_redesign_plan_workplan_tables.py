"""Redesign plan and workplan tables for HITL workflow.

Revision ID: d8f2a1b3c4e5
Revises: c7a3e5f1b2d4
Create Date: 2025-01-20

Updates plan_documents table:
- Add project_id, user_query, exploration_summary columns
- Change status default from 'draft' to 'exploring'

Updates work_plans table:
- Add plan_id FK to plan_documents
- Add project_id column
- Store steps as JSON instead of separate table
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d8f2a1b3c4e5"
down_revision: Union[str, Sequence[str], None] = "c7a3e5f1b2d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # plan_documents: add columns if they don't exist
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if inspector.has_table("plan_documents"):
        existing_cols = {c["name"] for c in inspector.get_columns("plan_documents")}

        if "project_id" not in existing_cols:
            op.add_column("plan_documents", sa.Column("project_id", sa.String(), nullable=True))

        if "user_query" not in existing_cols:
            op.add_column(
                "plan_documents", sa.Column("user_query", sa.Text(), nullable=True, default="")
            )

        if "exploration_summary" not in existing_cols:
            op.add_column(
                "plan_documents",
                sa.Column("exploration_summary", sa.Text(), nullable=True, default=""),
            )

        if "version" not in existing_cols:
            op.add_column(
                "plan_documents", sa.Column("version", sa.Integer(), nullable=True, default=1)
            )

        # Remove metadata_json if present
        if "metadata_json" in existing_cols:
            op.drop_column("plan_documents", "metadata_json")

    # work_plans: add plan_id and project_id
    if inspector.has_table("work_plans"):
        existing_cols = {c["name"] for c in inspector.get_columns("work_plans")}

        if "plan_id" not in existing_cols:
            op.add_column("work_plans", sa.Column("plan_id", sa.String(), nullable=True))
            # Add FK constraint
            op.create_foreign_key(
                "fk_work_plans_plan_id",
                "work_plans",
                "plan_documents",
                ["plan_id"],
                ["id"],
                ondelete="CASCADE",
            )

        if "project_id" not in existing_cols:
            op.add_column("work_plans", sa.Column("project_id", sa.String(), nullable=True))

        # Remove old columns if present
        if "completed_step_indices" in existing_cols:
            op.drop_column("work_plans", "completed_step_indices")

        if "workflow_pattern_id" in existing_cols:
            op.drop_column("work_plans", "workflow_pattern_id")


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if inspector.has_table("work_plans"):
        existing_cols = {c["name"] for c in inspector.get_columns("work_plans")}
        if "plan_id" in existing_cols:
            op.drop_constraint("fk_work_plans_plan_id", "work_plans", type_="foreignkey")
            op.drop_column("work_plans", "plan_id")
        if "project_id" in existing_cols:
            op.drop_column("work_plans", "project_id")

    if inspector.has_table("plan_documents"):
        existing_cols = {c["name"] for c in inspector.get_columns("plan_documents")}
        for col in ["project_id", "user_query", "exploration_summary", "version"]:
            if col in existing_cols:
                op.drop_column("plan_documents", col)
