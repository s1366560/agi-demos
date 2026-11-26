"""Adapter selection for the shared plugin and API relational store."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from plugins.business.billing.backend.invoices import Invoice
from src.configuration.config import Settings
from src.infrastructure.adapters.secondary.persistence import database
from src.infrastructure.adapters.secondary.persistence.models import (
    APIKey,
    Base,
    Tenant,
    User,
    UserSession,
    WebhookModel,
)
from src.infrastructure.adapters.secondary.persistence.relational_store import (
    open_relational_store,
    select_relational_store,
)
from src.infrastructure.plugins.v2.artifact_content_gc_runtime import (
    ASYNC_SESSION_FACTORY_SERVICE_V2,
    AsyncSessionFactoryServiceV2,
    async_session_factory_definition_v2,
)
from src.infrastructure.plugins.v2.runtime import ContextV2

_POSTGRES_URL = "postgresql://cloud-user:cloud-password@db.example.test:5432/memstack"


def _settings(tmp_path: Path, body: str) -> Settings:
    env_file = tmp_path / ".env"
    env_file.write_text(body, encoding="utf-8")
    return Settings(_env_file=env_file)


@pytest.mark.unit
async def test_postgres_driver_is_the_default_and_hides_the_password(tmp_path: Path) -> None:
    settings = _settings(
        tmp_path,
        f"{_POSTGRES_URL.replace('postgresql://', 'DATABASE_URL=postgresql://', 1)}\n"
        "POSTGRES_READ_REPLICA_HOST=replica.example.test\n"
        "POSTGRES_USER=cloud-user\n"
        "POSTGRES_PASSWORD=cloud-password\n"
        "POSTGRES_DB=memstack\n",
    )

    spec = select_relational_store(settings)
    store = open_relational_store(settings)
    replica = store.read_engine
    try:
        assert store.engine.dialect.name == "postgresql"
        assert replica is not None
        assert replica.dialect.name == "postgresql"
    finally:
        await store.engine.dispose()
        if replica is not None:
            await replica.dispose()

    assert spec.kind == "postgres"
    assert spec.dialect == "postgresql"
    assert spec.supports_advisory_locks is True
    assert spec.url.startswith("postgresql+asyncpg://")
    assert spec.read_replica_url is not None
    assert "replica.example.test" in spec.read_replica_url
    assert "cloud-password" not in spec.redacted_url


@pytest.mark.unit
def test_sqlite_driver_ignores_postgres_and_read_replicas(tmp_path: Path) -> None:
    database_path = tmp_path / "desktop" / "plugin.sqlite"
    settings = _settings(
        tmp_path,
        "\n".join(
            (
                "MEMSTACK_RELATIONAL_STORE=sqlite",
                f"MEMSTACK_SQLITE_PATH={database_path}",
                "POSTGRES_READ_REPLICA_HOST=replica.example.test",
                _POSTGRES_URL.replace("postgresql://", "DATABASE_URL=postgresql://", 1),
                "",
            )
        ),
    )

    spec = select_relational_store(settings)

    assert spec.kind == "sqlite"
    assert spec.dialect == "sqlite"
    assert spec.supports_advisory_locks is False
    assert spec.supports_read_replica is False
    assert spec.read_replica_url is None
    assert spec.database_path == str(database_path.resolve())
    assert spec.url.startswith("sqlite+aiosqlite:///")
    assert "db.example.test" not in spec.url


@pytest.mark.unit
def test_sqlite_driver_starts_without_a_database_url(tmp_path: Path) -> None:
    settings = _settings(
        tmp_path,
        f"MEMSTACK_RELATIONAL_STORE=sqlite\nMEMSTACK_SQLITE_PATH={tmp_path / 'local.sqlite'}\n",
    )

    spec = select_relational_store(settings)

    assert settings.database_url is None
    assert spec.kind == "sqlite"


@pytest.mark.unit
@pytest.mark.parametrize(
    "body",
    [
        "MEMSTACK_RELATIONAL_STORE=sqlite\n",
        "MEMSTACK_RELATIONAL_STORE=pglite\n",
        "MEMSTACK_RELATIONAL_STORE=sqlite\nMEMSTACK_SQLITE_PATH=sqlite:///memory\n",
    ],
)
def test_relational_store_rejects_an_unopenable_local_driver(tmp_path: Path, body: str) -> None:
    with pytest.raises(ValidationError, match="MEMSTACK_"):
        _ = _settings(tmp_path, body)


@pytest.mark.unit
async def test_sqlite_bootstrap_serves_plugin_rows_without_cloud_postgres(
    tmp_path: Path,
) -> None:
    settings = _settings(
        tmp_path,
        f"MEMSTACK_RELATIONAL_STORE=sqlite\nMEMSTACK_SQLITE_PATH={tmp_path / 'host.sqlite'}\n",
    )
    store = open_relational_store(settings)
    try:
        await database.initialize_database(store.engine)
        async with store.session_factory() as session:
            names = set((await session.scalars(text("SELECT name FROM sqlite_master"))).all())
            await _insert_plugin_invoice(session)
            amount = await session.scalar(select(Invoice.amount).where(Invoice.id == "i1"))
        assert "alembic_version" not in names
        assert "billing_alembic_version" in names
        assert "invoices" in names
        assert amount == 50
        assert store.engine.dialect.name == "sqlite"
        assert settings.database_url is None
    finally:
        await store.engine.dispose()


class _Context:
    def __init__(self) -> None:
        self.provided: dict[str, object] = {}

    def provide(
        self,
        service: str,
        value: object,
        *,
        version: str | None = None,
        label: str | None = None,
    ) -> None:
        _ = (version, label)
        self.provided[service] = value


def _publish(context: _Context) -> AsyncSessionFactoryServiceV2:
    async_session_factory_definition_v2().apply(
        cast("ContextV2", context),
        {"strategy": "sqlalchemy-async-sessionmaker"},
    )
    published = context.provided[ASYNC_SESSION_FACTORY_SERVICE_V2]
    assert isinstance(published, AsyncSessionFactoryServiceV2)
    return published


@pytest.mark.unit
def test_session_factory_service_publishes_the_selected_driver(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(
        tmp_path,
        f"MEMSTACK_RELATIONAL_STORE=sqlite\nMEMSTACK_SQLITE_PATH={tmp_path / 'session.sqlite'}\n",
    )
    monkeypatch.setattr(database, "relational_store", select_relational_store(settings))

    published = _publish(_Context())

    assert published.driver == "sqlite"
    assert published.dialect == "sqlite"
    assert published.advisory_locks is False
    assert published.factory is database.async_session_factory


@pytest.mark.unit
def test_postgresql_partial_indexes_keep_sqlite_predicates() -> None:
    missing = [
        f"{table.name}.{index.name}"
        for table in Base.metadata.tables.values()
        for index in table.indexes
        if index.dialect_options["postgresql"].get("where") is not None
        and index.dialect_options["sqlite"].get("where") is None
    ]

    assert missing == []


@pytest.mark.unit
async def test_sqlite_keeps_partial_uniqueness_and_foreign_key_actions(tmp_path: Path) -> None:
    settings = _settings(
        tmp_path,
        f"MEMSTACK_RELATIONAL_STORE=sqlite\nMEMSTACK_SQLITE_PATH={tmp_path / 'constraints.sqlite'}\n",
    )
    store = open_relational_store(settings)
    try:
        await database.initialize_database(store.engine)
        async with store.session_factory() as session:
            first_pragma = await session.scalar(text("PRAGMA foreign_keys"))
            index_sql = await session.scalar(
                text("SELECT sql FROM sqlite_master WHERE name = 'ix_webhooks_tenant_name'")
            )
            _insert_identity(session)
            await session.flush()
            session.add(
                WebhookModel(
                    id="wh-deleted",
                    tenant_id="t1",
                    name="billing",
                    url="https://example.test/old",
                    events=[],
                    deleted_at=datetime.now(UTC),
                )
            )
            session.add(
                WebhookModel(
                    id="wh-live",
                    tenant_id="t1",
                    name="billing",
                    url="https://example.test/new",
                    events=[],
                )
            )
            await session.commit()
        async with store.session_factory() as session:
            second_pragma = await session.scalar(text("PRAGMA foreign_keys"))
            session.add(
                APIKey(
                    id="k1",
                    key_hash="hash",
                    name="desktop",
                    user_id="u1",
                    permissions=[],
                )
            )
            session.add(
                UserSession(
                    id="s1",
                    user_id="u1",
                    family_id="family",
                    refresh_token_hash="a" * 64,
                    access_api_key_id="k1",
                    expires_at=datetime.now(UTC) + timedelta(hours=1),
                )
            )
            await session.commit()
            await session.execute(text("DELETE FROM api_keys WHERE id = 'k1'"))
            await session.commit()
            cleared = await session.scalar(
                select(UserSession.access_api_key_id).where(UserSession.id == "s1")
            )
            session.add(
                WebhookModel(
                    id="wh-conflict",
                    tenant_id="t1",
                    name="billing",
                    url="https://example.test/conflict",
                    events=[],
                )
            )
            with pytest.raises(IntegrityError):
                await session.commit()
        assert first_pragma == 1
        assert second_pragma == 1
        assert isinstance(index_sql, str)
        assert "deleted_at IS NULL" in index_sql
        assert cleared is None
    finally:
        await store.engine.dispose()


@pytest.mark.unit
def test_default_process_session_factory_stays_on_postgres() -> None:
    published = _publish(_Context())

    assert database.relational_store.kind == "postgres"
    assert published.driver == "postgres"
    assert published.dialect == "postgresql"
    assert published.advisory_locks is True


def _insert_identity(session: AsyncSession) -> None:
    session.add(
        User(
            id="u1",
            email="local@example.test",
            hashed_password="not-a-secret",
            full_name="Local",
            is_active=True,
            is_superuser=False,
            must_change_password=False,
            profile={},
        )
    )
    session.add(
        Tenant(
            id="t1",
            name="Local",
            slug="local",
            owner_id="u1",
            plan="free",
            max_projects=1,
            max_users=1,
            max_storage=1,
        )
    )


async def _insert_plugin_invoice(session: AsyncSession) -> None:
    _insert_identity(session)
    # Bare foreign keys do not order the unit of work, so the parent rows
    # must exist before the invoice insert. PostgreSQL enforces the same rule.
    await session.flush()
    now = datetime.now(UTC)
    session.add(
        Invoice(
            id="i1",
            tenant_id="t1",
            amount=50,
            currency="USD",
            status="paid",
            period_start=now,
            period_end=now,
        )
    )
    await session.commit()
