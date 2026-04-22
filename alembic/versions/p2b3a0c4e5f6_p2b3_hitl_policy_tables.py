"""p2b3 pending_reviews + decision_logs.

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-04-26

Track B · Agent First · P2-3 phase-2. Two new tables back the HITL
policy machinery introduced in ``src/domain/model/agent/conversation/
hitl_policy.py`` + ``decision_log.py``:

* ``pending_reviews`` — one row per ``blocking_human_only`` HITL request
  (declared by the agent or structurally upgraded by the protocol).
* ``decision_logs``   — audit row for every judgmental tool-call
  (multi-agent action tools + supervisor ``verdict``).

Pure additive; no data backfill required. ``downgrade`` drops both
tables only.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "p2b3a0c4e5f6"
down_revision: str | Sequence[str] | None = "b2c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create ``pending_reviews`` and ``decision_logs``."""
    op.create_table(
        "pending_reviews",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.String(),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("scope_agent_id", sa.String(), nullable=False),
        sa.Column("effective_category", sa.String(32), nullable=False),
        sa.Column("declared_category", sa.String(32), nullable=False),
        sa.Column("visibility", sa.String(16), nullable=False),
        sa.Column("urgency", sa.String(16), nullable=False, server_default=sa.text("'normal'")),
        sa.Column("question", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("context", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("rationale", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("proposed_fallback", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("status", sa.String(16), nullable=False, server_default=sa.text("'open'")),
        sa.Column(
            "structurally_upgraded",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_payload", sa.JSON(), nullable=True),
        sa.Column("meta", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
    )
    op.create_index(
        "ix_pending_reviews_conversation_status",
        "pending_reviews",
        ["conversation_id", "status"],
    )
    op.create_index("ix_pending_reviews_agent", "pending_reviews", ["scope_agent_id"])

    op.create_table(
        "decision_logs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.String(),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("agent_id", sa.String(), nullable=False),
        sa.Column("tool_name", sa.String(64), nullable=False),
        sa.Column(
            "input_payload",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
        sa.Column("output_summary", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("rationale", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default=sa.text("-1")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("meta", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
    )
    op.create_index(
        "ix_decision_logs_conversation_created",
        "decision_logs",
        ["conversation_id", "created_at"],
    )
    op.create_index("ix_decision_logs_agent", "decision_logs", ["agent_id"])
    op.create_index("ix_decision_logs_tool", "decision_logs", ["tool_name"])


def downgrade() -> None:
    """Drop both tables. Safe: lock_timeout guard per Track A convention."""
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.drop_index("ix_decision_logs_tool", table_name="decision_logs")
    op.drop_index("ix_decision_logs_agent", table_name="decision_logs")
    op.drop_index("ix_decision_logs_conversation_created", table_name="decision_logs")
    op.drop_table("decision_logs")

    op.drop_index("ix_pending_reviews_agent", table_name="pending_reviews")
    op.drop_index("ix_pending_reviews_conversation_status", table_name="pending_reviews")
    op.drop_table("pending_reviews")
