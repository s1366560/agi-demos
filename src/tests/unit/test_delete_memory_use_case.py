import logging
from unittest.mock import AsyncMock, Mock

import pytest

from src.application.use_cases.memory.delete_memory import DeleteMemoryCommand, DeleteMemoryUseCase
from src.domain.model.memory.memory import Memory
from src.domain.ports.repositories.memory_repository import MemoryRepository
from src.domain.ports.services.graph_service_port import GraphServicePort


@pytest.fixture
def mock_repo():
    return Mock(spec=MemoryRepository)


@pytest.fixture
def mock_graph_service():
    return Mock(spec=GraphServicePort)


@pytest.mark.asyncio
async def test_delete_memory_graph_failure_is_graceful_and_quiet(
    mock_repo, mock_graph_service, caplog, capsys
):
    use_case = DeleteMemoryUseCase(mock_repo, mock_graph_service)
    memory = Memory(
        id="memory-123",
        project_id="project-123",
        title="Sensitive Memory",
        content="Sensitive content",
        author_id="user-123",
    )
    mock_repo.find_by_id = AsyncMock(return_value=memory)
    mock_repo.delete = AsyncMock()
    mock_graph_service.delete_episode_by_memory_id = AsyncMock(
        side_effect=Exception("Graph delete leaked sensitive content")
    )
    caplog.set_level(
        logging.WARNING,
        logger="src.application.use_cases.memory.delete_memory",
    )

    await use_case.execute(DeleteMemoryCommand(memory_id=memory.id))

    mock_graph_service.delete_episode_by_memory_id.assert_awaited_once_with(memory.id)
    mock_repo.delete.assert_awaited_once_with(memory.id)
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Graph delete leaked sensitive content" not in caplog.text
    assert "Failed to delete memory from Graphiti" in caplog.text
