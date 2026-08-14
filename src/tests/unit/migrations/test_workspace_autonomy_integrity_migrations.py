"""Integrity contracts for durable Workspace Autonomy migrations."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = pytest.mark.unit


def _migration(filename: str, module_name: str) -> ModuleType:
    repository_root = next(
        parent
        for parent in Path(__file__).resolve().parents
        if (parent / "alembic" / "versions").is_dir()
    )
    path = repository_root / "alembic" / "versions" / filename
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_progression_references_are_scoped_and_snapshot_is_immutable() -> None:
    migration = _migration(
        "f184bcdba7ea_add_workspace_autonomy_progression_.py",
        "workspace_autonomy_progression_integrity",
    )
    upgrade = "\n".join(migration._UPGRADE_DDL)
    downgrade = "\n".join(migration._DOWNGRADE_DDL)
    normalized_upgrade = " ".join(upgrade.split())

    assert "uq_workspace_autonomy_ticks_scope_id" in upgrade
    assert "UNIQUE (tenant_id, project_id, workspace_id, tick_id)" in upgrade
    assert "uq_workspace_agent_bindings_scope_id" in upgrade
    assert "UNIQUE (tenant_id, project_id, workspace_id, binding_id)" in upgrade
    assert "FOREIGN KEY (tenant_id, project_id, workspace_id, tick_id)" in normalized_upgrade
    assert (
        "FOREIGN KEY (tenant_id, project_id, workspace_id, workspace_agent_binding_id)"
        in normalized_upgrade
    )
    assert "reject_workspace_autonomy_progression_snapshot_update" in upgrade
    assert "trg_workspace_autonomy_progression_snapshot_immutable" in upgrade
    for field in (
        "tick_id",
        "tenant_id",
        "project_id",
        "workspace_id",
        "root_task_id",
        "actor_id",
        "judge_agent_id",
        "workspace_agent_binding_id",
        "task_title",
        "task_description",
        "created_at_ms",
    ):
        assert f"NEW.{field}" in upgrade
        assert f"OLD.{field}" in upgrade

    assert (
        "DROP FUNCTION avernet.reject_workspace_autonomy_progression_snapshot_update()" in downgrade
    )
    assert "DROP CONSTRAINT uq_workspace_autonomy_ticks_scope_id" in downgrade
    assert "DROP CONSTRAINT uq_workspace_agent_bindings_scope_id" in downgrade


def test_judgment_and_bootstrap_authority_snapshots_are_scoped_and_immutable() -> None:
    migration = _migration(
        "a72d9c31e5bf_add_workspace_autonomy_judgment_claims.py",
        "workspace_autonomy_judgment_integrity",
    )
    upgrade = "\n".join(migration._UPGRADE_DDL)
    downgrade = "\n".join(migration._DOWNGRADE_DDL)

    assert "uq_workspace_judge_audits_scope_id" in upgrade
    assert "UNIQUE (tenant_id, project_id, workspace_id, audit_id)" in upgrade
    assert "FOREIGN KEY (tenant_id, project_id, workspace_id, audit_id)" in upgrade
    assert "reject_workspace_autonomy_judgment_claim_snapshot_update" in upgrade
    assert "trg_workspace_autonomy_judgment_claim_snapshot_immutable" in upgrade
    assert "reject_workspace_autonomy_bootstrap_snapshot_update" in upgrade
    assert "trg_workspace_autonomy_bootstrap_snapshot_immutable" in upgrade

    for field in (
        "tenant_id",
        "project_id",
        "workspace_id",
        "actor_id",
        "idempotency_key",
        "request_hash",
        "expected_revision",
        "created_at_ms",
    ):
        assert f"NEW.{field}" in upgrade
        assert f"OLD.{field}" in upgrade
    for field in (
        "objective_title",
        "objective_description",
    ):
        assert f"NEW.{field}" in upgrade
        assert f"OLD.{field}" in upgrade

    assert (
        "DROP FUNCTION avernet.reject_workspace_autonomy_judgment_claim_snapshot_update()"
        in downgrade
    )
    assert (
        "DROP FUNCTION avernet.reject_workspace_autonomy_bootstrap_snapshot_update()" in downgrade
    )
    assert "DROP CONSTRAINT uq_workspace_judge_audits_scope_id" in downgrade
