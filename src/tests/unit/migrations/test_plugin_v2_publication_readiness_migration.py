"""Contract tests for the protocol-v2 publication readiness migration."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import Mock

import pytest

_MIGRATION_PATH = (
    Path(__file__).parents[4]
    / "alembic"
    / "versions"
    / "e91f4c7b2d60_add_plugin_v2_publication_readiness.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location(
        "plugin_v2_publication_readiness_migration",
        _MIGRATION_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.unit
def test_readiness_migration_backfills_deadline_and_historical_ready_evidence() -> None:
    migration = _load_migration()
    migration_op = Mock()
    migration.op = migration_op

    migration.upgrade()

    sql = "\n".join(str(call.args[0]) for call in migration_op.execute.call_args_list).lower()
    assert "created_at + interval '30 seconds'" in sql
    assert "from platform_plugin_v2_apply_state_events as event" in sql
    assert "publication.id = event.requested_publication_id" in sql
    assert "event.applied_publication_id = publication.id" in sql
    assert "event.status = 'ack'" in sql
    assert "min(event.recorded_at)" in sql
