"""Project-bound graph recovery after publication, restart and revoked scope."""

import asyncio
from collections.abc import Callable
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services import memory_update_runtime
from src.application.services.memory_update_dispatch import (
    MemoryUpdateDispatcher,
    install_memory_update_dispatcher,
)
from src.application.services.memory_update_jobs import MemoryUpdateJobError
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.primary.web.startup.memory_update_recovery import (
    scoped_memory_update_stages,
)
from src.infrastructure.adapters.secondary.persistence.models import Project, TaskLog
from src.infrastructure.plugins.v2.graph_runtime import GraphRuntimeServiceV2
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.tests.unit.application.services.test_memory_update_jobs import (
    _seed,
    _stage_update,
    factory as _factory,
)

factory = _factory
pytestmark = pytest.mark.unit


async def test_recovery_holds_one_project_lease_through_extraction_and_indexing(
    factory: Callable[[], AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _seed(factory)
    await _stage_update(factory, content="after")
    scope = ScopeV2(kind=ScopeKindV2.PROJECT, tenant_id="tenant-1", project_id="project-1")
    graph = SimpleNamespace(embedder=object())
    generation = Mock()
    generation.resolve.return_value = GraphRuntimeServiceV2(graph_service=graph)
    release = AsyncMock()
    runtime = Mock()
    runtime.acquire = AsyncMock(
        return_value=SimpleNamespace(
            scope=scope,
            claim=Mock(),
            lease=SimpleNamespace(generation=generation, release=release),
        )
    )
    observed = []

    async def extract(payload, graph_service):
        release.assert_not_awaited()
        observed.append(("extract", graph_service, payload["project_id"]))

    async def index(payload, session_factory, embedding_service):
        release.assert_not_awaited()
        assert session_factory is factory
        observed.append(("index", embedding_service, payload["project_id"]))

    monkeypatch.setattr(memory_update_runtime, "extract_with_graph", extract)
    monkeypatch.setattr(memory_update_runtime, "index_with_session", index)
    dispatcher = MemoryUpdateDispatcher(
        factory,
        acquire_stages=scoped_memory_update_stages(factory, runtime),
    )
    assert await dispatcher.resume() == ["completed"]
    runtime.acquire.assert_awaited_once_with(scope)
    release.assert_awaited_once()
    assert observed == [("extract", graph, "project-1"), ("index", graph.embedder, "project-1")]


async def test_unavailable_project_generation_defers_recovery_without_consuming_retry(
    factory: Callable[[], AsyncSession],
) -> None:
    await _seed(factory)
    task_id = await _stage_update(factory, content="after")
    runtime = Mock()
    runtime.acquire = AsyncMock(side_effect=RuntimeV2Error("scope_not_admitted", "unavailable"))
    runtime.prepare_current = AsyncMock(
        side_effect=RuntimeV2Error("scope_not_admitted", "unavailable")
    )
    dispatcher = MemoryUpdateDispatcher(
        factory,
        acquire_stages=scoped_memory_update_stages(factory, runtime),
    )
    assert await dispatcher.resume() == ["not_ready"]
    async with factory() as session:
        row = await session.get(TaskLog, task_id)
        assert row.status == "PENDING"
        assert row.retry_count == 0
        assert row.worker_id is None


async def test_switching_project_generation_never_redirects_an_open_job(factory, monkeypatch):
    await _seed(factory)
    async with factory() as session:
        session.add(Project(id="project-2", tenant_id="tenant-1", name="Two", owner_id="user-1"))
        await session.commit()
    resources = {}
    releases = []

    async def reserve(scope):
        graph = resources[scope.project_id]
        generation = Mock()
        generation.resolve.return_value = GraphRuntimeServiceV2(graph_service=graph)
        release = AsyncMock()
        releases.append(release)
        return SimpleNamespace(
            scope=scope, lease=SimpleNamespace(generation=generation, release=release), claim=Mock()
        )

    runtime = SimpleNamespace(acquire=reserve)
    provider = scoped_memory_update_stages(factory, runtime)
    first, replacement, separate = [SimpleNamespace(embedder=object()) for _ in range(3)]
    resources.update({"project-1": first, "project-2": separate})
    extract = AsyncMock()
    index = AsyncMock()
    monkeypatch.setattr(memory_update_runtime, "extract_with_graph", extract)
    monkeypatch.setattr(memory_update_runtime, "index_with_session", index)
    payload = {"project_id": "project-1", "tenant_id": "tenant-1", "user_id": "user-1"}
    async with provider(payload) as (run_extract, run_index):
        await run_extract()
        resources["project-1"] = replacement
        async with provider({**payload, "project_id": "project-2"}) as (other_extract, _):
            await other_extract()
        releases[0].assert_not_awaited()
        await run_index()
    assert [c.kwargs["graph_service"] for c in extract.await_args_list] == [first, separate]
    assert index.await_args.kwargs["embedding_service"] is first.embedder
    for release in releases:
        release.assert_awaited_once()

    with pytest.raises(MemoryUpdateJobError, match="scope_mismatch"):
        async with provider({**payload, "tenant_id": "wrong-tenant"}):
            pytest.fail("foreign project job should not start")
    assert len(releases) == 2


async def test_production_startup_recovers_without_a_chat_turn(factory, monkeypatch):
    from src.infrastructure.adapters.primary.web import main

    await _seed(factory)
    task = await _stage_update(factory, content="restored")
    runtime = Mock()
    scope = ScopeV2(kind=ScopeKindV2.PROJECT, tenant_id="tenant-1", project_id="project-1")
    lease = Mock()
    lease.release = AsyncMock()
    lease.generation.resolve.return_value = GraphRuntimeServiceV2(
        graph_service=SimpleNamespace(embedder=None),
    )
    runtime.acquire = AsyncMock(
        side_effect=[
            RuntimeV2Error("scope_recovery_unavailable", "first access"),
            SimpleNamespace(scope=scope, lease=lease, claim=Mock()),
        ]
    )
    runtime.prepare_current = AsyncMock(
        return_value=SimpleNamespace(publication=SimpleNamespace(accepted=True))
    )
    monkeypatch.setattr(main, "async_session_factory", factory)
    apply = AsyncMock()
    monkeypatch.setattr(memory_update_runtime, "extract_with_graph", apply)
    monkeypatch.setattr(memory_update_runtime, "index_with_session", AsyncMock())

    app = FastAPI()
    app.state.scoped_profile_runtime_v2 = runtime
    main._install_memory_update_recovery(app)
    try:
        async with asyncio.timeout(3):
            while not apply.await_count:
                await asyncio.sleep(0.01)
            while True:
                async with factory() as session:
                    if (await session.get(TaskLog, task)).status == "COMPLETED":
                        break
                await asyncio.sleep(0.01)
        runtime.prepare_current.assert_awaited_once()
        assert runtime.prepare_current.await_args.kwargs["actor_id"] == "user-1"
        lease.release.assert_awaited_once()
    finally:
        await app.state.memory_update_dispatcher.aclose()
        install_memory_update_dispatcher(None)


async def test_pending_jobs_do_not_starve_a_later_project(factory):
    from contextlib import asynccontextmanager
    from datetime import UTC, datetime, timedelta

    from src.application.services.memory_update_jobs import MEMORY_UPDATE_JOB, GraphNotReady

    await _seed(factory)
    async with factory() as session, session.begin():
        session.add_all(
            TaskLog(
                id=f"unavailable-{i:02}",
                task_type=MEMORY_UPDATE_JOB,
                group_id="unavailable",
                status="PENDING",
                created_at=datetime.now(UTC) - timedelta(hours=1),
                payload={"project_id": "unavailable"},
            )
            for i in range(23)
        )
    await _stage_update(factory, content="ready")

    @asynccontextmanager
    async def acquire(payload):
        if payload["project_id"] == "unavailable":
            raise GraphNotReady
        yield AsyncMock(), AsyncMock()

    outcomes = await MemoryUpdateDispatcher(factory, acquire_stages=acquire).resume()
    assert outcomes[:-1] == ["not_ready"] * 23
    assert outcomes[-1] == "completed"
