"""Unit tests for EmbeddingService."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.infrastructure.graph.embedding.embedding_service import (
    EmbeddingService,
)


class MockEmbedder:
    """Mock embedder for testing."""

    def __init__(self, embedding_dim: int = 768) -> None:
        self.embedding_dim = embedding_dim
        self._create_mock = AsyncMock()

    async def create(self, input_data: str) -> list:
        """Create mock embedding."""
        return await self._create_mock(input_data=input_data)


class MockBatchEmbedder(MockEmbedder):
    """Mock embedder with a batch API."""

    def __init__(self, embedding_dim: int = 768) -> None:
        super().__init__(embedding_dim=embedding_dim)
        self._create_batch_mock = AsyncMock()

    async def create_batch(self, texts: list[str]) -> list[list[float]]:
        """Create mock batch embeddings."""
        return await self._create_batch_mock(texts)


@pytest.fixture
def mock_embedder():
    """Create mock embedder."""
    return MockEmbedder(embedding_dim=768)


@pytest.fixture
def embedding_service(mock_embedder):
    """Create embedding service with mock embedder."""
    return EmbeddingService(mock_embedder)


class TestEmbeddingService:
    """Tests for EmbeddingService."""

    @pytest.mark.unit
    async def test_embed_text_success(self, embedding_service, mock_embedder):
        """Test successful text embedding."""
        expected_embedding = [0.1] * 768
        mock_embedder._create_mock.return_value = expected_embedding

        result = await embedding_service.embed_text("Hello world")

        assert result == expected_embedding
        mock_embedder._create_mock.assert_called_once_with(input_data="Hello world")

    @pytest.mark.unit
    async def test_embed_text_empty_returns_zero_vector(self, embedding_service):
        """Test empty text returns zero vector."""
        result = await embedding_service.embed_text("")

        assert result == [0.0] * 768

    @pytest.mark.unit
    async def test_embed_text_whitespace_returns_zero_vector(self, embedding_service):
        """Test whitespace-only text returns zero vector."""
        result = await embedding_service.embed_text("   ")

        assert result == [0.0] * 768

    @pytest.mark.unit
    async def test_embed_text_handles_nested_list(self, embedding_service, mock_embedder):
        """Test handling of nested list return format."""
        expected_embedding = [0.1] * 768
        mock_embedder._create_mock.return_value = [expected_embedding]  # Nested

        result = await embedding_service.embed_text("Test")

        assert result == expected_embedding

    @pytest.mark.unit
    async def test_embed_text_dimension_mismatch_pads(self, embedding_service, mock_embedder):
        """Test dimension padding when embedding is too short."""
        short_embedding = [0.1] * 512  # Too short
        mock_embedder._create_mock.return_value = short_embedding

        result = await embedding_service.embed_text("Test")

        # Should be padded to 768
        assert len(result) == 768
        assert result[:512] == short_embedding
        assert result[512:] == [0.0] * 256

    @pytest.mark.unit
    async def test_embed_text_dimension_mismatch_truncates(self, embedding_service, mock_embedder):
        """Test dimension truncation when embedding is too long."""
        long_embedding = [0.1] * 1024  # Too long
        mock_embedder._create_mock.return_value = long_embedding

        result = await embedding_service.embed_text("Test")

        # Should be truncated to 768
        assert len(result) == 768
        assert result == long_embedding[:768]

    @pytest.mark.unit
    async def test_embed_text_propagates_error(self, embedding_service, mock_embedder):
        """Test error propagation from embedder."""
        mock_embedder._create_mock.side_effect = RuntimeError("API Error")

        with pytest.raises(RuntimeError, match="API Error"):
            await embedding_service.embed_text("Test")

    @pytest.mark.unit
    async def test_embed_text_error_log_redacts_exception_content(
        self,
        embedding_service,
        mock_embedder,
        caplog,
    ):
        """Embedding failures should not log raw provider exception text."""
        secret = "graph-embedding-secret-13579"
        mock_embedder._create_mock.side_effect = RuntimeError(f"provider echoed {secret}")

        with (
            caplog.at_level(
                "ERROR",
                logger="src.infrastructure.graph.embedding.embedding_service",
            ),
            pytest.raises(RuntimeError, match=secret),
        ):
            await embedding_service.embed_text(f"Test {secret}")

        assert secret not in caplog.text
        assert "error_type=RuntimeError" in caplog.text

    @pytest.mark.unit
    async def test_embed_text_safe_error_log_redacts_exception_content(
        self,
        embedding_service,
        mock_embedder,
        caplog,
    ):
        """Safe embedding fallback logs should not include raw exception text."""
        secret = "graph-embedding-safe-secret-24680"
        mock_embedder._create_mock.side_effect = RuntimeError(f"provider echoed {secret}")

        with caplog.at_level(
            "WARNING",
            logger="src.infrastructure.graph.embedding.embedding_service",
        ):
            result = await embedding_service.embed_text_safe(f"Test {secret}")

        assert result is None
        assert secret not in caplog.text
        assert "error_type=RuntimeError" in caplog.text

    @pytest.mark.unit
    async def test_embed_batch_empty_list(self, embedding_service):
        """Test batch embedding with empty list."""
        result = await embedding_service.embed_batch([])

        assert result == []

    @pytest.mark.unit
    async def test_embed_batch_all_empty_texts(self, embedding_service):
        """Test batch embedding with all empty texts."""
        result = await embedding_service.embed_batch(["", "  ", ""])

        assert len(result) == 3
        assert all(emb == [0.0] * 768 for emb in result)

    @pytest.mark.unit
    async def test_embed_batch_success(self, embedding_service, mock_embedder):
        """Test successful batch embedding."""
        texts = ["Hello", "World"]
        mock_embedder._create_mock.side_effect = lambda input_data: [0.1] * 768

        result = await embedding_service.embed_batch(texts)

        assert len(result) == 2
        assert all(len(emb) == 768 for emb in result)

    @pytest.mark.unit
    async def test_embed_batch_handles_empty_in_middle(self, embedding_service, mock_embedder):
        """Test batch embedding handles empty texts in the middle."""
        texts = ["Hello", "", "World"]
        mock_embedder._create_mock.side_effect = lambda input_data: [0.1] * 768

        result = await embedding_service.embed_batch(texts)

        assert len(result) == 3
        # Middle should be zero vector
        assert result[1] == [0.0] * 768
        # Others should be normal
        assert result[0] != [0.0] * 768
        assert result[2] != [0.0] * 768

    @pytest.mark.unit
    async def test_embed_batch_api_fallback_log_redacts_exception_content(self, caplog):
        """Batch API fallback logs should not include raw provider exception text."""
        secret = "graph-batch-api-secret-97531"
        embedder = MockBatchEmbedder()
        embedder._create_batch_mock.side_effect = RuntimeError(f"provider echoed {secret}")
        embedder._create_mock.side_effect = lambda input_data: [0.1] * 768
        service = EmbeddingService(embedder)

        with caplog.at_level(
            "WARNING",
            logger="src.infrastructure.graph.embedding.embedding_service",
        ):
            result = await service.embed_batch([f"First {secret}", "Second"])

        assert len(result) == 2
        assert all(embedding == [0.1] * 768 for embedding in result)
        assert secret not in caplog.text
        assert "error_type=RuntimeError" in caplog.text

    @pytest.mark.unit
    async def test_embed_batch_safe_error_log_redacts_exception_content(
        self,
        embedding_service,
        mock_embedder,
        caplog,
    ):
        """Safe batch fallback logs should not include raw exception text."""
        secret = "graph-batch-safe-secret-86420"
        mock_embedder._create_mock.side_effect = RuntimeError(f"provider echoed {secret}")

        with caplog.at_level(
            "WARNING",
            logger="src.infrastructure.graph.embedding.embedding_service",
        ):
            result = await embedding_service.embed_batch_safe([f"First {secret}", "Second"])

        assert result == [None, None]
        assert secret not in caplog.text
        assert "error_type=RuntimeError" in caplog.text

    @pytest.mark.unit
    def test_embedding_dim_from_embedder(self, mock_embedder):
        """Test embedding dimension is read from embedder."""
        service = EmbeddingService(mock_embedder)

        assert service.embedding_dim == 768

    @pytest.mark.unit
    def test_embedding_dim_default_when_not_available(self):
        """Test default dimension when embedder doesn't have it."""
        embedder = MagicMock(spec=[])  # No embedding_dim attribute
        service = EmbeddingService(embedder)

        assert service.embedding_dim == 1024  # Default

    @pytest.mark.unit
    def test_embedding_dim_from_config(self):
        """Test embedding dimension from embedder config."""
        embedder = MagicMock(spec=["config"])
        embedder.config = MagicMock()
        embedder.config.embedding_dim = 512

        service = EmbeddingService(embedder)

        assert service.embedding_dim == 512

    @pytest.mark.unit
    def test_embedding_dim_consistent(self, embedding_service, mock_embedder):
        """Test embedding dimension is consistent across calls."""
        dim1 = embedding_service.embedding_dim
        dim2 = embedding_service.embedding_dim

        assert dim1 == dim2 == 768


