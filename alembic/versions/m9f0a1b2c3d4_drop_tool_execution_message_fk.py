"""drop legacy message fk from tool execution records

Revision ID: m9f0a1b2c3d4
Revises: l9e0f1a2b3c4
Create Date: 2026-04-27
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "m9f0a1b2c3d4"
down_revision: str | Sequence[str] | None = "l9e0f1a2b3c4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Allow tool evidence to reference event-timeline message IDs."""
    op.execute(
        "ALTER TABLE tool_execution_records "
        "DROP CONSTRAINT IF EXISTS tool_execution_records_message_id_fkey"
    )


def downgrade() -> None:
    """Restore the legacy messages FK after deleting incompatible rows."""
    op.execute(
        """
        DELETE FROM tool_execution_records AS ter
        WHERE NOT EXISTS (
            SELECT 1
            FROM messages AS msg
            WHERE msg.id = ter.message_id
        )
        """
    )
    op.create_foreign_key(
        "tool_execution_records_message_id_fkey",
        "tool_execution_records",
        "messages",
        ["message_id"],
        ["id"],
    )
