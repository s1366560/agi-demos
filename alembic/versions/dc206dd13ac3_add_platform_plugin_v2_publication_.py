"""add platform plugin v2 publication ledger

Revision ID: dc206dd13ac3
Revises: 822cd9402ce6
Create Date: 2026-08-20 21:34:29.178820
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "dc206dd13ac3"
down_revision: str | Sequence[str] | None = "822cd9402ce6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the isolated protocol-v2 publication and receipt ledger."""
    op.create_table(
        "platform_plugin_v2_publications",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("profile_id", sa.String(length=255), nullable=False),
        sa.Column("generation", sa.BigInteger(), nullable=False),
        sa.Column("snapshot_digest", sa.String(length=64), nullable=False),
        sa.Column("requested_version", sa.BigInteger(), nullable=False),
        sa.Column("nonce", sa.String(length=128), nullable=False),
        sa.Column("type_url", sa.String(length=255), nullable=False),
        sa.Column("distribution", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "generation > 0 AND requested_version > 0",
            name="ck_platform_plugin_v2_publication_versions",
        ),
        sa.CheckConstraint(
            "length(snapshot_digest) = 64",
            name="ck_platform_plugin_v2_publication_digest",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("nonce"),
    )
    op.create_index(
        "ix_platform_plugin_v2_publication_profile_generation",
        "platform_plugin_v2_publications",
        ["profile_id", "generation"],
    )
    op.create_index(
        "ix_platform_plugin_v2_publications_requested_version",
        "platform_plugin_v2_publications",
        ["requested_version"],
    )
    op.create_index(
        "ix_platform_plugin_v2_publications_snapshot_digest",
        "platform_plugin_v2_publications",
        ["snapshot_digest"],
    )
    op.create_table(
        "platform_plugin_v2_apply_state_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("data_plane_id", sa.String(length=255), nullable=False),
        sa.Column("requested_publication_id", sa.String(length=36), nullable=False),
        sa.Column("requested_version", sa.BigInteger(), nullable=False),
        sa.Column("requested_digest", sa.String(length=64), nullable=False),
        sa.Column("applied_publication_id", sa.String(length=36), nullable=True),
        sa.Column("applied_version", sa.BigInteger(), nullable=True),
        sa.Column("applied_digest", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('ack', 'nack')",
            name="ck_platform_plugin_v2_apply_event_status",
        ),
        sa.CheckConstraint(
            "requested_version > 0 AND (applied_version IS NULL OR applied_version > 0)",
            name="ck_platform_plugin_v2_apply_event_versions",
        ),
        sa.ForeignKeyConstraint(
            ["applied_publication_id"],
            ["platform_plugin_v2_publications.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["requested_publication_id"],
            ["platform_plugin_v2_publications.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_platform_plugin_v2_apply_event_plane_recorded",
        "platform_plugin_v2_apply_state_events",
        ["data_plane_id", "recorded_at"],
    )
    op.create_index(
        "ix_platform_plugin_v2_apply_state_events_data_plane_id",
        "platform_plugin_v2_apply_state_events",
        ["data_plane_id"],
    )
    op.create_table(
        "platform_plugin_v2_apply_states",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("data_plane_id", sa.String(length=255), nullable=False),
        sa.Column("requested_publication_id", sa.String(length=36), nullable=False),
        sa.Column("requested_version", sa.BigInteger(), nullable=False),
        sa.Column("requested_digest", sa.String(length=64), nullable=False),
        sa.Column("applied_publication_id", sa.String(length=36), nullable=True),
        sa.Column("applied_version", sa.BigInteger(), nullable=True),
        sa.Column("applied_digest", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("last_ack_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('ack', 'nack')",
            name="ck_platform_plugin_v2_apply_status",
        ),
        sa.CheckConstraint(
            "(applied_publication_id IS NULL AND applied_version IS NULL "
            "AND applied_digest IS NULL) OR "
            "(applied_publication_id IS NOT NULL AND applied_version IS NOT NULL "
            "AND applied_digest IS NOT NULL)",
            name="ck_platform_plugin_v2_apply_last_good",
        ),
        sa.CheckConstraint(
            "requested_version > 0 AND (applied_version IS NULL OR applied_version > 0)",
            name="ck_platform_plugin_v2_apply_versions",
        ),
        sa.ForeignKeyConstraint(
            ["applied_publication_id"],
            ["platform_plugin_v2_publications.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["requested_publication_id"],
            ["platform_plugin_v2_publications.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("data_plane_id"),
    )


def downgrade() -> None:
    """Remove the isolated protocol-v2 publication and receipt ledger."""
    op.drop_table("platform_plugin_v2_apply_states")
    op.drop_index(
        "ix_platform_plugin_v2_apply_state_events_data_plane_id",
        table_name="platform_plugin_v2_apply_state_events",
    )
    op.drop_index(
        "ix_platform_plugin_v2_apply_event_plane_recorded",
        table_name="platform_plugin_v2_apply_state_events",
    )
    op.drop_table("platform_plugin_v2_apply_state_events")
    op.drop_index(
        "ix_platform_plugin_v2_publications_snapshot_digest",
        table_name="platform_plugin_v2_publications",
    )
    op.drop_index(
        "ix_platform_plugin_v2_publications_requested_version",
        table_name="platform_plugin_v2_publications",
    )
    op.drop_index(
        "ix_platform_plugin_v2_publication_profile_generation",
        table_name="platform_plugin_v2_publications",
    )
    op.drop_table("platform_plugin_v2_publications")
