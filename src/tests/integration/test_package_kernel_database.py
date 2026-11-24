"""Exercise the standalone migration and identity boundary on disposable PostgreSQL servers."""

import asyncio
import json
import logging
import os
import secrets
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import docker
from src.cli.package_kernel_owner import provision_owner
from src.infrastructure.adapters.secondary.persistence.package_kernel_database import (
    VERSION_TABLE,
    initialize_package_kernel_database,
    package_kernel_metadata,
)
from src.tests.unit.routers import test_optional_business_http_v2 as project_fixtures

publisher = project_fixtures.publisher
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("PACKAGE_KERNEL_DATABASE_TESTS") != "1",
        reason="requires disposable PostgreSQL Docker images",
    ),
]


@pytest_asyncio.fixture(loop_scope="function")
async def database(request):
    client = docker.from_env()
    image = getattr(request, "param", "postgres:16-alpine")
    name = "pkgdbqa" + uuid4().hex[:12]
    container = client.containers.run(
        image,
        name=name,
        environment={"POSTGRES_HOST_AUTH_METHOD": "trust", "POSTGRES_DB": name},
        ports={"5432/tcp": ("127.0.0.1", None)},
        detach=True,
    )
    try:
        container.reload()
        port = container.attrs["NetworkSettings"]["Ports"]["5432/tcp"][0]["HostPort"]
        for _ in range(100):
            if (
                container.exec_run(
                    ["pg_isready", "-h", "127.0.0.1", "-U", "postgres", "-d", name]
                ).exit_code
                == 0
            ):
                break
            await asyncio.sleep(0.15)
        else:
            pytest.fail("disposable Postgres did not start")
        engine = create_async_engine(f"postgresql+asyncpg://postgres@127.0.0.1:{port}/{name}")
        try:
            async with engine.connect() as connection:
                assert await connection.scalar(text("SELECT current_database()")) == name
                assert engine.url.host == "127.0.0.1" and engine.url.port == int(port)
            yield engine
        finally:
            await engine.dispose()
    finally:
        container.remove(force=True, v=True)
        client.close()


async def _tables(engine):
    async with engine.connect() as connection:
        return set(await connection.run_sync(lambda sync: inspect(sync).get_table_names()))


def _isolate_cli_settings(monkeypatch):
    from src.configuration import config

    # Embedded migrations must use the caller's engine even when CLI settings
    # point elsewhere. A regression here cannot connect to any developer database.
    settings = SimpleNamespace(
        postgres_url="postgresql+asyncpg://unused@127.0.0.1:1/unreachable", environment="production"
    )
    monkeypatch.setattr(config, "get_settings", lambda: settings)


async def _first_owner(database):
    email, password = "project-owner@example.org", secrets.token_urlsafe(32)

    async def bootstrap():
        return await provision_owner(
            database, email=email, password=password, tenant_name="Tenant", project_name="Project"
        )

    results = await asyncio.gather(bootstrap(), bootstrap(), return_exceptions=True)
    (scope_pair,) = (value for value in results if isinstance(value, tuple))
    assert (
        sum(isinstance(value, RuntimeError) and "already exists" in str(value) for value in results)
        == 1
    )
    with pytest.raises(RuntimeError, match="already exists"):
        await bootstrap()
    tenant, project = scope_pair
    async with database.connect() as connection:
        assert await connection.scalar(text("SELECT count(*) FROM users WHERE is_superuser")) == 0
    return email, password, {"tenant_id": tenant, "project_id": project}


async def _check_native_identity(api, headers, scope):
    projects = (await api.get("/api/v1/project-packages/projects/", headers=headers)).json()
    assert [p["project_id"] for p in projects if p["can_manage"]] == [scope["project_id"]]
    context = (await api.get("/api/v1/workspace-context", headers=headers)).json()["context"]
    assert (context["tenant_id"], context["project_id"]) == (
        scope["tenant_id"],
        scope["project_id"],
    )
    assert (await api.get("/api/v1/tenants/", headers=headers)).json()["total"] == 1
    assert (
        await api.get(
            "/api/v1/projects/", headers=headers, params={"tenant_id": scope["tenant_id"]}
        )
    ).json()["total"] == 1
    project_url = "/api/v1/projects/" + scope["project_id"]
    assert (await api.get(project_url, headers=headers)).json()["tenant_id"] == scope["tenant_id"]
    assert (
        await api.get(project_url, headers=headers, params={"tenant_id": "other"})
    ).status_code == 404
    assert (await api.get("/api/v1/plugin-marketplace/packages", headers=headers)).json() == []


