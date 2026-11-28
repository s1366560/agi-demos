"""merge local run events and project package heads

Revision ID: a86060255286
Revises: 8de32c54a61f, f4a5b6c7d8e9
Create Date: 2026-11-23 11:34:53.453130

"""
from collections.abc import Sequence


revision = "a86060255286"
down_revision: tuple[str, str] = ("8de32c54a61f", "f4a5b6c7d8e9")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
