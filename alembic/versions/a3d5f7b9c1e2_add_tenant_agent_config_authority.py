"""add tenant agent config authority

Revision ID: a3d5f7b9c1e2
Revises: 048a7630034e
Create Date: 2026-08-03 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a3d5f7b9c1e2"
down_revision: str | Sequence[str] | None = "048a7630034e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the tenant agent configuration revision authority."""
    op.create_table(
        "tenant_agent_config_authority",
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("authority_revision", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "authority_revision >= 1",
            name="ck_tenant_agent_config_authority_revision_positive",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("tenant_id"),
    )


def downgrade() -> None:
    """Remove the tenant agent configuration revision authority."""
    op.drop_table("tenant_agent_config_authority")
