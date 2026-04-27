"""
Unit tests for DI Container.
"""

from unittest.mock import Mock

import pytest

from src.configuration.di_container import DIContainer
from src.infrastructure.adapters.secondary.persistence.sql_plan_repository import SqlPlanRepository
from src.infrastructure.agent.workspace_plan.repository import InMemoryPlanRepository


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

    @pytest.mark.asyncio
    async def test_workspace_orchestrator_uses_sql_repository_when_scoped_with_db(self, test_db):
        """Workspace V2 should use the durable SQL path in request-scoped containers."""
        scoped_container = DIContainer().with_db(test_db)
        orchestrator = scoped_container.workspace_orchestrator()

        assert isinstance(orchestrator._repo, SqlPlanRepository)
        assert not isinstance(orchestrator._repo, InMemoryPlanRepository)
