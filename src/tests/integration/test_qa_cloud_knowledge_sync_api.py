"""Real auth and production CRUD through the isolated, compiled Cloud QA profile."""

from __future__ import annotations

import json
import os
import secrets
from dataclasses import replace
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient

from scripts.qa_cloud_knowledge_sync_api import create_qa_cloud_knowledge_sync_app
from scripts.qa_cloud_knowledge_sync_database import (
    QaCloudDatabase,
    cleanup_qa_database,
    initialize_qa_database,
    qa_engine,
)
from scripts.qa_cloud_knowledge_sync_graph import QA_NEO4J_URI
from scripts.qa_cloud_knowledge_sync_runtime import QaNoDispatchTaskManager
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.plugins.v2.background_task_services import (
    BACKGROUND_TASK_MANAGER_SERVICE_V2,
)

pytestmark = pytest.mark.skipif(
    os.getenv("KNOWLEDGE_SYNC_POSTGRES_TESTS") != "1",
    reason="Explicit opt-in required for the dedicated real PostgreSQL QA database",
)


@pytest.fixture
async def qa_database(tmp_path):
    metadata = tmp_path / "qa-cloud.json"
    email = "qa-cloud@example.test"
    password = secrets.token_urlsafe(24)
    state = await initialize_qa_database(
        metadata, neo4j_uri=QA_NEO4J_URI, email=email, password=password
    )
    try:
        yield metadata, state, email, password
    finally:
        await cleanup_qa_database(metadata, confirm_schema=state.schema)


async def login(client, email, password):
    result = await client.post("/api/v1/auth/token", data={"username": email, "password": password})
    assert result.status_code == 200
    token = result.json()["access_token"]
    client.headers["Authorization"] = "Bearer " + token
    return token


async def tenant_project(client):
    tenant = await client.post("/api/v1/tenants/", json={"name": "Isolated Cloud QA"})
    assert tenant.status_code == 201, tenant.text
    tenant_id = tenant.json()["id"]
    project = await client.post(
        "/api/v1/projects/", json={"name": "QA Knowledge", "tenant_id": tenant_id}
    )
    assert project.status_code == 201, project.text
    return tenant_id, project.json()["id"]


async def assert_discovery(client, tenant_id, project_id):
    actor = await client.get("/api/v1/auth/me")
    assert actor.status_code == 200 and actor.json()["user_id"]
    assert actor.json()["is_active"] is True
    tenants = await client.get("/api/v1/tenants/", params={"page_size": 100})
    assert tenants.status_code == 200 and tenants.json()["tenants"][0]["id"] == tenant_id
    projects = await client.get(
        "/api/v1/projects/", params={"tenant_id": tenant_id, "page_size": 100}
    )
    assert projects.status_code == 200 and projects.json()["projects"][0]["id"] == project_id
    detail = await client.get(f"/api/v1/projects/{project_id}", params={"tenant_id": tenant_id})
    assert detail.status_code == 200


