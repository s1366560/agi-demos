"""Tests for memory auto-recall prompt filtering."""

from dataclasses import dataclass

import pytest

from src.infrastructure.agent.memory.recall import MemoryRecallPreprocessor


@dataclass
class _ChunkResult:
    content: str
    score: float = 1.0
    category: str = "conversation"
    source_type: str = "chunk"
    source_id: str = "chunk-1"
    created_at: object | None = None


class _ChunkSearch:
    def __init__(self, results: list[_ChunkResult]) -> None:
        self._results = results

    async def search(
        self,
        query: str,
        project_id: str,
        max_results: int,
    ) -> list[_ChunkResult]:
        return self._results


class _FailingChunkSearch:
    def __init__(self, error: Exception) -> None:
        self._error = error

    async def search(
        self,
        query: str,
        project_id: str,
        max_results: int,
    ) -> list[_ChunkResult]:
        raise self._error


class _FailingGraphSearch:
    def __init__(self, error: Exception) -> None:
        self._error = error

    async def search(
        self,
        query: str,
        *,
        project_id: str,
        limit: int,
    ) -> list[object]:
        raise self._error


@pytest.mark.unit
async def test_recall_filters_workspace_task_bindings_from_other_workspaces() -> None:
    query = """Complete the assigned workspace task.

[workspace-task-binding]
workspace_id=current-workspace
workspace_task_id=task-current
[/workspace-task-binding]
"""
    old_workspace_memory = """[user] Complete the assigned workspace task.

[workspace-task-binding]
workspace_id=old-workspace
workspace_task_id=task-old
[/workspace-task-binding]

Old task details that should not bleed into the current worker.
"""
    current_workspace_memory = """[assistant] Progress report.

[workspace-task-binding]
workspace_id=current-workspace
workspace_task_id=task-current
[/workspace-task-binding]

Current task details.
"""
    generic_memory = "User prefers compact verification summaries."
    preprocessor = MemoryRecallPreprocessor(
        chunk_search=_ChunkSearch(
            [
                _ChunkResult(content=old_workspace_memory, score=0.99, source_id="old"),
                _ChunkResult(content=current_workspace_memory, score=0.9, source_id="current"),
                _ChunkResult(content=generic_memory, score=0.5, source_id="generic"),
            ]
        )
    )

    context = await preprocessor.recall(query, "project-1", max_results=3)

    assert context is not None
    assert "old-workspace" not in context
    assert "Current task details" in context
    assert generic_memory in context
    assert {result["source_id"] for result in preprocessor.last_results} == {"current", "generic"}


@pytest.mark.unit
async def test_recall_filters_workspace_task_memory_when_query_has_no_workspace_binding() -> None:
    workspace_memory = """[workspace-task-binding]
workspace_id=some-workspace
workspace_task_id=task-1
[/workspace-task-binding]

Prior task content.
"""
    generic_memory = "User prefers concise greetings."
    preprocessor = MemoryRecallPreprocessor(
        chunk_search=_ChunkSearch(
            [
                _ChunkResult(content=workspace_memory, score=0.99, source_id="workspace"),
                _ChunkResult(content=generic_memory, score=0.5, source_id="generic"),
            ]
        )
    )

    context = await preprocessor.recall("hi", "project-1")

    assert context is not None
    assert "Prior task content" not in context
    assert generic_memory in context
    assert {result["source_id"] for result in preprocessor.last_results} == {"generic"}


@pytest.mark.unit
async def test_recall_returns_none_when_unbound_query_only_matches_workspace_task_memory() -> None:
    workspace_memory = """[workspace-task-binding]
workspace_id=some-workspace
workspace_task_id=task-1
[/workspace-task-binding]

Prior task content.
"""
    preprocessor = MemoryRecallPreprocessor(
        chunk_search=_ChunkSearch([_ChunkResult(content=workspace_memory)])
    )

    context = await preprocessor.recall("hi", "project-1")

    assert context is None
    assert preprocessor.last_results == []


@pytest.mark.unit
async def test_recall_redacts_secret_like_memory_content_from_context_and_events() -> None:
    secret_value = "a" * 64
    token_value = "b" * 48
    memory = f"""EvoMap node credentials:
NODE_SECRET: {secret_value}
Current verified secret is {token_value}
Bearer abcdefghijklmnopqrstuvwxyz123456
Keep the node id and status context.
"""
    preprocessor = MemoryRecallPreprocessor(
        chunk_search=_ChunkSearch([_ChunkResult(content=memory)])
    )

    context = await preprocessor.recall("what is the node status?", "project-1")

    assert context is not None
    assert secret_value not in context
    assert token_value not in context
    assert "Bearer abcdefghijklmnopqrstuvwxyz123456" not in context
    assert "NODE_SECRET: [REDACTED]" in context
    assert "Current verified secret is [REDACTED]" in context
    assert "Bearer [REDACTED]" in context
    assert secret_value not in preprocessor.last_results[0]["content"]
    assert token_value not in preprocessor.last_results[0]["content"]


@pytest.mark.unit
async def test_search_chunks_failure_log_omits_query_and_exception_content(caplog) -> None:
    exception_detail = "chunk backend leaked recall query chunk-secret-1357"
    preprocessor = MemoryRecallPreprocessor(
        chunk_search=_FailingChunkSearch(RuntimeError(exception_detail))
    )

    with caplog.at_level("WARNING", logger="src.infrastructure.agent.memory.recall"):
        results = await preprocessor._search_chunks(
            query="find memory chunk-secret-1357",
            project_id="project-secret",
            max_results=3,
        )

    assert results == []
    assert exception_detail not in caplog.text
    assert "chunk-secret-1357" not in caplog.text
    assert "error_type=RuntimeError" in caplog.text


@pytest.mark.unit
async def test_search_graph_failure_log_omits_query_and_exception_content(caplog) -> None:
    exception_detail = "graph backend leaked recall query graph-secret-2468"
    preprocessor = MemoryRecallPreprocessor(
        graph_search=_FailingGraphSearch(RuntimeError(exception_detail))
    )

    with caplog.at_level("WARNING", logger="src.infrastructure.agent.memory.recall"):
        results = await preprocessor._search_graph(
            query="find memory graph-secret-2468",
            project_id="project-secret",
            max_results=3,
        )

    assert results == []
    assert exception_detail not in caplog.text
    assert "graph-secret-2468" not in caplog.text
    assert "error_type=RuntimeError" in caplog.text