async def test_concurrent_standalone_start_owner_login_refresh_and_signed_command(
    database, publisher, monkeypatch, caplog
):
    from src.host.transport import package_kernel
    from src.infrastructure.adapters.primary.web.routers import auth
    from src.infrastructure.adapters.secondary.persistence.database import (
        get_db,
        initialize_database,
    )

    caplog.set_level(logging.INFO, logger="plugin_audit")
    await asyncio.gather(*(initialize_package_kernel_database(database) for _ in range(3)))
    tables = await _tables(database)
    assert tables == set(package_kernel_metadata().tables) | {VERSION_TABLE}
    assert {"tenant_plugin_installations", "tenant_plugin_releases"} <= tables
    assert not {"invoices", "memories", "alembic_version"}.intersection(tables)
    async with database.connect() as connection:
        assert await connection.scalar(text("SELECT count(*) FROM users")) == 0
        assert (
            await connection.scalar(
                text("SELECT count(*) FROM pg_available_extensions WHERE name='vector'")
            )
            == 0
        )
    _isolate_cli_settings(monkeypatch)
    with pytest.raises(RuntimeError, match="cannot use the full"):
        await initialize_database(database)
    assert await _tables(database) == tables

    email, password, scope = await _first_owner(database)
    settings = SimpleNamespace(
        secret_key=secrets.token_urlsafe(40),
        api_allowed_origins=[],
        package_application_runtime_url=None,
    )
    monkeypatch.setattr(auth, "get_settings", lambda: settings)
    monkeypatch.setattr(package_kernel, "get_settings", lambda: settings)
    app = package_kernel.create_app()
    app.state.plugin_marketplace_trusted_public_keys_v2 = (publisher[0],)
    sessions = async_sessionmaker(database, expire_on_commit=False)

    async def get_isolated_db():
        async with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = get_isolated_db
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://kernel"
    ) as api:
        login = await api.post("/api/v1/auth/token", data={"username": email, "password": password})
        assert login.is_success, login.status_code
        refreshed = await api.post(
            "/api/v1/auth/refresh", json={"refresh_token": login.json()["refresh_token"]}
        )
        assert refreshed.is_success, refreshed.status_code
        headers = {"Authorization": "Bearer " + refreshed.json()["access_token"]}
        await _check_native_identity(api, headers, scope)
        base = "/api/v1/platform-plugins/v2/optional-business"
        release, digest = publisher[1]()
        assert (
            await api.post(base + "/install", json={**release, **scope}, headers=headers)
        ).is_success
        assert (
            await api.post(base + "/sample.notes/enable", json=scope, headers=headers)
        ).is_success
        reply = await api.post(
            base + "/sample.notes/commands",
            json={**scope, "expected_digest": digest, "command_id": "ping"},
            headers=headers,
        )
        assert reply.json()["op"] == "ping"
        receipts = [
            json.loads(r.getMessage())
            for r in caplog.records
            if r.name == "plugin_audit.project_package"
        ]
        (command,) = (event for event in receipts if event["operation"] == "command")
        identity = (await api.get("/api/v1/auth/me", headers=headers)).json()
        assert (command["actor_id"], command["project_id"], command["digest"]) == (
            identity["user_id"],
            scope["project_id"],
            digest,
        )
        assert password not in caplog.text
        assert (await api.get("/health/ready")).is_success
    await initialize_package_kernel_database(database)
    assert await _tables(database) == tables


@pytest.mark.parametrize("database", ["pgvector/pgvector:pg16"], indirect=True)
async def test_standalone_refuses_existing_full_database(database, monkeypatch):
    from src.infrastructure.adapters.secondary.persistence.database import initialize_database

    _isolate_cli_settings(monkeypatch)
    await initialize_database(database)
    old = await _tables(database)
    assert {"agent_run_authorities", "memories", "alembic_version"} <= old
    with pytest.raises(RuntimeError, match="full MemStack database"):
        await initialize_package_kernel_database(database)
    assert await _tables(database) == old


async def test_unversioned_database_refused_and_package_owned_tables_ignored(database):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import Column, Integer

    from alembic import command
    from src.infrastructure.adapters.secondary.persistence.package_kernel_database import (
        migration_config,
    )

    def add_business_table(connection):
        Operations(MigrationContext.configure(connection)).create_table(
            "package_owned_rows", Column("id", Integer, primary_key=True)
        )

    async with database.begin() as connection:
        await connection.run_sync(add_business_table)
    with pytest.raises(RuntimeError, match="empty dedicated database"):
        await initialize_package_kernel_database(database)
    assert await _tables(database) == {"package_owned_rows"}
    async with database.begin() as connection:
        await connection.run_sync(
            lambda sync: Operations(MigrationContext.configure(sync)).drop_table(
                "package_owned_rows"
            )
        )
    await initialize_package_kernel_database(database)
    async with database.begin() as connection:
        await connection.run_sync(add_business_table)
        await connection.run_sync(lambda sync: command.check(migration_config(sync)))
    assert "package_owned_rows" in await _tables(database)


async def test_concurrent_reviewed_installations_activate_exactly_one_version(database, publisher):
    from base64 import b64decode

    from src.host.packages.project_plugin_installation import ProjectPluginInstallationService
    from src.infrastructure.plugins.v2.signed_optional_business_v2 import (
        OptionalBusinessError,
        ScopeBindingV2,
    )

    await initialize_package_kernel_database(database)
    _, _, ids = await _first_owner(database)
    scope = ScopeBindingV2(**ids)
    sessions = async_sessionmaker(database, expire_on_commit=False)

    async def choose(version):
        body, digest = publisher[1](version)
        async with sessions() as db:
            service = ProjectPluginInstallationService(db, scope, (publisher[0],))
            try:
                await service.record_selection(
                    b64decode(body["archive_base64"]),
                    frozenset(body["approved_permissions"]),
                    "test-owner",
                    expected_revision=0,
                    expected_digest=digest,
                    expected_identity=("sample.notes", version),
                    activate=True,
                )
            except OptionalBusinessError as exc:
                assert exc.code == "conflict"
                return None
            return digest

    results = await asyncio.gather(choose("1.0.0"), choose("2.0.0"))
    assert results.count(None) == 1
    async with sessions() as db:
        service = ProjectPluginInstallationService(db, scope, (publisher[0],))
        installation = await service.projection("sample.notes")
        assert installation["desired_revision"] == 1
        assert installation["actual_digest"] == installation["desired_digest"]
        assert installation["actual_digest"] in results
