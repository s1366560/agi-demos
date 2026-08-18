"""add llm shadow rollout capability

Revision ID: af959ee425da
Revises: 23dc191c451d
Create Date: 2026-08-18
"""

from collections.abc import Sequence

from alembic import op

revision: str = "af959ee425da"
down_revision: str | Sequence[str] | None = "23dc191c451d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Allow durable LLM route shadow comparison evidence."""
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


def downgrade() -> None:
    """Restore the agent-only shadow capability vocabulary."""
    op.drop_constraint(
        "ck_platform_plugin_shadow_capability",
        table_name="platform_plugin_shadow_rollout_events",
        type_="check",
    )
    op.create_check_constraint(
        "ck_platform_plugin_shadow_capability",
        "platform_plugin_shadow_rollout_events",
        "capability IN ('agent_events', 'agent_tools')",
    )
