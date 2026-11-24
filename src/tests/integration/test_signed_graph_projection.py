"""Reprocess an enrolled memory over HTTP, kill a real projection guest, and resume its fixed release."""

import asyncio
import base64
import importlib.util
import os
import shutil
import subprocess
import time
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.operations.ops import CreateTableOp
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from neo4j import GraphDatabase
from sqlalchemy import text

import docker
from plugins.business.automation.workflow.tasks import TaskManager
from plugins.business.knowledge.backend import graph_workflows as workflow
from plugins.business.knowledge.backend.project_memory_operation import list_project_memories
from src.application.services import graph_projection_jobs as jobs
from src.configuration.config import get_settings
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.host.transport.project_package_routes import project_package_router
from src.infrastructure.adapters.primary.web.backend_store_authority_v2 import (
    backend_store_authority_dependency_v2,
)
from src.infrastructure.adapters.primary.web.dependencies import create_api_key
from src.infrastructure.adapters.primary.web.graph_application_authority_v2 import (
    graph_application_authority_dependency_v2,
)
from src.infrastructure.adapters.primary.web.memory_application_authority_v2 import (
    memory_application_authority_dependency_v2,
)
from src.infrastructure.adapters.primary.web.routers import episodes, memories, projects
from src.infrastructure.adapters.primary.web.startup.workflow_graph_authority import (
    bind_workflow_graph,
)
from src.infrastructure.adapters.primary.web.workflow_application_authority_v2 import (
    workflow_engine_authority_dependency_v2,
)
from src.infrastructure.adapters.secondary.persistence import database
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.knowledge_sync_models import (
    KnowledgeSyncEnrollmentModel as Enrollment,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    Base,
    Memory,
    TaskLog,
)
from src.infrastructure.adapters.secondary.persistence.sql_knowledge_graph_sync_repository import (
    SqlKnowledgeGraphSyncRepository,
)
from src.infrastructure.plugins.v2 import project_package_execution
from src.infrastructure.plugins.v2.oci_mcp_worker import OciWorkerSession
from src.tests.integration.test_knowledge_graph_sync_postgres import (
    QA_DATABASE,
    _extraction_result,
    pg_sync as _pg_sync,
)
from src.tests.integration.test_oci_mcp_worker_docker import disposable_worker_registry

pg_sync = _pg_sync
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("OCI_WORKER_DOCKER_TESTS") != "1"
        or os.getenv("KNOWLEDGE_SYNC_POSTGRES_TESTS") != "1",
        reason="requires isolated SQL, Neo4j and OCI worker",
    ),
]
ROOT = Path(__file__).resolve().parents[3]
PLUGIN = "memstack-knowledge"
SELECTION = {"plugin_id": PLUGIN, "tool": "project_graph"}


