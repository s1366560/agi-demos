"""Unit tests for NativeGraphAdapter."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.domain.model.memory.episode import Episode, SourceType
from src.infrastructure.graph.native_graph_adapter import NativeGraphAdapter
from src.infrastructure.graph.schemas import HybridSearchResult, SearchResultItem


@pytest.fixture
def mock_neo4j_client():
    """Create a mock Neo4j client."""
    client = MagicMock()
    client.execute_query = AsyncMock()
    client.save_node = AsyncMock()
    client.save_edge = AsyncMock()
    client.find_node_by_uuid = AsyncMock(return_value=None)
    client.driver = MagicMock()
    return client


@pytest.fixture
def mock_llm_client():
    """Create a mock LLM client."""
    client = MagicMock()
    client.generate_response = AsyncMock(return_value='{"entities": []}')
    return client


@pytest.fixture
def mock_embedding_service():
    """Create a mock embedding service."""
    service = MagicMock()
    service.embedding_dim = 768
    service.embed_text = AsyncMock(return_value=[0.1] * 768)
    service.embed_batch = AsyncMock(return_value=[[0.1] * 768])
    return service


@pytest.fixture
def mock_queue_port():
    """Create a mock queue port."""
    port = MagicMock()
    port.add_episode = AsyncMock()
    return port


@pytest.fixture
def adapter(mock_neo4j_client, mock_llm_client, mock_embedding_service, mock_queue_port):
    """Create NativeGraphAdapter with mocked dependencies."""
    return NativeGraphAdapter(
        neo4j_client=mock_neo4j_client,
        llm_client=mock_llm_client,
        embedding_service=mock_embedding_service,
        queue_port=mock_queue_port,
        enable_reflexion=False,
    )


@pytest.mark.unit
class TestNativeGraphAdapterInit:
    """Tests for NativeGraphAdapter initialization."""

    def test_adapter_creation(self, mock_neo4j_client, mock_llm_client, mock_embedding_service):
        """Test creating adapter with required dependencies."""
        adapter = NativeGraphAdapter(
            neo4j_client=mock_neo4j_client,
            llm_client=mock_llm_client,
            embedding_service=mock_embedding_service,
        )

        assert adapter._neo4j_client is mock_neo4j_client
        assert adapter._llm_client is mock_llm_client
        assert adapter._embedding_service is mock_embedding_service
        assert adapter._queue_port is None
        assert adapter._enable_reflexion is True


@pytest.mark.unit
class TestNativeGraphAdapterProperties:
    """Tests for adapter properties."""

    def test_client_property(self, adapter, mock_neo4j_client):
        """Test client property returns Neo4j client."""
        assert adapter.client is mock_neo4j_client

    def test_driver_property(self, adapter, mock_neo4j_client):
        """Test driver property returns Neo4j driver."""
        assert adapter.driver is mock_neo4j_client.driver

    def test_embedder_property(self, adapter, mock_embedding_service):
        """Test embedder property returns embedding service."""
        assert adapter.embedder is mock_embedding_service


@pytest.mark.unit
class TestNativeGraphAdapterAddEpisode:
    """Tests for add_episode method."""

    @pytest.mark.asyncio
    async def test_add_episode_success(self, adapter, mock_neo4j_client, mock_queue_port):
        """Test adding episode successfully."""
        mock_neo4j_client.execute_query.return_value = MagicMock(records=[])

        episode = Episode(
            id=str(uuid4()),
            content="Test episode content",
            source_type=SourceType.TEXT,
            valid_at=datetime.now(timezone.utc),
            tenant_id="tenant-1",
            project_id="project-1",
            user_id="user-1",
            metadata={"memory_id": "mem-1"},
        )

        result = await adapter.add_episode(episode)

        assert result is episode
        mock_neo4j_client.execute_query.assert_called()
        mock_queue_port.add_episode.assert_called_once()


@pytest.mark.unit
class TestNativeGraphAdapterSearch:
    """Tests for search method."""

    @pytest.mark.asyncio
    async def test_search_returns_results(self, adapter):
        """Test search returns formatted results."""
        mock_search_result = HybridSearchResult(
            items=[
                SearchResultItem(
                    type="entity",
                    uuid="entity-1",
                    name="Test Entity",
                    summary="A test entity",
                    score=0.9,
                ),
                SearchResultItem(
                    type="episode",
                    uuid="episode-1",
                    content="Test content",
                    score=0.8,
                ),
            ],
            total_results=2,
        )

        with patch.object(adapter, "_get_hybrid_search") as mock_get_search:
            mock_search = MagicMock()
            mock_search.search = AsyncMock(return_value=mock_search_result)
            mock_get_search.return_value = mock_search

            results = await adapter.search("test query", project_id="proj-1", limit=10)

            assert len(results) == 2
            assert results[0]["type"] == "entity"
            assert results[0]["name"] == "Test Entity"


@pytest.mark.unit
class TestNativeGraphAdapterDeleteEpisode:
    """Tests for delete_episode methods."""

    @pytest.mark.asyncio
    async def test_delete_episode_by_name(self, adapter, mock_neo4j_client):
        """Test deleting episode by name."""
        mock_neo4j_client.execute_query.return_value = MagicMock()

        result = await adapter.delete_episode("test-episode")

        assert result is True
        mock_neo4j_client.execute_query.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_episode_by_memory_id(self, adapter, mock_neo4j_client):
        """Test deleting episode by memory_id."""
        mock_neo4j_client.execute_query.return_value = MagicMock()

        result = await adapter.delete_episode_by_memory_id("memory-123")

        assert result is True


@pytest.mark.unit
class TestNativeGraphAdapterRemoveEpisode:
    """Tests for remove_episode methods."""

    @pytest.mark.asyncio
    async def test_remove_episode(self, adapter, mock_neo4j_client):
        """Test removing episode with cleanup."""
        mock_neo4j_client.execute_query.return_value = MagicMock(
            summary=MagicMock(counters=MagicMock(relationships_deleted=0))
        )

        result = await adapter.remove_episode("episode-uuid-123")

        assert result is True
        assert mock_neo4j_client.execute_query.call_count >= 3