@pytest.mark.unit
class TestFindMostSimilar:
    """Tests for the vectorized top-k cosine similarity search."""

    async def test_single_query_matches_pairwise_cosine(self, embedding_service):
        query = [1.0, 0.0, 0.0]
        candidates = [
            [1.0, 0.0, 0.0],  # cosine 1.0
            [0.0, 1.0, 0.0],  # cosine 0.0
            [0.5, 0.5, 0.0],  # cosine ~0.707
        ]

        results = await embedding_service.find_most_similar(query, candidates, top_k=3)

        assert [idx for idx, _ in results] == [0, 2, 1]
        assert results[0][1] == pytest.approx(1.0)
        assert results[1][1] == pytest.approx(2**0.5 / 2)
        assert results[2][1] == pytest.approx(0.0)

    async def test_ties_resolve_to_lower_candidate_index(self, embedding_service):
        query = [1.0, 0.0]
        candidates = [[1.0, 0.0], [2.0, 0.0], [1.0, 0.0]]

        results = await embedding_service.find_most_similar(query, candidates, top_k=2)

        assert [idx for idx, _ in results] == [0, 1]

    async def test_zero_vectors_score_zero(self, embedding_service):
        query = [0.0, 0.0]
        candidates = [[0.0, 0.0], [1.0, 0.0]]

        results = await embedding_service.find_most_similar(query, candidates, top_k=2)

        assert all(score == 0.0 for _, score in results)

    async def test_batch_matches_single_query_results(self, embedding_service):
        candidates = [[1.0, 0.0], [0.0, 1.0], [1.0, 1.0]]
        queries = [[1.0, 0.0], [0.0, 1.0]]

        batch = await embedding_service.find_most_similar_batch(queries, candidates, top_k=1)
        singles = [
            await embedding_service.find_most_similar(q, candidates, top_k=1) for q in queries
        ]

        assert batch == singles
        assert batch[0][0][0] == 0
        assert batch[1][0][0] == 1

    async def test_batch_without_candidates_returns_empty_lists(self, embedding_service):
        batch = await embedding_service.find_most_similar_batch([[1.0], [2.0]], [], top_k=1)

        assert batch == [[], []]

    async def test_dimension_mismatch_raises(self, embedding_service):
        with pytest.raises(ValueError, match="dimensions"):
            await embedding_service.find_most_similar([1.0, 0.0], [[1.0]], top_k=1)
