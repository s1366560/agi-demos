"""HTTP contract tests mount the graph sync foundation in an isolated app."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.knowledge_graph_sync_service import (
    KnowledgeGraphSyncApplication,
    KnowledgeGraphSyncService,
)
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.routers.knowledge_sync import (
    create_knowledge_graph_sync_router,
)
from src.infrastructure.adapters.secondary.persistence.models import Project, User
from src.infrastructure.adapters.secondary.persistence.sql_knowledge_graph_sync_repository import (
    SqlKnowledgeGraphSyncRepository,
)


@pytest.fixture
async def sync_client(
    db: AsyncSession, test_user: User, test_project_db: Project
) -> AsyncGenerator[AsyncClient, None]:
    async def application() -> KnowledgeGraphSyncApplication:
        return KnowledgeGraphSyncApplication(
            service=KnowledgeGraphSyncService(repository=SqlKnowledgeGraphSyncRepository(db)),
            commit=db.commit,
        )

    async def actor() -> User:
        return test_user

    app = FastAPI()
    app.dependency_overrides[get_current_user] = actor
    app.include_router(create_knowledge_graph_sync_router(application))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://sync.test") as client:
        yield client


def projection(name: str = "Alice") -> dict:
    return {
        "source_revision": 1,
        "change_sequence": 7,
        "audit_attempt": 1,
        "entities": [
            {"name": name, "kind": "person"},
            {"name": "Acme", "kind": "organization"},
        ],
        "relationships": [
            {
                "source_index": 0,
                "target_index": 1,
                "relation_type": "works_at",
                "fact": f"{name} works at Acme",
                "score": 0.9,
            }
        ],
    }


def body() -> dict:
    return {
        "change_id": str(uuid4()),
        "operation": "create",
        "object_id": "http-memory",
        "expected_revision": 0,
        "content": projection(),
    }


async def test_http_conflict_commits_and_replays_with_both_versions(
    sync_client: AsyncClient, test_project_db: Project, db: AsyncSession
) -> None:
    base = f"/projects/{test_project_db.id}/knowledge-sync/graph"
    original = body()
    assert (await sync_client.post(base + "/mutations", json=original)).status_code == 200
    edit = {**body(), "operation": "update", "expected_revision": 1}
    assert (await sync_client.post(base + "/mutations", json=edit)).status_code == 200
    conflict = await sync_client.post(
        base + "/mutations",
        json=edit | {"change_id": str(uuid4()), "content": projection("Offline")},
    )
    assert conflict.status_code == 409
    await db.rollback()
    conflict_id = conflict.json()["receipt"]["conflict_id"]
    stored = await sync_client.get(base + "/conflicts/" + conflict_id)
    assert stored.status_code == 200
    assert stored.json()["current"]["revision"] == 2
    assert stored.json()["proposed"]["content"]["entities"][0]["name"] == "Offline"
    resolved = await sync_client.post(
        base + "/conflicts/" + conflict_id + "/resolve",
        json={
            "change_id": str(uuid4()),
            "expected_current_revision": 2,
            "decision": "keep_current",
        },
    )
    assert resolved.status_code == 200 and resolved.json()["receipt"]["status"] == "resolved"
    assert (await sync_client.get(base + "/changes")).json()["next_cursor"] == 2
    replay = await sync_client.post(base + "/mutations", json=original)
    assert replay.json()["replayed"] and replay.json()["receipt"]["version"]["revision"] == 1


@pytest.mark.parametrize("field", ["actor_id", "tenant_id", "project_id", "author_id"])
async def test_http_rejects_scope_and_actor_overrides(
    sync_client: AsyncClient, test_project_db: Project, field: str
) -> None:
    response = await sync_client.post(
        f"/projects/{test_project_db.id}/knowledge-sync/graph/mutations",
        json=body() | {field: "attacker"},
    )
    assert response.status_code == 422


async def test_http_structural_errors_do_not_advance_cursor(
    sync_client: AsyncClient, test_project_db: Project
) -> None:
    base = f"/projects/{test_project_db.id}/knowledge-sync/graph"
    malformed = body() | {"expected_revision": 1}
    response = await sync_client.post(base + "/mutations", json=malformed)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "knowledge_sync_input_invalid"
    assert (await sync_client.get(base + "/changes")).json()["next_cursor"] == 0


async def test_http_dangling_relationship_index_rejected(
    sync_client: AsyncClient, test_project_db: Project
) -> None:
    base = f"/projects/{test_project_db.id}/knowledge-sync/graph"
    dangling = body()
    dangling["content"]["relationships"][0]["target_index"] = 5
    response = await sync_client.post(base + "/mutations", json=dangling)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "knowledge_sync_input_invalid"
