"""Unit tests for HybridSearch."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from src.infrastructure.graph.search.hybrid_search import (
    HybridSearch,
    DEFAULT_RRF_K,
    DEFAULT_VECTOR_WEIGHT,
    DEFAULT_KEYWORD_WEIGHT,
)
from src.infrastructure.graph.schemas import HybridSearchResult, SearchResultItem


@pytest.fixture
def mock_neo4j_client():
    """Create mock Neo4j client."""
    client = MagicMock()
    client.execute_query = AsyncMock()
    client.execute_read = AsyncMock()
    return client


@pytest.fixture
def mock_embedding_service():
    """Create mock embedding service."""
    service = MagicMock()
    service.embed_text = AsyncMock(return_value=[0.1] * 768)
    service.embedding_dim = 768
    return service


@pytest.fixture
def hybrid_search(mock_neo4j_client, mock_embedding_service):
    """Create HybridSearch instance with mocked dependencies."""
    return HybridSearch(
        neo4j_client=mock_neo4j_client,
        embedding_service=mock_embedding_service,
    )


@pytest.fixture
def sample_entity_result():
    """Create sample entity search result."""
    return SearchResultItem(
        id="entity-1",
        type="entity",
        name="Test Entity",
        summary="A test entity summary",
        content="Full content here",
        score=0.9,
        project_id="proj-1",
        created_at=datetime.utcnow(),
    )


@pytest.fixture
def sample_episode_result():
    """Create sample episode search result."""
    return SearchResultItem(
        id="episode-1",
        type="episode",
        name="Test Episode",
        summary="A test episode summary",
        content="Episode content here",
        score=0.8,
        project_id="proj-1",
        created_at=datetime.utcnow(),
    )


class TestHybridSearch:
    """Tests for HybridSearch."""

    @pytest.mark.unit
    async def test_search_empty_query_returns_empty_result(self, hybrid_search):
        """Test empty query returns empty result."""
        result = await hybrid_search.search("")

        assert result.total_results == 0
        assert result.items == []

    @pytest.mark.unit
    async def test_search_whitespace_query_returns_empty_result(self, hybrid_search):
        """Test whitespace-only query returns empty result."""
        result = await hybrid_search.search("   ")

        assert result.total_results == 0
        assert result.items == []

    @pytest.mark.unit
    def test_rrf_fusion_single_list(self, hybrid_search, sample_entity_result):
        """Test RRF fusion with single result list."""
        results = [sample_entity_result]

        fused = hybrid_search._rrf_fusion(results, [])

        assert len(fused) == 1
        assert fused[0].id == sample_entity_result.id

    @pytest.mark.unit
    def test_rrf_fusion_combines_scores(self, hybrid_search):
        """Test RRF fusion properly combines scores."""
        item1 = SearchResultItem(
            id="item-1",
            type="entity",
            name="Item 1",
            score=0.9,
            project_id="p1",
            created_at=datetime.utcnow(),
        )
        item2 = SearchResultItem(
            id="item-2",
            type="entity",
            name="Item 2",
            score=0.8,
            project_id="p1",
            created_at=datetime.utcnow(),
        )

        # Same items in both lists
        vector_results = [item1, item2]
        keyword_results = [item1, item2]

        fused = hybrid_search._rrf_fusion(vector_results, keyword_results)

        # Should have 2 unique items
        assert len(fused) == 2
        # Item appearing in both lists should have higher combined score
        assert fused[0].score > 0

    @pytest.mark.unit
    def test_rrf_fusion_different_items(self, hybrid_search):
        """Test RRF fusion with completely different items."""
        vector_item = SearchResultItem(
            id="vector-item",
            type="entity",
            name="Vector Item",
            score=0.9,
            project_id="p1",
            created_at=datetime.utcnow(),
        )
        keyword_item = SearchResultItem(
            id="keyword-item",
            type="entity",
            name="Keyword Item",
            score=0.8,
            project_id="p1",
            created_at=datetime.utcnow(),
        )

        fused = hybrid_search._rrf_fusion([vector_item], [keyword_item])

        assert len(fused) == 2

    @pytest.mark.unit
    def test_rrf_fusion_respects_weights(self, hybrid_search):
        """Test RRF fusion respects custom weights."""
        # Create new instance with different weights
        hybrid_search._vector_weight = 0.8
        hybrid_search._keyword_weight = 0.2

        vector_item = SearchResultItem(
            id="item-1",
            type="entity",
            name="Item",
            score=0.9,
            project_id="p1",
            created_at=datetime.utcnow(),
        )
        keyword_item = SearchResultItem(
            id="item-2",
            type="entity",
            name="Item 2",
            score=0.9,
            project_id="p1",
            created_at=datetime.utcnow(),
        )

        fused = hybrid_search._rrf_fusion([vector_item], [keyword_item])

        # With vector_weight=0.8, vector item should rank higher
        assert fused[0].id == "item-1"

    @pytest.mark.unit
    async def test_vector_search_calls_embedding_service(
        self, hybrid_search, mock_embedding_service, mock_neo4j_client
    ):
        """Test vector search calls embedding service."""
        mock_neo4j_client.execute_read.return_value = []

        await hybrid_search.vector_search("test query")

        mock_embedding_service.embed_text.assert_called_once_with("test query")

    @pytest.mark.unit
    async def test_search_limits_results(self, hybrid_search):
        """Test search respects limit parameter."""
        # Create many mock results
        mock_results = [
            SearchResultItem(
                id=f"item-{i}",
                type="entity",
                name=f"Item {i}",
                score=0.9 - (i * 0.01),
                project_id="p1",
                created_at=datetime.utcnow(),
            )
            for i in range(20)
        ]

        with patch.object(
            hybrid_search, "_vector_search_entities", return_value=mock_results[:10]
        ):
            with patch.object(
                hybrid_search, "_keyword_search_entities", return_value=mock_results[10:]
            ):
                with patch.object(
                    hybrid_search, "_keyword_search_episodes", return_value=[]
                ):
                    result = await hybrid_search.search("test", limit=5)

        assert len(result.items) == 5

    @pytest.mark.unit
    async def test_search_handles_search_errors_gracefully(
        self, hybrid_search, mock_embedding_service
    ):
        """Test search handles errors from individual searches."""
        mock_embedding_service.embed_text.side_effect = RuntimeError("Embedding failed")

        with patch.object(
            hybrid_search,
            "_keyword_search_entities",
            return_value=[],
        ):
            with patch.object(
                hybrid_search,
                "_keyword_search_episodes",
                return_value=[],
            ):
                # Should not raise, just log warning
                result = await hybrid_search.search("test")

        # Should return empty or partial results, not raise
        assert isinstance(result, HybridSearchResult)

    @pytest.mark.unit
    def test_default_parameters(self, hybrid_search):
        """Test default parameters are set correctly."""
        assert hybrid_search._rrf_k == DEFAULT_RRF_K
        assert hybrid_search._vector_weight == DEFAULT_VECTOR_WEIGHT
        assert hybrid_search._keyword_weight == DEFAULT_KEYWORD_WEIGHT

    @pytest.mark.unit
    async def test_search_excludes_episodes_when_disabled(self, hybrid_search):
        """Test search excludes episodes when include_episodes=False."""
        with patch.object(
            hybrid_search, "_vector_search_entities", return_value=[]
        ) as mock_vec:
            with patch.object(
                hybrid_search, "_keyword_search_entities", return_value=[]
            ) as mock_kw_ent:
                with patch.object(
                    hybrid_search, "_keyword_search_episodes", return_value=[]
                ) as mock_kw_ep:
                    await hybrid_search.search(
                        "test", include_episodes=False, include_entities=True
                    )

        # Episode search should not be called
        mock_kw_ep.assert_not_called()

    @pytest.mark.unit
    async def test_search_excludes_entities_when_disabled(self, hybrid_search):
        """Test search excludes entities when include_entities=False."""
        with patch.object(
            hybrid_search, "_vector_search_entities", return_value=[]
        ) as mock_vec:
            with patch.object(
                hybrid_search, "_keyword_search_entities", return_value=[]
            ) as mock_kw_ent:
                with patch.object(
                    hybrid_search, "_keyword_search_episodes", return_value=[]
                ) as mock_kw_ep:
                    await hybrid_search.search(
                        "test", include_episodes=True, include_entities=False
                    )

        # Entity searches should not be called
        mock_vec.assert_not_called()
        mock_kw_ent.assert_not_called()
