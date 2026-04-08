"""add blackboard_files table

Revision ID: 0f7a8f48758d
Revises: bb0df731bf08
Create Date: 2026-04-07 14:07:16.497154

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0f7a8f48758d'
down_revision: Union[str, Sequence[str], None] = 'bb0df731bf08'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('blackboard_files',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('workspace_id', sa.String(), nullable=False),
    sa.Column('parent_path', sa.String(length=1024), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('is_directory', sa.Boolean(), nullable=False),
    sa.Column('file_size', sa.Integer(), nullable=False),
    sa.Column('content_type', sa.String(length=128), nullable=False),
    sa.Column('storage_key', sa.String(length=512), nullable=False),
    sa.Column('uploader_type', sa.String(length=10), nullable=False),
    sa.Column('uploader_id', sa.String(), nullable=False),
    sa.Column('uploader_name', sa.String(length=128), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_blackboard_files_workspace', 'blackboard_files', ['workspace_id'], unique=False)
    op.create_index('uq_blackboard_files_ws_path_name', 'blackboard_files', ['workspace_id', 'parent_path', 'name'], unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('uq_blackboard_files_ws_path_name', table_name='blackboard_files')
    op.drop_index('ix_blackboard_files_workspace', table_name='blackboard_files')
    op.drop_table('blackboard_files')
