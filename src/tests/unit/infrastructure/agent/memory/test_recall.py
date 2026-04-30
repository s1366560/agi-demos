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
async def test_recall_keeps_workspace_task_memory_when_query_has_no_workspace_binding() -> None:
    workspace_memory = """[workspace-task-binding]
workspace_id=some-workspace
workspace_task_id=task-1
[/workspace-task-binding]

Prior task content.
"""
    preprocessor = MemoryRecallPreprocessor(
        chunk_search=_ChunkSearch([_ChunkResult(content=workspace_memory)])
    )

    context = await preprocessor.recall("summarize prior workspace work", "project-1")

    assert context is not None
    assert "Prior task content" in context
