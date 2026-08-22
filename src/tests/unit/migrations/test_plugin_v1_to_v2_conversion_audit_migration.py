"""Contract test for the one-shot plugin protocol conversion audit table."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import Mock

import pytest

_MIGRATION_PATH = (
    Path(__file__).parents[4]
    / "alembic"
    / "versions"
    / "b5e9f3d8c012_add_plugin_v1_conversion_audit.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location(
        "plugin_v1_to_v2_conversion_audit_migration",
        _MIGRATION_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.unit
def test_conversion_audit_migration_is_append_only_and_follows_desired_set_head() -> None:
    migration = _load_migration()
    migration_op = Mock()
    migration.op = migration_op

    migration.upgrade()

    assert migration.down_revision == "a4d8e2c7b901"
    create = next(
        call
        for call in migration_op.create_table.call_args_list
        if call.args[0] == "platform_plugin_v1_conversion_runs"
    )
    column_names = {item.name for item in create.args[1:] if hasattr(item, "name")}
    assert {
        "migration_id",
        "source_digest",
        "mapping_digest",
        "output_digest",
        "actor_id",
        "report",
        "created_at",
    } <= column_names
    constraints = " ".join(str(item) for item in create.args[1:]).lower()
    assert "uniqueconstraint" in constraints
    assert "migration_id" in constraints
