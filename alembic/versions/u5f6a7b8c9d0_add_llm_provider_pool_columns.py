"""add load-balancing pool columns to llm_providers

Adds columns that let multiple ``llm_providers`` rows participate in a
tenant-wide model pool with weighted, tiered, least-loaded routing:

- ``pool_weight``      : float, used as tiebreaker by the balancer
- ``pool_enabled``     : bool, opt-out from the pool without disabling the row
- ``model_tier``       : 'small' | 'medium' | 'large' | NULL hint for routing
- ``secondary_models`` : optional extra model names sharing this provider's key

All columns are nullable / have safe defaults so existing rows continue
to behave identically until they are opted into the pool.

Revision ID: u5f6a7b8c9d0
Revises: t4e5f6a7b8c9
Create Date: 2026-05-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "u5f6a7b8c9d0"
down_revision: str | Sequence[str] | None = "t4e5f6a7b8c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table):
        return False
    return any(col["name"] == column for col in inspector.get_columns(table))


def upgrade() -> None:
    if not sa.inspect(op.get_bind()).has_table("llm_providers"):
        return

    if not _has_column("llm_providers", "pool_weight"):
        op.add_column(
            "llm_providers",
            sa.Column(
                "pool_weight",
                sa.Float(),
                nullable=False,
                server_default=sa.text("1.0"),
            ),
        )

    if not _has_column("llm_providers", "pool_enabled"):
        op.add_column(
            "llm_providers",
            sa.Column(
                "pool_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("true"),
            ),
        )

    if not _has_column("llm_providers", "model_tier"):
        op.add_column(
            "llm_providers",
            sa.Column("model_tier", sa.String(length=16), nullable=True),
        )

    if not _has_column("llm_providers", "secondary_models"):
        op.add_column(
            "llm_providers",
            sa.Column(
                "secondary_models",
                sa.JSON().with_variant(JSONB, "postgresql"),
                nullable=True,
            ),
        )

    op.execute(
        "ALTER TABLE llm_providers DROP CONSTRAINT IF EXISTS llm_providers_valid_model_tier"
    )
    op.execute(
        "ALTER TABLE llm_providers "
        "ADD CONSTRAINT llm_providers_valid_model_tier "
        "CHECK (model_tier IS NULL OR model_tier IN ('small', 'medium', 'large'))"
    )

    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_llm_providers_pool_enabled "
        "ON llm_providers (pool_enabled) WHERE pool_enabled = TRUE"
    )


def downgrade() -> None:
    if not sa.inspect(op.get_bind()).has_table("llm_providers"):
        return

    op.execute("DROP INDEX IF EXISTS idx_llm_providers_pool_enabled")
    op.execute(
        "ALTER TABLE llm_providers DROP CONSTRAINT IF EXISTS llm_providers_valid_model_tier"
    )

    for column in ("secondary_models", "model_tier", "pool_enabled", "pool_weight"):
        if _has_column("llm_providers", column):
            op.drop_column("llm_providers", column)
