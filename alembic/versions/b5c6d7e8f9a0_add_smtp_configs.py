"""add smtp_configs

Revision ID: b5c6d7e8f9a0
Revises: a4b5c6d7e8f9
Create Date: 2026-03-27 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b5c6d7e8f9a0"
down_revision: str | Sequence[str] | None = "a4b5c6d7e8f9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "smtp_configs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("smtp_host", sa.String(), nullable=False),
        sa.Column(
            "smtp_port",
            sa.Integer(),
            nullable=False,
            server_default="587",
        ),
        sa.Column("smtp_username", sa.String(), nullable=False),
        sa.Column("smtp_password_encrypted", sa.Text(), nullable=False),
        sa.Column("from_email", sa.String(), nullable=False),
        sa.Column("from_name", sa.String(), nullable=True),
        sa.Column(
            "use_tls",
            sa.Boolean(),
            nullable=False,
            server_default="true",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("tenant_id", name="uq_smtp_configs_tenant_id"),
    )
    op.create_index("ix_smtp_configs_tenant_id", "smtp_configs", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_smtp_configs_tenant_id", table_name="smtp_configs")
    op.drop_table("smtp_configs")
