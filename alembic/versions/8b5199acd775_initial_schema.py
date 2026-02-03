"""initial_schema

Revision ID: 8b5199acd775
Revises: 
Create Date: 2026-02-03 15:34:45.974270

This is the baseline migration representing the existing database schema.
All tables were created manually before Alembic was introduced.

Note: The following legacy tables exist in the database but are not in SQLAlchemy models:
- llm_providers (legacy LLM provider configuration)
- provider_health (legacy health monitoring)
- llm_usage_logs (legacy usage tracking)
- tenant_provider_mappings (legacy tenant-provider associations)

These tables are preserved for backward compatibility but should be migrated
or removed in a future cleanup migration.
"""
from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = '8b5199acd775'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.
    
    This is a baseline migration - no changes needed.
    The schema already exists in the database.
    """
    pass


def downgrade() -> None:
    """Downgrade schema.
    
    This is a baseline migration - cannot downgrade to "before Alembic".
    """
    pass
