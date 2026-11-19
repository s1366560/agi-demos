"""Memory updates release SQL write locks before graph processing starts."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.application.services.memory_service import MemoryUpdateResult
from src.domain.model.memory.memory import Memory
from src.infrastructure.agent.tools.memory_tools import _execute_memory_update


@pytest.fixture
def updated_memory() -> Memory:
    return Memory(
        id="memory",
        project_id="project",
        author_id="actor",
        title="Updated",
        content="New content",
        version=2,
        metadata={"tenant_id": "tenant", "category": "fact"},
    )


def update_call(memory: Memory, session: AsyncMock):
    return _execute_memory_update(
        memory_id=memory.id,
        title=None,
        content=memory.content,
        tags=None,
        metadata=None,
        session_factory=MagicMock(return_value=session),
        graph_service=object(),
    )


@pytest.mark.unit
class TestMemoryUpdateTransactions:
    async def test_commit_precedes_graph_and_chunk_sync(self, updated_memory: Memory) -> None:
        committed = asyncio.Event()
        session = AsyncMock()
        session.commit.side_effect = committed.set
        service = MagicMock()
        service.prepare_memory_update = AsyncMock(
            return_value=MemoryUpdateResult(memory=updated_memory, content_changed=True)
        )

        async def reprocess(memory: Memory) -> None:
            assert committed.is_set()
            assert memory is updated_memory

        service.reprocess_memory = AsyncMock(side_effect=reprocess)
        with patch("src.application.services.memory_service.MemoryService", return_value=service):
            result = await update_call(updated_memory, session)
        payload = json.loads(result)
        assert payload["status"] == "updated"
        assert payload["saved"] is True
        assert payload["processing_status"] == "PENDING"
        assert payload["searchable"] is False
        service.reprocess_memory.assert_not_awaited()
        session.commit.assert_awaited()
        session.close.assert_awaited_once()

    async def test_slow_graph_is_not_on_the_tool_path(self, updated_memory: Memory) -> None:
        session = AsyncMock()
        service = MagicMock()
        service.prepare_memory_update = AsyncMock(
            return_value=MemoryUpdateResult(memory=updated_memory, content_changed=True)
        )
        service.reprocess_memory = AsyncMock(side_effect=asyncio.Event().wait)
        with patch("src.application.services.memory_service.MemoryService", return_value=service):
            result = await asyncio.wait_for(update_call(updated_memory, session), timeout=1)
        assert json.loads(result)["processing_status"] == "PENDING"
        service.reprocess_memory.assert_not_awaited()
        session.close.assert_awaited_once()

    async def test_failed_commit_does_not_start_graph(self, updated_memory: Memory) -> None:
        session = AsyncMock()
        session.commit.side_effect = RuntimeError("commit failed")
        service = MagicMock()
        service.prepare_memory_update = AsyncMock(
            return_value=MemoryUpdateResult(memory=updated_memory, content_changed=True)
        )
        service.reprocess_memory = AsyncMock()
        with patch("src.application.services.memory_service.MemoryService", return_value=service):
            result = await update_call(updated_memory, session)
        assert "error" in json.loads(result)
        service.reprocess_memory.assert_not_awaited()
        session.rollback.assert_awaited_once()
        session.close.assert_awaited_once()
