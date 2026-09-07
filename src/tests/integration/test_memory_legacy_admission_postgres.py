"""Legacy services hold admission through graph work and SQL commit."""

import asyncio
import hashlib
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa

from src.application.services.memory_service import MemoryService
from src.domain.model.knowledge_sync.contracts import KnowledgeSyncError
from src.infrastructure.adapters.secondary.persistence.models import Memory, MemoryChunk
from src.infrastructure.adapters.secondary.persistence.sql_knowledge_sync_enrollment import (
    SqlKnowledgeSyncEnrollment,
)
from src.infrastructure.adapters.secondary.persistence.sql_memory_repository import (
    SqlMemoryRepository,
)
from src.infrastructure.adapters.secondary.sql_memory_repository import SqlAlchemyMemoryRepository
from src.tests.integration.test_knowledge_sync_postgres import (  # noqa: F401
    pg_sync as _pg_sync,
    pytestmark,
)

pg_sync = _pg_sync


@pytest.mark.parametrize("repo_type", [SqlMemoryRepository, SqlAlchemyMemoryRepository])
async def test_enrolled_service_rejects_before_graph(pg_sync, repo_type):
    sessions, scope = pg_sync
    async with sessions() as db:
        db.add(
            Memory(
                id="legacy",
                project_id=scope.project_id,
                author_id=scope.actor_id,
                title="Original",
                content="Source",
                version=1,
            )
        )
        await db.commit()
        await SqlKnowledgeSyncEnrollment(db).bootstrap(scope)
        await db.commit()
        graph = AsyncMock()
        service = MemoryService(repo_type(db), graph)
        with pytest.raises(KnowledgeSyncError, match="knowledge_sync_write_context_required"):
            await service.delete_memory("legacy")
        graph.delete_episode_by_memory_id.assert_not_awaited()
        await db.rollback()
        assert await db.get(Memory, "legacy") is not None


@pytest.mark.parametrize("repo_type", [SqlMemoryRepository, SqlAlchemyMemoryRepository])
async def test_service_graph_barrier_prevents_bootstrap(pg_sync, repo_type):
    sessions, scope = pg_sync
    entered, release = asyncio.Event(), asyncio.Event()

    async def graph_add(*args, **kwargs):
        # A foreign-key checker in another SQL session must coexist with admission.
        async with sessions() as graph_db:
            graph_db.add(
                MemoryChunk(
                    id="graph-chunk",
                    project_id=scope.project_id,
                    source_type="memory",
                    source_id=args[0].metadata["memory_id"],
                    chunk_index=0,
                    content="Source",
                    content_hash=hashlib.sha256(b"Source").hexdigest(),
                )
            )
            await graph_db.flush()
            await graph_db.commit()
        entered.set()
        await release.wait()

    graph = AsyncMock()
    graph.add_episode.side_effect = graph_add
    async with sessions() as writer, sessions() as bootstrapper:
        service = MemoryService(repo_type(writer), graph)
        task = asyncio.create_task(
            service.create_memory(
                "Legacy", "Source", scope.project_id, scope.actor_id, scope.tenant_id
            )
        )
        await asyncio.wait_for(entered.wait(), 5)
        bootstrap = asyncio.create_task(SqlKnowledgeSyncEnrollment(bootstrapper).bootstrap(scope))
        await asyncio.sleep(0.1)
        assert not bootstrap.done()
        release.set()
        await asyncio.wait_for(task, 5)
        if repo_type is SqlMemoryRepository:
            await asyncio.sleep(0.1)
            assert not bootstrap.done()
        await writer.commit()
        result = await asyncio.wait_for(bootstrap, 5)
        await bootstrapper.commit()
        assert result["bootstrap_count"] == 1


