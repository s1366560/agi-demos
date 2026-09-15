"""Process-shared asynchronous registry using the application's PostgreSQL database."""

import threading

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from src.configuration.config import get_settings
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error

from .async_run_registry_v2 import AsyncSubAgentRunRegistryV2

_REGISTRIES: dict[tuple[str, int], AsyncSubAgentRunRegistryV2] = {}
_LOCK = threading.Lock()


def production_subagent_run_registry_v2() -> AsyncSubAgentRunRegistryV2:
    """Resolve without connecting; migrations and awaited transactions own storage."""
    settings = get_settings()
    if settings.agent_subagent_run_registry_path or settings.agent_subagent_run_sqlite_path:
        raise RuntimeV2Error(
            "subagent_persistence_backend_invalid",
            "Cloud SubAgent persistence requires the application PostgreSQL database",
        )
    override = settings.agent_subagent_run_postgres_dsn
    dsn = make_url(override) if override else make_url(settings.postgres_url)
    if dsn.get_backend_name() not in {"postgresql", "postgres"}:
        raise RuntimeV2Error("subagent_persistence_backend_invalid", "PostgreSQL is required")
    url = dsn.set(drivername="postgresql+asyncpg").render_as_string(hide_password=False)
    retention = settings.agent_subagent_terminal_retention_seconds
    with _LOCK:
        key = (url, retention)
        registry = _REGISTRIES.get(key)
        if registry is None:
            if override:
                engine = create_async_engine(url, poolclass=NullPool, connect_args={"timeout": 5})
                sessions = async_sessionmaker(engine, expire_on_commit=False)
            else:
                from src.infrastructure.adapters.secondary.persistence.database import (
                    async_session_factory,
                )

                sessions = async_session_factory
            registry = AsyncSubAgentRunRegistryV2(sessions, terminal_retention_seconds=retention)
            _REGISTRIES[key] = registry
        return registry
