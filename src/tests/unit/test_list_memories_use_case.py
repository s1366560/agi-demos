from unittest.mock import AsyncMock, Mock

import pytest

from src.application.use_cases.memory.list_memories import (
    ListMemoriesQuery,
    ListMemoriesUseCase,
)
from src.domain.ports.repositories.memory_repository import MemoryRepository


@pytest.fixture
def mock_repo() -> Mock:
    return Mock(spec=MemoryRepository)


@pytest.mark.asyncio
async def test_list_memories_without_search_lists_project(mock_repo: Mock) -> None:
    mock_repo.list_by_project = AsyncMock(return_value=[])
    use_case = ListMemoriesUseCase(mock_repo)

    result = await use_case.execute(ListMemoriesQuery(project_id="proj-1", limit=25, offset=5))

    assert result == []
    mock_repo.list_by_project.assert_awaited_once_with(project_id="proj-1", limit=25, offset=5)


@pytest.mark.asyncio
async def test_list_memories_with_search_uses_repository_search(mock_repo: Mock) -> None:
    mock_repo.search_by_project = AsyncMock(return_value=[])
    use_case = ListMemoriesUseCase(mock_repo)

    result = await use_case.execute(
        ListMemoriesQuery(project_id="proj-1", search="  retention  ", limit=10, offset=2)
    )

    assert result == []
    mock_repo.search_by_project.assert_awaited_once_with(
        project_id="proj-1", search="retention", limit=10, offset=2
    )


@pytest.mark.asyncio
async def test_list_memories_with_blank_search_lists_project(mock_repo: Mock) -> None:
    mock_repo.list_by_project = AsyncMock(return_value=[])
    use_case = ListMemoriesUseCase(mock_repo)

    result = await use_case.execute(ListMemoriesQuery(project_id="proj-1", search="   "))

    assert result == []
    mock_repo.list_by_project.assert_awaited_once_with(project_id="proj-1", limit=50, offset=0)