async def test_bootstrap_first_rejects_waiting_service_before_graph(pg_sync):
    sessions, scope = pg_sync
    async with sessions() as bootstrapper, sessions() as writer:
        await SqlKnowledgeSyncEnrollment(bootstrapper).bootstrap(scope)
        graph = AsyncMock()
        service = MemoryService(SqlMemoryRepository(writer), graph)
        task = asyncio.create_task(
            service.create_memory(
                "Late", "Source", scope.project_id, scope.actor_id, scope.tenant_id
            )
        )
        await asyncio.sleep(0.1)
        assert not task.done()
        await bootstrapper.commit()
        with pytest.raises(KnowledgeSyncError, match="knowledge_sync_write_context_required"):
            await asyncio.wait_for(task, 5)
        graph.add_episode.assert_not_awaited()
        await writer.rollback()


@pytest.mark.parametrize(
    "operation",
    [
        "create",
        "update",
        "share",
        "create_use_case",
        "delete_use_case",
        "tool_create",
        "tool_update",
        "tool_delete",
    ],
)
async def test_enrolled_entrypoints_have_no_graph_or_chunk_side_effects(pg_sync, operation):
    import json
    from unittest.mock import patch

    from src.application.use_cases.memory.create_memory import (
        CreateMemoryCommand,
        CreateMemoryUseCase,
    )
    from src.application.use_cases.memory.delete_memory import (
        DeleteMemoryCommand,
        DeleteMemoryUseCase,
    )
    from src.infrastructure.agent.tools.memory_tools import (
        _execute_memory_create,
        _execute_memory_delete,
        _execute_memory_update,
    )

    sessions, scope = pg_sync
    async with sessions() as db:
        db.add(
            Memory(
                id="legacy",
                project_id=scope.project_id,
                author_id=scope.actor_id,
                title="Original",
                content="Source",
                version=1,
            )
        )
        await db.commit()
        await SqlKnowledgeSyncEnrollment(db).bootstrap(scope)
        await db.commit()
        graph = AsyncMock()
        repo = SqlMemoryRepository(db)
        service = MemoryService(repo, graph)
        calls = {
            "create": lambda: service.create_memory(
                "New", "Source", scope.project_id, scope.actor_id, scope.tenant_id
            ),
            "update": lambda: service.update_memory("legacy", content="Replacement"),
            "share": lambda: service.share_memory("legacy", ["collaborator"]),
            "create_use_case": lambda: CreateMemoryUseCase(repo, graph).execute(
                CreateMemoryCommand(
                    title="New",
                    content="Source",
                    project_id=scope.project_id,
                    author_id=scope.actor_id,
                    tenant_id=scope.tenant_id,
                )
            ),
            "delete_use_case": lambda: DeleteMemoryUseCase(repo, graph).execute(
                DeleteMemoryCommand(memory_id="legacy")
            ),
            "tool_create": lambda: _execute_memory_create(
                content="New",
                title="New",
                category="fact",
                tags=[],
                session_factory=sessions,
                graph_service=graph,
                project_id=scope.project_id,
                tenant_id=scope.tenant_id,
                user_id=scope.actor_id,
            ),
            "tool_update": lambda: _execute_memory_update(
                memory_id="legacy",
                title=None,
                content="New",
                tags=None,
                metadata=None,
                session_factory=sessions,
                graph_service=graph,
            ),
            "tool_delete": lambda: _execute_memory_delete(
                memory_id="legacy", session_factory=sessions, graph_service=graph
            ),
        }
        with (
            patch(
                "src.infrastructure.memory.chunk_sync.upsert_memory_chunks", new_callable=AsyncMock
            ) as upsert,
            patch(
                "src.infrastructure.memory.chunk_sync.delete_memory_chunks", new_callable=AsyncMock
            ) as delete,
            patch(
                "src.infrastructure.agent.tools.memory_tools._schedule_memory_create_background_sync"
            ) as schedule,
        ):
            if operation.startswith("tool_"):
                result = json.loads(await calls[operation]())
                assert result["code"] == "knowledge_sync_write_context_required"
            else:
                with pytest.raises(
                    KnowledgeSyncError, match="knowledge_sync_write_context_required"
                ):
                    await calls[operation]()
            upsert.assert_not_awaited()
            delete.assert_not_awaited()
            schedule.assert_not_called()
        graph.add_episode.assert_not_awaited()
        graph.delete_episode_by_memory_id.assert_not_awaited()
        await db.rollback()
        assert (await db.get(Memory, "legacy")).content == "Source"


