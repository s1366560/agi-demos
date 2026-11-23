"""Migration contract for run-level execution target columns."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

pytestmark = pytest.mark.unit

_MIGRATION_PATH = (
    Path(__file__).resolve().parents[4]
    / "alembic"
    / "versions"
    / "e8a1b2c3d4f5_add_run_execution_target.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("run_execution_target_migration", _MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _bind(
    migration, monkeypatch, *, has_table: bool, columns: list[str], checks: list[str]
) -> Mock:
    operation = Mock()
    inspector = SimpleNamespace(
        has_table=lambda _name: has_table,
        get_columns=lambda _name: [{"name": name} for name in columns],
        get_check_constraints=lambda _name: [{"name": name} for name in checks],
    )
    migration.op = operation
    monkeypatch.setattr(migration.sa, "inspect", lambda _bind: inspector)
    return operation


def test_upgrade_skips_when_authority_table_is_absent(monkeypatch) -> None:
    migration = _load_migration()
    operation = _bind(migration, monkeypatch, has_table=False, columns=[], checks=[])

    migration.upgrade()

    operation.add_column.assert_not_called()
    operation.execute.assert_not_called()
    operation.create_check_constraint.assert_not_called()


def test_upgrade_adds_columns_backfills_cloud_and_checks_the_closed_set(monkeypatch) -> None:
    migration = _load_migration()
    operation = _bind(migration, monkeypatch, has_table=True, columns=["id"], checks=[])

    migration.upgrade()

    added = [call.args[1].name for call in operation.add_column.call_args_list]
    assert added == [
        "execution_target",
        "execution_machine_id",
        "execution_environment_id",
        "local_root_label",
    ]
    target_column = operation.add_column.call_args_list[0].args[1]
    assert target_column.nullable is False
    assert target_column.server_default.arg == "cloud"
    statement = str(operation.execute.call_args.args[0])
    assert "SET execution_target = 'cloud'" in statement
    assert "NOT IN ('local', 'cloud')" in statement
    operation.create_check_constraint.assert_called_once_with(
        "ck_agent_run_authorities_execution_target",
        "agent_run_authorities",
        "execution_target IN ('local', 'cloud')",
    )


def test_downgrade_drops_constraint_and_columns(monkeypatch) -> None:
    migration = _load_migration()
    operation = _bind(
        migration,
        monkeypatch,
        has_table=True,
        columns=[
            "execution_target",
            "execution_machine_id",
            "execution_environment_id",
            "local_root_label",
        ],
        checks=["ck_agent_run_authorities_execution_target"],
    )

    migration.downgrade()

    operation.drop_constraint.assert_called_once_with(
        "ck_agent_run_authorities_execution_target",
        "agent_run_authorities",
        type_="check",
    )
    dropped = [call.args[1] for call in operation.drop_column.call_args_list]
    assert dropped == [
        "local_root_label",
        "execution_environment_id",
        "execution_machine_id",
        "execution_target",
    ]


def test_downgrade_skips_when_authority_table_is_absent(monkeypatch) -> None:
    migration = _load_migration()
    operation = _bind(migration, monkeypatch, has_table=False, columns=[], checks=[])

    migration.downgrade()

    operation.drop_constraint.assert_not_called()
    operation.drop_column.assert_not_called()
