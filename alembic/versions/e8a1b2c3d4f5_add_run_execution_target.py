"""Add run-level execution target columns to agent run authorities.

Revision ID: e8a1b2c3d4f5
Revises: d7e8f9a0b1c2
Create Date: 2026-11-20 00:00:00.000000

Linear follow-up to the refresh-token migration on main.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e8a1b2c3d4f5"
down_revision: str | Sequence[str] | None = "d7e8f9a0b1c2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "agent_run_authorities"
_CHECK = "ck_agent_run_authorities_execution_target"
_COLUMNS = (
    ("execution_target", sa.String(length=16), False, "cloud"),
    ("execution_machine_id", sa.String(length=128), True, None),
    ("execution_environment_id", sa.String(length=64), True, None),
    ("local_root_label", sa.String(length=255), True, None),
)


def _inspector() -> sa.Inspector:
    return sa.inspect(op.get_bind())


def upgrade() -> None:
    """Add the four columns and backfill every existing run as cloud."""

    inspector = _inspector()
    if not inspector.has_table(_TABLE):
        return
    columns = {column["name"] for column in inspector.get_columns(_TABLE)}
    for name, column_type, nullable, server_default in _COLUMNS:
        if name in columns:
            continue
        op.add_column(
            _TABLE,
            sa.Column(
                name,
                column_type,
                nullable=nullable,
                server_default=server_default,
            ),
        )
    op.execute(
        "UPDATE agent_run_authorities "
        "SET execution_target = 'cloud' "
        "WHERE execution_target IS NULL "
        "OR execution_target NOT IN ('local', 'cloud')"
    )
    checks = {item["name"] for item in inspector.get_check_constraints(_TABLE)}
    if _CHECK not in checks:
        op.create_check_constraint(
            _CHECK,
            _TABLE,
            "execution_target IN ('local', 'cloud')",
        )


def downgrade() -> None:
    """Remove the execution-location columns and their check constraint."""

    inspector = _inspector()
    if not inspector.has_table(_TABLE):
        return
    checks = {item["name"] for item in inspector.get_check_constraints(_TABLE)}
    if _CHECK in checks:
        op.drop_constraint(_CHECK, _TABLE, type_="check")
    columns = {column["name"] for column in inspector.get_columns(_TABLE)}
    for name in (
        "local_root_label",
        "execution_environment_id",
        "execution_machine_id",
        "execution_target",
    ):
        if name in columns:
            op.drop_column(_TABLE, name)