def module(path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


@pytest.fixture
def graph():
    # This recorder makes an intentionally non-idempotent graph write on every extraction.
    # Its extraction result is fixed to keep the regression independent of an LLM provider.
    docker_engine = docker.from_env()
    container = docker_engine.containers.run(
        "neo4j:5.26-community",
        detach=True,
        environment={
            "NEO4J_AUTH": "none",
            "NEO4J_server_memory_heap_initial__size": "128m",
            "NEO4J_server_memory_heap_max__size": "128m",
            "NEO4J_server_memory_pagecache_size": "32m",
        },
        ports={"7687/tcp": ("127.0.0.1", None)},
    )
    try:
        container.reload()
        port = container.attrs["NetworkSettings"]["Ports"]["7687/tcp"][0]["HostPort"]
        with GraphDatabase.driver("bolt://127.0.0.1:" + port, connection_timeout=1) as driver:
            for _ in range(120):
                try:
                    driver.verify_connectivity()
                    break
                except Exception:
                    time.sleep(0.25)
            else:
                pytest.fail("isolated Neo4j did not start")

            async def extract(**data):
                await asyncio.to_thread(
                    driver.execute_query,
                    "CREATE (:Extraction {project: $p, episode: $e})",
                    p=data["project_id"],
                    e=data["episode_uuid"],
                    database_="neo4j",
                )
                return _extraction_result()

            def count():
                return driver.execute_query(
                    "MATCH (x:Extraction) RETURN count(x) AS n", database_="neo4j"
                ).records[0]["n"]

            yield SimpleNamespace(process_episode=extract), count
    finally:
        container.remove(force=True, v=True)
        docker_engine.close()


@pytest.fixture
def releases(tmp_path):
    source = ROOT / "plugins/business/knowledge/workers/graph_projection"
    v2 = tmp_path / "revision"
    shutil.copytree(source, v2)
    guest = v2 / "worker.py"
    old = '"kind": n["kind"]'
    assert old in guest.read_text()
    guest.write_text(guest.read_text().replace(old, '"kind": n["kind"].upper()'))
    signer = Ed25519PrivateKey.generate()
    key = tmp_path / "signer.pub"
    key.write_bytes(
        signer.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    )
    from plugins.business.knowledge.build import release

    target = tmp_path / "compiled"
    subprocess.run(
        [
            "cargo",
            "build",
            "--locked",
            "--release",
            "--target",
            "wasm32-unknown-unknown",
            "--manifest-path",
            str(source.parent / "device_search/Cargo.toml"),
            "--target-dir",
            str(target),
        ],
        check=True,
    )
    wasm = target / "wasm32-unknown-unknown/release/memstack_device_knowledge.wasm"
    with disposable_worker_registry() as (publish, registry, _):
        archives = [
            base64.b64encode(release(publish(folder), wasm, version, signer)).decode()
            for folder, version in ((source, "1.0.0"), (v2, "1.1.0"))
        ]
        yield key, registry, archives


def migrate(c):
    assert c.scalar(text("select current_database()")) == QA_DATABASE
    ctx = MigrationContext.configure(c)
    ops = Operations(ctx)
    for name in (
        "api_keys",
        "user_sessions",
        "platform_plugin_packages",
        "project_plugin_releases",
        "project_plugin_installations",
    ):
        ops.invoke(CreateTableOp.from_table(Base.metadata.tables[name]))
    revision = module(ROOT / "alembic/versions/8de32c54a61f_pin_graph_projection_jobs.py")
    with Operations.context(ctx):
        revision.upgrade()
        revision.downgrade()
        revision.upgrade()


async def _configure_project(http, scope):
    selected = await http.put(
        f"/api/v1/projects/{scope.project_id}",
        json={"graph_config": {"sync_projection": SELECTION}},
    )
    assert selected.status_code == 200, selected.text
    assert selected.json()["graph_config"]["sync_projection"] == SELECTION
    plain = await http.post(
        "/api/v1/episodes/?background=true",
        json={
            "name": "Standalone",
            "content": "No Memory revision",
            "tenant_id": scope.tenant_id,
            "project_id": scope.project_id,
        },
    )
    assert plain.status_code == 501, plain.text


@pytest.fixture
async def pipeline(pg_sync, graph, releases, monkeypatch):
    sessions, scope = pg_sync
    keys, registry, archives = releases
    graph_service, count = graph
    settings = get_settings().model_copy(
        update={
            "plugin_worker_allowed_registries": (registry,),
            "plugin_marketplace_trusted_key_files": (keys,),
        }
    )
    monkeypatch.setattr(jobs, "get_settings", lambda: settings)
    monkeypatch.setattr(project_package_execution, "get_settings", lambda: settings)
    monkeypatch.setattr(workflow, "async_session_factory", sessions)
    monkeypatch.setattr(database, "async_session_factory", sessions)
    async with sessions.begin() as db:
        await (await db.connection()).run_sync(migrate)
        db.add(Enrollment(tenant_id=scope.tenant_id, project_id=scope.project_id, enabled=True))
        access_key, _ = await create_api_key(db, scope.actor_id, "projection HTTP test", [])
        for key in ("first", "second", "third", "fourth"):
            db.add(
                Memory(
                    id=key,
                    project_id=scope.project_id,
                    author_id=scope.actor_id,
                    title="Memory",
                    content="An enrolled source",
                    processing_status="COMPLETED",
                    status="ENABLED",
                    version=1,
                )
            )
    app = FastAPI()
    app.state.package_operations_v1 = {"app.knowledge.memories.read": list_project_memories}
    app.include_router(memories.router)
    app.include_router(projects.router)
    app.include_router(episodes.router)
    app.include_router(project_package_router)
    app.state.plugin_marketplace_trusted_public_keys_v2 = (keys.read_text(),)

    async def db_dep():
        async with sessions() as db:
            yield db

    async def memory_authority():
        async with sessions() as db:
            yield SimpleNamespace(
                db=db,
                services=SimpleNamespace(graph_service=graph_service, graph_store=graph_service),
            )

    binding = ScopeV2(
        kind=ScopeKindV2.PROJECT, tenant_id=scope.tenant_id, project_id=scope.project_id
    )

    @asynccontextmanager
    async def project_graph(payload, *, actor_id):
        assert actor_id == scope.actor_id
        assert payload["tenant_id"] == scope.tenant_id and payload["project_id"] == scope.project_id
        yield binding, graph_service

    engine = workflow.build_asyncio_workflow_engine_v2(manager=TaskManager())

    async def engine_authority():
        with bind_workflow_graph(
            SimpleNamespace(project_graph=project_graph), binding, scope.actor_id
        ):
            yield engine

    app.dependency_overrides[get_db] = db_dep

    async def backend_store():
        async with sessions() as db:
            view = SimpleNamespace(
                env_default_store_view=lambda _: {"name": "Fixture", "source": "env"}
            )
            yield SimpleNamespace(
                db=db, services=SimpleNamespace(graph_service=view, retrieval_service=view)
            )

    app.dependency_overrides[backend_store_authority_dependency_v2] = backend_store
    app.dependency_overrides[memory_application_authority_dependency_v2] = memory_authority
    app.dependency_overrides[graph_application_authority_dependency_v2] = memory_authority
    app.dependency_overrides[workflow_engine_authority_dependency_v2] = engine_authority
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        http.headers["Authorization"] = "Bearer " + access_key
        await _configure_project(http, scope)
        yield http, sessions, scope, archives, count, engine


async def _recover_admitted_projection(sessions, first):
    # The same lifespan recovery loop used after process restart claims the durable snapshot.
    async with jobs.recovery_loop(sessions), asyncio.timeout(15):
        while True:
            async with sessions() as db:
                if (await db.get(TaskLog, first)).result["projection_state"] == "complete":
                    break
            await asyncio.sleep(0.05)
    assert (await jobs.deliver(sessions, first))["projection_state"] == "complete"
    assert (await jobs.deliver(sessions, first))["projection_state"] == "complete"


async def verify_memory_page(http, base, binding, digest):
    page = await http.get(
        f"{base}/{PLUGIN}/ui",
        params={**binding, "page_id": "memories", "target": "web", "expected_digest": digest},
    )
    assert page.is_success, page.text
    assert set(page.json()["commands"]) == {
        "list-memories",
        "read-memory",
        "save-memory",
        "reindex-memory",
        "delete-memory",
        "index-status",
        "optimize-content",
    }
    read = await http.post(
        f"{base}/{PLUGIN}/commands",
        json={
            **binding,
            "command_id": "list-memories",
            "expected_digest": digest,
            "payload": {"search": "enrolled"},
        },
    )
    assert read.is_success, read.text
    assert {row["id"] for row in read.json()["items"]} == {"first", "second", "third", "fourth"}


async def test_episode_projection_runs_once_across_worker_loss_upgrade_and_withdrawal(
    pipeline, monkeypatch
):
    http, sessions, scope, archives, count, engine = pipeline
    binding = {"tenant_id": scope.tenant_id, "project_id": scope.project_id}
    base = "/api/v1/platform-plugins/v2/optional-business"

    async def install(archive):
        res = await http.post(
            base + "/install",
            json={
                **binding,
                "archive_base64": archive,
                "approved_permissions": sorted(
                    jobs.GRANT
                    | {
                        "ui.slot",
                        "app.knowledge.memories.read",
                        "app.knowledge.memories.write",
                        "app.knowledge.memories.delete",
                        "app.knowledge.memories.reindex",
                        "app.knowledge.memories.index_status",
                        "app.knowledge.memories.optimize",
                        "app.knowledge.entities.list",
                        "app.knowledge.entities.types",
                        "app.knowledge.entities.relationships",
                        "app.knowledge.graph.read",
                        "app.knowledge.graph.subgraph",
                    }
                ),
            },
        )
        assert res.status_code == 200, res.text
        enabled = await http.post(f"{base}/{PLUGIN}/enable", json=binding)
        assert enabled.status_code == 200, enabled.text
        await verify_memory_page(http, base, binding, res.json()["digest"])

    async def process(memory):
        res = await http.post(f"/api/v1/memories/{memory}/reprocess")
        assert res.status_code == 200, res.text
        result = await engine.get_workflow_result(f"episode-reprocess-{memory}", 20)
        assert not result["error"], result
        return res.json()["task_id"]

    original = OciWorkerSession.invoke

    async def killed(self, *args, **kwargs):
        await asyncio.to_thread(self._container.kill)
        return await original(self, *args, **kwargs)

    await install(archives[0])
    monkeypatch.setattr(OciWorkerSession, "invoke", killed)
    monkeypatch.setattr(jobs, "RETRY_DELAY", timedelta(0))
    first = await process("first")
    assert count() == 1
    async with sessions() as db:
        assert (await db.get(TaskLog, first)).result["projection_state"] == "pending"
        assert (
            await SqlKnowledgeGraphSyncRepository(db).graph_changes(scope, 0, 100)
        ).next_cursor == 0
    await install(archives[1])
    monkeypatch.setattr(OciWorkerSession, "invoke", original)
    await _recover_admitted_projection(sessions, first)
    assert count() == 1
    second = await process("second")
    assert count() == 2
    async with sessions() as db:
        page = await SqlKnowledgeGraphSyncRepository(db).graph_changes(scope, 0, 100)
        assert page.next_cursor == 2
        first_kind, second_kind = (
            c["version"]["content"]["entities"][0]["kind"] for c in page.to_dict()["changes"]
        )
        assert first_kind == "Person" and second_kind == "PERSON"
        assert (await db.get(TaskLog, second)).result["projection_state"] == "complete"
    rollback = await http.post(f"{base}/{PLUGIN}/rollback", json=binding)
    assert rollback.status_code == 200
    third = await process("third")
    async with sessions() as db:
        last = await SqlKnowledgeGraphSyncRepository(db).graph_changes(scope, 2, 100)
        assert last.to_dict()["changes"][0]["version"]["content"]["entities"][0]["kind"] == "Person"
        assert (await db.get(TaskLog, third)).result["projection_state"] == "complete"
    monkeypatch.setattr(OciWorkerSession, "invoke", killed)
    fourth = await process("fourth")
    withdrawn = await http.post(f"{base}/{PLUGIN}/disable", json=binding)
    assert withdrawn.status_code == 200
    assert (await jobs.deliver(sessions, fourth))["projection_state"] == "withdrawn"
    assert count() == 4


async def test_lost_extractor_guard_requires_reconciliation(pg_sync):
    from src.infrastructure.adapters.secondary.persistence.graph_projection_job_model import (
        GraphProjectionJob,
    )

    sessions, scope = pg_sync
    async with sessions.begin() as db:
        await (await db.connection()).run_sync(migrate)
        db.add(
            Memory(
                id="uncertain",
                project_id=scope.project_id,
                author_id=scope.actor_id,
                content="QA",
                title="QA",
                version=1,
                processing_status="PROCESSING",
                task_id="lost",
            )
        )
        db.add(
            TaskLog(
                id="lost",
                group_id=scope.project_id,
                task_type="add_episode",
                status="PROCESSING",
                payload={},
            )
        )
        await db.flush()
    async with sessions.begin() as owner:
        assert await jobs.extraction_guard(owner, "lost")
        async with sessions.begin() as db:
            db.add(
                GraphProjectionJob(
                    task_id="lost",
                    tenant_id=scope.tenant_id,
                    project_id=scope.project_id,
                    memory_id="uncertain",
                    source_revision=1,
                    actor_id=scope.actor_id,
                    author_id=scope.actor_id,
                    pin={},
                    tool="project_graph",
                    phase="extracting",
                )
            )
        await jobs.recover(sessions)
        async with sessions() as db:
            assert (await db.get(GraphProjectionJob, "lost")).phase == "extracting"
    await jobs.recover(sessions)
    async with sessions() as db:
        assert (await db.get(GraphProjectionJob, "lost")).phase == "review"
        assert (await db.get(TaskLog, "lost")).status == "FAILED"
