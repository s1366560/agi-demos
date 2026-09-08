"""Actual V2 publication, request operations and isolated PostgreSQL enrollment."""

from __future__ import annotations

import os
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select, update

from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.startup.generation_http_v2 import (
    mount_generation_http_dispatcher_v2,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.knowledge_sync_models import (
    KnowledgeSyncChangeModel as Change,
    KnowledgeSyncEnrollmentModel as Enrollment,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    Memory,
    Project,
    Tenant,
    User,
    UserProject,
    UserTenant,
)
from src.infrastructure.plugins.v2.boundary import PluginGenerationMiddlewareV2
from src.infrastructure.plugins.v2.builtin_cloud_knowledge_sync_http_routes import (
    CLOUD_KNOWLEDGE_SYNC_HTTP_ENTRY_V2,
)
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.http_routes import (
    RouteTableRegistryV2,
    RouteTableV2,
    install_route_definitions_v2,
)
from src.infrastructure.plugins.v2.route_effects import ROUTE_TABLE_BUILDER_SERVICE_V2
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2
from src.tests.integration.test_knowledge_sync_postgres import pg_sync as _pg_sync

pg_sync = _pg_sync
pytestmark = pytest.mark.skipif(
    os.getenv("KNOWLEDGE_SYNC_POSTGRES_TESTS") != "1",
    reason="Requires the existing dedicated PostgreSQL QA database opt-in",
)
BASE = "/api/v1/projects/project/knowledge-sync"
ENROLL = {"contract_version": "1.0.0", "operation": "enroll"}


@pytest.fixture
async def cloud_sync_http(pg_sync, request):
    sessions, scope = pg_sync
    enabled = getattr(request, "param", True)
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())

    def qualify(document):
        return replace(
            document,
            entries=tuple(
                replace(entry, enabled=enabled)
                if entry.entry_id.startswith("builtin-cloud-knowledge-sync-")
                else entry
                for entry in document.entries
            ),
        )

    publication = await host.bootstrap(
        profile_path="config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=("config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=81,
        version=81,
        profile_projector=qualify,
    )
    assert publication.accepted
    async with await host.acquire() as generation:
        from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2

        builder = generation.resolve(ROUTE_TABLE_BUILDER_SERVICE_V2, ScopeV2(kind=ScopeKindV2.ROOT))
        definitions = tuple(
            item
            for item in builder.definitions
            if item.owner_entry_id == CLOUD_KNOWLEDGE_SYNC_HTTP_ENTRY_V2
        )
    assert len(definitions) == (6 if enabled else 0)
    async with sessions() as db:
        actor = await db.get(User, scope.actor_id)

    async def database():
        async with sessions() as db:
            yield db

    private = FastAPI()
    private.dependency_overrides[get_db] = database
    private.dependency_overrides[get_current_user] = lambda: actor
    install_route_definitions_v2(private, definitions)
    registry = RouteTableRegistryV2()
    await registry.publish(
        host.current_distribution.descriptor,
        RouteTableV2.from_fastapi_graph(private, definitions=definitions),
    )
    outer = FastAPI()
    outer.state.platform_plugin_route_registry_v2 = registry
    mount_generation_http_dispatcher_v2(outer)
    outer.add_middleware(PluginGenerationMiddlewareV2, host_provider=lambda _scope: host)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=outer), base_url="http://sync.test"
        ) as client:
            yield SimpleNamespace(client=client, sessions=sessions, scope=scope, host=host)
    finally:
        await host.close()


def mutation(**changes):
    return {
        "change_id": str(uuid4()),
        "operation": "create",
        "memory_id": "memory",
        "expected_revision": 0,
        "content": {"title": "Source", "content": "Body"},
        **changes,
    }


async def test_unenrolled_project_has_status_but_no_sync_reads_or_writes(cloud_sync_http):
    f = cloud_sync_http
    status = await f.client.get(BASE + "/enrollment")
    assert status.status_code == 200, status.text
    assert status.json() == {
        **f.scope.__dict__,
        "contract_version": "1.0.0",
        "enabled": False,
        "can_enroll": True,
        "bootstrap_count": 0,
        "next_cursor": 0,
        "replayed": False,
    }
    for result in (
        await f.client.get(BASE + "/changes"),
        await f.client.post(BASE + "/mutations", json=mutation()),
    ):
        assert result.status_code == 503, result.text
        assert result.json()["detail"]["code"] == "knowledge_sync_not_enrolled"
    async with f.sessions() as db:
        assert (await db.scalars(select(Memory))).all() == []
        assert (await db.scalars(select(Change))).all() == []


async def test_explicit_enrollment_bootstraps_existing_content_and_replays(cloud_sync_http):
    f = cloud_sync_http
    async with f.sessions() as db:
        db.add(
            Memory(id="seed", project_id="project", author_id="actor", title="Seed", content="Old")
        )
        await db.commit()
    first = await f.client.post(BASE + "/enrollment", json=ENROLL)
    assert first.status_code == 200, first.text
    assert first.json()["bootstrap_count"] == 1
    assert first.json()["enabled"] is True and first.json()["replayed"] is False
    replay = await f.client.post(BASE + "/enrollment", json=ENROLL)
    assert replay.status_code == 200 and replay.json()["replayed"] is True
    page = await f.client.get(BASE + "/changes")
    assert page.status_code == 200, page.text
    assert page.json()["next_cursor"] == 1
    async with f.sessions() as db:
        assert len((await db.scalars(select(Change))).all()) == 1
        assert (await db.get(Memory, "seed")).content == "Old"


