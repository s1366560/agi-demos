from unittest.mock import AsyncMock, Mock

import pytest

from src.application.use_cases.memory.create_memory import CreateMemoryCommand, CreateMemoryUseCase
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
async def test_create_memory_success(mock_repo, mock_graph_service):
    # Arrange
    use_case = CreateMemoryUseCase(mock_repo, mock_graph_service)
    command = CreateMemoryCommand(
        project_id="proj_123",
        title="Test Memory",
        content="Test Content",
        author_id="user_123",
        tenant_id="tenant_123",
        tags=["tag1"],
        entities=[{"name": "Entity1"}],
    )

    mock_repo.save = AsyncMock()
    mock_graph_service.add_episode = AsyncMock()

    # Act
    memory = await use_case.execute(command)

    # Assert
    assert isinstance(memory, Memory)
    assert memory.title == "Test Memory"
    assert memory.status == "ENABLED"
    assert memory.processing_status == "PENDING"
    assert memory.project_id == "proj_123"

    # Verify repository call
    mock_repo.save.assert_called_once()
    saved_memory = mock_repo.save.call_args[0][0]
    assert saved_memory.title == "Test Memory"

    # Verify graph service call
    mock_graph_service.add_episode.assert_called_once()
    episode = mock_graph_service.add_episode.call_args[0][0]
    assert episode.content == "Test Content"
    assert episode.metadata["memory_id"] == memory.id


@pytest.mark.asyncio
async def test_create_memory_graph_failure_is_graceful(mock_repo, mock_graph_service):
    # Arrange
    use_case = CreateMemoryUseCase(mock_repo, mock_graph_service)
    command = CreateMemoryCommand(
        project_id="proj_123",
        title="Test Memory",
        content="Test Content",
        author_id="user_123",
        tenant_id="tenant_123",
    )

    mock_repo.save = AsyncMock()
    mock_graph_service.add_episode = AsyncMock(side_effect=Exception("Graph Error"))

    # Act
    # Should not raise exception
    memory = await use_case.execute(command)

    # Assert
    assert memory.id is not None
    mock_repo.save.assert_called_once()
    mock_graph_service.add_episode.assert_called_once()
