import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from src.application.services.search_service import SearchService
from src.domain.model.memory.episode import Episode
from src.domain.model.memory.memory import Memory
from src.domain.ports.repositories.memory_repository import MemoryRepository
from src.tests._helpers import NullGraphStoreStub


class _GraphServiceStub(NullGraphStoreStub):
    def __init__(self, items: list[dict[str, Any]]) -> None:
        self._items = items
        self.search_calls: list[dict[str, Any]] = []

    async def add_episode(self, episode: Episode) -> Episode:
        return episode

    async def search(self, query: str, project_id: str | None = None, limit: int = 10) -> list[Any]:
        self.search_calls.append({"query": query, "project_id": project_id, "limit": limit})
        return self._items[:limit]

    async def get_graph_data(self, project_id: str, limit: int = 100) -> dict[str, Any]:
        return {"nodes": [], "edges": []}

    async def delete_episode(self, episode_name: str) -> bool:
        return True

    async def delete_episode_by_memory_id(self, memory_id: str) -> bool:
        return True

    async def remove_episode(self, episode_uuid: str) -> bool:
        return True


class _FailingGraphServiceStub(_GraphServiceStub):
    def __init__(self, error_message: str) -> None:
        super().__init__([])
        self._error_message = error_message

    async def search(self, query: str, project_id: str | None = None, limit: int = 10) -> list[Any]:
        raise RuntimeError(self._error_message)


class _FailingGraphDataServiceStub(_GraphServiceStub):
    def __init__(self, error_message: str) -> None:
        super().__init__([])
        self._error_message = error_message

    async def get_graph_data(self, project_id: str, limit: int = 100) -> dict[str, Any]:
        raise RuntimeError(self._error_message)


class _MemoryRepositoryStub(MemoryRepository):
    def __init__(self, memories: list[Memory]) -> None:
        self._memories = memories
        self.list_calls: list[dict[str, Any]] = []

    async def save(self, memory: Memory) -> Memory:
        self._memories.append(memory)
        return memory

    async def find_by_id(self, memory_id: str) -> Memory | None:
        return next((memory for memory in self._memories if memory.id == memory_id), None)

    async def list_by_project(
        self, project_id: str, limit: int = 50, offset: int = 0
    ) -> list[Memory]:
        self.list_calls.append({"project_id": project_id, "limit": limit, "offset": offset})
        project_memories = [memory for memory in self._memories if memory.project_id == project_id]
        return project_memories[offset : offset + limit]

    async def delete(self, memory_id: str) -> bool:
        before = len(self._memories)
        self._memories = [memory for memory in self._memories if memory.id != memory_id]
        return len(self._memories) != before


class _FailingMemoryRepositoryStub(_MemoryRepositoryStub):
    def __init__(self, error_message: str) -> None:
        super().__init__([])
        self._error_message = error_message

    async def list_by_project(
        self, project_id: str, limit: int = 50, offset: int = 0
    ) -> list[Memory]:
        raise RuntimeError(self._error_message)


def _episode(index: int) -> dict[str, Any]:
    return {
        "type": "episode",
        "uuid": f"episode-{index}",
        "name": f"Episode {index}",
        "content": f"Episode content {index}",
        "score": 1.0,
    }


def _entity(index: int) -> dict[str, Any]:
    return {
        "type": "entity",
        "uuid": f"entity-{index}",
        "name": f"Entity {index}",
        "summary": f"Entity summary {index}",
        "score": 1.0,
    }


