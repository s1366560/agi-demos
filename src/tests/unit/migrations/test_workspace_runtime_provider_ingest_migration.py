"""Contracts for durable Workspace Runtime Provider ingest markers."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

pytestmark = pytest.mark.unit


class _Recorder:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def execute(self, statement: Any) -> None:
        self.statements.append(str(statement))


def _migration() -> ModuleType:
    repository_root = next(
        parent
        for parent in Path(__file__).resolve().parents
        if (parent / "alembic" / "versions").is_dir()
    )
    path = (
        repository_root
        / "alembic"
        / "versions"
        / "a72d9c31e5bf_add_workspace_autonomy_judgment_claims.py"
    )
    spec = importlib.util.spec_from_file_location("workspace_runtime_provider_ingest", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_provider_ingest_marker_is_constrained_indexed_and_downgrade_safe() -> None:
    migration = _migration()
    upgrade = "\n".join(migration._UPGRADE_DDL)
    downgrade = "\n".join(migration._DOWNGRADE_DDL)

    assert "provider_event_hash VARCHAR(64)" in upgrade
    assert "provider_event_ingested_at TIMESTAMPTZ" in upgrade
    assert "ck_workspace_runtime_provider_event_ingest" in upgrade
    assert "provider_event_hash ~ '^[0-9a-f]{64}$'" in upgrade
    assert "ix_avn_workspace_runtime_provider_event_ingest" in upgrade

    assert "provider_event_hash IS NOT NULL" in downgrade
    assert "provider_event_ingested_at IS NOT NULL" in downgrade
    assert "durable Provider ingest markers" in downgrade
    assert downgrade.index("durable Provider ingest markers") < downgrade.index(
        "DROP COLUMN IF EXISTS provider_event_ingested_at"
    )

    upgrade_recorder = _Recorder()
    migration.op = upgrade_recorder
    migration.upgrade()
    assert upgrade_recorder.statements == list(migration._UPGRADE_DDL)

    downgrade_recorder = _Recorder()
    migration.op = downgrade_recorder
    migration.downgrade()
    assert downgrade_recorder.statements == list(migration._DOWNGRADE_DDL)
