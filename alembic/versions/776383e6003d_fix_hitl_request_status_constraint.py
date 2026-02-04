"""fix_hitl_request_status_constraint

Revision ID: 776383e6003d
Revises: 276db25ba465
Create Date: 2026-02-04 10:55:51.061113

Fix HITL request status check constraint to match domain model values.

Domain model uses: 'pending', 'answered', 'processing', 'completed', 'timeout', 'cancelled'
Previous constraint had: 'pending', 'responded', 'timeout', 'expired', 'skipped', 'cancelled'
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "776383e6003d"
down_revision: Union[str, Sequence[str], None] = "276db25ba465"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Fix HITL request status constraint to match domain model."""
    # Drop old constraint with wrong values
    op.drop_constraint("ck_hitl_requests_status", "hitl_requests", type_="check")

    # Create new constraint with correct domain model values
    op.create_check_constraint(
        "ck_hitl_requests_status",
        "hitl_requests",
        "status IN ('pending', 'answered', 'processing', 'completed', 'timeout', 'cancelled')",
    )


def downgrade() -> None:
    """Revert to old constraint (not recommended)."""
    op.drop_constraint("ck_hitl_requests_status", "hitl_requests", type_="check")
    op.create_check_constraint(
        "ck_hitl_requests_status",
        "hitl_requests",
        "status IN ('pending', 'responded', 'timeout', 'expired', 'skipped', 'cancelled')",
    )
