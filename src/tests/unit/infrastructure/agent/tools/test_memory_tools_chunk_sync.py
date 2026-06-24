from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.infrastructure.agent.tools.memory_tools import (
    _background_sync_created_memory,
    _execute_memory_create,
    _execute_memory_delete,
    _execute_memory_get,
    _execute_memory_update,
)


@pytest.mark.unit
class TestMemoryToolsChunkSync:
    @pytest.mark.asyncio
    async def test_memory_get_reports_processing_when_chunks_are_pending(self) -> None:
        session = AsyncMock()
        session_factory = MagicMock(return_value=session)

        chunk_result = MagicMock()
        chunk_result.scalars.return_value.all.return_value = []
        memory_result = MagicMock()
        memory_result.scalar_one_or_none.return_value = SimpleNamespace(
            id="mem-1",
            project_id="proj-1",
            processing_status="PENDING",
            content="remember this",
            meta={"category": "fact"},
            created_at=None,
        )
        session.execute = AsyncMock(side_effect=[chunk_result, memory_result])

        result = await _execute_memory_get(
            session_factory=session_factory,
            project_id="proj-1",
            source_id="mem-1",
        )

        assert result["status"] == "processing"
        assert result["processing_status"] == "PENDING"
        assert "error" not in result
        assert session.execute.await_count == 2
        session.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_create_returns_after_commit_and_schedules_background_sync(self) -> None:
        session = AsyncMock()
        session_factory = MagicMock(return_value=session)
        repo = MagicMock()
        service = MagicMock()
        service.create_memory = AsyncMock(
            return_value=SimpleNamespace(
                id="mem-1",
                title="Memory title",
                processing_status="PENDING",
            )
        )
        schedule_sync = MagicMock()

        with (
            patch(
                "src.infrastructure.adapters.secondary.persistence.sql_memory_repository.SqlMemoryRepository",
                return_value=repo,
            ),
            patch(
                "src.application.services.memory_service.MemoryService",
                return_value=service,
            ),
            patch(
                "src.infrastructure.agent.tools.memory_tools._schedule_memory_create_background_sync",
                schedule_sync,
            ),
        ):
            result = await _execute_memory_create(
                content="remember this",
                title="Memory title",
                category="fact",
                tags=["tag-1"],
                session_factory=session_factory,
                graph_service=object(),
                project_id="proj-1",
                tenant_id="tenant-1",
                user_id="user-1",
                embedding_service=None,
            )

        payload = json.loads(result)
        assert payload["status"] == "created"
        service.create_memory.assert_awaited_once()
        assert service.create_memory.await_args.kwargs["enqueue_graph"] is False
        assert schedule_sync.call_args.kwargs["memory_id"] == "mem-1"
        assert schedule_sync.call_args.kwargs["project_id"] == "proj-1"
        assert schedule_sync.call_args.kwargs["embedding_service"] is None

    @pytest.mark.asyncio
    async def test_background_sync_marks_created_memory_completed_after_graph_sync(self) -> None:
        sessions = [AsyncMock(), AsyncMock()]
        session_factory = MagicMock(side_effect=sessions)
        memory = SimpleNamespace(id="mem-1", processing_status="PENDING")
        repo = MagicMock()
        repo.find_by_id = AsyncMock(return_value=memory)
        repo.save = AsyncMock(return_value=memory)
        graph_service = SimpleNamespace(add_episode=AsyncMock())
        upsert_chunks = AsyncMock(return_value=1)

        with (
            patch(
                "src.infrastructure.adapters.secondary.persistence.sql_memory_repository.SqlMemoryRepository",
                return_value=repo,
            ),
            patch(
                "src.infrastructure.adapters.secondary.persistence.sql_chunk_repository.SqlChunkRepository",
                return_value="chunk-repo",
            ),
            patch(
                "src.infrastructure.memory.chunk_sync.upsert_memory_chunks",
                upsert_chunks,
            ),
        ):
            await _background_sync_created_memory(
                session_factory=session_factory,
                graph_service=graph_service,
                memory_id="mem-1",
                title="Memory title",
                content="remember this",
                project_id="proj-1",
                tenant_id="tenant-1",
                user_id="user-1",
                category="fact",
                tags=["tag-1"],
                embedding_service=None,
            )

        graph_service.add_episode.assert_awaited_once()
        assert memory.processing_status == "COMPLETED"
        repo.save.assert_awaited_once_with(memory)
        sessions[0].commit.assert_awaited_once()
        upsert_chunks.assert_awaited_once()
        sessions[1].commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_background_sync_marks_created_memory_failed_when_graph_sync_fails(self) -> None:
        session = AsyncMock()
        session_factory = MagicMock(return_value=session)
        memory = SimpleNamespace(id="mem-1", processing_status="PENDING")
        repo = MagicMock()
        repo.find_by_id = AsyncMock(return_value=memory)
        repo.save = AsyncMock(return_value=memory)
        graph_service = SimpleNamespace(add_episode=AsyncMock(side_effect=RuntimeError("boom")))
        upsert_chunks = AsyncMock(return_value=1)

        with (
            patch(
                "src.infrastructure.adapters.secondary.persistence.sql_memory_repository.SqlMemoryRepository",
                return_value=repo,
            ),
            patch(
                "src.infrastructure.memory.chunk_sync.upsert_memory_chunks",
                upsert_chunks,
            ),
        ):
            await _background_sync_created_memory(
                session_factory=session_factory,
                graph_service=graph_service,
                memory_id="mem-1",
                title="Memory title",
                content="remember this",
                project_id="proj-1",
                tenant_id="tenant-1",
                user_id="user-1",
                category="fact",
                tags=[],
                embedding_service=None,
            )

        assert memory.processing_status == "FAILED"
        repo.save.assert_awaited_once_with(memory)
        session.commit.assert_awaited_once()
        upsert_chunks.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_update_uses_shared_chunk_sync_helper(self) -> None:
        session = AsyncMock()
        session_factory = MagicMock(return_value=session)
        repo = MagicMock()
        service = MagicMock()
        service.update_memory = AsyncMock(
            return_value=SimpleNamespace(
                id="mem-1",
                title="Updated title",
                project_id="proj-1",
                processing_status="PENDING",
                content="updated content",
                tags=["tag-2"],
                metadata={"category": "decision"},
            )
        )
        upsert_chunks = AsyncMock(return_value=1)

        with (
            patch(
                "src.infrastructure.adapters.secondary.persistence.sql_memory_repository.SqlMemoryRepository",
                return_value=repo,
            ),
            patch(
                "src.application.services.memory_service.MemoryService",
                return_value=service,
            ),
            patch(
                "src.infrastructure.adapters.secondary.persistence.sql_chunk_repository.SqlChunkRepository",
                return_value="chunk-repo",
            ),
            patch(
                "src.infrastructure.memory.chunk_sync.upsert_memory_chunks",
                upsert_chunks,
            ),
        ):
            result = await _execute_memory_update(
                memory_id="mem-1",
                title="Updated title",
                content="updated content",
                tags=["tag-2"],
                metadata={"category": "decision"},
                session_factory=session_factory,
                graph_service=object(),
            )

        payload = json.loads(result)
        assert payload["status"] == "updated"
        assert upsert_chunks.await_args.kwargs["memory_id"] == "mem-1"
        assert upsert_chunks.await_args.kwargs["project_id"] == "proj-1"
        assert upsert_chunks.await_args.kwargs["category"] == "decision"

    @pytest.mark.asyncio
    async def test_update_logs_do_not_include_memory_identifier(self, caplog) -> None:
        session = AsyncMock()
        session_factory = MagicMock(return_value=session)
        secret_memory_id = "mem-update-secret"
        repo = MagicMock()
        service = MagicMock()
        service.update_memory = AsyncMock(
            return_value=SimpleNamespace(
                id=secret_memory_id,
                title="Updated title",
                project_id="proj-1",
                processing_status="COMPLETED",
                content="updated content",
                tags=[],
                metadata={"category": "fact"},
            )
        )
        caplog.set_level(logging.INFO, logger="src.infrastructure.agent.tools.memory_tools")

        with (
            patch(
                "src.infrastructure.adapters.secondary.persistence.sql_memory_repository.SqlMemoryRepository",
                return_value=repo,
            ),
            patch(
                "src.application.services.memory_service.MemoryService",
                return_value=service,
            ),
        ):
            result = await _execute_memory_update(
                memory_id=secret_memory_id,
                title=None,
                content=None,
                tags=None,
                metadata=None,
                session_factory=session_factory,
                graph_service=object(),
            )

        payload = json.loads(result)
        assert payload["status"] == "updated"
        assert secret_memory_id not in caplog.text
        assert "memory_update: updated memory" in caplog.text

    @pytest.mark.asyncio
    async def test_update_chunk_failure_logs_do_not_include_exception_content(
        self,
        caplog,
    ) -> None:
        session = AsyncMock()
        session_factory = MagicMock(return_value=session)
        secret_memory_id = "mem-update-chunk-secret"
        exception_detail = "chunk sync leaked memory id mem-update-chunk-secret"
        repo = MagicMock()
        service = MagicMock()
        service.update_memory = AsyncMock(
            return_value=SimpleNamespace(
                id=secret_memory_id,
                title="Updated title",
                project_id="proj-1",
                processing_status="PENDING",
                content="updated content",
                tags=["tag-2"],
                metadata={"category": "decision"},
            )
        )
        upsert_chunks = AsyncMock(side_effect=RuntimeError(exception_detail))
        caplog.set_level(logging.WARNING, logger="src.infrastructure.agent.tools.memory_tools")

        with (
            patch(
                "src.infrastructure.adapters.secondary.persistence.sql_memory_repository.SqlMemoryRepository",
                return_value=repo,
            ),
            patch(
                "src.application.services.memory_service.MemoryService",
                return_value=service,
            ),
            patch(
                "src.infrastructure.adapters.secondary.persistence.sql_chunk_repository.SqlChunkRepository",
                return_value="chunk-repo",
            ),
            patch(
                "src.infrastructure.memory.chunk_sync.upsert_memory_chunks",
                upsert_chunks,
            ),
        ):
            result = await _execute_memory_update(
                memory_id=secret_memory_id,
                title="Updated title",
                content="updated content",
                tags=["tag-2"],
                metadata={"category": "decision"},
                session_factory=session_factory,
                graph_service=object(),
            )

        payload = json.loads(result)
        assert payload["status"] == "updated"
        assert secret_memory_id not in caplog.text
        assert exception_detail not in caplog.text
        assert "error_type=RuntimeError" in caplog.text

    @pytest.mark.asyncio
    async def test_update_failure_logs_do_not_include_exception_content(
        self,
        caplog,
    ) -> None:
        session = AsyncMock()
        session_factory = MagicMock(return_value=session)
        secret_memory_id = "mem-update-failure-secret"
        exception_detail = "update service leaked memory id mem-update-failure-secret"
        repo = MagicMock()
        service = MagicMock()
        service.update_memory = AsyncMock(side_effect=RuntimeError(exception_detail))
        caplog.set_level(logging.WARNING, logger="src.infrastructure.agent.tools.memory_tools")

        with (
            patch(
                "src.infrastructure.adapters.secondary.persistence.sql_memory_repository.SqlMemoryRepository",
                return_value=repo,
            ),
            patch(
                "src.application.services.memory_service.MemoryService",
                return_value=service,
            ),
        ):
            result = await _execute_memory_update(
                memory_id=secret_memory_id,
                title=None,
                content=None,
                tags=None,
                metadata=None,
                session_factory=session_factory,
                graph_service=object(),
            )

        payload = json.loads(result)
        assert "error" in payload
        assert secret_memory_id not in caplog.text
        assert exception_detail not in caplog.text
        assert "error_type=RuntimeError" in caplog.text

    @pytest.mark.asyncio
    async def test_delete_uses_shared_chunk_delete_helper(self) -> None:
        session = AsyncMock()
        session_factory = MagicMock(return_value=session)
        repo = MagicMock()
        repo.find_by_id = AsyncMock(return_value=SimpleNamespace(project_id="proj-1"))
        service = MagicMock()
        service.delete_memory = AsyncMock()
        delete_chunks = AsyncMock(return_value=1)

        with (
            patch(
                "src.infrastructure.adapters.secondary.persistence.sql_memory_repository.SqlMemoryRepository",
                return_value=repo,
            ),
            patch(
                "src.application.services.memory_service.MemoryService",
                return_value=service,
            ),
            patch(
                "src.infrastructure.adapters.secondary.persistence.sql_chunk_repository.SqlChunkRepository",
                return_value="chunk-repo",
            ),
            patch(
                "src.infrastructure.memory.chunk_sync.delete_memory_chunks",
                delete_chunks,
            ),
        ):
            result = await _execute_memory_delete(
                memory_id="mem-1",
                session_factory=session_factory,
                graph_service=object(),
            )

        payload = json.loads(result)
        assert payload["status"] == "deleted"
        assert delete_chunks.await_args.kwargs["memory_id"] == "mem-1"
        assert delete_chunks.await_args.kwargs["project_id"] == "proj-1"

    @pytest.mark.asyncio
    async def test_delete_logs_do_not_include_memory_identifier(self, caplog) -> None:
        session = AsyncMock()
        session_factory = MagicMock(return_value=session)
        secret_memory_id = "mem-delete-secret"
        repo = MagicMock()
        repo.find_by_id = AsyncMock(return_value=SimpleNamespace(project_id="proj-1"))
        service = MagicMock()
        service.delete_memory = AsyncMock()
        delete_chunks = AsyncMock(return_value=1)
        caplog.set_level(logging.INFO, logger="src.infrastructure.agent.tools.memory_tools")

        with (
            patch(
                "src.infrastructure.adapters.secondary.persistence.sql_memory_repository.SqlMemoryRepository",
                return_value=repo,
            ),
            patch(
                "src.application.services.memory_service.MemoryService",
                return_value=service,
            ),
            patch(
                "src.infrastructure.adapters.secondary.persistence.sql_chunk_repository.SqlChunkRepository",
                return_value="chunk-repo",
            ),
            patch(
                "src.infrastructure.memory.chunk_sync.delete_memory_chunks",
                delete_chunks,
            ),
        ):
            result = await _execute_memory_delete(
                memory_id=secret_memory_id,
                session_factory=session_factory,
                graph_service=object(),
            )

        payload = json.loads(result)
        assert payload["status"] == "deleted"
        assert secret_memory_id not in caplog.text
        assert "memory_delete: deleted memory" in caplog.text

    @pytest.mark.asyncio
    async def test_delete_chunk_failure_logs_do_not_include_exception_content(
        self,
        caplog,
    ) -> None:
        session = AsyncMock()
        session_factory = MagicMock(return_value=session)
        secret_memory_id = "mem-delete-chunk-secret"
        exception_detail = "chunk cleanup leaked memory id mem-delete-chunk-secret"
        repo = MagicMock()
        repo.find_by_id = AsyncMock(return_value=SimpleNamespace(project_id="proj-1"))
        service = MagicMock()
        service.delete_memory = AsyncMock()
        delete_chunks = AsyncMock(side_effect=RuntimeError(exception_detail))
        caplog.set_level(logging.WARNING, logger="src.infrastructure.agent.tools.memory_tools")

        with (
            patch(
                "src.infrastructure.adapters.secondary.persistence.sql_memory_repository.SqlMemoryRepository",
                return_value=repo,
            ),
            patch(
                "src.application.services.memory_service.MemoryService",
                return_value=service,
            ),
            patch(
                "src.infrastructure.adapters.secondary.persistence.sql_chunk_repository.SqlChunkRepository",
                return_value="chunk-repo",
            ),
            patch(
                "src.infrastructure.memory.chunk_sync.delete_memory_chunks",
                delete_chunks,
            ),
        ):
            result = await _execute_memory_delete(
                memory_id=secret_memory_id,
                session_factory=session_factory,
                graph_service=object(),
            )

        payload = json.loads(result)
        assert payload["status"] == "deleted"
        assert secret_memory_id not in caplog.text
        assert exception_detail not in caplog.text
        assert "error_type=RuntimeError" in caplog.text

    @pytest.mark.asyncio
    async def test_delete_failure_logs_do_not_include_exception_content(
        self,
        caplog,
    ) -> None:
        session = AsyncMock()
        session_factory = MagicMock(return_value=session)
        secret_memory_id = "mem-delete-failure-secret"
        exception_detail = "delete service leaked memory id mem-delete-failure-secret"
        repo = MagicMock()
        repo.find_by_id = AsyncMock(return_value=SimpleNamespace(project_id="proj-1"))
        service = MagicMock()
        service.delete_memory = AsyncMock(side_effect=RuntimeError(exception_detail))
        caplog.set_level(logging.WARNING, logger="src.infrastructure.agent.tools.memory_tools")

        with (
            patch(
                "src.infrastructure.adapters.secondary.persistence.sql_memory_repository.SqlMemoryRepository",
                return_value=repo,
            ),
            patch(
                "src.application.services.memory_service.MemoryService",
                return_value=service,
            ),
        ):
            result = await _execute_memory_delete(
                memory_id=secret_memory_id,
                session_factory=session_factory,
                graph_service=object(),
            )

        payload = json.loads(result)
        assert "error" in payload
        assert secret_memory_id not in caplog.text
        assert exception_detail not in caplog.text
        assert "error_type=RuntimeError" in caplog.text
