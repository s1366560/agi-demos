"""Active read purity and live request authority against isolated PostgreSQL."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic.autogenerate import produce_migrations
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from fastapi import FastAPI, HTTPException
from sqlalchemy import insert, update
from starlette.requests import Request

from src.application.schemas.schema import EntityTypeCreate, EntityTypeResponse
from src.domain.model.project_schema.validation import ProjectSchemaError
from src.infrastructure.adapters.primary.web.schema_application_authority_v2 import (
    schema_application_authority_dependency_v2,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    Base,
    User,
    UserProject,
    UserTenant,
)
from src.infrastructure.adapters.secondary.schema import dynamic_schema
from src.infrastructure.adapters.secondary.schema.active_schema_reads import (
    SchemaCommandRequiredV2,
    active_schema_snapshot,
)
from src.infrastructure.plugins.v2.boundary import pin_generation_v2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2
from src.infrastructure.plugins.v2.schema_services import SchemaAccessDeniedV2
from src.tests.integration.project_schema_command_support import (
    SCOPE,
    activated,
    replacement,
    schema_command_pg as _schema_command_pg,
    schema_storage_pg as _schema_storage_pg,
)
from src.tests.integration.project_schema_storage_support import _invoke

schema_command_pg = _schema_command_pg
schema_storage_pg = _schema_storage_pg

pytestmark = pytest.mark.integration
_ROOT = Path(__file__).resolve().parents[3]


def add_memberships(connection):
    context = MigrationContext.configure(
        connection,
        opts={
            "include_object": lambda obj, name, kind, reflected, compare: (
                name in {"user_tenants", "user_projects"} if kind == "table" else True
            ),
        },
    )
    generated = produce_migrations(context, Base.metadata)
    for item in generated.upgrade_ops.ops:
        _invoke(Operations(context), item)
    connection.execute(
        insert(UserTenant),
        {
            "id": "membership-tenant",
            "user_id": "owner",
            "tenant_id": "tenant-a",
            "role": "owner",
        },
    )
    connection.execute(
        insert(UserProject),
        {
            "id": "membership-project",
            "user_id": "owner",
            "project_id": "project-a",
            "role": "owner",
        },
    )


@pytest.fixture
async def live_schema_pg(schema_command_pg):
    engine, sessions = schema_command_pg
    async with engine.begin() as connection:
        await connection.run_sync(add_memberships)
    yield engine, sessions


@pytest.fixture
async def schema_host():
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=41,
        version=41,
    )
    try:
        assert publication.accepted, publication
        yield host
    finally:
        await host.close()


def request(tenant=None):
    return Request(
        {
            "type": "http",
            "app": FastAPI(),
            "headers": [],
            "method": "GET",
            "path": "/api/v1/projects/project-a/schema/entities",
            "path_params": {"project_id": "project-a"},
            "query_string": b"" if tenant is None else f"tenant_id={tenant}".encode(),
            "scheme": "http",
            "server": ("test", 80),
        }
    )


@asynccontextmanager
async def authority(host, sessions, tenant=None):
    async with sessions() as db, pin_generation_v2(host):
        dependency = schema_application_authority_dependency_v2(
            request=request(tenant),
            current_user=SimpleNamespace(id="owner"),
            db=db,
        )
        try:
            yield await anext(dependency)
        finally:
            await dependency.aclose()


async def test_project_only_authority_uses_actual_tenant_and_rejects_forged_scope(
    live_schema_pg, schema_host
):
    _, sessions = live_schema_pg
    async with authority(schema_host, sessions) as value:
        assert value.operation.context.scope.tenant_id == "tenant-a"
        assert value.services.scope == SCOPE
        with pytest.raises(SchemaAccessDeniedV2):
            await value.services.list_entity_types(user_id="owner", project_id="project-b")
    with pytest.raises(HTTPException) as error:
        async with authority(schema_host, sessions, "tenant-b"):
            pytest.fail("forged tenant admitted")
    assert error.value.status_code == 403


async def test_active_reads_keep_exact_snapshot_and_original_timestamps(
    live_schema_pg, schema_host, monkeypatch
):
    _, sessions = live_schema_pg
    commands, receipt = await activated(sessions)
    monkeypatch.setattr(dynamic_schema, "async_session_factory", sessions)
    dynamic_schema._set_cached_schema_context(
        "project-a", dynamic_schema.get_default_schema_context()
    )
    async with authority(schema_host, sessions) as value:
        original = await value.services.list_entity_types(user_id="owner", project_id="project-a")
        assert [item.name for item in original] == ["Person"]
        assert EntityTypeResponse.model_validate(original[0]).created_at is not None
        await value.db.rollback()
        await commands.replace(
            SCOPE, replacement(receipt, lambda doc: doc["entity_types"][0].update(name="Renamed"))
        )
        current = await value.services.list_entity_types(user_id="owner", project_id="project-a")
        assert [item.name for item in current] == ["Renamed"]
        assert current[0].created_at == original[0].created_at
        assert not value.db.new and not value.db.dirty and not value.db.deleted
        with pytest.raises(SchemaCommandRequiredV2):
            await value.services.create_entity_type(
                user_id="owner", project_id="project-a", data=EntityTypeCreate(name="Unexpected")
            )
    context = await dynamic_schema.get_project_schema_context("project-a")
    assert context["project_schema_document"]["revision"] == 2
    assert [item["entity_type_name"] for item in context["entity_types_context"]] == ["Renamed"]
    entities, _, mappings = await dynamic_schema.get_project_schema("project-a")
    assert list(entities) == ["Renamed"]
    assert mappings == {("Renamed", "Renamed"): ["KNOWS"]}
    async with sessions() as db:
        snapshot = await active_schema_snapshot(db, "project-a")
        assert snapshot.document.to_dict()["revision"] == 2


@pytest.mark.parametrize("change", ["membership", "user"])
async def test_read_reauthorizes_after_snapshot_await(
    live_schema_pg, schema_host, monkeypatch, change
):
    _, sessions = live_schema_pg
    await activated(sessions)
    async with authority(schema_host, sessions) as value:
        persistence_type = type(value.services.persistence)
        original = persistence_type.active_snapshot

        async def revoke(self, **kwargs):
            result = await original(self, **kwargs)
            async with sessions.begin() as revoke_db:
                if change == "membership":
                    await revoke_db.execute(
                        UserProject.__table__.delete().where(UserProject.user_id == "owner")
                    )
                else:
                    await revoke_db.execute(
                        update(User).where(User.id == "owner").values(is_active=False)
                    )
            return result

        monkeypatch.setattr(persistence_type, "active_snapshot", revoke)
        with pytest.raises(SchemaAccessDeniedV2):
            await value.services.list_entity_types(user_id="owner", project_id="project-a")


@pytest.mark.parametrize("retire", ["operation", "generation"])
async def test_read_rejects_retirement_during_snapshot_await(
    live_schema_pg, schema_host, monkeypatch, retire
):
    _, sessions = live_schema_pg
    await activated(sessions)
    async with authority(schema_host, sessions) as value:
        persistence_type = type(value.services.persistence)
        original = persistence_type.active_snapshot

        async def retire_after_read(self, **kwargs):
            result = await original(self, **kwargs)
            if retire == "operation":
                await value.operation.dispose()
            else:
                await value.operation.generation.dispose()
            return result

        monkeypatch.setattr(persistence_type, "active_snapshot", retire_after_read)
        with pytest.raises(RuntimeV2Error):
            await value.services.list_entity_types(user_id="owner", project_id="project-a")


async def test_activation_during_legacy_cache_read_returns_only_active_snapshot(
    live_schema_pg, monkeypatch
):
    _, sessions = live_schema_pg
    monkeypatch.setattr(dynamic_schema, "async_session_factory", sessions)
    original = dynamic_schema.active_schema_snapshot
    probes = 0

    async def activate_between_reads(session, project_id):
        nonlocal probes
        probes += 1
        result = await original(session, project_id)
        if probes == 1:
            await activated(sessions)
        return result

    monkeypatch.setattr(dynamic_schema, "active_schema_snapshot", activate_between_reads)
    dynamic_schema._set_cached_schema_context(
        "project-a", dynamic_schema.get_default_schema_context()
    )
    context = await dynamic_schema.get_project_schema_context("project-a")
    assert context["project_schema_document"]["revision"] == 1
    assert len(context["entity_types_context"]) == 1
    assert probes == 2


@pytest.mark.parametrize(
    "writer,args",
    [
        ("initialize_default_types_for_project", ()),
        ("_ensure_default_types_initialized", ()),
        ("save_discovered_entity_type", ("Person",)),
        ("save_discovered_edge_type", ("KNOWS",)),
        ("save_discovered_edge_type_map", ("Person", "Person", "KNOWS")),
        ("save_discovered_types_batch", ([], [], [])),
    ],
)
async def test_active_default_and_discovery_writers_reject_before_noop(
    live_schema_pg, monkeypatch, writer, args
):
    _, sessions = live_schema_pg
    await activated(sessions)
    monkeypatch.setattr(dynamic_schema, "async_session_factory", sessions)
    dynamic_schema._initialized_projects.add("project-a")
    with pytest.raises(SchemaCommandRequiredV2):
        await getattr(dynamic_schema, writer)("project-a", *args)


async def test_terminal_schema_reads_empty_without_restoring_defaults(
    live_schema_pg, schema_host, monkeypatch
):
    _, sessions = live_schema_pg
    commands, initial = await activated(sessions)

    def delete_document(value):
        value["deleted"] = True
        for collection, kind in (
            ("entity_types", "entity_type"),
            ("edge_types", "edge_type"),
            ("mappings", "mapping"),
        ):
            value["tombstones"].extend(
                {
                    "id": item["id"],
                    "kind": kind,
                    "deleted_revision": value["revision"],
                }
                for item in value[collection]
            )
            value[collection] = []

    await commands.replace(SCOPE, replacement(initial, delete_document))
    monkeypatch.setattr(dynamic_schema, "async_session_factory", sessions)
    async with authority(schema_host, sessions) as value:
        assert await value.services.list_entity_types(user_id="owner", project_id="project-a") == []
        assert await value.services.list_edge_types(user_id="owner", project_id="project-a") == []
        assert await value.services.list_edge_maps(user_id="owner", project_id="project-a") == []
    context = await dynamic_schema.get_project_schema_context("project-a")
    assert context["project_schema_document"]["deleted"] is True
    assert context["entity_types_context"] == []
    assert await dynamic_schema.get_project_schema("project-a") == ({}, {}, {})


async def test_http_returns_typed_write_failure_and_preserves_snapshot_corruption(
    live_schema_pg, schema_host, monkeypatch
):
    from httpx import ASGITransport, AsyncClient

    from src.infrastructure.adapters.primary.web.dependencies import get_current_user
    from src.infrastructure.adapters.primary.web.routers import schema
    from src.infrastructure.adapters.secondary.persistence.database import get_db
    from src.infrastructure.plugins.v2.schema_services import SqlSchemaPersistenceV2

    _, sessions = live_schema_pg
    await activated(sessions)
    app = FastAPI()
    app.include_router(schema.router)
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="owner")

    async def session_dependency():
        async with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = session_dependency
    async with (
        pin_generation_v2(schema_host),
        AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client,
    ):
        entities = await client.get("/api/v1/projects/project-a/schema/entities")
        assert entities.status_code == 200
        assert [item["name"] for item in entities.json()] == ["Person"]
        edges = await client.get("/api/v1/projects/project-a/schema/edges")
        assert edges.status_code == 200
        assert [item["name"] for item in edges.json()] == ["KNOWS"]
        maps = await client.get("/api/v1/projects/project-a/schema/mappings")
        assert maps.status_code == 200
        assert maps.json()[0]["source_type"] == "Person"
        denied = await client.get("/api/v1/projects/project-a/schema/entities?tenant_id=tenant-b")
        assert denied.status_code == 403
        write = await client.post(
            "/api/v1/projects/project-a/schema/entities", json={"name": "Unexpected"}
        )
        assert write.status_code == 409
        assert write.json()["detail"]["code"] == "project_schema_command_required"

        async def corrupt(self, **kwargs):
            raise ProjectSchemaError("project_schema_document_invalid")

        monkeypatch.setattr(SqlSchemaPersistenceV2, "active_snapshot", corrupt)
        with pytest.raises(ProjectSchemaError, match="project_schema_document_invalid"):
            await client.get("/api/v1/projects/project-a/schema/entities")
