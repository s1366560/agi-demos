"""add_subagent_templates

Revision ID: c7a3e5f1b2d4
Revises: b53b799a2e84
Create Date: 2026-02-11 11:58:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c7a3e5f1b2d4'
down_revision: Union[str, Sequence[str], None] = 'b53b799a2e84'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('subagent_templates',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('tenant_id', sa.String(), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('version', sa.String(length=20), nullable=False, server_default='1.0.0'),
        sa.Column('display_name', sa.String(length=200), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('category', sa.String(length=100), nullable=False, server_default='general'),
        sa.Column('tags', sa.JSON(), nullable=True),
        sa.Column('system_prompt', sa.Text(), nullable=False),
        sa.Column('trigger_description', sa.Text(), nullable=True),
        sa.Column('trigger_keywords', sa.JSON(), nullable=True),
        sa.Column('trigger_examples', sa.JSON(), nullable=True),
        sa.Column('model', sa.String(length=50), nullable=False, server_default='inherit'),
        sa.Column('max_tokens', sa.Integer(), nullable=False, server_default='4096'),
        sa.Column('temperature', sa.Float(), nullable=False, server_default='0.7'),
        sa.Column('max_iterations', sa.Integer(), nullable=False, server_default='10'),
        sa.Column('allowed_tools', sa.JSON(), nullable=False, server_default='["*"]'),
        sa.Column('author', sa.String(length=200), nullable=True),
        sa.Column('is_builtin', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('is_published', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('install_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('rating', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('metadata_json', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'name', 'version', name='uq_template_tenant_name_version'),
    )
    op.create_index('ix_subagent_templates_tenant_id', 'subagent_templates', ['tenant_id'], unique=False)
    op.create_index('ix_subagent_templates_category', 'subagent_templates', ['category'], unique=False)
    op.create_index('ix_subagent_templates_is_published', 'subagent_templates', ['is_published'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_subagent_templates_is_published', table_name='subagent_templates')
    op.drop_index('ix_subagent_templates_category', table_name='subagent_templates')
    op.drop_index('ix_subagent_templates_tenant_id', table_name='subagent_templates')
    op.drop_table('subagent_templates')
