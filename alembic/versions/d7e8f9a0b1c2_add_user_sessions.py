"""Add rotating cloud login sessions.

Revision ID: d7e8f9a0b1c2
Revises: c4e5f6a7b8c0
Create Date: 2026-11-20 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d7e8f9a0b1c2"
down_revision: str | Sequence[str] | None = "c4e5f6a7b8c0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_login_tables() -> bool:
    """Workspace-only upgrade paths stamp past the MemStack login tables."""
    inspector = sa.inspect(op.get_bind())
    return inspector.has_table("users") and inspector.has_table("api_keys")


def upgrade() -> None:
    if not _has_login_tables():
        return
    op.create_table(
        "user_sessions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("family_id", sa.String(), nullable=False),
        sa.Column("refresh_token_hash", sa.String(length=64), nullable=False),
        sa.Column("access_api_key_id", sa.String(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replaced_by", sa.String(), nullable=True),
        sa.Column("device_label", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["access_api_key_id"], ["api_keys.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("refresh_token_hash", name="uq_user_sessions_refresh_token_hash"),
    )
    op.create_index("ix_user_sessions_family", "user_sessions", ["family_id"])
    op.create_index("ix_user_sessions_user", "user_sessions", ["user_id"])
    op.create_index("ix_user_sessions_access_api_key", "user_sessions", ["access_api_key_id"])


def downgrade() -> None:
    if not sa.inspect(op.get_bind()).has_table("user_sessions"):
        return
    op.drop_index("ix_user_sessions_access_api_key", table_name="user_sessions")
    op.drop_index("ix_user_sessions_user", table_name="user_sessions")
    op.drop_index("ix_user_sessions_family", table_name="user_sessions")
    op.drop_table("user_sessions")
