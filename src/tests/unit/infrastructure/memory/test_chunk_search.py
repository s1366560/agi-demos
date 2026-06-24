"""Tests for memory chunk hybrid search."""

import pytest

from src.infrastructure.memory.chunk_search import ChunkHybridSearch


@pytest.mark.unit
async def test_get_chunk_repo_failure_log_omits_exception_content(caplog) -> None:
    exception_detail = "session factory leaked postgres password chunk-repo-secret-9753"

    def _raise_session_error() -> object:
        raise RuntimeError(exception_detail)

    search = ChunkHybridSearch(
        embedding_service=object(),
        session_factory=_raise_session_error,
    )

    with caplog.at_level("WARNING", logger="src.infrastructure.memory.chunk_search"):
        chunk_repo = await search._get_chunk_repo()

    assert chunk_repo is None
    assert exception_detail not in caplog.text
    assert "chunk-repo-secret-9753" not in caplog.text
    assert "error_type=RuntimeError" in caplog.text
