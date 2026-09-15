"""The actual builtin factory defaults to awaited application PostgreSQL storage."""

from types import SimpleNamespace

import pytest

from src.infrastructure.agent.subagent import production_run_registry_v2 as production
from src.infrastructure.agent.subagent.async_run_registry_v2 import AsyncSubAgentRunRegistryV2
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.subagent_run_registry_service import (
    create_subagent_run_registry_v2,
)


def settings(**overrides):
    values = {
        "agent_subagent_run_registry_path": None,
        "agent_subagent_run_sqlite_path": None,
        "agent_subagent_run_postgres_dsn": None,
        "agent_subagent_terminal_retention_seconds": 86400,
        "postgres_url": "postgresql://unused:unused@localhost/unused",
    }
    return SimpleNamespace(**(values | overrides))


def test_builtin_default_uses_actual_application_async_sessions(monkeypatch):
    from src.infrastructure.adapters.secondary.persistence.database import async_session_factory

    monkeypatch.setattr(production, "get_settings", lambda: settings())
    monkeypatch.setattr(production, "_REGISTRIES", {})
    registry = create_subagent_run_registry_v2({"strategy": "settings-shared"})
    assert isinstance(registry, AsyncSubAgentRunRegistryV2)
    assert registry._sessions is async_session_factory
    assert create_subagent_run_registry_v2({"strategy": "settings-shared"}) is registry
    with pytest.raises(RuntimeV2Error, match="awaited"):
        registry.create_run("conversation", "worker", "task")


@pytest.mark.parametrize(
    "field", ["agent_subagent_run_registry_path", "agent_subagent_run_sqlite_path"]
)
def test_cloud_cannot_silently_fallback_to_process_or_file_storage(monkeypatch, field):
    monkeypatch.setattr(production, "get_settings", lambda: settings(**{field: "legacy-path"}))
    with pytest.raises(RuntimeV2Error, match="PostgreSQL"):
        production.production_subagent_run_registry_v2()
