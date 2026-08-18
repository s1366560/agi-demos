"""add http shadow rollout capability

Revision ID: 822cd9402ce6
Revises: af959ee425da
Create Date: 2026-08-18
"""

from collections.abc import Sequence

from alembic import op

revision: str = "822cd9402ce6"
down_revision: str | Sequence[str] | None = "af959ee425da"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Allow durable HTTP route shadow comparison evidence."""
    op.drop_constraint(
        "ck_platform_plugin_shadow_capability",
        table_name="platform_plugin_shadow_rollout_events",
        type_="check",
    )
    op.create_check_constraint(
        "ck_platform_plugin_shadow_capability",
        "platform_plugin_shadow_rollout_events",
        "capability IN ('agent_events', 'agent_tools', 'llm_routes', 'http_routes')",
    )


def downgrade() -> None:
    """Remove the HTTP shadow capability vocabulary."""
    op.drop_constraint(
        "ck_platform_plugin_shadow_capability",
        table_name="platform_plugin_shadow_rollout_events",
        type_="check",
    )
    op.create_check_constraint(
        "ck_platform_plugin_shadow_capability",
        "platform_plugin_shadow_rollout_events",
        "capability IN ('agent_events', 'agent_tools', 'llm_routes')",
    )
