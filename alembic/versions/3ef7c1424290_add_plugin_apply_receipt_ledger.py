"""add plugin apply receipt ledger

Revision ID: 3ef7c1424290
Revises: c9d0e1f2a3b4
Create Date: 2026-08-18
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "3ef7c1424290"
down_revision: str | Sequence[str] | None = "c9d0e1f2a3b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Persist immutable ACK/NACK history for rollback-drill audits."""
    op.create_table(
        "platform_plugin_apply_state_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("data_plane_id", sa.String(length=255), nullable=False),
        sa.Column("snapshot_digest", sa.String(length=64), nullable=False),
        sa.Column("requested_version", sa.BigInteger(), nullable=False),
        sa.Column("applied_version", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "requested_version > 0 AND applied_version >= 0",
            name="ck_platform_plugin_apply_event_versions",
        ),
        sa.CheckConstraint(
            "status IN ('ack', 'nack')",
            name="ck_platform_plugin_apply_event_status",
        ),
    )
    op.create_index(
        "ix_platform_plugin_apply_state_events_data_plane_id",
        "platform_plugin_apply_state_events",
        ["data_plane_id"],
    )
    op.create_index(
        "ix_platform_plugin_apply_event_plane_recorded",
        "platform_plugin_apply_state_events",
        ["data_plane_id", "recorded_at", "requested_version"],
    )


def downgrade() -> None:
    """Remove the append-only receipt ledger."""
    op.drop_index(
        "ix_platform_plugin_apply_event_plane_recorded",
        table_name="platform_plugin_apply_state_events",
    )
    op.drop_index(
        "ix_platform_plugin_apply_state_events_data_plane_id",
        table_name="platform_plugin_apply_state_events",
    )
    op.drop_table("platform_plugin_apply_state_events")
