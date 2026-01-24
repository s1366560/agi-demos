"""
Unit tests for DI Container.
"""

from unittest.mock import Mock

import pytest

from src.configuration.di_container import DIContainer


@pytest.mark.unit
class TestDIContainer:
    """Test cases for DIContainer dependency injection."""

    @pytest.mark.asyncio
    async def test_create_task_use_case(self, test_db):
        """Test creating task use case."""
        container = DIContainer(test_db)
        use_case = container.create_task_use_case()

        assert use_case is not None
        assert use_case._task_repo is not None

    @pytest.mark.asyncio
    async def test_create_memory_use_case(self, test_db):
        """Test creating memory use case."""
        mock_graph_service = Mock()
        container = DIContainer(test_db, graph_service=mock_graph_service)
        use_case = container.create_memory_use_case()

        assert use_case is not None
        assert use_case._memory_repo is not None

    @pytest.mark.asyncio
    async def test_container_with_graph_service(self, test_db):
        """Test container with graph service."""
        mock_graph = Mock()
        container = DIContainer(test_db, graph_service=mock_graph)

        # Graph service should be stored
        assert container._graph_service == mock_graph
