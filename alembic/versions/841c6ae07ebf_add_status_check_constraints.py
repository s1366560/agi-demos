"""add_status_check_constraints

Revision ID: 841c6ae07ebf
Revises: 8b5199acd775
Create Date: 2026-02-03 16:09:42.733928

This migration adds CHECK constraints for status fields to ensure data integrity.
It does NOT remove the legacy LLM provider tables - those should be handled separately.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "841c6ae07ebf"
down_revision: Union[str, Sequence[str], None] = "8b5199acd775"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add CHECK constraints for status fields."""
    # Memory processing_status constraint
    op.create_check_constraint(
        "ck_memories_processing_status",
        "memories",
        "processing_status IN ('PENDING', 'PROCESSING', 'COMPLETED', 'FAILED')",
    )

    # Memory status constraint
    op.create_check_constraint(
        "ck_memories_status",
        "memories",
        "status IN ('ENABLED', 'DISABLED')",
    )

    # Conversation status constraint
    op.create_check_constraint(
        "ck_conversations_status",
        "conversations",
        "status IN ('active', 'completed', 'archived', 'paused')",
    )

    # Work plan status constraint
    op.create_check_constraint(
        "ck_work_plans_status",
        "work_plans",
        "status IN ('planning', 'in_progress', 'completed', 'failed', 'cancelled')",
    )

    # Tool execution record status constraint
    op.create_check_constraint(
        "ck_tool_execution_records_status",
        "tool_execution_records",
        "status IN ('running', 'success', 'failed', 'cancelled')",
    )

    # Plan execution status constraint
    op.create_check_constraint(
        "ck_plan_executions_status",
        "plan_executions",
        "status IN ('pending', 'running', 'completed', 'failed', 'cancelled', 'paused')",
    )

    # HITL request status constraint
    op.create_check_constraint(
        "ck_hitl_requests_status",
        "hitl_requests",
        "status IN ('pending', 'responded', 'timeout', 'expired', 'skipped', 'cancelled')",
    )

    # Project sandbox_type constraint
    op.create_check_constraint(
        "ck_projects_sandbox_type",
        "projects",
        "sandbox_type IN ('cloud', 'local')",
    )

    # Message role constraint
    op.create_check_constraint(
        "ck_messages_role",
        "messages",
        "role IN ('user', 'assistant', 'system', 'tool')",
    )


def downgrade() -> None:
    """Remove CHECK constraints."""
    op.drop_constraint("ck_memories_processing_status", "memories", type_="check")
    op.drop_constraint("ck_memories_status", "memories", type_="check")
    op.drop_constraint("ck_conversations_status", "conversations", type_="check")
    op.drop_constraint("ck_work_plans_status", "work_plans", type_="check")
    op.drop_constraint("ck_tool_execution_records_status", "tool_execution_records", type_="check")
    op.drop_constraint("ck_plan_executions_status", "plan_executions", type_="check")
    op.drop_constraint("ck_hitl_requests_status", "hitl_requests", type_="check")
    op.drop_constraint("ck_projects_sandbox_type", "projects", type_="check")
    op.drop_constraint("ck_messages_role", "messages", type_="check")
