"""Select the primary relational store shared by the API and plugins.

Cloud hosts use PostgreSQL. Desktop and local development use embedded SQLite
through SQLAlchemy + aiosqlite. Plugins keep consuming
``service:persistence.async-session-factory`` and ``service:operation.db-session``;
they do not open a cloud driver themselves.

SQLite is the embedded driver because the desktop sidecar, Workspace Core, and
the test suite already use it. PGlite is not wired.

These host resources are still cloud-shaped and are not selected by this module:

- Redis (``service:runtime.redis-client``)
- S3-compatible object storage (``service:storage.object-storage``)
- Neo4j / ``GRAPH_STORE_*`` graph runtime
- Ray actors (desktop already has its own local agent runtime mode)
- Workspace Core's separate PostgreSQL/SQLite ``DbPlugin`` authority
- PostgreSQL repair SQL such as ``pg_constraint`` and package-kernel advisory locks
- The SubAgent production registry, which still requires PostgreSQL
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol

from sqlalchemy import event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import NullPool

if TYPE_CHECKING:
    from src.configuration.config import Settings

logger = logging.getLogger(__name__)

RelationalStoreKind = Literal["postgres", "sqlite"]
_NULL_POOL_MODES = frozenset({"null", "none", "disabled"})
_SQLITE_JSONB_REGISTERED = False


@dataclass(frozen=True, kw_only=True)
class RelationalStoreSpec:
    """Driver choice for one process. The URL is an engine input, not a log line."""

    kind: RelationalStoreKind
    dialect: Literal["postgresql", "sqlite"]
    url: str
    database_path: str | None = None
    supports_advisory_locks: bool
    read_replica_url: str | None = None

    @property
    def supports_read_replica(self) -> bool:
        return self.read_replica_url is not None

    @property
    def redacted_url(self) -> str:
        return make_url(self.url).render_as_string(hide_password=True)


@dataclass(frozen=True, kw_only=True)
class RelationalStore:
    """Opened engines for the selected spec."""

    spec: RelationalStoreSpec
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    read_engine: AsyncEngine | None
    read_session_factory: async_sessionmaker[AsyncSession] | None


def select_relational_store(settings: Settings) -> RelationalStoreSpec:
    """Resolve the process driver without opening a connection."""
    if settings.relational_store == "sqlite":
        if not settings.sqlite_path:
            raise ValueError("MEMSTACK_SQLITE_PATH is required for the sqlite relational store")
        url = make_url("sqlite+aiosqlite://").set(database=settings.sqlite_path)
        return RelationalStoreSpec(
            kind="sqlite",
            dialect="sqlite",
            url=url.render_as_string(hide_password=False),
            database_path=settings.sqlite_path,
            supports_advisory_locks=False,
            read_replica_url=None,
        )

    read_replica_url = None
    if settings.postgres_read_replica_host:
        read_replica_url = (
            f"postgresql+asyncpg://{settings.postgres_user}:{settings.postgres_password}"
            f"@{settings.postgres_read_replica_host}:{settings.postgres_read_replica_port}"
            f"/{settings.postgres_db}"
        )
    return RelationalStoreSpec(
        kind="postgres",
        dialect="postgresql",
        url=settings.postgres_url,
        supports_advisory_locks=True,
        read_replica_url=read_replica_url,
    )


def postgres_engine_kwargs(settings: Settings) -> dict[str, Any]:
    """Pool settings for the PostgreSQL driver. SQLite uses a null pool instead."""
    pool_mode = os.getenv("MEMSTACK_POSTGRES_POOL_MODE", "").strip().lower()
    common: dict[str, Any] = {
        "echo": settings.log_level.upper() == "DEBUG",
        "pool_recycle": settings.postgres_pool_recycle,
        "pool_pre_ping": settings.postgres_pool_pre_ping,
    }
    if pool_mode in _NULL_POOL_MODES:
        logger.info("Postgres NullPool enabled for this process")
        return {**common, "poolclass": NullPool}
    return {
        **common,
        "pool_size": settings.postgres_pool_size,
        "max_overflow": settings.postgres_max_overflow,
    }


def open_relational_store(settings: Settings) -> RelationalStore:
    """Open the selected driver. PostgreSQL connects lazily; SQLite creates its file."""
    spec = select_relational_store(settings)
    logger.info("Relational store selected: %s (%s)", spec.kind, spec.redacted_url)
    if spec.kind == "sqlite":
        register_sqlite_jsonb_compat()
        if spec.database_path is None:
            raise ValueError("sqlite relational store is missing its file path")
        Path(spec.database_path).parent.mkdir(parents=True, exist_ok=True)
        engine = create_async_engine(
            spec.url,
            echo=settings.log_level.upper() == "DEBUG",
            poolclass=NullPool,
        )
        _enable_sqlite_foreign_keys(engine)
        return RelationalStore(
            spec=spec,
            engine=engine,
            session_factory=_session_factory(engine),
            read_engine=None,
            read_session_factory=None,
        )

    engine = create_async_engine(spec.url, **postgres_engine_kwargs(settings))
    read_engine: AsyncEngine | None = None
    read_factory: async_sessionmaker[AsyncSession] | None = None
    if spec.read_replica_url is not None:
        read_engine = create_async_engine(spec.read_replica_url, **postgres_engine_kwargs(settings))
        read_factory = _session_factory(read_engine)
        logger.info(
            "Read replica enabled at %s:%s",
            settings.postgres_read_replica_host,
            settings.postgres_read_replica_port,
        )
    else:
        logger.info("No read replica configured, using primary for all operations")
    return RelationalStore(
        spec=spec,
        engine=engine,
        session_factory=_session_factory(engine),
        read_engine=read_engine,
        read_session_factory=read_factory,
    )


class _SqliteCursor(Protocol):
    def execute(self, statement: str) -> object: ...

    def close(self) -> None: ...


class _SqliteConnection(Protocol):
    def cursor(self) -> _SqliteCursor: ...


def _enable_sqlite_foreign_keys(engine: AsyncEngine) -> None:
    """Turn on referential actions for every fresh SQLite connection.

    NullPool opens a new connection per checkout, and SQLite leaves
    ``foreign_keys`` off unless each connection sets the pragma.
    """

    @event.listens_for(engine.sync_engine, "connect")
    def _set_foreign_keys(dbapi_connection: _SqliteConnection, _connection_record: object) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def register_sqlite_jsonb_compat() -> None:
    """Compile PostgreSQL JSONB columns as JSON when the sqlite driver creates tables."""
    global _SQLITE_JSONB_REGISTERED
    if _SQLITE_JSONB_REGISTERED:
        return

    @compiles(JSONB, "sqlite")
    def _compile_jsonb_for_sqlite(_type: object, _compiler: object, **_kw: object) -> str:
        return "JSON"

    _SQLITE_JSONB_REGISTERED = True


def _session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


def _import_relational_models() -> None:
    """Import ORM modules that register tables outside ``models.py``."""
    from plugins.business.billing.backend import invoices as billing_invoices
    from src.infrastructure.adapters.secondary.persistence import (
        device_plugin_grant_model as device_grants,
        platform_plugin_namespace_model_v2 as plugin_namespace,
        project_plugin_installation as project_plugins,
        tenant_plugin_installation as tenant_plugins,
    )

    _ = (billing_invoices, device_grants, plugin_namespace, project_plugins, tenant_plugins)


async def bootstrap_sqlite_relational_schema(engine: AsyncEngine) -> None:
    """Create the ORM schema and stamp the billing package migration on SQLite.

    Alembic's main history stays on PostgreSQL. The sqlite driver materializes
    the imported SQLAlchemy metadata, then runs the billing package migration,
    which already skips PostgreSQL advisory locks on other dialects.
    """
    if not isinstance(engine.dialect.name, str) or engine.dialect.name != "sqlite":
        raise RuntimeError("sqlite relational bootstrap requires a sqlite engine")
    register_sqlite_jsonb_compat()
    _import_relational_models()
    from plugins.business.billing.migration import migrate_invoices
    from src.infrastructure.adapters.secondary.persistence.models import Base

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions: Callable[[], AsyncSession] = _session_factory(engine)
    await migrate_invoices(sessions)


__all__ = [
    "RelationalStore",
    "RelationalStoreKind",
    "RelationalStoreSpec",
    "bootstrap_sqlite_relational_schema",
    "open_relational_store",
    "postgres_engine_kwargs",
    "register_sqlite_jsonb_compat",
    "select_relational_store",
]
