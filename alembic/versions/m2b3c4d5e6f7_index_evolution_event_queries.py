"""Index evolution event timeline queries.

Revision ID: m2b3c4d5e6f7
Revises: l1a2b3c4d5e6
Create Date: 2026-06-17 15:35:00.000000
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "m2b3c4d5e6f7"
down_revision: str | Sequence[str] | None = "l1a2b3c4d5e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


EVOLUTION_EVENTS_TABLE = "evolution_events"
INSTANCE_TIMELINE_INDEX = "ix_evolution_events_instance_created_id"
GENE_TIMELINE_INDEX = "ix_evolution_events_gene_created_id"


def upgrade() -> None:
    op.create_index(
        INSTANCE_TIMELINE_INDEX,
        EVOLUTION_EVENTS_TABLE,
        ["instance_id", "created_at", "id"],
        unique=False,
    )
    op.create_index(
        GENE_TIMELINE_INDEX,
        EVOLUTION_EVENTS_TABLE,
        ["gene_id", "created_at", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(GENE_TIMELINE_INDEX, table_name=EVOLUTION_EVENTS_TABLE)
    op.drop_index(INSTANCE_TIMELINE_INDEX, table_name=EVOLUTION_EVENTS_TABLE)
