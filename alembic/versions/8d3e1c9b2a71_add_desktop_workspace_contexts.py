"""Add authoritative desktop workspace contexts.

Revision ID: 8d3e1c9b2a71
Revises: 7c2e9d4a6f10
Create Date: 2026-07-14 20:10:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "8d3e1c9b2a71"
down_revision: str | Sequence[str] | None = "7c2e9d4a6f10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create per-user context state and its immutable switch audit log."""
    op.create_table(
        "agistack_desktop_workspace_contexts",
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("revision >= 0", name="ck_desktop_workspace_context_revision"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_index(
        "ix_desktop_workspace_context_scope",
        "agistack_desktop_workspace_contexts",
        ["tenant_id", "project_id"],
        unique=False,
    )

    op.create_table(
        "agistack_desktop_workspace_context_events",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("actor_api_key_id", sa.String(), nullable=True),
        sa.Column("from_tenant_id", sa.String(), nullable=True),
        sa.Column("from_project_id", sa.String(), nullable=True),
        sa.Column("to_tenant_id", sa.String(), nullable=False),
        sa.Column("to_project_id", sa.String(), nullable=False),
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column(
            "value_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("revision > 0", name="ck_desktop_workspace_context_event_revision"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "idempotency_key",
            name="uq_desktop_workspace_context_event_intent",
        ),
        sa.UniqueConstraint(
            "user_id",
            "revision",
            name="uq_desktop_workspace_context_event_revision",
        ),
    )
    op.create_index(
        "ix_desktop_workspace_context_events_user_revision",
        "agistack_desktop_workspace_context_events",
        ["user_id", sa.text("revision DESC")],
        unique=False,
    )


def downgrade() -> None:
    """Remove desktop context state after its immutable events."""
    op.drop_index(
        "ix_desktop_workspace_context_events_user_revision",
        table_name="agistack_desktop_workspace_context_events",
    )
    op.drop_table("agistack_desktop_workspace_context_events")
    op.drop_index(
        "ix_desktop_workspace_context_scope",
        table_name="agistack_desktop_workspace_contexts",
    )
    op.drop_table("agistack_desktop_workspace_contexts")
