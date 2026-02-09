"""add_skill_versions

Revision ID: b53b799a2e84
Revises: 0c10a5d7e203
Create Date: 2026-02-09 13:52:36.256005

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b53b799a2e84'
down_revision: Union[str, Sequence[str], None] = '0c10a5d7e203'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('skill_versions',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('skill_id', sa.String(), nullable=False),
    sa.Column('version_number', sa.Integer(), nullable=False),
    sa.Column('version_label', sa.String(length=50), nullable=True),
    sa.Column('skill_md_content', sa.Text(), nullable=False),
    sa.Column('resource_files', sa.JSON(), nullable=True),
    sa.Column('change_summary', sa.Text(), nullable=True),
    sa.Column('created_by', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['skill_id'], ['skills.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('skill_id', 'version_number', name='uq_skill_version_number')
    )
    op.create_index('ix_skill_versions_skill_id', 'skill_versions', ['skill_id'], unique=False)
    op.add_column('skills', sa.Column('current_version', sa.Integer(), server_default='0', nullable=False))
    op.add_column('skills', sa.Column('version_label', sa.String(length=50), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('skills', 'version_label')
    op.drop_column('skills', 'current_version')
    op.drop_index('ix_skill_versions_skill_id', table_name='skill_versions')
    op.drop_table('skill_versions')
