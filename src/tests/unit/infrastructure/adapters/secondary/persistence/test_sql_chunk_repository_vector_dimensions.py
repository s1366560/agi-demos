"""Tests for pgvector dimension guards in chunk search queries."""

from __future__ import annotations

from typing import Any

import pytest

from src.infrastructure.adapters.secondary.persistence.sql_chunk_repository import (
    SqlChunkRepository,
)


class _EmptyResult:
    def fetchall(self) -> list[Any]:
        return []


class _CaptureSession:
    def __init__(self) -> None:
        self.statements: list[str] = []

    async def execute(self, statement: Any, *_args: Any, **_kwargs: Any) -> _EmptyResult:
        self.statements.append(str(statement))
        return _EmptyResult()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_vector_search_filters_rows_by_embedding_dimension() -> None:
    session = _CaptureSession()
    repo = SqlChunkRepository(session)  # type: ignore[arg-type]

    await repo.vector_search([0.1, 0.2], project_id="project-1")

    assert "vector_dims(embedding) = vector_dims(CAST(:qvec_dims AS vector))" in session.statements[0]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_find_similar_filters_rows_by_embedding_dimension() -> None:
    session = _CaptureSession()
    repo = SqlChunkRepository(session)  # type: ignore[arg-type]

    await repo.find_similar([0.1, 0.2], project_id="project-1")

    assert "vector_dims(embedding) = vector_dims(CAST(:qvec_dims AS vector))" in session.statements[0]
