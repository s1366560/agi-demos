"""Unit tests for local workflow startup handlers."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import src.infrastructure.adapters.primary.web.startup.workflow as workflow_module
from src.domain.model.knowledge_sync.contracts import KnowledgeSyncError
from src.infrastructure.adapters.primary.web.startup.workflow import (
    _run_episode_processing_workflow,
    _run_incremental_refresh_workflow,
    _run_rebuild_communities_workflow,
    build_asyncio_workflow_engine_v2,
)
from src.infrastructure.adapters.secondary.background_tasks import TaskManager
from src.infrastructure.adapters.secondary.persistence.knowledge_sync_models import (
    KnowledgeSyncEnrollmentModel,
)
from src.infrastructure.adapters.secondary.persistence.models import Memory, Project, TaskLog, User
from src.infrastructure.plugins.v2.boundary import (
    clear_process_generation_host_v2,
    install_process_generation_host_v2,
)
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

_ROOT = Path(__file__).resolve().parents[8]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


@pytest.fixture(autouse=True)
async def legacy_project_fence(test_db, test_project_db):
    test_db.add(
        KnowledgeSyncEnrollmentModel(
            project_id=test_project_db.id,
            tenant_id=test_project_db.tenant_id,
            enabled=False,
        )
    )
    await test_db.commit()


def _task(task_id: str, project_id: str, payload: dict[str, object]) -> TaskLog:
    return TaskLog(
        id=task_id,
        group_id=project_id,
        task_type="add_episode",
        status="PENDING",
        payload=payload,
        entity_type="episode",
        created_at=datetime.now(UTC),
    )


def _memory(memory_id: str, project: Project, user: User) -> Memory:
    return Memory(
        id=memory_id,
        project_id=project.id,
        title="Workflow memory",
        content="Alice from OpenAI met Bob at Microsoft.",
        content_type="text",
        tags=[],
        entities=[],
        relationships=[],
        version=1,
        author_id=user.id,
        collaborators=[],
        is_public=False,
        status="ENABLED",
        processing_status="PENDING",
        meta={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


class FakeNeo4jClient:
    def __init__(self, records_by_call: list[list[dict[str, object]]]) -> None:
        self.records_by_call = records_by_call
        self.calls: list[dict[str, object]] = []

    async def execute_query(self, query: str, **params: object) -> SimpleNamespace:
        self.calls.append({"query": query, "params": params})
        return SimpleNamespace(records=self.records_by_call.pop(0))


@pytest.mark.unit
@pytest.mark.asyncio
async def test_build_asyncio_workflow_engine_registers_task_handlers() -> None:
    engine = build_asyncio_workflow_engine_v2(manager=TaskManager())

    assert engine is not None
    assert "episode_processing" in engine._workflow_handlers
    assert "incremental_refresh" in engine._workflow_handlers
    assert "rebuild_communities" in engine._workflow_handlers


@pytest.mark.unit
@pytest.mark.asyncio
async def test_workflow_handler_holds_an_independent_generation_lease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handler_started = asyncio.Event()
    finish_handler = asyncio.Event()
    observed_graph_services: list[object] = []

    class LeaseTrackedGraphService:
        def __init__(self) -> None:
            self.close_calls = 0

        async def close(self) -> None:
            self.close_calls += 1

    graph_services = [LeaseTrackedGraphService(), LeaseTrackedGraphService()]
    factory_calls = 0

    async def graph_factory() -> object:
        nonlocal factory_calls
        graph_service = graph_services[factory_calls]
        factory_calls += 1
        return graph_service

    async def episode_handler(_payload: dict[str, object], graph_service: object) -> None:
        observed_graph_services.append(graph_service)
        handler_started.set()
        await finish_handler.wait()

    monkeypatch.setattr(workflow_module, "_run_episode_processing_workflow", episode_handler)
    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(graph_runtime_factory=graph_factory)
    )
    first = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=1,
        version=1,
        nonce="workflow-generation-1",
    )
    assert first.accepted is True
    install_process_generation_host_v2(host)

    try:
        engine = build_asyncio_workflow_engine_v2(manager=TaskManager())
        assert engine is not None
        task = asyncio.create_task(engine._workflow_handlers["episode_processing"]({}))
        await handler_started.wait()

        second = await host.bootstrap(
            profile_path=_PROFILE_PATH,
            manifest_paths=(_MANIFEST_PATH,),
            generation=2,
            version=2,
            nonce="workflow-generation-2",
        )

        assert second.accepted is True
        assert observed_graph_services == [graph_services[0]]
        assert graph_services[0].close_calls == 0

        finish_handler.set()
        await task

        assert graph_services[0].close_calls == 1
        assert graph_services[1].close_calls == 0
    finally:
        finish_handler.set()
        clear_process_generation_host_v2(host)
        await host.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_episode_processing_workflow_updates_task_and_memory(
    test_db: AsyncSession,
    test_project_db: Project,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_factory = async_sessionmaker(
        test_db.bind,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    monkeypatch.setattr(workflow_module, "async_session_factory", session_factory)

    memory_id = str(uuid4())
    task_id = str(uuid4())
    memory = _memory(memory_id, test_project_db, test_user)
    memory.task_id = task_id
    payload = {
        "task_id": task_id,
        "memory_id": memory_id,
        "source_revision": 1,
        "uuid": memory_id,
        "content": memory.content,
        "project_id": test_project_db.id,
        "tenant_id": test_project_db.tenant_id,
        "user_id": test_user.id,
    }
    task = _task(task_id, test_project_db.id, payload)
    test_db.add_all([memory, task])
    await test_db.commit()

    graph_service = SimpleNamespace(
        process_episode=AsyncMock(
            return_value=SimpleNamespace(
                nodes=[object(), object()],
                edges=[object()],
                episodic_edges=[object(), object()],
            )
        )
    )

    result = await _run_episode_processing_workflow(payload, graph_service)

    assert result == {
        "episode_uuid": memory_id,
        "entities": 2,
        "relationships": 1,
        "mentions": 2,
    }
    graph_service.process_episode.assert_awaited_once_with(
        episode_uuid=memory_id,
        content=memory.content,
        project_id=test_project_db.id,
        tenant_id=test_project_db.tenant_id,
        user_id=test_user.id,
        excluded_entity_types=None,
    )
    await test_db.refresh(task)
    await test_db.refresh(memory)
    assert task.status == "COMPLETED"
    assert task.progress == 100
    assert task.message == "Graph processing complete"
    assert task.result == result
    assert memory.processing_status == "COMPLETED"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_episode_processing_workflow_marks_failures(
    test_db: AsyncSession,
    test_project_db: Project,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_factory = async_sessionmaker(
        test_db.bind,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    monkeypatch.setattr(workflow_module, "async_session_factory", session_factory)

    memory_id = str(uuid4())
    task_id = str(uuid4())
    memory = _memory(memory_id, test_project_db, test_user)
    memory.task_id = task_id
    payload = {
        "task_id": task_id,
        "memory_id": memory_id,
        "source_revision": 1,
        "uuid": memory_id,
        "content": memory.content,
        "project_id": test_project_db.id,
        "tenant_id": test_project_db.tenant_id,
        "user_id": test_user.id,
    }
    task = _task(task_id, test_project_db.id, payload)
    test_db.add_all([memory, task])
    await test_db.commit()

    graph_service = SimpleNamespace(process_episode=AsyncMock(side_effect=RuntimeError("boom")))

    with pytest.raises(RuntimeError, match="boom"):
        await _run_episode_processing_workflow(payload, graph_service)

    await test_db.refresh(task)
    await test_db.refresh(memory)
    assert task.status == "FAILED"
    assert task.progress == 100
    assert task.message == "Graph processing failed"
    assert task.error_message == "boom"
    assert memory.processing_status == "FAILED"


@pytest.mark.unit
@pytest.mark.parametrize("source_revision", [None, True, "1", 0, 2])
async def test_episode_job_without_matching_source_keeps_memory_state(
    test_db, test_project_db, test_user, monkeypatch, source_revision
):
    monkeypatch.setattr(
        workflow_module,
        "async_session_factory",
        async_sessionmaker(test_db.bind, class_=AsyncSession, expire_on_commit=False),
    )
    memory_id, task_id = str(uuid4()), str(uuid4())
    memory = _memory(memory_id, test_project_db, test_user)
    memory.task_id = task_id
    payload = {
        "task_id": task_id,
        "memory_id": memory_id,
        "uuid": memory_id,
        "project_id": test_project_db.id,
        "content": memory.content,
    }
    if source_revision is not None:
        payload["source_revision"] = source_revision
    task = _task(task_id, test_project_db.id, payload)
    test_db.add_all([memory, task])
    await test_db.commit()

    graph = SimpleNamespace(process_episode=AsyncMock(return_value=SimpleNamespace()))
    with pytest.raises(KnowledgeSyncError):
        await _run_episode_processing_workflow(payload, graph)
    graph.process_episode.assert_not_awaited()

    await test_db.refresh(task)
    await test_db.refresh(memory)
    assert task.status == "FAILED"
    assert memory.processing_status == "PENDING"


@pytest.mark.unit
async def test_replaced_task_failure_does_not_overwrite_current_task_success(
    test_db, test_project_db, test_user, monkeypatch
):
    monkeypatch.setattr(
        workflow_module,
        "async_session_factory",
        async_sessionmaker(test_db.bind, class_=AsyncSession, expire_on_commit=False),
    )
    memory_id, task_id = str(uuid4()), str(uuid4())
    memory = _memory(memory_id, test_project_db, test_user)
    memory.task_id = "replacement-task"
    memory.processing_status = "COMPLETED"
    payload = {
        "task_id": task_id,
        "memory_id": memory_id,
        "uuid": memory_id,
        "project_id": test_project_db.id,
        "content": memory.content,
        "source_revision": 1,
    }
    task = _task(task_id, test_project_db.id, payload)
    test_db.add_all([memory, task])
    await test_db.commit()

    with pytest.raises(KnowledgeSyncError, match="knowledge_sync_write_conflict"):
        await _run_episode_processing_workflow(
            payload,
            SimpleNamespace(process_episode=AsyncMock(side_effect=RuntimeError("late failure"))),
        )

    await test_db.refresh(task)
    await test_db.refresh(memory)
    assert task.status == "FAILED"
    assert memory.processing_status == "COMPLETED"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_episode_processing_workflow_fails_fast_for_missing_project(
    test_db: AsyncSession,
    test_project_db: Project,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_factory = async_sessionmaker(
        test_db.bind,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    monkeypatch.setattr(workflow_module, "async_session_factory", session_factory)

    missing_project_id = str(uuid4())
    memory_id = str(uuid4())
    task_id = str(uuid4())
    memory = _memory(memory_id, test_project_db, test_user)
    memory.task_id = task_id
    payload = {
        "task_id": task_id,
        "memory_id": memory_id,
        "source_revision": 1,
        "uuid": memory_id,
        "content": memory.content,
        "project_id": missing_project_id,
        "tenant_id": test_project_db.tenant_id,
        "user_id": test_user.id,
    }
    task = _task(task_id, missing_project_id, payload)
    test_db.add_all([memory, task])
    await test_db.commit()

    graph_service = SimpleNamespace(process_episode=AsyncMock())

    with pytest.raises(KnowledgeSyncError, match="knowledge_sync_write_conflict"):
        await _run_episode_processing_workflow(payload, graph_service)

    graph_service.process_episode.assert_not_awaited()
    await test_db.refresh(task)
    await test_db.refresh(memory)
    assert task.status == "FAILED"
    assert task.message == "Graph processing source rejected"
    assert "knowledge_sync_write_conflict" in (task.error_message or "")
    assert memory.processing_status == "PENDING"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_rebuild_communities_workflow_updates_task(
    test_db: AsyncSession,
    test_project_db: Project,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_factory = async_sessionmaker(
        test_db.bind,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    monkeypatch.setattr(workflow_module, "async_session_factory", session_factory)
    task_id = str(uuid4())
    task = TaskLog(
        id=task_id,
        group_id=test_project_db.id,
        task_type="rebuild_communities",
        status="PENDING",
        payload={"task_id": task_id, "project_id": test_project_db.id},
        created_at=datetime.now(UTC),
    )
    test_db.add(task)
    await test_db.commit()
    entity_records = [
        {"uuid": f"entity-{index}", "name": f"Entity {index}", "entity_type": "Person"}
        for index in range(1001)
    ]
    neo4j_client = FakeNeo4jClient(
        [
            [],
            entity_records,
        ]
    )
    community_updater = SimpleNamespace(
        update_communities_for_entities=AsyncMock(return_value=[object()])
    )
    graph_service = SimpleNamespace(
        _neo4j_client=neo4j_client,
        community_updater=community_updater,
    )

    result = await _run_rebuild_communities_workflow(
        {"task_id": task_id, "project_id": test_project_db.id},
        graph_service,
    )

    await test_db.refresh(task)
    assert result["communities"] == 1
    assert result["entities"] == len(entity_records)
    assert task.status == "COMPLETED"
    assert task.progress == 100
    assert task.message == "Community rebuild complete"
    community_updater.update_communities_for_entities.assert_awaited_once()
    entity_query = str(neo4j_client.calls[1]["query"])
    assert "LIMIT 1000" not in entity_query
    updater_kwargs = community_updater.update_communities_for_entities.await_args.kwargs
    assert len(updater_kwargs["entities"]) == len(entity_records)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_incremental_refresh_workflow_processes_loaded_episodes(
    test_db: AsyncSession,
    test_project_db: Project,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_factory = async_sessionmaker(
        test_db.bind,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    monkeypatch.setattr(workflow_module, "async_session_factory", session_factory)
    task_id = str(uuid4())
    task = TaskLog(
        id=task_id,
        group_id=test_project_db.id,
        task_type="incremental_refresh",
        status="PENDING",
        payload={"task_id": task_id, "project_id": test_project_db.id},
        created_at=datetime.now(UTC),
    )
    test_db.add(task)
    await test_db.commit()
    neo4j_client = FakeNeo4jClient(
        [
            [
                {
                    "uuid": "episode-1",
                    "content": "Ada met Bob.",
                    "project_id": test_project_db.id,
                    "tenant_id": test_project_db.tenant_id,
                    "user_id": test_user.id,
                }
            ]
        ]
    )
    graph_service = SimpleNamespace(
        _neo4j_client=neo4j_client,
        process_episode=AsyncMock(return_value=SimpleNamespace()),
    )

    result = await _run_incremental_refresh_workflow(
        {"task_id": task_id, "project_id": test_project_db.id},
        graph_service,
    )

    await test_db.refresh(task)
    assert result["processed"] == 1
    assert result["skipped"] == 0
    assert task.status == "COMPLETED"
    assert task.message == "Incremental refresh complete"
    graph_service.process_episode.assert_awaited_once_with(
        episode_uuid="episode-1",
        content="Ada met Bob.",
        project_id=test_project_db.id,
        tenant_id=test_project_db.tenant_id,
        user_id=test_user.id,
        excluded_entity_types=None,
    )


def _extraction_result() -> SimpleNamespace:
    from src.infrastructure.graph.schemas import EntityEdge, EntityNode

    alice = EntityNode(name="Alice", entity_type="Person")
    acme = EntityNode(name="OpenAI", entity_type="Organization")
    edge = EntityEdge(
        source_uuid=alice.uuid,
        target_uuid=acme.uuid,
        relationship_type="WORKS_AT",
        fact="Alice works at OpenAI",
        weight=0.8,
    )
    return SimpleNamespace(nodes=[alice, acme], edges=[edge], episodic_edges=[])


def _payload(memory_id: str, task_id: str, project: Project, user: User) -> dict[str, object]:
    return {
        "task_id": task_id,
        "memory_id": memory_id,
        "source_revision": 1,
        "uuid": memory_id,
        "content": "Alice from OpenAI met Bob at Microsoft.",
        "project_id": project.id,
        "tenant_id": project.tenant_id,
        "user_id": user.id,
    }


def _session_factory(test_db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        workflow_module,
        "async_session_factory",
        async_sessionmaker(test_db.bind, class_=AsyncSession, expire_on_commit=False),
    )


async def _enroll(test_db: AsyncSession, project: Project) -> None:
    from sqlalchemy import update

    await test_db.execute(
        update(KnowledgeSyncEnrollmentModel)
        .where(KnowledgeSyncEnrollmentModel.project_id == project.id)
        .values(enabled=True)
    )
    await test_db.commit()


async def _journal_state(test_db: AsyncSession, project: Project, memory_id: str):
    from sqlalchemy import func, select

    from src.infrastructure.adapters.secondary.persistence.knowledge_sync_models import (
        KnowledgeGraphSyncChangeModel,
        KnowledgeGraphSyncObjectModel,
    )

    stored = await test_db.get(
        KnowledgeGraphSyncObjectModel, (project.tenant_id, project.id, memory_id)
    )
    changes = await test_db.scalar(
        select(func.count())
        .select_from(KnowledgeGraphSyncChangeModel)
        .where(KnowledgeGraphSyncChangeModel.project_id == project.id)
    )
    return stored, changes


@pytest.mark.unit
@pytest.mark.asyncio
async def test_enrolled_extraction_enqueues_exactly_one_derived_record_with_provenance(
    test_db: AsyncSession,
    test_project_db: Project,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _session_factory(test_db, monkeypatch)
    await _enroll(test_db, test_project_db)
    memory_id, task_id = str(uuid4()), str(uuid4())
    memory = _memory(memory_id, test_project_db, test_user)
    memory.task_id = task_id
    test_db.add_all([memory, _task(task_id, test_project_db.id, {})])
    await test_db.commit()
    graph_service = SimpleNamespace(process_episode=AsyncMock(return_value=_extraction_result()))

    result = await _run_episode_processing_workflow(
        _payload(memory_id, task_id, test_project_db, test_user), graph_service
    )

    assert result["entities"] == 2 and result["relationships"] == 1
    stored, changes = await _journal_state(test_db, test_project_db, memory_id)
    assert changes == 1
    assert stored is not None and stored.revision == 1 and stored.deleted is False
    assert stored.author_id == test_user.id
    payload = stored.payload
    content = payload["content"]
    assert content["source_revision"] == 1
    assert content["change_sequence"] == 1
    assert content["audit_attempt"] == 1
    assert content["entities"] == [
        {"name": "Alice", "kind": "Person"},
        {"name": "OpenAI", "kind": "Organization"},
    ]
    assert content["relationships"] == [
        {
            "source_index": 0,
            "target_index": 1,
            "relation_type": "WORKS_AT",
            "fact": "Alice works at OpenAI",
            "score": 0.8,
        }
    ]
    await test_db.refresh(memory)
    assert memory.processing_status == "COMPLETED"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_unenrolled_extraction_completes_without_journaling(
    test_db: AsyncSession,
    test_project_db: Project,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _session_factory(test_db, monkeypatch)
    # The autouse fence leaves the project unenrolled: legacy behavior is kept.
    memory_id, task_id = str(uuid4()), str(uuid4())
    memory = _memory(memory_id, test_project_db, test_user)
    memory.task_id = task_id
    test_db.add_all([memory, _task(task_id, test_project_db.id, {})])
    await test_db.commit()
    graph_service = SimpleNamespace(process_episode=AsyncMock(return_value=_extraction_result()))

    await _run_episode_processing_workflow(
        _payload(memory_id, task_id, test_project_db, test_user), graph_service
    )

    stored, changes = await _journal_state(test_db, test_project_db, memory_id)
    assert stored is None and changes == 0
    await test_db.refresh(memory)
    assert memory.processing_status == "COMPLETED"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_reextraction_replaces_the_record_at_the_next_revision(
    test_db: AsyncSession,
    test_project_db: Project,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _session_factory(test_db, monkeypatch)
    await _enroll(test_db, test_project_db)
    memory_id, task_id = str(uuid4()), str(uuid4())
    memory = _memory(memory_id, test_project_db, test_user)
    memory.task_id = task_id
    test_db.add_all([memory, _task(task_id, test_project_db.id, {})])
    await test_db.commit()
    graph_service = SimpleNamespace(process_episode=AsyncMock(return_value=_extraction_result()))

    await _run_episode_processing_workflow(
        _payload(memory_id, task_id, test_project_db, test_user), graph_service
    )
    memory.version = 2
    memory.processing_status = "PENDING"
    await test_db.commit()
    payload = {**_payload(memory_id, task_id, test_project_db, test_user), "source_revision": 2}
    await _run_episode_processing_workflow(payload, graph_service)

    stored, changes = await _journal_state(test_db, test_project_db, memory_id)
    assert changes == 2
    assert stored is not None and stored.revision == 2
    assert stored.payload["content"]["source_revision"] == 2
    assert stored.payload["content"]["change_sequence"] == 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_unjournalable_shape_completes_without_enqueuing_partial_records(
    test_db: AsyncSession,
    test_project_db: Project,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _session_factory(test_db, monkeypatch)
    await _enroll(test_db, test_project_db)
    memory_id, task_id = str(uuid4()), str(uuid4())
    memory = _memory(memory_id, test_project_db, test_user)
    memory.task_id = task_id
    test_db.add_all([memory, _task(task_id, test_project_db.id, {})])
    await test_db.commit()
    bad = SimpleNamespace(
        nodes=[SimpleNamespace(name="  ", entity_type="Person", uuid="x")],
        edges=[],
        episodic_edges=[],
    )
    graph_service = SimpleNamespace(process_episode=AsyncMock(return_value=bad))

    await _run_episode_processing_workflow(
        _payload(memory_id, task_id, test_project_db, test_user), graph_service
    )

    stored, changes = await _journal_state(test_db, test_project_db, memory_id)
    assert stored is None and changes == 0
    await test_db.refresh(memory)
    assert memory.processing_status == "COMPLETED"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_neo4j_unavailable_after_extraction_does_not_block_the_journal(
    test_db: AsyncSession,
    test_project_db: Project,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _session_factory(test_db, monkeypatch)
    await _enroll(test_db, test_project_db)
    memory_id, task_id = str(uuid4()), str(uuid4())
    memory = _memory(memory_id, test_project_db, test_user)
    memory.task_id = task_id
    test_db.add_all([memory, _task(task_id, test_project_db.id, {})])
    await test_db.commit()

    class ExplodingNeo4j:
        async def execute_query(self, *_args, **_kwargs):
            raise ConnectionError("neo4j unavailable")

    # The extraction result already exists; every later Neo4j contact fails.
    graph_service = SimpleNamespace(
        process_episode=AsyncMock(return_value=_extraction_result()),
        _neo4j_client=ExplodingNeo4j(),
    )

    await _run_episode_processing_workflow(
        _payload(memory_id, task_id, test_project_db, test_user), graph_service
    )

    stored, changes = await _journal_state(test_db, test_project_db, memory_id)
    assert changes == 1 and stored is not None and stored.revision == 1
    await test_db.refresh(memory)
    assert memory.processing_status == "COMPLETED"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_failed_extraction_enqueues_nothing(
    test_db: AsyncSession,
    test_project_db: Project,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _session_factory(test_db, monkeypatch)
    await _enroll(test_db, test_project_db)
    memory_id, task_id = str(uuid4()), str(uuid4())
    memory = _memory(memory_id, test_project_db, test_user)
    memory.task_id = task_id
    test_db.add_all([memory, _task(task_id, test_project_db.id, {})])
    await test_db.commit()
    graph_service = SimpleNamespace(process_episode=AsyncMock(side_effect=RuntimeError("boom")))

    with pytest.raises(RuntimeError, match="boom"):
        await _run_episode_processing_workflow(
            _payload(memory_id, task_id, test_project_db, test_user), graph_service
        )

    stored, changes = await _journal_state(test_db, test_project_db, memory_id)
    assert stored is None and changes == 0
    await test_db.refresh(memory)
    assert memory.processing_status == "FAILED"
