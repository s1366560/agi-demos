"""Scope gene and genome slug uniqueness by tenant.

Revision ID: l1a2b3c4d5e6
Revises: k9f0a1b2c3d4
Create Date: 2026-06-17 14:45:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "l1a2b3c4d5e6"
down_revision: str | Sequence[str] | None = "k9f0a1b2c3d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


GENE_MARKET_TABLE = "gene_market"
GENOMES_TABLE = "genomes"

OLD_GENE_MARKET_SLUG_CONSTRAINT = "gene_market_slug_key"
OLD_GENOMES_SLUG_CONSTRAINT = "ix_genomes_slug"

GENE_MARKET_GLOBAL_SLUG_INDEX = "uq_gene_market_global_slug"
GENE_MARKET_TENANT_SLUG_INDEX = "uq_gene_market_tenant_slug"
GENOMES_GLOBAL_SLUG_INDEX = "uq_genomes_global_slug"
GENOMES_TENANT_SLUG_INDEX = "uq_genomes_tenant_slug"


def upgrade() -> None:
    _drop_existing_slug_unique(GENE_MARKET_TABLE)
    _drop_existing_slug_unique(GENOMES_TABLE)

    op.create_index(
        GENE_MARKET_GLOBAL_SLUG_INDEX,
        GENE_MARKET_TABLE,
        ["slug"],
        unique=True,
        postgresql_where=sa.text("tenant_id IS NULL"),
        sqlite_where=sa.text("tenant_id IS NULL"),
    )
    op.create_index(
        GENE_MARKET_TENANT_SLUG_INDEX,
        GENE_MARKET_TABLE,
        ["tenant_id", "slug"],
        unique=True,
        postgresql_where=sa.text("tenant_id IS NOT NULL"),
        sqlite_where=sa.text("tenant_id IS NOT NULL"),
    )
    op.create_index(
        GENOMES_GLOBAL_SLUG_INDEX,
        GENOMES_TABLE,
        ["slug"],
        unique=True,
        postgresql_where=sa.text("tenant_id IS NULL"),
        sqlite_where=sa.text("tenant_id IS NULL"),
    )
    op.create_index(
        GENOMES_TENANT_SLUG_INDEX,
        GENOMES_TABLE,
        ["tenant_id", "slug"],
        unique=True,
        postgresql_where=sa.text("tenant_id IS NOT NULL"),
        sqlite_where=sa.text("tenant_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(GENOMES_TENANT_SLUG_INDEX, table_name=GENOMES_TABLE)
    op.drop_index(GENOMES_GLOBAL_SLUG_INDEX, table_name=GENOMES_TABLE)
    op.drop_index(GENE_MARKET_TENANT_SLUG_INDEX, table_name=GENE_MARKET_TABLE)
    op.drop_index(GENE_MARKET_GLOBAL_SLUG_INDEX, table_name=GENE_MARKET_TABLE)

    op.create_unique_constraint(
        OLD_GENOMES_SLUG_CONSTRAINT,
        GENOMES_TABLE,
        ["slug"],
    )
    op.create_unique_constraint(
        OLD_GENE_MARKET_SLUG_CONSTRAINT,
        GENE_MARKET_TABLE,
        ["slug"],
    )


def _drop_existing_slug_unique(table_name: str) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    for constraint in inspector.get_unique_constraints(table_name):
        if constraint.get("column_names") == ["slug"]:
            op.drop_constraint(str(constraint["name"]), table_name, type_="unique")
            return

    for index in inspector.get_indexes(table_name):
        if index.get("unique") and index.get("column_names") == ["slug"]:
            op.drop_index(str(index["name"]), table_name=table_name)
            return

    raise RuntimeError(f"No single-column slug uniqueness found on {table_name}")