def _memory(
    index: int, *, tags: list[str] | None = None, created_at: datetime | None = None
) -> Memory:
    return Memory(
        id=f"memory-{index}",
        project_id="project-1",
        title=f"Memory {index}",
        content=f"Memory content {index}",
        author_id="user-1",
        tags=tags or [],
        created_at=created_at or datetime(2026, 1, 1, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_search_fetches_requested_window_before_local_pagination() -> None:
    graph_service = _GraphServiceStub([_episode(i) if i % 2 == 0 else _entity(i) for i in range(6)])
    memory_repo = _MemoryRepositoryStub([])
    service = SearchService(graph_service=graph_service, memory_repo=memory_repo)

    results = await service.search("query", "project-1", limit=2, offset=4)

    assert graph_service.search_calls == [{"query": "query", "project_id": "project-1", "limit": 6}]
    assert [result.id for result in results.results] == ["episode-4", "entity-5"]
    assert results.total == 6


@pytest.mark.asyncio
async def test_search_fetches_extra_candidates_before_content_type_filtering() -> None:
    graph_service = _GraphServiceStub(
        [*[_episode(i) for i in range(4)], *[_entity(i) for i in range(4)]]
    )
    memory_repo = _MemoryRepositoryStub([])
    service = SearchService(graph_service=graph_service, memory_repo=memory_repo)

    results = await service.search(
        "query",
        "project-1",
        filters={"content_type": "entity"},
        limit=2,
        offset=2,
    )

    assert graph_service.search_calls == [{"query": "query", "project_id": "project-1", "limit": 8}]
    assert [result.id for result in results.results] == ["entity-2", "entity-3"]
    assert results.total == 4


@pytest.mark.asyncio
async def test_search_failure_logs_do_not_include_query_or_exception_content(caplog) -> None:
    secret_query = "find customer secret token alpha-12345"
    exception_detail = "graph backend leaked password beta-98765"
    graph_service = _FailingGraphServiceStub(exception_detail)
    memory_repo = _MemoryRepositoryStub([])
    service = SearchService(graph_service=graph_service, memory_repo=memory_repo)
    caplog.set_level(logging.ERROR, logger="src.application.services.search_service")

    with pytest.raises(RuntimeError):
        await service.search(secret_query, "project-1")

    assert secret_query not in caplog.text
    assert exception_detail not in caplog.text
    assert "error_type=RuntimeError" in caplog.text


@pytest.mark.asyncio
async def test_search_memories_by_tags_reads_additional_pages_until_limit() -> None:
    memories = [_memory(i, tags=["target"] if i in {55, 56} else []) for i in range(60)]
    memory_repo = _MemoryRepositoryStub(memories)
    service = SearchService(graph_service=_GraphServiceStub([]), memory_repo=memory_repo)

    results = await service.search_memories_by_tags(["target"], "project-1", limit=2)

    assert memory_repo.list_calls == [
        {"project_id": "project-1", "limit": 50, "offset": 0},
        {"project_id": "project-1", "limit": 50, "offset": 50},
    ]
    assert [result["id"] for result in results] == ["memory-55", "memory-56"]


@pytest.mark.asyncio
async def test_search_memories_by_tags_failure_logs_do_not_include_exception_content(
    caplog,
) -> None:
    exception_detail = "memory repo leaked private tag omega-24680"
    memory_repo = _FailingMemoryRepositoryStub(exception_detail)
    service = SearchService(graph_service=_GraphServiceStub([]), memory_repo=memory_repo)
    caplog.set_level(logging.ERROR, logger="src.application.services.search_service")

    with pytest.raises(RuntimeError):
        await service.search_memories_by_tags(["customer-secret-tag"], "project-1", limit=2)

    assert "customer-secret-tag" not in caplog.text
    assert exception_detail not in caplog.text
    assert "tag_count=1" in caplog.text
    assert "error_type=RuntimeError" in caplog.text


@pytest.mark.asyncio
async def test_search_by_date_range_reads_additional_pages_until_limit() -> None:
    old_date = datetime(2026, 1, 1, tzinfo=UTC)
    matching_date = datetime(2026, 1, 10, tzinfo=UTC)
    memories = [
        _memory(i, created_at=matching_date if i in {55, 56} else old_date) for i in range(60)
    ]
    memory_repo = _MemoryRepositoryStub(memories)
    service = SearchService(graph_service=_GraphServiceStub([]), memory_repo=memory_repo)

    results = await service.search_by_date_range(
        "project-1",
        date_from=matching_date - timedelta(days=1),
        date_to=matching_date + timedelta(days=1),
        limit=2,
    )

    assert memory_repo.list_calls == [
        {"project_id": "project-1", "limit": 50, "offset": 0},
        {"project_id": "project-1", "limit": 50, "offset": 50},
    ]
    assert [result["id"] for result in results] == ["memory-55", "memory-56"]


@pytest.mark.asyncio
async def test_search_by_date_range_failure_logs_do_not_include_exception_content(
    caplog,
) -> None:
    exception_detail = "memory repo leaked date search payload gamma-13579"
    memory_repo = _FailingMemoryRepositoryStub(exception_detail)
    service = SearchService(graph_service=_GraphServiceStub([]), memory_repo=memory_repo)
    caplog.set_level(logging.ERROR, logger="src.application.services.search_service")

    with pytest.raises(RuntimeError):
        await service.search_by_date_range(
            "project-1",
            date_from=datetime(2026, 1, 1, tzinfo=UTC),
            date_to=datetime(2026, 1, 2, tzinfo=UTC),
            limit=2,
        )

    assert exception_detail not in caplog.text
    assert "error_type=RuntimeError" in caplog.text


@pytest.mark.asyncio
async def test_get_graph_context_failure_logs_do_not_include_entity_or_exception_content(
    caplog,
) -> None:
    secret_entity_id = "entity-secret-alpha-2468"
    secret_project_id = "project-secret-beta-1357"
    service = SearchService(
        graph_service=_GraphServiceStub([]), memory_repo=_MemoryRepositoryStub([])
    )
    caplog.set_level(logging.ERROR, logger="src.application.services.search_service")

    with pytest.raises(ValueError):
        await service.get_graph_context(
            secret_entity_id,
            secret_project_id,
            depth=3,
            limit=7,
        )

    assert secret_entity_id not in caplog.text
    assert secret_project_id not in caplog.text
    assert "not found" not in caplog.text
    assert "depth=3" in caplog.text
    assert "limit=7" in caplog.text
    assert "error_type=ValueError" in caplog.text


@pytest.mark.asyncio
async def test_get_recent_activity_failure_logs_do_not_include_project_or_exception_content(
    caplog,
) -> None:
    secret_project_id = "project-secret-delta-8642"
    exception_detail = "graph activity leaked customer node epsilon-97531"
    service = SearchService(
        graph_service=_FailingGraphDataServiceStub(exception_detail),
        memory_repo=_MemoryRepositoryStub([]),
    )
    caplog.set_level(logging.ERROR, logger="src.application.services.search_service")

    with pytest.raises(RuntimeError):
        await service.get_recent_activity(secret_project_id, days=3, limit=7)

    assert secret_project_id not in caplog.text
    assert exception_detail not in caplog.text
    assert "days=3" in caplog.text
    assert "limit=7" in caplog.text
    assert "error_type=RuntimeError" in caplog.text
