"""Promote one explicitly selected existing local development default administrator.

Revision ID: d10a27f4c901
Revises: c86fa94f00dd

This is an opt-in data migration. Ordinary deployments perform no account update.
Selection must be supplied through the reviewed Alembic -x arguments; application
startup never supplies them. No password, API key, role or membership is changed.
"""

from collections.abc import Sequence
from uuid import UUID

import sqlalchemy as sa

from alembic import op

revision: str = "d10a27f4c901"
down_revision: str | Sequence[str] | None = "c86fa94f00dd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Update only a selected active default account in a loopback development DB."""
    migration = op.get_context()
    selection = migration.opts.get("development_admin_promotion", {})
    user_id, email = selection.get("user_id"), selection.get("email")
    if user_id is None and email is None:
        return
    if not isinstance(user_id, str) or email != "admin@memstack.ai":
        raise RuntimeError("An exact default administrator ID and email are required")
    try:
        valid_id = str(UUID(user_id)) == user_id
    except ValueError:
        valid_id = False
    if not valid_id:
        raise RuntimeError("The selected administrator ID must be a canonical UUID")
    if selection.get("environment") != "development" or selection.get("database_host") not in {
        "localhost",
        "127.0.0.1",
        "::1",
    }:
        raise RuntimeError("Default administrator promotion is restricted to local development")
    if migration.as_sql:
        raise RuntimeError("Default administrator promotion requires online identity validation")

    users = sa.table(
        "users",
        sa.column("id", sa.String()),
        sa.column("email", sa.String()),
        sa.column("is_active", sa.Boolean()),
        sa.column("is_superuser", sa.Boolean()),
    )
    connection = op.get_bind()
    matches = (
        connection.execute(
            sa.select(users.c.id, users.c.is_active, users.c.is_superuser).where(
                users.c.email == email
            )
        )
        .mappings()
        .all()
    )
    if len(matches) != 1 or matches[0]["id"] != user_id:
        raise RuntimeError("The exact existing default administrator was not uniquely matched")
    selected = matches[0]
    if selected["is_active"] is not True:
        raise RuntimeError("The selected default administrator must already be active")
    if selected["is_superuser"] is True:
        return
    if selected["is_superuser"] is not False:
        raise RuntimeError("The selected administrator privilege flag is invalid")
    result = connection.execute(
        sa.update(users)
        .where(
            users.c.id == user_id,
            users.c.email == email,
            users.c.is_active.is_(True),
            users.c.is_superuser.is_(False),
        )
        .values(is_superuser=True)
    )
    if result.rowcount != 1:
        raise RuntimeError("The selected administrator changed during the migration")


def downgrade() -> None:
    """A later revocation needs an explicit authorization decision of its own."""
    raise RuntimeError(
        "Administrator promotion is forward-only; use an explicitly scoped follow-up migration "
        "to revoke access without demoting an administrator who was already privileged"
    )
