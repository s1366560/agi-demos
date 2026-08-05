"""Migration contract for Cloud session authority tables."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

pytestmark = pytest.mark.unit


class _Recorder:
    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []
        self.table_items: dict[str, tuple[Any, ...]] = {}

    def create_table(self, name: str, *items: Any) -> None:
        self.events.append(("create_table", name))
        self.table_items[name] = items

    def get_bind(self) -> object:
        return object()

    def add_column(self, table_name: str, column: Any) -> None:
        self.events.append(("add_column", f"{table_name}.{column.name}"))

    def drop_constraint(self, name: str, table_name: str, **_kwargs: Any) -> None:
        self.events.append(("drop_constraint", f"{table_name}.{name}"))

    def create_foreign_key(
        self,
        name: str,
        source_table: str,
        referent_table: str,
        *_args: Any,
        **_kwargs: Any,
    ) -> None:
        self.events.append(("create_foreign_key", f"{source_table}.{name}->{referent_table}"))

    def create_check_constraint(self, name: str, table_name: str, _condition: str) -> None:
        self.events.append(("create_check_constraint", f"{table_name}.{name}"))

    def create_index(self, name: str, *_args: Any, **_kwargs: Any) -> None:
        self.events.append(("create_index", name))

    def execute(self, _statement: Any) -> None:
        self.events.append(("execute", "backfill"))

    def drop_index(self, name: str, **_kwargs: Any) -> None:
        self.events.append(("drop_index", name))

    def drop_table(self, name: str) -> None:
        self.events.append(("drop_table", name))


def _load_migration() -> ModuleType:
    root = next(
        parent
        for parent in Path(__file__).resolve().parents
        if (parent / "alembic" / "versions").is_dir()
    )
    path = root / "alembic" / "versions" / "b4e6f8a0c2d4_add_agent_session_authority_projections.py"
    spec = importlib.util.spec_from_file_location("agent_session_authority_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _LegacyAuthorityInspector:
    def get_table_names(self) -> list[str]:
        return ["agent_run_inputs", "agent_run_summaries", "activity_read_receipts"]

    def get_columns(self, table_name: str) -> list[dict[str, Any]]:
        if table_name == "agent_run_inputs":
            return [
                {"name": name}
                for name in (
                    "id",
                    "tenant_id",
                    "project_id",
                    "conversation_id",
                    "run_id",
                    "actor_user_id",
                    "expected_run_revision",
                    "message",
                    "message_id",
                    "idempotency_key",
                    "payload_hash",
                    "delivery",
                    "references_json",
                    "context_items_json",
                    "status",
                    "sequence",
                    "queue_position",
                    "applied_round",
                    "applied_at",
                    "injected_via",
                    "promoted_run_id",
                    "promotion_key",
                    "promoted_at",
                    "created_at",
                    "updated_at",
                )
            ]
        if table_name == "agent_run_summaries":
            names = (
                "id",
                "tenant_id",
                "project_id",
                "conversation_id",
                "run_id",
                "status",
                "revision",
                "summary_state",
                "model_breakdown_json",
                "evidence_references_json",
                "created_at",
                "updated_at",
            )
        else:
            names = (
                "id",
                "tenant_id",
                "project_id",
                "user_id",
                "entry_id",
                "entry_revision",
                "revision",
                "read_at",
                "created_at",
                "updated_at",
            )
        return [{"name": name} for name in names]

    def get_foreign_keys(self, table_name: str) -> list[dict[str, Any]]:
        if table_name in {"agent_run_inputs", "agent_run_summaries"}:
            return [
                {
                    "name": f"{table_name}_run_id_fkey",
                    "constrained_columns": ["run_id"],
                    "referred_table": "agent_plan_runs",
                }
            ]
        return []

    def get_check_constraints(self, table_name: str) -> list[dict[str, Any]]:
        names = {
            "agent_run_inputs": (
                "ck_agent_run_inputs_delivery",
                "ck_agent_run_inputs_expected_revision_positive",
                "ck_agent_run_inputs_status",
            ),
            "agent_run_summaries": (
                "ck_agent_run_summaries_revision_positive",
                "ck_agent_run_summaries_state",
            ),
            "activity_read_receipts": (
                "ck_activity_read_receipts_entry_revision",
                "ck_activity_read_receipts_revision_positive",
            ),
        }[table_name]
        return [{"name": name} for name in names]

    def get_indexes(self, table_name: str) -> list[dict[str, Any]]:
        return [
            {
                "name": {
                    "agent_run_inputs": "ix_agent_run_inputs_scope_status",
                    "agent_run_summaries": "ix_agent_run_summaries_scope",
                    "activity_read_receipts": "ix_activity_read_receipts_scope_revision",
                }[table_name]
            }
        ]


class _EmptyInspector:
    def get_table_names(self) -> list[str]:
        return []


def test_upgrade_creates_all_authority_tables(monkeypatch: pytest.MonkeyPatch) -> None:
    migration = _load_migration()
    recorder = _Recorder()
    migration.op = recorder
    monkeypatch.setattr(migration.sa, "inspect", lambda _bind: _EmptyInspector())

    migration.upgrade()

    assert [item for event, item in recorder.events if event == "create_table"] == [
        "agent_run_authorities",
        "agent_run_inputs",
        "agent_run_summaries",
        "activity_read_receipts",
    ]
    run_input_columns = {
        item.name for item in recorder.table_items["agent_run_inputs"] if hasattr(item, "name")
    }
    assert {
        "dispatch_status",
        "dispatch_attempts",
        "dispatch_lease_expires_at",
        "dispatch_error_code",
    } <= run_input_columns


def test_downgrade_removes_tables_in_dependency_safe_order() -> None:
    migration = _load_migration()
    recorder = _Recorder()
    migration.op = recorder

    migration.downgrade()

    assert [item for event, item in recorder.events if event == "drop_table"] == [
        "activity_read_receipts",
        "agent_run_summaries",
        "agent_run_inputs",
        "agent_run_authorities",
    ]


def test_upgrade_adopts_legacy_projection_tables_and_rebinds_run_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = _load_migration()
    recorder = _Recorder()
    migration.op = recorder
    monkeypatch.setattr(migration.sa, "inspect", lambda _bind: _LegacyAuthorityInspector())

    migration.upgrade()

    assert [item for event, item in recorder.events if event == "create_table"] == [
        "agent_run_authorities"
    ]
    assert [item for event, item in recorder.events if event == "add_column"] == [
        "agent_run_inputs.dispatch_status",
        "agent_run_inputs.dispatch_attempts",
        "agent_run_inputs.dispatch_lease_expires_at",
        "agent_run_inputs.dispatch_error_code",
    ]
    assert [item for event, item in recorder.events if event == "drop_constraint"] == [
        "agent_run_inputs.agent_run_inputs_run_id_fkey",
        "agent_run_summaries.agent_run_summaries_run_id_fkey",
    ]
    assert [item for event, item in recorder.events if event == "create_foreign_key"] == [
        "agent_run_inputs.agent_run_inputs_run_id_fkey->agent_run_authorities",
        "agent_run_summaries.agent_run_summaries_run_id_fkey->agent_run_authorities",
    ]
    assert [item for event, item in recorder.events if event == "create_check_constraint"] == [
        "agent_run_inputs.ck_agent_run_inputs_dispatch_status",
        "agent_run_inputs.ck_agent_run_inputs_dispatch_attempts_nonnegative",
    ]
