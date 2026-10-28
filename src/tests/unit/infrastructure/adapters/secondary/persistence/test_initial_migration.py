"""The pre-Alembic baseline must never silently adopt a partial legacy schema."""

import importlib.util
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def initial_migration() -> ModuleType:
    path = Path(__file__).resolve().parents[7] / "alembic/versions/8b5199acd775_initial_schema.py"
    spec = importlib.util.spec_from_file_location("initial_schema_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.unit
def test_partial_unversioned_database_is_rejected_before_ddl(initial_migration: ModuleType) -> None:
    connection = MagicMock()
    connection.execute.return_value.scalar_one_or_none.return_value = "public.users"
    with (
        patch.object(initial_migration.context, "is_offline_mode", return_value=False),
        patch.object(initial_migration.op, "get_bind", return_value=connection),
        patch.object(initial_migration.op, "execute") as execute,
        pytest.raises(RuntimeError, match="nonempty database without an Alembic revision"),
    ):
        initial_migration.upgrade()
    execute.assert_not_called()


@pytest.mark.unit
def test_empty_database_baseline_includes_legacy_provider_and_hitl_tables(
    initial_migration: ModuleType,
) -> None:
    connection = MagicMock()
    connection.execute.return_value.scalar_one_or_none.return_value = None
    with (
        patch.object(initial_migration.context, "is_offline_mode", return_value=False),
        patch.object(initial_migration.op, "get_bind", return_value=connection),
        patch.object(initial_migration.op, "execute") as execute,
    ):
        initial_migration.upgrade()
    statements = [str(call.args[0]) for call in execute.call_args_list]
    assert any(statement.startswith("CREATE TABLE hitl_requests (") for statement in statements)
    assert any(statement.startswith("CREATE TABLE llm_providers (") for statement in statements)
    assert sum(statement.startswith("CREATE TABLE ") for statement in statements) == 46
    assert not any("IF NOT EXISTS" in statement for statement in statements)
