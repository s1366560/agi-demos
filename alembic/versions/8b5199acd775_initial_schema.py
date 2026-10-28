"""initial_schema

Revision ID: 8b5199acd775
Revises:
Create Date: 2026-02-03 15:34:45.974270

The frozen PostgreSQL DDL comes from the models, attachment model and legacy
provider models at c425f1f09c47004442e223df77ac9d0221c7f99f, when this revision was
introduced. It deliberately does not import current application metadata.
Existing versioned deployments already have this ancestor and do not replay it.
"""

import json
from collections.abc import Sequence
from pathlib import Path

import sqlalchemy as sa

from alembic import context, op

# revision identifiers, used by Alembic.
revision: str = "8b5199acd775"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the historical baseline only in a genuinely empty database."""
    if not context.is_offline_mode():
        existing = (
            op.get_bind()
            .execute(
                sa.text("""
            SELECT namespace.nspname || '.' || relation.relname
            FROM pg_class AS relation
            JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
            WHERE namespace.nspname NOT IN ('pg_catalog', 'information_schema')
              AND namespace.nspname NOT LIKE 'pg_toast%'
              AND namespace.nspname NOT LIKE 'pg_temp_%'
              AND relation.relkind IN ('r', 'p', 'v', 'm', 'f', 'S')
              AND NOT (namespace.nspname = 'public' AND relation.relname = 'alembic_version')
              AND NOT EXISTS (
                  SELECT 1 FROM pg_depend AS dependency
                  WHERE dependency.classid = 'pg_class'::regclass
                    AND dependency.objid = relation.oid AND dependency.deptype = 'e'
              )
            ORDER BY namespace.nspname, relation.relname
            LIMIT 1
        """)
            )
            .scalar_one_or_none()
        )
        if existing is not None:
            raise RuntimeError(
                "Cannot initialize a nonempty database without an Alembic revision "
                f"(found {existing}). Restore its migration history before upgrading."
            )
    baseline = Path(__file__).resolve().parents[1] / "baselines" / f"{revision}.json"
    for statement in json.loads(baseline.read_text(encoding="utf-8")):
        op.execute(sa.text(statement))


def downgrade() -> None:
    """Retain the historical schema when removing Alembic bookkeeping."""
