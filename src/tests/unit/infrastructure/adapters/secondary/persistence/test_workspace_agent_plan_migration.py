from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

pytestmark = pytest.mark.unit


class _SchemaInspector:
    def __init__(self) -> None:
        self.tables = {
            "workspace_agent_policies",
            "agent_plan_versions",
            "agent_plan_runs",
            "agent_tasks",
            "trust_policies",
        }
        self.columns = {
            "agent_tasks": {
                "id",
                "conversation_id",
                "content",
                "status",
                "priority",
                "order_index",
                "created_at",
                "updated_at",
            },
            "trust_policies": {
                "id",
                "tenant_id",
                "project_id",
                "tool_name",
            },
        }
        self.indexes = {
            "workspace_agent_policies": {"ix_workspace_agent_policies_scope"},
            "agent_plan_versions": {"ix_agent_plan_versions_conversation"},
            "agent_plan_runs": {"ix_agent_plan_runs_conversation"},
        }

    def get_table_names(self) -> list[str]:
        return sorted(self.tables)

    def get_columns(self, table_name: str) -> list[dict[str, str]]:
        return [{"name": name} for name in sorted(self.columns.get(table_name, set()))]

    def get_indexes(self, table_name: str) -> list[dict[str, str]]:
        return [{"name": name} for name in sorted(self.indexes.get(table_name, set()))]


class _OperationRecorder:
    def __init__(self) -> None:
        self.bind = object()
        self.created_tables: list[str] = []
        self.created_indexes: list[str] = []
        self.added_columns: list[tuple[str, str]] = []
        self.altered_columns: list[tuple[str, str]] = []
        self.executed_sql: list[str] = []

    def get_bind(self) -> object:
        return self.bind

    def create_table(self, name: str, *_items: Any) -> None:
        self.created_tables.append(name)

    def create_index(self, name: str, *_args: Any, **_kwargs: Any) -> None:
        self.created_indexes.append(name)

    def add_column(self, table_name: str, column: Any) -> None:
        self.added_columns.append((table_name, column.name))

    def alter_column(self, table_name: str, column_name: str, **_kwargs: Any) -> None:
        self.altered_columns.append((table_name, column_name))

    def execute(self, statement: str) -> None:
        self.executed_sql.append(" ".join(statement.split()))


def test_upgrade_reuses_create_all_tables_and_adds_only_missing_columns(monkeypatch: Any) -> None:
    migration = _load_migration()
    inspector = _SchemaInspector()
    recorder = _OperationRecorder()
    migration.op = recorder
    monkeypatch.setattr(migration.sa, "inspect", lambda bind: inspector)

    migration.upgrade()

    assert recorder.created_tables == []
    assert recorder.created_indexes == []
    assert recorder.added_columns == [
        ("agent_tasks", "title"),
        ("agent_tasks", "description"),
        ("agent_tasks", "estimated_duration_seconds"),
        ("agent_tasks", "started_at"),
        ("agent_tasks", "completed_at"),
        ("agent_tasks", "result_summary"),
        ("agent_tasks", "evidence_refs"),
        ("trust_policies", "scope"),
        ("trust_policies", "canonical_tool_name"),
        ("trust_policies", "source_hitl_request_id"),
        ("trust_policies", "revision"),
        ("trust_policies", "revoked_by"),
        ("trust_policies", "revoked_at"),
    ]
    assert recorder.altered_columns == [
        ("agent_tasks", "title"),
        ("agent_tasks", "evidence_refs"),
    ]
    assert recorder.executed_sql == ["UPDATE agent_tasks SET title = content WHERE title IS NULL"]


def _load_migration() -> ModuleType:
    repository_root = next(
        parent
        for parent in Path(__file__).resolve().parents
        if (parent / "alembic" / "versions").is_dir()
    )
    migration_path = (
        repository_root
        / "alembic"
        / "versions"
        / "b2c7d8e9f0a1_add_workspace_agent_policy_and_plan_metadata.py"
    )
    spec = importlib.util.spec_from_file_location("workspace_agent_plan_migration", migration_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
