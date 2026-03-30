"""add trust_policies and decision_records tables

Revision ID: a4b5c6d7e8f9
Revises: 9877be02d003
Create Date: 2026-03-27 16:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a4b5c6d7e8f9"
down_revision: str | Sequence[str] | None = "9877be02d003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "trust_policies",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("workspace_id", sa.String(), nullable=False),
        sa.Column("agent_instance_id", sa.String(), nullable=False),
        sa.Column("action_type", sa.String(), nullable=False),
        sa.Column("granted_by", sa.String(), nullable=False),
        sa.Column("grant_type", sa.String(), nullable=False),
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
        op.f("ix_trust_policies_tenant_id"),
        "trust_policies",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_trust_policies_workspace_id"),
        "trust_policies",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_trust_policies_agent_instance_id"),
        "trust_policies",
        ["agent_instance_id"],
        unique=False,
    )

    op.create_table(
        "decision_records",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("workspace_id", sa.String(), nullable=False),
        sa.Column("agent_instance_id", sa.String(), nullable=False),
        sa.Column("decision_type", sa.String(), nullable=False),
        sa.Column("context_summary", sa.Text(), nullable=True),
        sa.Column(
            "proposal",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column(
            "outcome",
            sa.String(),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("reviewer_id", sa.String(), nullable=True),
        sa.Column("review_type", sa.String(), nullable=True),
        sa.Column("review_comment", sa.Text(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
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
        op.f("ix_decision_records_tenant_id"),
        "decision_records",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_decision_records_workspace_id"),
        "decision_records",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_decision_records_agent_instance_id"),
        "decision_records",
        ["agent_instance_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_decision_records_agent_instance_id"),
        table_name="decision_records",
    )
    op.drop_index(
        op.f("ix_decision_records_workspace_id"),
        table_name="decision_records",
    )
    op.drop_index(
        op.f("ix_decision_records_tenant_id"),
        table_name="decision_records",
    )
    op.drop_table("decision_records")

    op.drop_index(
        op.f("ix_trust_policies_agent_instance_id"),
        table_name="trust_policies",
    )
    op.drop_index(
        op.f("ix_trust_policies_workspace_id"),
        table_name="trust_policies",
    )
    op.drop_index(
        op.f("ix_trust_policies_tenant_id"),
        table_name="trust_policies",
    )
    op.drop_table("trust_policies")
