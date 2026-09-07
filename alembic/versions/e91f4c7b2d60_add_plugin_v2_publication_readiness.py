"""add plugin v2 publication readiness

Revision ID: e91f4c7b2d60
Revises: dc206dd13ac3
Create Date: 2026-08-22 10:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e91f4c7b2d60"
down_revision: str | Sequence[str] | None = "dc206dd13ac3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add immutable data-plane roster, deadline, and readiness evidence."""
    op.add_column(
        "platform_plugin_v2_publications",
        sa.Column(
            "required_data_plane_ids",
            sa.JSON(),
            server_default=sa.text("'[\"python-api-v2\"]'"),
            nullable=False,
        ),
    )
    op.add_column(
        "platform_plugin_v2_publications",
        sa.Column(
            "ack_deadline_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now() + interval '30 seconds'"),
            nullable=False,
        ),
    )
    op.add_column(
        "platform_plugin_v2_publications",
        sa.Column(
            "status",
            sa.String(length=16),
            server_default="reconciling",
            nullable=False,
        ),
    )
    op.add_column(
        "platform_plugin_v2_publications",
        sa.Column("ready_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "platform_plugin_v2_publications",
        sa.Column(
            "status_updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.add_column(
        "platform_plugin_v2_publications",
        sa.Column("republished_from_id", sa.String(length=36), nullable=True),
    )
    op.execute(
        sa.text(
            """
            UPDATE platform_plugin_v2_publications
            SET ack_deadline_at = created_at + interval '30 seconds'
            """
        )
    )
    op.create_foreign_key(
        "fk_platform_plugin_v2_publication_republished_from",
        "platform_plugin_v2_publications",
        "platform_plugin_v2_publications",
        ["republished_from_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_platform_plugin_v2_publication_status",
        "platform_plugin_v2_publications",
        "status IN ('reconciling', 'ready', 'degraded')",
    )
    op.create_check_constraint(
        "ck_platform_plugin_v2_publication_deadline",
        "platform_plugin_v2_publications",
        "ack_deadline_at > created_at",
    )
    op.create_index(
        "ix_platform_plugin_v2_publication_status_ready",
        "platform_plugin_v2_publications",
        ["status", "ready_at"],
    )
    op.create_index(
        "ix_platform_plugin_v2_publication_republished_from",
        "platform_plugin_v2_publications",
        ["republished_from_id"],
    )
    op.execute(
        sa.text(
            """
            WITH ready_event AS (
                SELECT event.requested_publication_id AS publication_id,
                       MIN(event.recorded_at) AS recorded_at
                FROM platform_plugin_v2_apply_state_events AS event
                JOIN platform_plugin_v2_publications AS publication
                  ON publication.id = event.requested_publication_id
                WHERE event.data_plane_id = 'python-api-v2'
                  AND event.status = 'ack'
                  AND event.applied_publication_id = publication.id
                  AND event.requested_version = publication.requested_version
                  AND event.requested_digest = publication.snapshot_digest
                  AND event.applied_version = publication.requested_version
                  AND event.applied_digest = publication.snapshot_digest
                GROUP BY event.requested_publication_id
            )
            UPDATE platform_plugin_v2_publications AS publication
            SET status = 'ready',
                ready_at = ready_event.recorded_at,
                status_updated_at = ready_event.recorded_at
            FROM ready_event
            WHERE ready_event.publication_id = publication.id
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE platform_plugin_v2_publications
            SET status = 'degraded', status_updated_at = now()
            WHERE status = 'reconciling' AND ack_deadline_at <= now()
            """
        )
    )
    op.alter_column(
        "platform_plugin_v2_publications",
        "required_data_plane_ids",
        existing_type=sa.JSON(),
        server_default=None,
    )
    op.alter_column(
        "platform_plugin_v2_publications",
        "ack_deadline_at",
        existing_type=sa.DateTime(timezone=True),
        server_default=None,
    )
    op.alter_column(
        "platform_plugin_v2_publications",
        "status_updated_at",
        existing_type=sa.DateTime(timezone=True),
        server_default=None,
    )


def downgrade() -> None:
    """Remove protocol-v2 publication readiness metadata."""
    op.drop_index(
        "ix_platform_plugin_v2_publication_republished_from",
        table_name="platform_plugin_v2_publications",
    )
    op.drop_index(
        "ix_platform_plugin_v2_publication_status_ready",
        table_name="platform_plugin_v2_publications",
    )
    op.drop_constraint(
        "ck_platform_plugin_v2_publication_deadline",
        "platform_plugin_v2_publications",
        type_="check",
    )
    op.drop_constraint(
        "ck_platform_plugin_v2_publication_status",
        "platform_plugin_v2_publications",
        type_="check",
    )
    op.drop_constraint(
        "fk_platform_plugin_v2_publication_republished_from",
        "platform_plugin_v2_publications",
        type_="foreignkey",
    )
    op.drop_column("platform_plugin_v2_publications", "republished_from_id")
    op.drop_column("platform_plugin_v2_publications", "status_updated_at")
    op.drop_column("platform_plugin_v2_publications", "ready_at")
    op.drop_column("platform_plugin_v2_publications", "status")
    op.drop_column("platform_plugin_v2_publications", "ack_deadline_at")
    op.drop_column("platform_plugin_v2_publications", "required_data_plane_ids")
