"""add_invitations_table

Revision ID: 9877be02d003
Revises: 91c6f36287e1
Create Date: 2026-03-27 10:29:04.597719

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "9877be02d003"
down_revision: Union[str, Sequence[str], None] = "91c6f36287e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "invitations",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("token", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("invited_by", sa.String(), nullable=False),
        sa.Column("accepted_by", sa.String(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["accepted_by"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["invited_by"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_invitations_email"), "invitations", ["email"], unique=False)
    op.create_index(
        "ix_invitations_pending_unique",
        "invitations",
        ["tenant_id", "email"],
        unique=True,
        postgresql_where="status = 'pending' AND deleted_at IS NULL",
    )
    op.create_index(op.f("ix_invitations_status"), "invitations", ["status"], unique=False)
    op.create_index(op.f("ix_invitations_tenant_id"), "invitations", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_invitations_token"), "invitations", ["token"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_invitations_token"), table_name="invitations")
    op.drop_index(op.f("ix_invitations_tenant_id"), table_name="invitations")
    op.drop_index(op.f("ix_invitations_status"), table_name="invitations")
    op.drop_index(
        "ix_invitations_pending_unique",
        table_name="invitations",
        postgresql_where="status = 'pending' AND deleted_at IS NULL",
    )
    op.drop_index(op.f("ix_invitations_email"), table_name="invitations")
    op.drop_table("invitations")
