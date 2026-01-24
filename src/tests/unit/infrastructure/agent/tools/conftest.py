"""Shared fixtures for agent tools tests."""

from unittest.mock import AsyncMock, Mock

import pytest


@pytest.fixture
def mock_graph_service():
    """Create a mock graph service."""
    service = AsyncMock()
    service.search = AsyncMock(return_value=[])
    service.add_episode = AsyncMock()
    return service


@pytest.fixture
def mock_graphiti_client():
    """Create a mock Graphiti client with Neo4j driver."""
    client = Mock()
    client.driver = Mock()
    client.driver.execute_query = AsyncMock(return_value=[])
    return client


@pytest.fixture
def mock_llm():
    """Create a mock LLM for SummaryTool."""
    llm = AsyncMock()
    mock_response = Mock()
    mock_response.content = "This is a test summary."
    llm.ainvoke = AsyncMock(return_value=mock_response)
    return llm


@pytest.fixture
def mock_redis_client():
    """Create a mock Redis client for WebSearchTool."""
    client = AsyncMock()
    client.get = AsyncMock(return_value=None)
    client.setex = AsyncMock()
    return client