async def assert_idle_runtime(app):
    async with await app.state.qa_host.acquire() as generation:
        runtime = generation.resolve(
            BACKGROUND_TASK_MANAGER_SERVICE_V2, ScopeV2(kind=ScopeKindV2.ROOT)
        )
        assert isinstance(runtime.manager, QaNoDispatchTaskManager)
        assert not runtime.manager.tasks and runtime.manager._cleanup_task is None
    async with app.state.qa_sessions() as db:
        tables = (
            (
                await db.execute(
                    sa.text(
                        "SELECT table_name FROM information_schema.tables WHERE table_schema=current_schema()"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert "knowledge_sync_enrollments" in tables
        assert not any(table.startswith("platform_plugin") for table in tables)
        assert (await db.execute(sa.text("SELECT status FROM task_logs"))).scalars().all() == [
            "PENDING",
            "PENDING",
        ]


async def test_real_auth_http_seed_enrollment_memory_crud_and_restart(qa_database):
    metadata, state, email, password = qa_database
    app = create_qa_cloud_knowledge_sync_app(metadata)
    assert get_current_user not in app.dependency_overrides
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://qa.test") as client,
    ):
        denied = await client.get("/api/v1/tenants/")
        assert denied.status_code in (401, 403)
        wrong = await client.post(
            "/api/v1/auth/token", data={"username": email, "password": "incorrect"}
        )
        assert wrong.status_code == 401
        token = await login(client, email, password)
        tenant_id, project_id = await tenant_project(client)
        await assert_discovery(client, tenant_id, project_id)
        data = {"project_id": project_id, "title": "QA Source", "content": "Version one"}
        blocked = await client.post("/api/v1/memories/", json=data)
        assert blocked.status_code == 409
        assert blocked.json()["detail"]["code"] == "qa_cloud_sync_enrollment_required"
        base = f"/api/v1/projects/{project_id}/knowledge-sync"
        status = await client.get(base + "/enrollment")
        assert status.status_code == 200, status.text
        observed = status.json()["generation"]
        assert observed["descriptor"]["profile_id"] == state.profile_id
        assert observed["descriptor"]["digest"] == state.profile_digest
        assert not status.json()["enabled"] and status.json()["can_enroll"]
        missing = await client.post(
            base + "/enrollment", json={"contract_version": "1.0.0", "operation": "enroll"}
        )
        assert missing.status_code == 428
        client.headers["X-Memstack-Knowledge-Sync-Generation"] = json.dumps(observed)
        enrolled = await client.post(
            base + "/enrollment", json={"contract_version": "1.0.0", "operation": "enroll"}
        )
        assert enrolled.status_code == 200 and enrolled.json()["enabled"]
        key = str(uuid4())
        create = await client.post(
            "/api/v1/memories/",
            json=data,
            headers={"Idempotency-Key": key, "X-Memory-Expected-Revision": "0"},
        )
        assert create.status_code == 201, create.text
        memory_id = create.json()["id"]
        assert create.json()["version"] == 1
        replay = await client.post(
            "/api/v1/memories/",
            json=data,
            headers={"Idempotency-Key": key, "X-Memory-Expected-Revision": "0"},
        )
        assert replay.status_code == 201 and replay.headers["Idempotency-Replayed"] == "true"
        update = await client.patch(
            f"/api/v1/memories/{memory_id}",
            params={"project_id": project_id},
            json={"version": 1, "content": "Version two"},
            headers={"Idempotency-Key": str(uuid4()), "X-Memory-Expected-Revision": "1"},
        )
        assert update.status_code == 200, update.text
        assert update.json()["version"] == 2
        listed = await client.get("/api/v1/memories/", params={"project_id": project_id})
        assert (
            listed.status_code == 200 and listed.json()["memories"][0]["content"] == "Version two"
        )
        changes = await client.get(base + "/changes", params={"after": 0, "limit": 10})
        assert changes.status_code == 200, changes.text
        await assert_idle_runtime(app)
    # Same schema, API key, enrolled target and revision remain available in a fresh host.
    restored = create_qa_cloud_knowledge_sync_app(metadata)
    async with (
        restored.router.lifespan_context(restored),
        AsyncClient(
            transport=ASGITransport(app=restored),
            base_url="http://qa.test",
            headers={"Authorization": "Bearer " + token},
        ) as client,
    ):
        result = await client.get(f"/api/v1/memories/{memory_id}")
        assert result.status_code == 200 and result.json()["version"] == 2
        status = await client.get(base + "/enrollment")
        assert status.status_code == 200 and status.json()["enabled"]


async def test_metadata_guards_cleanup_scope_and_no_public_fallback(
    qa_database, tmp_path, monkeypatch
):
    metadata, state, email, password = qa_database
    assert password not in metadata.read_text()
    assert metadata.stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError, match="exact schema"):
        await cleanup_qa_database(metadata, confirm_schema="public")
    for invalid in (
        replace(state, database="memstack"),
        replace(state, schema="public"),
        replace(state, neo4j_uri="bolt://127.0.0.1:7687"),
    ):
        with pytest.raises(ValueError):
            qa_engine(invalid)
    missing = replace(state, schema="qa_cloud_sync_" + uuid4().hex)
    missing_path = tmp_path / "missing.json"
    missing.save(missing_path)
    app = create_qa_cloud_knowledge_sync_app(missing_path)
    with pytest.raises(RuntimeError, match="exact QA schema is absent"):
        async with app.router.lifespan_context(app):
            pytest.fail("Missing schema cannot fall back to public")
    changed = replace(state, profile_digest="0" * 64)
    changed_path = tmp_path / "changed.json"
    changed.save(changed_path)
    with pytest.raises(ValueError, match="compiled Cloud profile"):
        create_qa_cloud_knowledge_sync_app(changed_path)
    assert QaCloudDatabase.load(metadata) == state

    # A name collision must never clean up a pre-existing run's schema.
    monkeypatch.setattr(
        "scripts.qa_cloud_knowledge_sync_database.uuid4",
        lambda: UUID(state.schema.removeprefix("qa_cloud_sync_")),
    )
    with pytest.raises(sa.exc.ProgrammingError):
        await initialize_qa_database(
            tmp_path / "collision.json", neo4j_uri=QA_NEO4J_URI, email=email, password=password
        )
    engine = qa_engine(state)
    try:
        async with engine.connect() as connection:
            assert await connection.scalar(sa.text("SELECT count(*) FROM users")) == 1
    finally:
        await engine.dispose()
