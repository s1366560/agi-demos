"""Add the monotonic local-run event log.

Revision ID: f4a5b6c7d8e9
Revises: e8a1b2c3d4f5
Create Date: 2026-11-23 00:00:00.000000

Follows the single P2 execution-target head. Local runs reuse the existing
run authority row; this table is only the seq log.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f4a5b6c7d8e9"
down_revision: str | Sequence[str] | None = "e8a1b2c3d4f5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "agent_local_run_events"
_KIND_CHECK = "ck_agent_local_run_events_kind"
_SEQ_CHECK = "ck_agent_local_run_events_seq_positive"
_KIND_SQL = (
    "kind IN ('user_message', 'assistant_message', 'tool_call', 'tool_result', "
    "'log', 'artifact', 'error', 'status')"
)


def _inspector() -> sa.Inspector:
    return sa.inspect(op.get_bind())


def upgrade() -> None:
    """Create the seq log when it is not already present."""

    inspector = _inspector()
    if inspector.has_table(_TABLE):
        return
    op.create_table(
        _TABLE,
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("conversation_id", sa.String(), nullable=False),
        sa.Column("seq", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
        sa.Column("artifact_id", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["run_id"], ["agent_run_authorities.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "seq", name="uq_agent_local_run_events_run_seq"),
        sa.CheckConstraint("seq >= 1", name=_SEQ_CHECK),
        sa.CheckConstraint(_KIND_SQL, name=_KIND_CHECK),
    )
    op.create_index(
        "ix_agent_local_run_events_conversation_seq",
        _TABLE,
        ["conversation_id", "seq"],
    )


def downgrade() -> None:
    """Drop the local-run event log."""

    inspector = _inspector()
    if not inspector.has_table(_TABLE):
        return
    op.drop_index("ix_agent_local_run_events_conversation_seq", table_name=_TABLE)
    op.drop_table(_TABLE)
