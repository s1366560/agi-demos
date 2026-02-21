"""Create channel configuration tables

Revision ID: 2024xxxx_channel_config
Revises: (latest revision)
Create Date: 2024-xx-xx

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '2024xxxx_channel_config'
down_revision: Union[str, None] = None  # Set to your latest migration
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create channel_configs table
    op.create_table(
        'channel_configs',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('project_id', sa.String(), nullable=False),
        sa.Column('channel_type', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('connection_mode', sa.String(), nullable=False, server_default='websocket'),
        sa.Column('app_id', sa.String(), nullable=True),
        sa.Column('app_secret', sa.String(), nullable=True),
        sa.Column('encrypt_key', sa.String(), nullable=True),
        sa.Column('verification_token', sa.String(), nullable=True),
        sa.Column('webhook_url', sa.String(), nullable=True),
        sa.Column('webhook_port', sa.Integer(), nullable=True),
        sa.Column('webhook_path', sa.String(), nullable=True),
        sa.Column('domain', sa.String(), nullable=True, server_default='feishu'),
        sa.Column('extra_settings', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('status', sa.String(), nullable=False, server_default='disconnected'),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_by', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create indexes
    op.create_index('ix_channel_configs_project_id', 'channel_configs', ['project_id'])
    op.create_index('ix_channel_configs_channel_type', 'channel_configs', ['channel_type'])
    op.create_index('ix_channel_configs_project_type', 'channel_configs', ['project_id', 'channel_type'])
    op.create_index('ix_channel_configs_project_enabled', 'channel_configs', ['project_id', 'enabled'])
    
    # Create channel_messages table
    op.create_table(
        'channel_messages',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('channel_config_id', sa.String(), nullable=False),
        sa.Column('project_id', sa.String(), nullable=False),
        sa.Column('channel_message_id', sa.String(), nullable=False),
        sa.Column('chat_id', sa.String(), nullable=False),
        sa.Column('chat_type', sa.String(), nullable=False),
        sa.Column('sender_id', sa.String(), nullable=False),
        sa.Column('sender_name', sa.String(), nullable=True),
        sa.Column('message_type', sa.String(), nullable=False),
        sa.Column('content_text', sa.Text(), nullable=True),
        sa.Column('content_data', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('reply_to', sa.String(), nullable=True),
        sa.Column('mentions', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('direction', sa.String(), nullable=False),
        sa.Column('raw_data', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['channel_config_id'], ['channel_configs.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create indexes
    op.create_index('ix_channel_messages_config_id', 'channel_messages', ['channel_config_id'])
    op.create_index('ix_channel_messages_project_id', 'channel_messages', ['project_id'])
    op.create_index('ix_channel_messages_channel_message_id', 'channel_messages', ['channel_message_id'])
    op.create_index('ix_channel_messages_chat_id', 'channel_messages', ['chat_id'])
    op.create_index('ix_channel_messages_sender_id', 'channel_messages', ['sender_id'])
    op.create_index('ix_channel_messages_project_chat', 'channel_messages', ['project_id', 'chat_id'])
    op.create_index('ix_channel_messages_config_time', 'channel_messages', ['channel_config_id', 'created_at'])


def downgrade() -> None:
    op.drop_index('ix_channel_messages_config_time', table_name='channel_messages')
    op.drop_index('ix_channel_messages_project_chat', table_name='channel_messages')
    op.drop_index('ix_channel_messages_sender_id', table_name='channel_messages')
    op.drop_index('ix_channel_messages_chat_id', table_name='channel_messages')
    op.drop_index('ix_channel_messages_channel_message_id', table_name='channel_messages')
    op.drop_index('ix_channel_messages_project_id', table_name='channel_messages')
    op.drop_index('ix_channel_messages_config_id', table_name='channel_messages')
    op.drop_table('channel_messages')
    
    op.drop_index('ix_channel_configs_project_enabled', table_name='channel_configs')
    op.drop_index('ix_channel_configs_project_type', table_name='channel_configs')
    op.drop_index('ix_channel_configs_channel_type', table_name='channel_configs')
    op.drop_index('ix_channel_configs_project_id', table_name='channel_configs')
    op.drop_table('channel_configs')
