"""relax platform plugin NACK applied version

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-08-18
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b8c9d0e1f2a3"
down_revision: str | Sequence[str] | None = "a7b8c9d0e1f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Allow the first rejected snapshot to report that no version was applied."""
    with op.batch_alter_table("platform_plugin_apply_states") as batch:
        batch.drop_constraint("ck_platform_plugin_apply_versions", type_="check")
        batch.create_check_constraint(
            "ck_platform_plugin_apply_versions",
            "requested_version > 0 AND applied_version >= 0",
        )


def downgrade() -> None:
    """Restore the pre-zero applied-version invariant."""
    op.execute(
        "UPDATE platform_plugin_apply_states SET applied_version = 1 WHERE applied_version < 1"
    )
    with op.batch_alter_table("platform_plugin_apply_states") as batch:
        batch.drop_constraint("ck_platform_plugin_apply_versions", type_="check")
        batch.create_check_constraint(
            "ck_platform_plugin_apply_versions",
            "requested_version > 0 AND applied_version > 0",
        )
