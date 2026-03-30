"""add org_gene_policies and registry_configs tables

Revision ID: 02ebbece83c2
Revises: a25d7458e158
Create Date: 2026-03-27 19:38:21.662015

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "02ebbece83c2"
down_revision: Union[str, Sequence[str], None] = "a25d7458e158"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "org_gene_policies",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("policy_key", sa.String(), nullable=False),
        sa.Column("policy_value", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_org_gene_policies_tenant_id"), "org_gene_policies", ["tenant_id"], unique=False
    )
    op.create_index(
        "uq_org_gene_policies_tenant_key",
        "org_gene_policies",
        ["tenant_id", "policy_key"],
        unique=True,
        postgresql_where="deleted_at IS NULL",
    )
    op.create_table(
        "registry_configs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("registry_type", sa.String(), nullable=False),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("username", sa.String(), nullable=True),
        sa.Column("password_encrypted", sa.Text(), nullable=True),
        sa.Column("is_default", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_registry_configs_tenant_id"), "registry_configs", ["tenant_id"], unique=False
    )
    op.create_index(
        "uq_registry_configs_tenant_name",
        "registry_configs",
        ["tenant_id", "name"],
        unique=True,
        postgresql_where="deleted_at IS NULL",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "uq_registry_configs_tenant_name",
        table_name="registry_configs",
        postgresql_where="deleted_at IS NULL",
    )
    op.drop_index(op.f("ix_registry_configs_tenant_id"), table_name="registry_configs")
    op.drop_table("registry_configs")
    op.drop_index(
        "uq_org_gene_policies_tenant_key",
        table_name="org_gene_policies",
        postgresql_where="deleted_at IS NULL",
    )
    op.drop_index(op.f("ix_org_gene_policies_tenant_id"), table_name="org_gene_policies")
    op.drop_table("org_gene_policies")
