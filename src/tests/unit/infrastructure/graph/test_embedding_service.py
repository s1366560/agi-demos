"""Unit tests for EmbeddingService."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.infrastructure.graph.embedding.embedding_service import (
    EmbeddingService,
    EmbedderProtocol,
)


class MockEmbedder:
    """Mock embedder for testing."""

    def __init__(self, embedding_dim: int = 768):
        self.embedding_dim = embedding_dim
        self._create_mock = AsyncMock()

    async def create(self, input_data: str) -> list:
        """Create mock embedding."""
        return await self._create_mock(input_data)


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
        embedder = MagicMock()
        embedder.config = MagicMock()
        embedder.config.embedding_dim = 512

        service = EmbeddingService(embedder)

        assert service.embedding_dim == 512

    @pytest.mark.unit
    def test_embedding_dim_cached(self, embedding_service, mock_embedder):
        """Test embedding dimension is cached."""
        dim1 = embedding_service.embedding_dim
        dim2 = embedding_service.embedding_dim

        assert dim1 == dim2 == 768
        # Should only access once due to caching
