"""drop deprecated skill columns

Removes five columns from the ``skills`` table that the runtime no longer
reads or writes after the trigger-pattern matching path was eliminated:

- ``trigger_type``
- ``trigger_patterns``
- ``prompt_template``
- ``success_count``
- ``failure_count``

Skill activation now happens exclusively via explicit ``/skill-name``
slash commands or the LLM-invoked ``skill_loader`` tool, so trigger
metadata is dead weight. Usage counters were never read by any caller
after the deprecation of the legacy stats endpoint.

The migration also scrubs the same five keys out of the JSON snapshots
stored on ``curated_skills.payload`` and ``skill_submissions.skill_snapshot``
so the rows stop carrying ghost fields. ``curated_skills.revision_hash``
is **not** recomputed because the canonical hash input never included any of
the removed keys, so existing hashes remain stable.

Revision ID: v6a7b8c9d0e1
Revises: u5f6a7b8c9d0
Create Date: 2026-05-12
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "v6a7b8c9d0e1"
down_revision: str | Sequence[str] | None = "u5f6a7b8c9d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_DEPRECATED_KEYS = (
    "trigger_type",
    "trigger_patterns",
    "prompt_template",
    "success_count",
    "failure_count",
)


def _strip_keys_sql(table: str, column: str) -> str:
    """Return SQL that removes ``_DEPRECATED_KEYS`` from a JSONB column."""
    keys_sql = ", ".join(f"'{k}'" for k in _DEPRECATED_KEYS)
    # ``-`` with a text[] right-hand side removes each named key in one pass.
    return (
        f"UPDATE {table} SET {column} = ({column}::jsonb - ARRAY[{keys_sql}]::text[])::json "
        f"WHERE {column} IS NOT NULL"
    )


def upgrade() -> None:
    # 1. Drop columns from the skills table.
    with op.batch_alter_table("skills") as batch_op:
        batch_op.drop_column("trigger_type")
        batch_op.drop_column("trigger_patterns")
        batch_op.drop_column("prompt_template")
        batch_op.drop_column("success_count")
        batch_op.drop_column("failure_count")

    # 2. Strip deprecated keys out of the curated payload and submission snapshots.
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bind.execute(sa.text(_strip_keys_sql("curated_skills", "payload")))
        bind.execute(sa.text(_strip_keys_sql("skill_submissions", "skill_snapshot")))
    # On other dialects (e.g. sqlite during tests) the JSON column is opaque
    # text; downstream code already tolerates missing keys, so we leave the
    # snapshots untouched rather than introduce a Python-side scrubber.


def downgrade() -> None:
    # Restore the columns with their original defaults so existing application
    # code that reads them via raw SQL keeps working. Backfill is not attempted
    # because the data was already canonically ignored by the runtime.
    with op.batch_alter_table("skills") as batch_op:
        batch_op.add_column(
            sa.Column(
                "trigger_type",
                sa.String(length=50),
                nullable=False,
                server_default="hybrid",
            )
        )
        batch_op.add_column(
            sa.Column(
                "trigger_patterns",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'[]'::json"),
            )
        )
        batch_op.add_column(
            sa.Column("prompt_template", sa.Text(), nullable=True),
        )
        batch_op.add_column(
            sa.Column(
                "success_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch_op.add_column(
            sa.Column(
                "failure_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
