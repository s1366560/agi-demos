"""add plugin shadow rollout ledger

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-08-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "c9d0e1f2a3b4"
down_revision: str | Sequence[str] | None = "b8c9d0e1f2a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Persist shadow-mode rollout parity evidence beyond process lifetime."""
    op.create_table(
        "platform_plugin_shadow_rollout_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("capability", sa.String(length=64), nullable=False),
        sa.Column("event_name", sa.String(length=255), nullable=False),
        sa.Column("hook_name", sa.String(length=255), nullable=False),
        sa.Column("scope_type", sa.String(length=32), nullable=False),
        sa.Column("scope_id", sa.String(length=255), nullable=False),
        sa.Column("equal", sa.Boolean(), nullable=False),
        sa.Column("legacy_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("typed_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "capability IN ('agent_events', 'agent_tools')",
            name="ck_platform_plugin_shadow_capability",
        ),
        sa.CheckConstraint(
            "scope_type IN ('global', 'tenant', 'project', 'session')",
            name="ck_platform_plugin_shadow_scope",
        ),
    )
    op.create_index(
        "ix_platform_plugin_shadow_rollout_lookup",
        "platform_plugin_shadow_rollout_events",
        ["capability", "event_name", "occurred_at"],
    )


def downgrade() -> None:
    """Remove shadow rollout evidence."""
    op.drop_index(
        "ix_platform_plugin_shadow_rollout_lookup",
        table_name="platform_plugin_shadow_rollout_events",
    )
    op.drop_table("platform_plugin_shadow_rollout_events")
