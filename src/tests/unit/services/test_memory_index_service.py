"""Unit tests for MemoryIndexService."""

import logging
from unittest.mock import AsyncMock, Mock

import pytest

from src.application.services.memory_index_service import MemoryIndexService


@pytest.mark.asyncio
class TestMemoryIndexService:
    """Test memory chunk indexing behavior."""

    async def test_index_memory_logs_do_not_include_source_identifier(self, caplog):
        """Index logs must not expose source IDs."""
        chunk_repo = Mock()
        chunk_repo.delete_by_source = AsyncMock()
        chunk_repo.save_batch = AsyncMock()
        service = MemoryIndexService(chunk_repo, embedding_service=None)
        secret_memory_id = "memory-index-secret-alpha"
        caplog.set_level(logging.INFO, logger="src.application.services.memory_index_service")

        created = await service.index_memory(
            memory_id=secret_memory_id,
            content="Sensitive memory content for indexing",
            project_id="project-index-secret",
        )

        assert created == 1
        assert secret_memory_id not in caplog.text
        assert "source_type=memory" in caplog.text
        assert "created_count=1" in caplog.text

    async def test_embedding_failure_logs_do_not_include_exception_content(self, caplog):
        """Embedding failure logs must not expose backend exception text."""
        chunk_repo = Mock()
        chunk_repo.delete_by_source = AsyncMock()
        chunk_repo.save_batch = AsyncMock()
        embedding_service = Mock()
        exception_detail = "embedding backend leaked chunk text lambda-2604"
        embedding_service.embed_batch_safe = AsyncMock(side_effect=RuntimeError(exception_detail))
        service = MemoryIndexService(chunk_repo, embedding_service=embedding_service)
        caplog.set_level(logging.WARNING, logger="src.application.services.memory_index_service")

        created = await service.index_memory(
            memory_id="memory-index-secret-beta",
            content="Sensitive memory content for embedding",
            project_id="project-index-secret",
        )

        assert created == 1
        assert exception_detail not in caplog.text
        assert "error_type=RuntimeError" in caplog.text
