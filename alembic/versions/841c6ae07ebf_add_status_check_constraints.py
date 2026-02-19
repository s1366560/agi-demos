"""add_status_check_constraints

Revision ID: 841c6ae07ebf
Revises: 8b5199acd775
Create Date: 2026-02-03 16:09:42.733928

This migration adds CHECK constraints for status fields to ensure data integrity.
It does NOT remove the legacy LLM provider tables - those should be handled separately.
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "841c6ae07ebf"
down_revision: Union[str, Sequence[str], None] = "8b5199acd775"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _create_check_if_table_exists(constraint_name: str, table_name: str, condition: str) -> None:
    """Create check constraint only when target table exists."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if table_name not in inspector.get_table_names():
        return

    existing = {
        constraint.get("name")
        for constraint in inspector.get_check_constraints(table_name)
        if constraint.get("name")
    }
    if constraint_name in existing:
        return

    op.create_check_constraint(constraint_name, table_name, condition)


def _drop_check_if_exists(constraint_name: str, table_name: str) -> None:
    """Drop check constraint only when table/constraint exist."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if table_name not in inspector.get_table_names():
        return

    existing = {
        constraint.get("name")
        for constraint in inspector.get_check_constraints(table_name)
        if constraint.get("name")
    }
    if constraint_name not in existing:
        return

    op.drop_constraint(constraint_name, table_name, type_="check")


def upgrade() -> None:
    """Add CHECK constraints for status fields."""
    _create_check_if_table_exists(
        "ck_memories_processing_status",
        "memories",
        "processing_status IN ('PENDING', 'PROCESSING', 'COMPLETED', 'FAILED')",
    )
    _create_check_if_table_exists(
        "ck_memories_status",
        "memories",
        "status IN ('ENABLED', 'DISABLED')",
    )
    _create_check_if_table_exists(
        "ck_conversations_status",
        "conversations",
        "status IN ('active', 'completed', 'archived', 'paused')",
    )
    _create_check_if_table_exists(
        "ck_work_plans_status",
        "work_plans",
        "status IN ('planning', 'in_progress', 'completed', 'failed', 'cancelled')",
    )
    _create_check_if_table_exists(
        "ck_tool_execution_records_status",
        "tool_execution_records",
        "status IN ('running', 'success', 'failed', 'cancelled')",
    )
    _create_check_if_table_exists(
        "ck_plan_executions_status",
        "plan_executions",
        "status IN ('pending', 'running', 'completed', 'failed', 'cancelled', 'paused')",
    )
    _create_check_if_table_exists(
        "ck_hitl_requests_status",
        "hitl_requests",
        "status IN ('pending', 'responded', 'timeout', 'expired', 'skipped', 'cancelled')",
    )
    _create_check_if_table_exists(
        "ck_projects_sandbox_type",
        "projects",
        "sandbox_type IN ('cloud', 'local')",
    )
    _create_check_if_table_exists(
        "ck_messages_role",
        "messages",
        "role IN ('user', 'assistant', 'system', 'tool')",
    )


def downgrade() -> None:
    """Remove CHECK constraints."""
    _drop_check_if_exists("ck_memories_processing_status", "memories")
    _drop_check_if_exists("ck_memories_status", "memories")
    _drop_check_if_exists("ck_conversations_status", "conversations")
    _drop_check_if_exists("ck_work_plans_status", "work_plans")
    _drop_check_if_exists("ck_tool_execution_records_status", "tool_execution_records")
    _drop_check_if_exists("ck_plan_executions_status", "plan_executions")
    _drop_check_if_exists("ck_hitl_requests_status", "hitl_requests")
    _drop_check_if_exists("ck_projects_sandbox_type", "projects")
    _drop_check_if_exists("ck_messages_role", "messages")