async def test_missing_enrollment_and_unknown_id_fail_closed(pg_sync):
    from src.infrastructure.adapters.secondary.persistence.knowledge_sync_models import (
        KnowledgeSyncEnrollmentModel,
    )

    sessions, scope = pg_sync
    async with sessions() as db:
        graph = AsyncMock()
        service = MemoryService(SqlMemoryRepository(db), graph)
        with pytest.raises(KnowledgeSyncError, match="knowledge_sync_memory_not_found"):
            await service.delete_memory("unknown")
        await db.rollback()
        await db.execute(sa.delete(KnowledgeSyncEnrollmentModel))
        await db.commit()
        with pytest.raises(KnowledgeSyncError, match="knowledge_sync_fence_missing"):
            await service.create_memory(
                "New", "Source", scope.project_id, scope.actor_id, scope.tenant_id
            )
        graph.add_episode.assert_not_awaited()
        graph.delete_episode_by_memory_id.assert_not_awaited()
        await db.rollback()


async def test_old_repository_preserves_standalone_commit_and_rolls_back_failed_scope(pg_sync):
    from src.domain.model.memory.memory import Memory as DomainMemory

    sessions, scope = pg_sync
    async with sessions() as db, sessions() as observer:
        repo = SqlAlchemyMemoryRepository(db)
        memory = DomainMemory(
            project_id=scope.project_id,
            author_id=scope.actor_id,
            title="Committed",
            content="Source",
        )
        await repo.save(memory)
        assert (await observer.get(Memory, memory.id)).title == "Committed"
        await observer.rollback()
        with pytest.raises(RuntimeError, match="abort"):
            async with repo.legacy_write(project_id=scope.project_id):
                memory.title = "Rolled back"
                await repo.save(memory)
                raise RuntimeError("abort")
        assert (await observer.get(Memory, memory.id)).title == "Committed"
        await repo.delete(memory.id)
        await observer.rollback()
        assert await observer.get(Memory, memory.id) is None


@pytest.mark.parametrize("repo_type", [SqlMemoryRepository, SqlAlchemyMemoryRepository])
async def test_delete_use_case_rejects_explicit_other_project_before_side_effects(
    pg_sync, repo_type
):
    from unittest.mock import patch

    from src.application.use_cases.memory.delete_memory import (
        DeleteMemoryCommand,
        DeleteMemoryUseCase,
    )
    from src.infrastructure.adapters.secondary.persistence.knowledge_sync_models import (
        KnowledgeSyncEnrollmentModel,
    )
    from src.infrastructure.adapters.secondary.persistence.models import Project

    sessions, scope = pg_sync
    async with sessions() as db:
        db.add(
            Project(
                id="other-project", tenant_id=scope.tenant_id, name="Other", owner_id=scope.actor_id
            )
        )
        await db.flush()
        db.add(
            Memory(
                id="other-memory",
                project_id="other-project",
                author_id=scope.actor_id,
                title="Unchanged",
                content="Original",
                version=1,
            )
        )
        await db.commit()
        assert not (await db.get(KnowledgeSyncEnrollmentModel, "other-project")).enabled
        graph = AsyncMock()
        repo = repo_type(db)
        with patch.object(repo, "delete", wraps=repo.delete) as delete:
            with pytest.raises(KnowledgeSyncError, match="knowledge_sync_write_conflict"):
                await DeleteMemoryUseCase(repo, graph).execute(
                    DeleteMemoryCommand(memory_id="other-memory", project_id=scope.project_id)
                )
            delete.assert_not_awaited()
        graph.delete_episode_by_memory_id.assert_not_awaited()
        await db.rollback()
        assert (await db.get(Memory, "other-memory")).content == "Original"


