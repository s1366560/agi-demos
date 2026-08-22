"""Contract tests for the protocol-v2 DesiredBundleSet persistence migration."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import Mock

import pytest

_MIGRATION_PATH = (
    Path(__file__).parents[4]
    / "alembic"
    / "versions"
    / "a4d8e2c7b901_add_plugin_v2_desired_bundle_sets.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location(
        "plugin_v2_desired_bundle_set_migration",
        _MIGRATION_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.unit
def test_desired_bundle_set_migration_is_append_only_and_follows_readiness_head() -> None:
    migration = _load_migration()
    migration_op = Mock()
    migration.op = migration_op

    migration.upgrade()

    assert migration.down_revision == "e91f4c7b2d60"
    create = next(
        call
        for call in migration_op.create_table.call_args_list
        if call.args[0] == "platform_plugin_v2_desired_bundle_sets"
    )
    column_names = {item.name for item in create.args[1:] if hasattr(item, "name")}
    assert {
        "scope_key",
        "scope_kind",
        "tenant_id",
        "project_id",
        "session_id",
        "desired_set_id",
        "revision",
        "digest",
        "payload",
        "actor_id",
    } <= column_names
    constraints = " ".join(str(item) for item in create.args[1:]).lower()
    assert "uniqueconstraint" in constraints
    assert "revision" in constraints
