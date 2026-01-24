"""
Unit tests for LiteLLM Embedder adapter.

Tests the LiteLLMEmbedder implementation of Graphiti's EmbedderClient interface.
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.domain.llm_providers.models import ProviderConfig, ProviderType
from src.infrastructure.llm.litellm.litellm_embedder import LiteLLMEmbedder


class TestLiteLLMEmbedder:
    """Test suite for LiteLLMEmbedder."""

    @pytest.fixture
    def provider_config(self):
        """Create a test provider configuration."""
        return ProviderConfig(
            id=uuid4(),
            name="test-provider",
            provider_type=ProviderType.OPENAI,
            api_key_encrypted="encrypted_key",
            llm_model="gpt-4o",
            llm_small_model="gpt-4o-mini",
            embedding_model="text-embedding-3-small",
            config={},
            is_active=True,
            is_default=False,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

    @pytest.fixture
    def embedder(self, provider_config):
        """Create a LiteLLMEmbedder instance."""
        with patch(
            "src.infrastructure.llm.litellm.litellm_embedder.get_encryption_service"
        ) as mock_get:
            mock_encryption = MagicMock()
            mock_encryption.decrypt.return_value = "sk-test-api-key"
            mock_get.return_value = mock_encryption
            return LiteLLMEmbedder(
                config=provider_config,
                embedding_dim=1536,
            )

    @pytest.mark.asyncio
    async def test_create_single_embedding(self, embedder):
        """Test creating a single embedding."""
        mock_response = MagicMock()
        mock_response.data = [MagicMock()]
        mock_response.data[0].embedding = [0.1] * 1536

        with patch("litellm.aembedding", new_callable=AsyncMock) as mock_aembedding:
            mock_aembedding.return_value = mock_response

            embedding = await embedder.create("Test text")

            assert len(embedding) == 1536
            assert embedding == [0.1] * 1536
            mock_aembedding.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_batch_embeddings(self, embedder):
        """Test creating multiple embeddings."""
        mock_response = MagicMock()
        mock_response.data = [
            MagicMock(embedding=[0.1] * 1536),
            MagicMock(embedding=[0.2] * 1536),
            MagicMock(embedding=[0.3] * 1536),
        ]

        with patch("litellm.aembedding", new_callable=AsyncMock) as mock_aembedding:
            mock_aembedding.return_value = mock_response

            texts = ["Text 1", "Text 2", "Text 3"]
            embeddings = await embedder.create_batch(texts)

            assert len(embeddings) == 3
            assert embeddings[0] == [0.1] * 1536
            assert embeddings[1] == [0.2] * 1536
            assert embeddings[2] == [0.3] * 1536

    @pytest.mark.asyncio
    async def test_create_empty_list(self, embedder):
        """Test creating embeddings for empty list."""
        embeddings = await embedder.create_batch([])
        assert embeddings == []

    @pytest.mark.asyncio
    async def test_create_handles_different_input_types(self, embedder):
        """Test that create handles different input types."""
        mock_response = MagicMock()
        mock_response.data = [MagicMock()]
        mock_response.data[0].embedding = [0.1] * 1536

        with patch("litellm.aembedding", new_callable=AsyncMock) as mock_aembedding:
            mock_aembedding.return_value = mock_response

            # Test with string
            embedding1 = await embedder.create("Test")
            assert len(embedding1) == 1536

            # Test with list of strings
            embedding2 = await embedder.create(["Test"])
            assert len(embedding2) == 1536

    @pytest.mark.asyncio
    async def test_create_error_handling(self, embedder):
        """Test error handling in embedding creation."""
        with patch("litellm.aembedding", new_callable=AsyncMock) as mock_aembedding:
            mock_aembedding.side_effect = Exception("API error")

            with pytest.raises(Exception):
                await embedder.create("Test text")

    @pytest.mark.asyncio
    async def test_create_validates_input(self, embedder):
        """Test that create validates input."""
        with pytest.raises(ValueError):
            # Empty list should raise error
            await embedder.create([])

    @pytest.mark.asyncio
    async def test_create_handles_no_embedding_returned(self, embedder):
        """Test handling when no embedding is returned."""
        mock_response = MagicMock()
        mock_response.data = None

        with patch("litellm.aembedding", new_callable=AsyncMock) as mock_aembedding:
            mock_aembedding.return_value = mock_response

            with pytest.raises(ValueError, match="No embedding returned"):
                await embedder.create("Test")

    @pytest.mark.asyncio
    async def test_create_handles_empty_data(self, embedder):
        """Test handling when response data is empty."""
        mock_response = MagicMock()
        mock_response.data = []

        with patch("litellm.aembedding", new_callable=AsyncMock) as mock_aembedding:
            mock_aembedding.return_value = mock_response

            with pytest.raises(ValueError, match="No embedding returned"):
                await embedder.create(["Test"])