@pytest.mark.parametrize(
    "extra",
    [
        {},
        {"actor_id": "other"},
        {"project_id": "other"},
        {"tenant_id": "other"},
        {"operation": "disable"},
        {"contract_version": "2.0.0"},
    ],
)
async def test_enrollment_requires_exact_explicit_command(cloud_sync_http, extra):
    body = extra if not extra else ENROLL | extra
    response = await cloud_sync_http.client.post(BASE + "/enrollment", json=body)
    assert response.status_code == 422
    async with cloud_sync_http.sessions() as db:
        assert not (await db.get(Enrollment, "project")).enabled


async def test_sync_conflict_resolution_and_replay_survive_request_boundaries(cloud_sync_http):
    f = cloud_sync_http
    assert (await f.client.post(BASE + "/enrollment", json=ENROLL)).status_code == 200
    original = mutation()
    assert (await f.client.post(BASE + "/mutations", json=original)).status_code == 200
    update_body = mutation(operation="update", expected_revision=1)
    assert (await f.client.post(BASE + "/mutations", json=update_body)).status_code == 200
    proposed = mutation(
        operation="update", expected_revision=1, content={"title": "Offline", "content": "Kept"}
    )
    conflict = await f.client.post(BASE + "/mutations", json=proposed)
    assert conflict.status_code == 409, conflict.text
    conflict_id = conflict.json()["receipt"]["conflict_id"]
    details = await f.client.get(BASE + "/conflicts/" + conflict_id)
    assert details.status_code == 200, details.text
    assert details.json()["current"]["revision"] == 2
    assert details.json()["proposed"]["content"]["title"] == "Offline"
    resolved = await f.client.post(
        BASE + "/conflicts/" + conflict_id + "/resolve",
        json={
            "change_id": str(uuid4()),
            "expected_current_revision": 2,
            "decision": "keep_current",
        },
    )
    assert resolved.status_code == 200, resolved.text
    replay = await f.client.post(BASE + "/mutations", json=original)
    assert replay.status_code == 200 and replay.json()["replayed"]
    assert replay.json()["receipt"]["version"]["revision"] == 1


async def test_role_loss_blocks_enrollment_and_member_revocation_blocks_receipt_replay(
    cloud_sync_http,
):
    f = cloud_sync_http
    assert (await f.client.post(BASE + "/enrollment", json=ENROLL)).status_code == 200
    original = mutation()
    assert (await f.client.post(BASE + "/mutations", json=original)).status_code == 200
    async with f.sessions() as db:
        await db.execute(update(UserProject).values(role="viewer"))
        await db.commit()
    status = await f.client.get(BASE + "/enrollment")
    assert status.status_code == 200 and status.json()["can_enroll"] is False
    assert (await f.client.post(BASE + "/enrollment", json=ENROLL)).status_code == 403
    assert (
        await f.client.post(BASE + "/mutations", json=mutation(memory_id="other"))
    ).status_code == 403
    async with f.sessions() as db:
        await db.delete((await db.scalars(select(UserProject))).one())
        await db.commit()
    assert (await f.client.post(BASE + "/mutations", json=original)).status_code == 403
    assert (await f.client.get(BASE + "/changes")).status_code == 403


@pytest.mark.parametrize("cloud_sync_http", [False], indirect=True)
async def test_default_closed_generation_publishes_no_enrollment_or_sync_routes(cloud_sync_http):
    f = cloud_sync_http
    assert (await f.client.get(BASE + "/enrollment")).status_code == 404
    assert (await f.client.post(BASE + "/enrollment", json=ENROLL)).status_code == 404
    assert (await f.client.get(BASE + "/changes")).status_code == 404
    async with f.sessions() as db:
        assert not (await db.get(Enrollment, "project")).enabled


@pytest.mark.parametrize("revocation", ["inactive_actor", "tenant_membership"])
async def test_current_database_authority_rejects_revoked_actor_before_enrollment(
    cloud_sync_http, revocation
):
    f = cloud_sync_http
    async with f.sessions() as db:
        if revocation == "inactive_actor":
            await db.execute(
                update(User).where(User.id == f.scope.actor_id).values(is_active=False)
            )
        else:
            await db.execute(delete(UserTenant).where(UserTenant.user_id == f.scope.actor_id))
        await db.commit()
    # The auth fixture retains its earlier User object, so these responses prove
    # authorization is rechecked in PostgreSQL rather than trusting cached identity.
    for response in (
        await f.client.get(BASE + "/enrollment"),
        await f.client.post(BASE + "/enrollment", json=ENROLL),
        await f.client.get(BASE + "/changes"),
    ):
        assert response.status_code == 403, response.text
        assert response.json()["detail"]["code"] == "knowledge_sync_forbidden"
    async with f.sessions() as db:
        assert not (await db.get(Enrollment, f.scope.project_id)).enabled
        assert (await db.scalars(select(Change))).all() == []


async def test_foreign_tenant_project_cannot_be_discovered_or_enrolled(cloud_sync_http):
    f = cloud_sync_http
    async with f.sessions() as db:
        db.add(Tenant(id="foreign", name="Other", slug="other", owner_id=f.scope.actor_id))
        await db.flush()
        db.add(
            Project(
                id="foreign-project", name="Other", tenant_id="foreign", owner_id=f.scope.actor_id
            )
        )
        await db.commit()
    foreign_base = "/api/v1/projects/foreign-project/knowledge-sync"
    for response in (
        await f.client.get(foreign_base + "/enrollment"),
        await f.client.post(foreign_base + "/enrollment", json=ENROLL),
        await f.client.get(foreign_base + "/changes"),
        await f.client.post(foreign_base + "/mutations", json=mutation()),
    ):
        assert response.status_code == 403, response.text
    async with f.sessions() as db:
        assert not (await db.get(Enrollment, "foreign-project")).enabled
        assert (await db.scalars(select(Memory))).all() == []
        assert (await db.scalars(select(Change))).all() == []
