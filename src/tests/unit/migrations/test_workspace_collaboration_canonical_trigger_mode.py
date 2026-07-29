"""Static contract for canonical trigger suppression."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

_MIGRATION_PATH = (
    Path(__file__).parents[4]
    / "alembic"
    / "versions"
    / "d4e9f0a1b2c3_add_workspace_collaboration_authority.py"
)


@pytest.mark.unit
def test_workspace_authority_trigger_skips_only_canonical_transaction() -> None:
    spec = importlib.util.spec_from_file_location("workspace_authority_migration", _MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    migration_op = Mock()
    migration_op.get_bind.return_value = SimpleNamespace(
        dialect=SimpleNamespace(name="postgresql")
    )
    migration.op = migration_op

    migration.upgrade()

    sql = "\n".join(str(call.args[0]) for call in migration_op.execute.call_args_list)
    assert "current_setting(" in sql
    assert "memstack.workspace_collaboration_authority_mode" in sql
    assert "= 'canonical'" in sql
