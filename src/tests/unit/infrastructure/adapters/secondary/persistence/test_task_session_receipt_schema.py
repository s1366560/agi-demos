from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import sqlalchemy as sa

from src.infrastructure.adapters.secondary.persistence.models import (
    TaskSessionCreationReceiptModel,
)

pytestmark = pytest.mark.unit


class _OperationRecorder:
    def __init__(self) -> None:
        self.created_table: tuple[str, tuple[Any, ...]] | None = None
        self.executed_sql: list[str] = []
        self.events: list[tuple[str, str]] = []

    def create_table(self, name: str, *items: Any) -> None:
        self.created_table = (name, items)
        self.events.append(("create_table", name))

    def create_index(self, name: str, *_args: Any, **_kwargs: Any) -> None:
        self.events.append(("create_index", name))

    def execute(self, statement: str) -> None:
        normalized = " ".join(statement.split())
        self.executed_sql.append(normalized)
        self.events.append(("execute", normalized))

    def drop_index(self, name: str, **_kwargs: Any) -> None:
        self.events.append(("drop_index", name))

    def drop_table(self, name: str) -> None:
        self.events.append(("drop_table", name))


def test_receipt_orm_keeps_ledger_at_root_and_tombstones_children() -> None:
    table = TaskSessionCreationReceiptModel.__table__
    assert table.columns["conversation_id"].nullable is True
    assert table.columns["initial_message_id"].nullable is True

    delete_actions = {
        column_name: next(iter(table.columns[column_name].foreign_keys)).ondelete
        for column_name in (
            "tenant_id",
            "project_id",
            "workspace_id",
            "conversation_id",
            "initial_message_id",
        )
    }
    assert delete_actions == {
        "tenant_id": "CASCADE",
        "project_id": "CASCADE",
        "workspace_id": "CASCADE",
        "conversation_id": "SET NULL",
        "initial_message_id": "SET NULL",
    }


def test_receipt_migration_matches_orm_and_installs_both_tombstone_triggers() -> None:
    migration = _load_migration()
    recorder = _OperationRecorder()
    migration.op = recorder
    migration.upgrade()

    assert recorder.created_table is not None
    table_name, items = recorder.created_table
    assert table_name == "task_session_creation_receipts"
    columns = {item.name: item for item in items if isinstance(item, sa.Column)}
    assert columns["conversation_id"].nullable is True
    assert columns["initial_message_id"].nullable is True

    foreign_keys = {
        next(iter(item.column_keys)): item.ondelete
        for item in items
        if isinstance(item, sa.ForeignKeyConstraint)
    }
    assert foreign_keys == {
        "actor_user_id": "CASCADE",
        "tenant_id": "CASCADE",
        "project_id": "CASCADE",
        "workspace_id": "CASCADE",
        "conversation_id": "SET NULL",
        "initial_message_id": "SET NULL",
    }

    migration_sql = "\n".join(recorder.executed_sql)
    assert (
        "CREATE TRIGGER trg_task_session_receipt_conversation_delete BEFORE DELETE ON conversations"
    ) in migration_sql
    assert (
        "CREATE TRIGGER trg_task_session_receipt_message_delete BEFORE DELETE ON workspace_messages"
    ) in migration_sql
    function_sql = recorder.executed_sql[0]
    assert function_sql.count("SET conversation_id = NULL") == 2
    assert function_sql.count("initial_message_id = NULL") == 2
    assert function_sql.count("response_json = json_build_object('tombstone', true)") == 2
    assert 'workspace"' not in function_sql
    assert 'conversation"' not in function_sql
    assert 'initial_message"' not in function_sql


def test_receipt_migration_downgrade_removes_triggers_and_function_before_table() -> None:
    migration = _load_migration()
    recorder = _OperationRecorder()
    migration.op = recorder
    migration.downgrade()

    assert recorder.events[:3] == [
        (
            "execute",
            "DROP TRIGGER IF EXISTS trg_task_session_receipt_message_delete ON workspace_messages",
        ),
        (
            "execute",
            "DROP TRIGGER IF EXISTS trg_task_session_receipt_conversation_delete ON conversations",
        ),
        (
            "execute",
            "DROP FUNCTION IF EXISTS tombstone_task_session_creation_receipt()",
        ),
    ]
    assert recorder.events[-1] == ("drop_table", "task_session_creation_receipts")


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
        / "a1f6e8c2d4b7_add_task_session_creation_receipts.py"
    )
    spec = importlib.util.spec_from_file_location("task_session_receipt_migration", migration_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
