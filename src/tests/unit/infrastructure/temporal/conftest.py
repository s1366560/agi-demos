"""Pytest configuration and fixtures for Temporal tests."""

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def mock_neo4j_result():
    """Create a mock Neo4j query result."""
    result = MagicMock()
    result.records = []
    return result


@pytest.fixture
def mock_graph_service_factory():
    """Factory for creating mock graph services."""

    def _create(
        process_episode_result=None,
        extract_result=None,
        community_updater_enabled=True,
    ):
        service = MagicMock()
        service.client = MagicMock()
        service.client.execute_query = AsyncMock()

        # Process episode
        if process_episode_result is None:
            process_episode_result = MagicMock(nodes=[], edges=[])
        service.process_episode = AsyncMock(return_value=process_episode_result)

        # Entity extractor
        if extract_result is None:
            extract_result = MagicMock(entities=[])
        service._entity_extractor = MagicMock()
        service._entity_extractor.extract = AsyncMock(return_value=extract_result)

        # Community updater
        if community_updater_enabled:
            service.community_updater = MagicMock()
            service.community_updater.update_communities_for_entities = AsyncMock()
        else:
            service.community_updater = None

        return service

    return _create


@pytest.fixture
def mock_activity_info():
    """Create mock Temporal activity info."""
    info = MagicMock()
    info.workflow_id = "wf_test_default"
    info.workflow_run_id = "run_test_default"
    info.activity_id = "act_test_default"
    info.attempt = 1
    info.task_queue = "test-queue"
    return info


@pytest.fixture
def sample_episode_payload():
    """Create a sample episode processing payload."""
    return {
        "uuid": "ep_fixture_123",
        "content": "This is test content for the fixture episode.",
        "name": "Fixture Test Episode",
        "group_id": "proj_fixture",
        "project_id": "proj_fixture",
        "tenant_id": "tenant_fixture",
        "user_id": "user_fixture",
        "memory_id": "mem_fixture",
        "task_id": "task_fixture",
    }


@pytest.fixture
def sample_refresh_payload():
    """Create a sample incremental refresh payload."""
    return {
        "project_id": "proj_fixture",
        "tenant_id": "tenant_fixture",
        "user_id": "user_fixture",
        "episode_uuids": ["ep_1", "ep_2", "ep_3"],
        "rebuild_communities": False,
        "task_id": "task_refresh_fixture",
    }


@pytest.fixture
def mock_entity():
    """Create a mock entity."""

    def _create(uuid="entity_test", name="Test Entity"):
        entity = MagicMock()
        entity.uuid = uuid
        entity.name = name
        return entity

    return _create


@pytest.fixture
def mock_extraction_result(mock_entity):
    """Create a mock extraction result with entities."""

    def _create(entity_count=3):
        result = MagicMock()
        result.entities = [
            mock_entity(uuid=f"entity_{i}", name=f"Entity {i}") for i in range(entity_count)
        ]
        result.nodes = result.entities
        result.edges = []
        return result

    return _create
