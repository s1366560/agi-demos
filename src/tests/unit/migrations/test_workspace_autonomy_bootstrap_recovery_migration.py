"""Contracts for autonomous Workspace bootstrap recovery."""

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
        / "b84e2f6a9c31_backfill_workspace_autonomy_bootstraps.py"
    )
    spec = importlib.util.spec_from_file_location("workspace_autonomy_bootstrap_recovery", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_upgrade_is_scoped_idempotent_and_preserves_existing_goal_roots() -> None:
    migration = _migration()
    upgrade = migration._UPGRADE_DDL

    assert "autonomy-bootstrap-recovery:" in upgrade
    assert "profile.metadata_json ->> 'collaboration_mode' = 'autonomous'" in upgrade
    assert (
        "profile.metadata_json -> 'legacy_desktop' ->> 'collaboration_mode' = 'autonomous'"
        in upgrade
    )
    assert "root.metadata_json ->> 'task_role' = 'goal_root'" in upgrade
    assert "NOT EXISTS" in upgrade
    assert "ON CONFLICT (workspace_id) DO NOTHING" in upgrade
    assert "profile.tenant_id" in upgrade
    assert "profile.project_id" in upgrade
    assert "profile.workspace_id" in upgrade
    assert "length(trim(profile.name)) > 0" in upgrade
    assert "'Autonomous workspace ' || profile.workspace_id" in upgrade

    recorder = _Recorder()
    migration.op = recorder
    migration.upgrade()
    assert recorder.statements == [migration._UPGRADE_DDL]


def test_downgrade_refuses_to_discard_recovered_durable_rows() -> None:
    migration = _migration()
    assert "autonomy-bootstrap-recovery:%" in migration._DOWNGRADE_GUARD
    assert "durable data" in migration._DOWNGRADE_GUARD

    recorder = _Recorder()
    migration.op = recorder
    migration.downgrade()
    assert recorder.statements == [migration._DOWNGRADE_GUARD]
