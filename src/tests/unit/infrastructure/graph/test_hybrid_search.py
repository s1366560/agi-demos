"""Unit tests for HybridSearch."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.infrastructure.graph.schemas import HybridSearchResult, SearchResultItem
from src.infrastructure.graph.search.hybrid_search import (
    DEFAULT_KEYWORD_WEIGHT,
    DEFAULT_RRF_K,
    DEFAULT_VECTOR_WEIGHT,
    GraphSearchConfig,
    HybridSearch,
    _dict_to_item,
    _item_to_dict,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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
def default_config():
    """Create default GraphSearchConfig with all features enabled."""
    return GraphSearchConfig()


@pytest.fixture
def disabled_config():
    """Create GraphSearchConfig with all features disabled."""
    return GraphSearchConfig(
        enable_mmr=False,
        enable_temporal_decay=False,
        enable_query_expansion=False,
    )


@pytest.fixture
def hybrid_search(mock_neo4j_client, mock_embedding_service):
    """Create HybridSearch instance with mocked dependencies and defaults."""
    return HybridSearch(
        neo4j_client=mock_neo4j_client,
        embedding_service=mock_embedding_service,
    )


@pytest.fixture
def hybrid_search_no_enhancements(mock_neo4j_client, mock_embedding_service, disabled_config):
    """Create HybridSearch instance with all enhancements disabled."""
    return HybridSearch(
        neo4j_client=mock_neo4j_client,
        embedding_service=mock_embedding_service,
        search_config=disabled_config,
    )


def _make_entity(uuid: str, name: str, summary: str, score: float, **meta) -> SearchResultItem:
    """Helper to create a valid entity SearchResultItem."""
    return SearchResultItem(
        type="entity",
        uuid=uuid,
        name=name,
        summary=summary,
        score=score,
        metadata=meta,
    )


def _make_episode(uuid: str, name: str, content: str, score: float, **meta) -> SearchResultItem:
    """Helper to create a valid episode SearchResultItem."""
    return SearchResultItem(
        type="episode",
        uuid=uuid,
        name=name,
        content=content,
        score=score,
        metadata=meta,
    )


# ---------------------------------------------------------------------------
# TestGraphSearchConfig
# ---------------------------------------------------------------------------


class TestGraphSearchConfig:
    """Tests for GraphSearchConfig dataclass."""

    @pytest.mark.unit
    def test_defaults(self):
        """All enhancements enabled by default."""
        cfg = GraphSearchConfig()
        assert cfg.enable_mmr is True
        assert cfg.mmr_lambda == 0.7
        assert cfg.enable_temporal_decay is True
        assert cfg.temporal_half_life_days == 30.0
        assert cfg.enable_query_expansion is True

    @pytest.mark.unit
    def test_custom_values(self):
        """Custom values are accepted."""
        cfg = GraphSearchConfig(
            enable_mmr=False,
            mmr_lambda=0.5,
            enable_temporal_decay=False,
            temporal_half_life_days=7.0,
            enable_query_expansion=False,
        )
        assert cfg.enable_mmr is False
        assert cfg.mmr_lambda == 0.5
        assert cfg.temporal_half_life_days == 7.0


# ---------------------------------------------------------------------------
# TestItemConversion
# ---------------------------------------------------------------------------


class TestItemConversion:
    """Tests for _item_to_dict / _dict_to_item round-trip."""

    @pytest.mark.unit
    def test_entity_round_trip(self):
        """Entity item survives dict conversion round-trip."""
        item = _make_entity("e1", "Entity One", "A summary", 0.85, search_type="vector")
        d = _item_to_dict(item)

        assert d["uuid"] == "e1"
        assert d["type"] == "entity"
        assert d["content"] == "A summary"  # falls back to summary for entity
        assert d["score"] == 0.85

        restored = _dict_to_item(d)
        assert restored.uuid == "e1"
        assert restored.type == "entity"
        assert restored.summary == "A summary"
        assert restored.content is None  # entity -> content cleared

    @pytest.mark.unit
    def test_episode_round_trip(self):
        """Episode item survives dict conversion round-trip."""
        item = _make_episode("ep1", "Episode One", "Full content here", 0.75)
        d = _item_to_dict(item)

        assert d["content"] == "Full content here"

        restored = _dict_to_item(d)
        assert restored.uuid == "ep1"
        assert restored.content == "Full content here"
        assert restored.summary is None  # episode -> summary cleared

    @pytest.mark.unit
    def test_entity_content_fallback_chain(self):
        """Entity with no summary falls back to name for content field."""
        item = SearchResultItem(type="entity", uuid="e2", name="Named Only", score=0.5, metadata={})
        d = _item_to_dict(item)
        assert d["content"] == "Named Only"

    @pytest.mark.unit
    def test_entity_all_none_content(self):
        """Entity with nothing falls back to empty string."""
        item = SearchResultItem(type="entity", uuid="e3", score=0.5, metadata={})
        d = _item_to_dict(item)
        assert d["content"] == ""


# ---------------------------------------------------------------------------
# TestHybridSearch (basic / existing)
# ---------------------------------------------------------------------------


class TestHybridSearch:
    """Tests for HybridSearch core functionality."""

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
    def test_rrf_fusion_single_list(self, hybrid_search):
        """Test RRF fusion with single result list."""
        item = _make_entity("entity-1", "Test Entity", "summary", 0.9)
        fused = hybrid_search._rrf_fusion([item], [])
        assert len(fused) == 1
        assert fused[0].uuid == "entity-1"

    @pytest.mark.unit
    def test_rrf_fusion_combines_scores(self, hybrid_search):
        """Test RRF fusion properly combines scores from both lists."""
        item1 = _make_entity("item-1", "Item 1", "s1", 0.9)
        item2 = _make_entity("item-2", "Item 2", "s2", 0.8)

        fused = hybrid_search._rrf_fusion([item1, item2], [item1, item2])
        assert len(fused) == 2
        assert fused[0].score > 0

    @pytest.mark.unit
    def test_rrf_fusion_different_items(self, hybrid_search):
        """Test RRF fusion with completely different items."""
        vec = _make_entity("vec-item", "Vector Item", "s", 0.9)
        kw = _make_entity("kw-item", "Keyword Item", "s", 0.8)

        fused = hybrid_search._rrf_fusion([vec], [kw])
        assert len(fused) == 2

    @pytest.mark.unit
    def test_rrf_fusion_respects_weights(self, hybrid_search):
        """Test RRF fusion respects custom weights."""
        hybrid_search._vector_weight = 0.8
        hybrid_search._keyword_weight = 0.2

        vec = _make_entity("item-1", "Item", "s", 0.9)
        kw = _make_entity("item-2", "Item 2", "s", 0.9)

        fused = hybrid_search._rrf_fusion([vec], [kw])
        assert fused[0].uuid == "item-1"

    @pytest.mark.unit
    async def test_vector_search_calls_embedding_service(
        self, hybrid_search, mock_embedding_service, mock_neo4j_client
    ):
        """Test vector search calls embedding service."""
        mock_result = MagicMock()
        mock_result.records = []
        mock_neo4j_client.execute_query.return_value = mock_result

        await hybrid_search.vector_search("test query")
        mock_embedding_service.embed_text.assert_called_once_with("test query")

    @pytest.mark.unit
    async def test_search_limits_results(self, hybrid_search):
        """Test search respects limit parameter."""
        items = [
            _make_entity(f"item-{i}", f"Item {i}", f"summary {i}", 0.9 - (i * 0.01))
            for i in range(20)
        ]

        with (
            patch.object(hybrid_search, "_vector_search_entities", return_value=items[:10]),
            patch.object(hybrid_search, "_keyword_search_entities", return_value=items[10:]),
            patch.object(hybrid_search, "_keyword_search_episodes", return_value=[]),
        ):
            result = await hybrid_search.search("test", limit=5)

        assert len(result.items) <= 5

    @pytest.mark.unit
    async def test_search_handles_search_errors_gracefully(
        self, hybrid_search, mock_embedding_service
    ):
        """Test search handles errors from individual searches."""
        mock_embedding_service.embed_text.side_effect = RuntimeError("Embedding failed")

        with (
            patch.object(hybrid_search, "_keyword_search_entities", return_value=[]),
            patch.object(hybrid_search, "_keyword_search_episodes", return_value=[]),
        ):
            result = await hybrid_search.search("test")

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
        with (
            patch.object(hybrid_search, "_vector_search_entities", return_value=[]),
            patch.object(hybrid_search, "_keyword_search_entities", return_value=[]),
            patch.object(hybrid_search, "_keyword_search_episodes", return_value=[]) as mock_kw_ep,
        ):
            await hybrid_search.search("test", include_episodes=False, include_entities=True)
        mock_kw_ep.assert_not_called()

    @pytest.mark.unit
    async def test_search_excludes_entities_when_disabled(self, hybrid_search):
        """Test search excludes entities when include_entities=False."""
        with (
            patch.object(hybrid_search, "_vector_search_entities", return_value=[]) as mock_vec,
            patch.object(hybrid_search, "_keyword_search_entities", return_value=[]) as mock_kw_ent,
            patch.object(hybrid_search, "_keyword_search_episodes", return_value=[]),
        ):
            await hybrid_search.search("test", include_episodes=True, include_entities=False)
        mock_vec.assert_not_called()
        mock_kw_ent.assert_not_called()


# ---------------------------------------------------------------------------
# TestTemporalDecay
# ---------------------------------------------------------------------------


class TestTemporalDecay:
    """Tests for temporal decay post-processing."""

    @pytest.mark.unit
    def test_temporal_decay_reduces_old_scores(self, hybrid_search):
        """Older items get lower scores after temporal decay."""
        now = datetime.now(UTC)
        recent_ts = (now - timedelta(days=1)).isoformat()
        old_ts = (now - timedelta(days=90)).isoformat()

        recent = _make_entity("recent", "Recent", "summary recent", 0.9, created_at=recent_ts)
        old = _make_entity("old", "Old", "summary old", 0.9, created_at=old_ts)

        result = hybrid_search._apply_post_processing([recent, old])

        scores = {r.uuid: r.score for r in result}
        assert scores["recent"] > scores["old"], "Recent item should score higher after decay"

    @pytest.mark.unit
    def test_temporal_decay_skips_missing_timestamp(self, hybrid_search):
        """Items without created_at keep original score through decay step."""
        item = _make_entity("no-ts", "No Timestamp", "summary", 0.8)
        # No created_at in metadata

        result = hybrid_search._apply_post_processing([item])
        # Score may change due to MMR (single item keeps ~1.0), but shouldn't crash
        assert len(result) == 1

    @pytest.mark.unit
    def test_temporal_decay_disabled(self, hybrid_search_no_enhancements):
        """No decay applied when enable_temporal_decay=False."""
        now = datetime.now(UTC)
        old_ts = (now - timedelta(days=365)).isoformat()

        item = _make_entity("old", "Old", "summary", 0.9, created_at=old_ts)

        result = hybrid_search_no_enhancements._apply_post_processing([item])
        # With all enhancements disabled, score should pass through unchanged
        assert result[0].score == 0.9


# ---------------------------------------------------------------------------
# TestMMR
# ---------------------------------------------------------------------------


class TestMMR:
    """Tests for MMR diversity re-ranking."""

    @pytest.mark.unit
    def test_mmr_promotes_diversity(self, mock_neo4j_client, mock_embedding_service):
        """MMR should promote diverse items over similar duplicates.

        Uses a low mmr_lambda (0.3) so the diversity penalty dominates over
        the relevance component, causing the unique item to rank above the
        near-duplicate.
        """
        cfg = GraphSearchConfig(
            enable_mmr=True,
            mmr_lambda=0.3,
            enable_temporal_decay=False,
        )
        hs = HybridSearch(
            neo4j_client=mock_neo4j_client,
            embedding_service=mock_embedding_service,
            search_config=cfg,
        )
        # Two items with identical content vs one unique item
        dup1 = _make_entity("dup1", "Machine Learning", "machine learning applications", 0.95)
        dup2 = _make_entity("dup2", "ML Apps", "machine learning applications", 0.90)
        unique = _make_entity(
            "unique", "Database Design", "relational database normalization", 0.85
        )

        result = hs._apply_post_processing([dup1, dup2, unique])
        uuids = [r.uuid for r in result]
        assert uuids.index("unique") < uuids.index("dup2"), (
            "Unique item should rank above duplicate"
        )

    @pytest.mark.unit
    def test_mmr_preserves_single_item(self, hybrid_search):
        """Single item list is returned unchanged by MMR."""
        item = _make_entity("solo", "Solo", "content", 0.9)
        result = hybrid_search._apply_post_processing([item])
        assert len(result) == 1
        assert result[0].uuid == "solo"

    @pytest.mark.unit
    def test_mmr_disabled(self, hybrid_search_no_enhancements):
        """No MMR applied when enable_mmr=False."""
        dup1 = _make_entity("dup1", "ML", "machine learning", 0.95)
        dup2 = _make_entity("dup2", "ML2", "machine learning", 0.90)
        unique = _make_entity("unique", "DB", "database design", 0.85)

        result = hybrid_search_no_enhancements._apply_post_processing([dup1, dup2, unique])
        # Without MMR, order should just be by score (already sorted)
        assert result[0].uuid == "dup1"
        assert result[1].uuid == "dup2"
        assert result[2].uuid == "unique"

    @pytest.mark.unit
    def test_mmr_lambda_high_favors_relevance(self, mock_neo4j_client, mock_embedding_service):
        """High lambda (close to 1.0) prioritizes relevance over diversity."""
        cfg = GraphSearchConfig(
            enable_mmr=True,
            mmr_lambda=0.99,
            enable_temporal_decay=False,
        )
        hs = HybridSearch(
            neo4j_client=mock_neo4j_client,
            embedding_service=mock_embedding_service,
            search_config=cfg,
        )

        high = _make_entity("high", "Top", "machine learning", 0.95)
        med = _make_entity("med", "Mid", "machine learning", 0.90)
        low = _make_entity("low", "Low", "database design", 0.50)

        result = hs._apply_post_processing([high, med, low])
        # With lambda ~1.0, order should track original relevance closely
        assert result[0].uuid == "high"


# ---------------------------------------------------------------------------
# TestQueryExpansion
# ---------------------------------------------------------------------------


class TestQueryExpansion:
    """Tests for query expansion integration in HybridSearch."""

    @pytest.mark.unit
    async def test_query_expansion_in_search(self, hybrid_search):
        """search() applies query expansion to keyword search queries."""
        with (
            patch.object(hybrid_search, "_vector_search_entities", return_value=[]) as mock_vec,
            patch.object(hybrid_search, "_keyword_search_entities", return_value=[]) as mock_kw_ent,
            patch.object(hybrid_search, "_keyword_search_episodes", return_value=[]) as mock_kw_ep,
        ):
            await hybrid_search.search("What is machine learning?")

        # Vector search should receive the original query
        vec_query = mock_vec.call_args[0][0]
        assert vec_query == "What is machine learning?"

        # Keyword searches should receive expanded (stop-words removed) query
        kw_ent_query = mock_kw_ent.call_args[0][0]
        kw_ep_query = mock_kw_ep.call_args[0][0]
        # "What", "is" are stop words; "machine" and "learning" should remain
        assert "machine" in kw_ent_query
        assert "learning" in kw_ent_query
        assert kw_ent_query == kw_ep_query

    @pytest.mark.unit
    async def test_query_expansion_disabled(self, hybrid_search_no_enhancements):
        """Query expansion is skipped when disabled."""
        with (
            patch.object(hybrid_search_no_enhancements, "_vector_search_entities", return_value=[]),
            patch.object(
                hybrid_search_no_enhancements, "_keyword_search_entities", return_value=[]
            ) as mock_kw,
            patch.object(
                hybrid_search_no_enhancements, "_keyword_search_episodes", return_value=[]
            ),
        ):
            await hybrid_search_no_enhancements.search("What is machine learning?")

        # Should pass original query unmodified
        kw_query = mock_kw.call_args[0][0]
        assert kw_query == "What is machine learning?"

    @pytest.mark.unit
    async def test_keyword_search_applies_expansion(self, hybrid_search, mock_neo4j_client):
        """keyword_search() also applies query expansion."""
        mock_result = MagicMock()
        mock_result.records = []
        mock_neo4j_client.execute_query.return_value = mock_result

        await hybrid_search.keyword_search("How does authentication work?")

        # Should have been called with expanded keywords
        call_kwargs = mock_neo4j_client.execute_query.call_args
        # The search_query param should not contain stop words like "how", "does"
        search_query = call_kwargs.kwargs.get("search_query", "")
        assert "authentication" in search_query


# ---------------------------------------------------------------------------
# TestOverFetch
# ---------------------------------------------------------------------------


class TestOverFetch:
    """Tests for over-fetch multiplier logic."""

    @pytest.mark.unit
    async def test_overfetch_with_mmr_enabled(self, hybrid_search):
        """With MMR enabled, fetch_limit = limit * 3."""
        with (
            patch.object(hybrid_search, "_vector_search_entities", return_value=[]) as mock_vec,
            patch.object(hybrid_search, "_keyword_search_entities", return_value=[]),
            patch.object(hybrid_search, "_keyword_search_episodes", return_value=[]),
        ):
            await hybrid_search.search("test", limit=10)

        # Vector search should be called with limit * 3 = 30
        called_limit = mock_vec.call_args[0][2]
        assert called_limit == 30

    @pytest.mark.unit
    async def test_overfetch_without_mmr(self, hybrid_search_no_enhancements):
        """Without MMR, fetch_limit = limit * 2."""
        with (
            patch.object(
                hybrid_search_no_enhancements, "_vector_search_entities", return_value=[]
            ) as mock_vec,
            patch.object(
                hybrid_search_no_enhancements, "_keyword_search_entities", return_value=[]
            ),
            patch.object(
                hybrid_search_no_enhancements, "_keyword_search_episodes", return_value=[]
            ),
        ):
            await hybrid_search_no_enhancements.search("test", limit=10)

        called_limit = mock_vec.call_args[0][2]
        assert called_limit == 20


# ---------------------------------------------------------------------------
# TestHybridSearchInit
# ---------------------------------------------------------------------------


class TestHybridSearchInit:
    """Tests for HybridSearch initialization with GraphSearchConfig."""

    @pytest.mark.unit
    def test_default_config_when_none(self, hybrid_search):
        """Default config is created when search_config is None."""
        cfg = hybrid_search._search_config
        assert isinstance(cfg, GraphSearchConfig)
        assert cfg.enable_mmr is True

    @pytest.mark.unit
    def test_custom_config(self, mock_neo4j_client, mock_embedding_service):
        """Custom config is preserved."""
        cfg = GraphSearchConfig(enable_mmr=False, mmr_lambda=0.3)
        hs = HybridSearch(
            neo4j_client=mock_neo4j_client,
            embedding_service=mock_embedding_service,
            search_config=cfg,
        )
        assert hs._search_config.enable_mmr is False
        assert hs._search_config.mmr_lambda == 0.3


# ---------------------------------------------------------------------------
# TestPostProcessingPipeline
# ---------------------------------------------------------------------------


class TestPostProcessingPipeline:
    """Tests for the combined temporal decay + MMR pipeline."""

    @pytest.mark.unit
    def test_empty_list(self, hybrid_search):
        """Empty list returns empty list."""
        assert hybrid_search._apply_post_processing([]) == []

    @pytest.mark.unit
    def test_full_pipeline_order(self, hybrid_search):
        """Temporal decay runs before MMR in the pipeline."""
        now = datetime.now(UTC)
        # Recent + unique content should rank first
        recent_unique = _make_entity(
            "ru",
            "API Design",
            "restful api design patterns",
            0.8,
            created_at=(now - timedelta(hours=1)).isoformat(),
        )
        # Old + duplicate content should rank last
        old_dup1 = _make_entity(
            "od1",
            "ML Intro",
            "machine learning basics",
            0.9,
            created_at=(now - timedelta(days=120)).isoformat(),
        )
        old_dup2 = _make_entity(
            "od2",
            "ML Guide",
            "machine learning basics",
            0.88,
            created_at=(now - timedelta(days=120)).isoformat(),
        )

        result = hybrid_search._apply_post_processing([old_dup1, old_dup2, recent_unique])
        uuids = [r.uuid for r in result]

        # recent_unique should be promoted: it's fresh and diverse
        assert uuids[0] == "ru", f"Expected recent unique first, got order: {uuids}"

    @pytest.mark.unit
    def test_pipeline_preserves_metadata(self, hybrid_search):
        """Post-processing preserves metadata through round-trip."""
        item = _make_entity(
            "e1",
            "Entity",
            "content",
            0.9,
            search_type="vector",
            entity_type="Person",
            created_at=datetime.now(UTC).isoformat(),
        )
        result = hybrid_search._apply_post_processing([item])
        assert result[0].metadata.get("search_type") == "vector"
        assert result[0].metadata.get("entity_type") == "Person"

    @pytest.mark.unit
    def test_invalid_created_at_does_not_crash(self, hybrid_search):
        """Invalid created_at string is silently skipped."""
        item = _make_entity("e1", "Entity", "content", 0.9, created_at="not-a-date")
        result = hybrid_search._apply_post_processing([item])
        assert len(result) == 1  # should not raise
