"""Migration contract for the local-run event log."""

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
    / "f4a5b6c7d8e9_add_local_run_events.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("local_run_events_migration", _MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_revision_follows_the_execution_target_head() -> None:
    migration = _load_migration()
    assert migration.revision == "f4a5b6c7d8e9"
    assert migration.down_revision == "e8a1b2c3d4f5"


def test_upgrade_skips_when_the_event_table_exists(monkeypatch) -> None:
    migration = _load_migration()
    operation = Mock()
    migration.op = operation
    monkeypatch.setattr(
        migration.sa, "inspect", lambda _bind: SimpleNamespace(has_table=lambda _name: True)
    )

    migration.upgrade()

    operation.create_table.assert_not_called()


def test_upgrade_skips_when_the_authority_table_is_absent(monkeypatch) -> None:
    migration = _load_migration()
    operation = Mock()
    migration.op = operation

    def has_table(name: str) -> bool:
        return False

    monkeypatch.setattr(migration.sa, "inspect", lambda _bind: SimpleNamespace(has_table=has_table))

    migration.upgrade()

    operation.create_table.assert_not_called()


def test_upgrade_creates_the_event_table_when_the_authority_table_exists(monkeypatch) -> None:
    migration = _load_migration()
    operation = Mock()
    migration.op = operation

    def has_table(name: str) -> bool:
        return name == "agent_run_authorities"

    monkeypatch.setattr(migration.sa, "inspect", lambda _bind: SimpleNamespace(has_table=has_table))

    migration.upgrade()

    operation.create_table.assert_called_once()


def test_downgrade_skips_when_the_event_table_is_absent(monkeypatch) -> None:
    migration = _load_migration()
    operation = Mock()
    migration.op = operation
    monkeypatch.setattr(
        migration.sa, "inspect", lambda _bind: SimpleNamespace(has_table=lambda _name: False)
    )

    migration.downgrade()

    operation.drop_table.assert_not_called()
