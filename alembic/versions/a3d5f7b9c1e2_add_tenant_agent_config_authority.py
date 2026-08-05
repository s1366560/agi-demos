"""add tenant agent config authority

Revision ID: a3d5f7b9c1e2
Revises: 048a7630034e
Create Date: 2026-08-03 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a3d5f7b9c1e2"
down_revision: str | Sequence[str] | None = "048a7630034e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE_NAME = "tenant_agent_config_authority"
_REQUIRED_COLUMNS = frozenset({"tenant_id", "authority_revision", "created_at", "updated_at"})


def _validate_existing_table(inspector: Inspector) -> None:
    columns = {column["name"]: column for column in inspector.get_columns(_TABLE_NAME)}
    missing_columns = _REQUIRED_COLUMNS.difference(columns)
    if missing_columns:
        raise RuntimeError(
            "existing tenant Agent config authority table is missing required columns: "
            + ", ".join(sorted(missing_columns))
        )
    nullable_columns = {
        name for name in _REQUIRED_COLUMNS if bool(columns[name].get("nullable", True))
    }
    if nullable_columns:
        raise RuntimeError(
            "existing tenant Agent config authority columns must be non-nullable: "
            + ", ".join(sorted(nullable_columns))
        )

    primary_key = inspector.get_pk_constraint(_TABLE_NAME)
    if primary_key.get("constrained_columns") != ["tenant_id"]:
        raise RuntimeError(
            "existing tenant Agent config authority table has an invalid primary key"
        )

    check_names = {
        constraint.get("name") for constraint in inspector.get_check_constraints(_TABLE_NAME)
    }
    if "ck_tenant_agent_config_authority_revision_positive" not in check_names:
        raise RuntimeError(
            "existing tenant Agent config authority table lacks the positive revision check"
        )

    has_tenant_cascade = any(
        foreign_key.get("constrained_columns") == ["tenant_id"]
        and foreign_key.get("referred_table") == "tenants"
        and foreign_key.get("referred_columns") == ["id"]
        and str(foreign_key.get("options", {}).get("ondelete", "")).upper() == "CASCADE"
        for foreign_key in inspector.get_foreign_keys(_TABLE_NAME)
    )
    if not has_tenant_cascade:
        raise RuntimeError(
            "existing tenant Agent config authority table lacks the tenant cascade foreign key"
        )


def upgrade() -> None:
    """Create the tenant agent configuration revision authority."""
    inspector = sa.inspect(op.get_bind())
    if _TABLE_NAME in inspector.get_table_names():
        _validate_existing_table(inspector)
        return

    op.create_table(
        _TABLE_NAME,
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
    op.drop_table(_TABLE_NAME)