@pytest.mark.parametrize("repo_type", [SqlMemoryRepository, SqlAlchemyMemoryRepository])
@pytest.mark.parametrize("entrypoint", ["service", "use_case"])
async def test_create_rejects_caller_tenant_mismatch_before_side_effects(
    pg_sync, repo_type, entrypoint
):
    from unittest.mock import patch

    from src.application.use_cases.memory.create_memory import (
        CreateMemoryCommand,
        CreateMemoryUseCase,
    )
    from src.infrastructure.adapters.secondary.persistence.models import Tenant

    sessions, scope = pg_sync
    async with sessions() as db:
        db.add(Tenant(id="other-tenant", name="Other", slug="other", owner_id=scope.actor_id))
        await db.commit()
        graph = AsyncMock()
        repo = repo_type(db)
        with patch.object(repo, "save", wraps=repo.save) as save:
            with pytest.raises(KnowledgeSyncError, match="knowledge_sync_forbidden"):
                if entrypoint == "service":
                    await MemoryService(repo, graph).create_memory(
                        "Rejected", "Source", scope.project_id, scope.actor_id, "other-tenant"
                    )
                else:
                    await CreateMemoryUseCase(repo, graph).execute(
                        CreateMemoryCommand(
                            title="Rejected",
                            content="Source",
                            project_id=scope.project_id,
                            author_id=scope.actor_id,
                            tenant_id="other-tenant",
                        )
                    )
            save.assert_not_awaited()
        graph.add_episode.assert_not_awaited()
        await db.rollback()
        assert await db.scalar(sa.select(sa.func.count()).select_from(Memory)) == 0


@pytest.mark.parametrize("repo_type", [SqlMemoryRepository, SqlAlchemyMemoryRepository])
@pytest.mark.parametrize("tenant_value", ["other-tenant", None, "", 123])
async def test_update_rejects_metadata_tenant_before_save_and_graph(
    pg_sync, repo_type, tenant_value
):
    from unittest.mock import patch

    from src.infrastructure.adapters.secondary.persistence.models import Tenant

    sessions, scope = pg_sync
    async with sessions() as db:
        db.add(Tenant(id="other-tenant", name="Other", slug="other", owner_id=scope.actor_id))
        db.add(
            Memory(
                id="legacy",
                project_id=scope.project_id,
                author_id=scope.actor_id,
                title="Original",
                content="Source",
                version=1,
                meta={"tenant_id": scope.tenant_id},
            )
        )
        await db.commit()
        graph = AsyncMock()
        repo = repo_type(db)
        expected = (
            "knowledge_sync_forbidden"
            if tenant_value == "other-tenant"
            else "knowledge_sync_input_invalid"
        )
        with patch.object(repo, "save", wraps=repo.save) as save:
            with pytest.raises(KnowledgeSyncError, match=expected):
                await MemoryService(repo, graph).update_memory(
                    "legacy", content="Rejected", metadata={"tenant_id": tenant_value}
                )
            save.assert_not_awaited()
        graph.add_episode.assert_not_awaited()
        graph.delete_episode_by_memory_id.assert_not_awaited()
        await db.rollback()
        persisted = await db.get(Memory, "legacy")
        assert persisted.content == "Source"
        assert persisted.meta == {"tenant_id": scope.tenant_id}


@pytest.mark.parametrize("repo_type", [SqlMemoryRepository, SqlAlchemyMemoryRepository])
async def test_update_preserves_legacy_missing_metadata_tenant_behavior(pg_sync, repo_type):
    sessions, scope = pg_sync
    async with sessions() as db:
        db.add(
            Memory(
                id="legacy",
                project_id=scope.project_id,
                author_id=scope.actor_id,
                title="Original",
                content="Source",
                version=1,
                meta={},
            )
        )
        await db.commit()
        graph = AsyncMock()
        await MemoryService(repo_type(db), graph).update_memory("legacy", content="Updated")
        await db.commit()
        assert (await db.get(Memory, "legacy")).content == "Updated"
        graph.add_episode.assert_awaited_once()
        assert graph.add_episode.await_args.args[0].tenant_id is None
