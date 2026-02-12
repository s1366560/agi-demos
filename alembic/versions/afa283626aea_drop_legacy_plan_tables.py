"""drop_legacy_plan_tables

Revision ID: afa283626aea
Revises: d8f2a1b3c4e5
Create Date: 2026-02-12 13:51:22.501060

Drop legacy Plan Mode tables (plan_documents, work_plans, plan_executions,
plan_snapshots) and the conversations.current_plan_id FK. Plan Mode is now
a simple permission toggle stored in conversations.current_mode.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'afa283626aea'
down_revision: Union[str, Sequence[str], None] = 'd8f2a1b3c4e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Drop legacy plan tables and FK."""
    # Drop FK from conversations to plan_documents first
    op.drop_constraint(
        'conversations_current_plan_id_fkey', 'conversations', type_='foreignkey'
    )

    # Drop plan_snapshots (depends on plan_executions)
    op.drop_index('ix_plan_snapshots_execution_created', table_name='plan_snapshots')
    op.drop_table('plan_snapshots')

    # Drop plan_executions (depends on plan_documents)
    op.drop_index('ix_plan_executions_conversation_id', table_name='plan_executions')
    op.drop_index('ix_plan_executions_conversation_status', table_name='plan_executions')
    op.drop_index('ix_plan_executions_plan_id', table_name='plan_executions')
    op.drop_index('ix_plan_executions_status', table_name='plan_executions')
    op.drop_table('plan_executions')

    # Drop work_plans (depends on plan_documents)
    op.drop_index('ix_work_plans_conv_status', table_name='work_plans')
    op.drop_table('work_plans')

    # Drop plan_documents (now safe, no dependents)
    op.drop_index('ix_plan_documents_conversation_id', table_name='plan_documents')
    op.drop_table('plan_documents')


def downgrade() -> None:
    """Recreate legacy plan tables."""
    op.create_table(
        'plan_documents',
        sa.Column('id', sa.VARCHAR(), nullable=False),
        sa.Column('conversation_id', sa.VARCHAR(), nullable=False),
        sa.Column('project_id', sa.VARCHAR(), nullable=False),
        sa.Column('user_query', sa.TEXT(), nullable=False),
        sa.Column('title', sa.VARCHAR(length=500), nullable=False),
        sa.Column('content', sa.TEXT(), nullable=False),
        sa.Column('exploration_summary', sa.TEXT(), nullable=False),
        sa.Column('status', sa.VARCHAR(length=20), nullable=False),
        sa.Column('version', sa.INTEGER(), nullable=False),
        sa.Column('created_at', postgresql.TIMESTAMP(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'],
                                name='plan_documents_conversation_id_fkey',
                                ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name='plan_documents_pkey'),
    )
    op.create_index('ix_plan_documents_conversation_id', 'plan_documents',
                    ['conversation_id'])

    op.create_table(
        'work_plans',
        sa.Column('id', sa.VARCHAR(), nullable=False),
        sa.Column('plan_id', sa.VARCHAR(), nullable=False),
        sa.Column('conversation_id', sa.VARCHAR(), nullable=False),
        sa.Column('project_id', sa.VARCHAR(), nullable=False),
        sa.Column('status', sa.VARCHAR(length=20), nullable=False),
        sa.Column('steps', postgresql.JSON(astext_type=sa.Text()), nullable=False),
        sa.Column('current_step_index', sa.INTEGER(), nullable=False),
        sa.Column('created_at', postgresql.TIMESTAMP(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['plan_id'], ['plan_documents.id'],
                                ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_work_plans_conv_status', 'work_plans',
                    ['conversation_id', 'status'])

    op.create_table(
        'plan_executions',
        sa.Column('id', sa.VARCHAR(), nullable=False),
        sa.Column('conversation_id', sa.VARCHAR(), nullable=False),
        sa.Column('plan_id', sa.VARCHAR(), nullable=True),
        sa.Column('execution_mode', sa.VARCHAR(length=20), nullable=False),
        sa.Column('max_parallel_steps', sa.INTEGER(), nullable=False),
        sa.Column('status', sa.VARCHAR(length=20), nullable=False),
        sa.Column('reflection_enabled', sa.BOOLEAN(), nullable=False),
        sa.Column('max_reflection_cycles', sa.INTEGER(), nullable=False),
        sa.Column('current_reflection_cycle', sa.INTEGER(), nullable=False),
        sa.Column('steps', postgresql.JSON(astext_type=sa.Text()), nullable=False),
        sa.Column('current_step_index', sa.INTEGER(), nullable=False),
        sa.Column('completed_step_indices', postgresql.JSON(astext_type=sa.Text()),
                  nullable=False),
        sa.Column('failed_step_indices', postgresql.JSON(astext_type=sa.Text()),
                  nullable=False),
        sa.Column('workflow_pattern_id', sa.VARCHAR(), nullable=True),
        sa.Column('metadata_json', postgresql.JSON(astext_type=sa.Text()),
                  nullable=False),
        sa.Column('created_at', postgresql.TIMESTAMP(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('started_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('completed_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'],
                                ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['plan_id'], ['plan_documents.id'],
                                ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_plan_executions_conversation_id', 'plan_executions',
                    ['conversation_id'])
    op.create_index('ix_plan_executions_conversation_status', 'plan_executions',
                    ['conversation_id', 'status'])
    op.create_index('ix_plan_executions_plan_id', 'plan_executions', ['plan_id'])
    op.create_index('ix_plan_executions_status', 'plan_executions', ['status'])

    op.create_table(
        'plan_snapshots',
        sa.Column('id', sa.VARCHAR(), nullable=False),
        sa.Column('execution_id', sa.VARCHAR(), nullable=False),
        sa.Column('name', sa.VARCHAR(length=255), nullable=False),
        sa.Column('description', sa.TEXT(), nullable=True),
        sa.Column('step_states', postgresql.JSON(astext_type=sa.Text()),
                  nullable=False),
        sa.Column('auto_created', sa.BOOLEAN(), nullable=False),
        sa.Column('snapshot_type', sa.VARCHAR(length=50), nullable=False),
        sa.Column('metadata_json', postgresql.JSON(astext_type=sa.Text()),
                  nullable=False),
        sa.Column('created_at', postgresql.TIMESTAMP(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['execution_id'], ['plan_executions.id'],
                                ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_plan_snapshots_execution_created', 'plan_snapshots',
                    ['execution_id', 'created_at'])

    op.create_foreign_key('conversations_current_plan_id_fkey', 'conversations',
                          'plan_documents', ['current_plan_id'], ['id'])
