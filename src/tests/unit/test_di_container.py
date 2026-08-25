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
    async def test_scoped_container_reuses_application_infrastructure(self, test_db):
        """Request clones reuse singleton infrastructure without graph state."""
        container = DIContainer(redis_client=Mock())

        scoped_container = container.with_db(test_db)

        assert scoped_container._db is test_db
        assert scoped_container._infra is container._infra
        assert not hasattr(scoped_container, "_graph_service")
