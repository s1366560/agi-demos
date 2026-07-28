"""Contract tests for the Workspace Collaboration authority migration."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

_MIGRATION_PATH = (
    Path(__file__).parents[4]
    / "alembic"
    / "versions"
    / "d4e9f0a1b2c3_add_workspace_collaboration_authority.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location(
        "workspace_collaboration_authority_migration",
        _MIGRATION_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _postgres_op() -> Mock:
    migration_op = Mock()
    migration_op.get_bind.return_value = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
    return migration_op


@pytest.mark.unit
def test_workspace_authority_migration_backfills_and_covers_status_sources() -> None:
    migration = _load_migration()
    migration_op = _postgres_op()
    migration.op = migration_op

    migration.upgrade()

    executed_sql = [str(call.args[0]) for call in migration_op.execute.call_args_list]
    normalized_sql = "\n".join(executed_sql).lower()
    assert "insert into workspace_collaboration_authorities" in normalized_sql
    assert "select workspaces.id" in normalized_sql
    assert "on conflict (workspace_id) do nothing" in normalized_sql

    for table_name in (
        "workspace_task_session_attempts",
        "workspace_plans",
        "workspace_plan_nodes",
        "workspace_plan_outbox",
        "tool_execution_records",
    ):
        assert f"trg_{table_name}_collaboration_authority" in normalized_sql

    assert "from conversations" in normalized_sql
    assert "conversations.workspace_id = workspaces.id" in normalized_sql
    assert "conversations.tenant_id = workspaces.tenant_id" in normalized_sql
    assert "conversations.project_id = workspaces.project_id" in normalized_sql
    assert (
        "workspace_task_session_attempts.conversation_id =\n"
        "                                    conversations.id"
    ) in normalized_sql
    assert "from workspace_plans" in normalized_sql


@pytest.mark.unit
def test_workspace_authority_migration_downgrade_drops_every_trigger_and_function() -> None:
    migration = _load_migration()
    migration_op = _postgres_op()
    migration.op = migration_op

    migration.downgrade()

    normalized_sql = "\n".join(
        str(call.args[0]) for call in migration_op.execute.call_args_list
    ).lower()
    for table_name in (
        "workspace_task_session_attempts",
        "workspace_plans",
        "workspace_plan_nodes",
        "workspace_plan_outbox",
        "tool_execution_records",
    ):
        assert f"drop trigger if exists trg_{table_name}_collaboration_authority" in normalized_sql
    assert "drop function if exists bump_workspace_collaboration_authority()" in normalized_sql
    assert (
        "drop function if exists bump_workspace_collaboration_authority_for_workspace(text)"
    ) in normalized_sql
