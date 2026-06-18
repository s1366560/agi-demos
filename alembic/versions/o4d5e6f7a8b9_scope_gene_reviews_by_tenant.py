"""Scope gene reviews by tenant.

Revision ID: o4d5e6f7a8b9
Revises: n3c4d5e6f7a8
Create Date: 2026-06-18
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "o4d5e6f7a8b9"
down_revision: str | Sequence[str] | None = "n3c4d5e6f7a8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TABLE_NAME = "gene_reviews"
OLD_UNIQUE_INDEX = "uq_gene_review_user_gene"
TENANT_ID_FK = "fk_gene_reviews_tenant_id_tenants"
TENANT_UNIQUE_INDEX = "uq_gene_review_tenant_user_gene"
TENANT_LOOKUP_INDEX = "ix_gene_reviews_tenant_gene_created"


def upgrade() -> None:
    op.add_column(TABLE_NAME, sa.Column("tenant_id", sa.String(), nullable=True))
    op.create_foreign_key(
        TENANT_ID_FK,
        TABLE_NAME,
        "tenants",
        ["tenant_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.execute(
        sa.text(
            """
            UPDATE gene_reviews AS review
            SET tenant_id = gene.tenant_id
            FROM gene_market AS gene
            WHERE review.gene_id = gene.id
              AND review.tenant_id IS NULL
              AND gene.tenant_id IS NOT NULL
            """
        )
    )

    _drop_index_if_exists(OLD_UNIQUE_INDEX)
    op.create_index(
        TENANT_UNIQUE_INDEX,
        TABLE_NAME,
        ["tenant_id", "gene_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
        sqlite_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        TENANT_LOOKUP_INDEX,
        TABLE_NAME,
        ["tenant_id", "gene_id", "created_at"],
    )


def downgrade() -> None:
    _drop_index_if_exists(TENANT_LOOKUP_INDEX)
    _drop_index_if_exists(TENANT_UNIQUE_INDEX)
    _drop_foreign_key_if_exists(TENANT_ID_FK)
    op.drop_column(TABLE_NAME, "tenant_id")

    op.create_index(
        OLD_UNIQUE_INDEX,
        TABLE_NAME,
        ["gene_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
        sqlite_where=sa.text("deleted_at IS NULL"),
    )


def _drop_index_if_exists(index_name: str) -> None:
    inspector = sa.inspect(op.get_bind())
    for index in inspector.get_indexes(TABLE_NAME):
        if index["name"] == index_name:
            op.drop_index(index_name, table_name=TABLE_NAME)
            return


def _drop_foreign_key_if_exists(constraint_name: str) -> None:
    inspector = sa.inspect(op.get_bind())
    for constraint in inspector.get_foreign_keys(TABLE_NAME):
        if constraint["name"] == constraint_name:
            op.drop_constraint(constraint_name, TABLE_NAME, type_="foreignkey")
            return
