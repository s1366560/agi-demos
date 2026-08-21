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
    async def test_scoped_container_reuses_application_infrastructure(self, test_db):
        """Request clones reuse singleton infrastructure without graph state."""
        container = DIContainer(redis_client=Mock())

        scoped_container = container.with_db(test_db)

        assert scoped_container._db is test_db
        assert scoped_container._infra is container._infra
        assert not hasattr(scoped_container, "_graph_service")

    @pytest.mark.asyncio
    async def test_workspace_orchestrator_is_retired_when_scoped_with_db(self, test_db):
        scoped_container = DIContainer().with_db(test_db)

        with pytest.raises(RuntimeError, match="Avernet Workspace Core"):
            scoped_container.workspace_orchestrator()
