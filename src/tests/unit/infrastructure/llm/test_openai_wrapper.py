"""Unit tests for OpenAI native SDK wrappers."""

from unittest.mock import patch

import pytest

from src.domain.llm_providers.llm_types import ModelSize
from src.infrastructure.llm.openai import (
    OpenAIEmbedderWrapper,
    OpenAILLMWrapper,
    OpenAIRerankerWrapper,
)

pytestmark = pytest.mark.unit


@pytest.mark.unit
class TestOpenAILLMWrapper:
    """Test cases for OpenAILLMWrapper."""

    @pytest.mark.asyncio
    async def test_initialize_with_provider_config(self, openai_provider_config):
        """Test OpenAILLMWrapper initialization with ProviderConfig."""
        with patch("openai.AsyncOpenAI"):
            client = OpenAILLMWrapper(provider_config=openai_provider_config)

            # Model names come from provider_config fixture (gpt-4o, gpt-4o-mini)
            assert client.model == "gpt-4o"
            assert client.small_model == "gpt-4o-mini"

    @pytest.mark.asyncio
    async def test_get_model_for_size_small(self, openai_provider_config):
        """Test getting small model."""
        with patch("openai.AsyncOpenAI"):
            client = OpenAILLMWrapper(provider_config=openai_provider_config)

            model = client._get_model_for_size(ModelSize.small)
            assert model == "gpt-4o-mini"

    @pytest.mark.asyncio
    async def test_get_model_for_size_medium(self, openai_provider_config):
        """Test getting medium model (uses default large model)."""
        with patch("openai.AsyncOpenAI"):
            client = OpenAILLMWrapper(provider_config=openai_provider_config)

            model = client._get_model_for_size(ModelSize.medium)
            assert model == "gpt-4o"

    def test_get_provider_type(self, openai_provider_config):
        """Test provider type identifier."""
        with patch("openai.AsyncOpenAI"):
            client = OpenAILLMWrapper(provider_config=openai_provider_config)

            assert client._get_provider_type() == "openai"


@pytest.mark.unit
class TestOpenAIEmbedderWrapper:
    """Test cases for OpenAIEmbedderWrapper."""

    @pytest.mark.asyncio
    async def test_initialize_with_provider_config(self, openai_provider_config):
        """Test OpenAIEmbedderWrapper initialization with ProviderConfig."""
        with patch("openai.AsyncOpenAI"):
            embedder = OpenAIEmbedderWrapper(provider_config=openai_provider_config)

            assert embedder._embedding_dim == 1536

    def test_embedding_dim_property(self, openai_provider_config):
        """Test embedding_dim property."""
        with patch("openai.AsyncOpenAI"):
            embedder = OpenAIEmbedderWrapper(provider_config=openai_provider_config)

            # OpenAI text-embedding-3-small has 1536 dimensions
            assert embedder.embedding_dim == 1536


@pytest.mark.unit
class TestOpenAIRerankerWrapper:
    """Test cases for OpenAIRerankerWrapper."""

    @pytest.mark.asyncio
    async def test_initialize_with_provider_config(self, openai_provider_config):
        """Test OpenAIRerankerWrapper initialization with ProviderConfig."""
        with patch("openai.AsyncOpenAI"):
            reranker = OpenAIRerankerWrapper(provider_config=openai_provider_config)

            # Check model is set
            assert reranker.model is not None

    @pytest.mark.asyncio
    async def test_rank_single_passage(self, openai_provider_config):
        """Test ranking with single passage returns early without API call."""
        with patch("openai.AsyncOpenAI"):
            reranker = OpenAIRerankerWrapper(provider_config=openai_provider_config)

            # Mock the parent rank method to return early
            with patch.object(reranker, "rank", return_value=[("single passage", 1.0)]):
                result = await reranker.rank("query", ["single passage"])

                # Single passage should return 1.0 without API call
                assert result == [("single passage", 1.0)]

    @pytest.mark.asyncio
    async def test_rank_empty_passages(self, openai_provider_config):
        """Test ranking with empty passages list."""
        with patch("openai.AsyncOpenAI"):
            reranker = OpenAIRerankerWrapper(provider_config=openai_provider_config)

            # Mock the parent rank method
            with patch.object(reranker, "rank", return_value=[]):
                result = await reranker.rank("query", [])
                assert result == []

    @pytest.mark.asyncio
    async def test_score_single_passage(self, openai_provider_config):
        """Test scoring a single passage."""
        with patch("openai.AsyncOpenAI"):
            reranker = OpenAIRerankerWrapper(provider_config=openai_provider_config)

            # Mock the rank method
            with patch.object(reranker, "rank", return_value=[("passage", 1.0)]):
                result = await reranker.score("query", "passage")

                # Single passage should return 1.0
                assert result == 1.0
