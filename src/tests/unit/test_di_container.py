"""
Unit tests for DI Container.
"""

from unittest.mock import Mock

import pytest

from src.configuration.di_container import DIContainer


@pytest.mark.unit
class TestDIContainer:
    """Test cases for DIContainer dependency injection."""

    @pytest.mark.parametrize(
        "accessor",
        [
            "tool_execution_record_repository",
            "context_summary_adapter",
            "hitl_request_repository",
            "skill_repository",
            "subagent_repository",
            "agent_binding_repository",
            "agent_orchestrator",
            "graph_repository",
            "graph_orchestrator",
            "create_conversation_use_case",
            "list_conversations_use_case",
            "get_conversation_use_case",
        ],
    )
    def test_retired_business_facade_is_absent(self, accessor: str) -> None:
        assert not hasattr(DIContainer, accessor)

    @pytest.mark.asyncio
    async def test_scoped_container_reuses_application_infrastructure(self, test_db):
        """Request clones reuse singleton infrastructure without graph state."""
        container = DIContainer(redis_client=Mock())

        scoped_container = container.with_db(test_db)

        assert scoped_container._db is test_db
        assert scoped_container._infra is container._infra
        assert not hasattr(scoped_container, "_graph_service")
