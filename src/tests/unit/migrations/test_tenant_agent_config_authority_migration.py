"""Migration contract for tenant Agent configuration authority."""

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

    def get_bind(self) -> object:
        return object()

    def create_table(self, name: str, *_items: Any) -> None:
        self.events.append(("create_table", name))

    def drop_table(self, name: str) -> None:
        self.events.append(("drop_table", name))


class _ExistingAuthorityInspector:
    def __init__(self, *, include_positive_check: bool = True) -> None:
        self.include_positive_check = include_positive_check

    def get_table_names(self) -> list[str]:
        return ["tenant_agent_config_authority"]

    def get_columns(self, _table_name: str) -> list[dict[str, Any]]:
        return [
            {"name": "tenant_id", "nullable": False},
            {"name": "authority_revision", "nullable": False},
            {"name": "created_at", "nullable": False},
            {"name": "updated_at", "nullable": False},
        ]

    def get_pk_constraint(self, _table_name: str) -> dict[str, Any]:
        return {"constrained_columns": ["tenant_id"]}

    def get_check_constraints(self, _table_name: str) -> list[dict[str, Any]]:
        if not self.include_positive_check:
            return []
        return [{"name": "ck_tenant_agent_config_authority_revision_positive"}]

    def get_foreign_keys(self, _table_name: str) -> list[dict[str, Any]]:
        return [
            {
                "constrained_columns": ["tenant_id"],
                "referred_table": "tenants",
                "referred_columns": ["id"],
                "options": {"ondelete": "CASCADE"},
            }
        ]


def _load_migration() -> ModuleType:
    root = next(
        parent
        for parent in Path(__file__).resolve().parents
        if (parent / "alembic" / "versions").is_dir()
    )
    path = root / "alembic" / "versions" / "a3d5f7b9c1e2_add_tenant_agent_config_authority.py"
    spec = importlib.util.spec_from_file_location("tenant_agent_config_authority_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_upgrade_adopts_matching_existing_authority_table(monkeypatch: pytest.MonkeyPatch) -> None:
    migration = _load_migration()
    recorder = _Recorder()
    migration.op = recorder
    monkeypatch.setattr(migration.sa, "inspect", lambda _bind: _ExistingAuthorityInspector())

    migration.upgrade()

    assert recorder.events == []


def test_upgrade_rejects_incomplete_existing_authority_table(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = _load_migration()
    recorder = _Recorder()
    migration.op = recorder
    monkeypatch.setattr(
        migration.sa,
        "inspect",
        lambda _bind: _ExistingAuthorityInspector(include_positive_check=False),
    )

    with pytest.raises(RuntimeError, match="positive revision check"):
        migration.upgrade()
