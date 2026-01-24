"""Unit tests for Deepseek native SDK client."""

from datetime import datetime
from unittest.mock import patch
from uuid import uuid4

import pytest

from src.domain.llm_providers.llm_types import ModelSize
from src.domain.llm_providers.models import ProviderConfig, ProviderType
from src.infrastructure.llm.deepseek import (
    DeepseekClient,
    DeepseekEmbedder,
    DeepseekReranker,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def qwen_fallback_provider_config():
    """Create a fallback ProviderConfig for Qwen."""
    now = datetime.utcnow()
    return ProviderConfig(
        id=uuid4(),
        name="Qwen Fallback",
        provider_type=ProviderType.QWEN,
        is_active=True,
        is_default=False,
        llm_model="qwen-plus",
        embedding_model="text-embedding-v3",
        api_key_encrypted="encrypted_fallback-key",
        created_at=now,
        updated_at=now,
    )


@pytest.mark.unit
class TestDeepseekClient:
    """Test cases for DeepseekClient."""

    @pytest.mark.asyncio
    async def test_initialize_with_provider_config(self, deepseek_provider_config):
        """Test DeepseekClient initialization with ProviderConfig."""
        with patch("src.infrastructure.llm.deepseek.deepseek_client.AsyncOpenAI"):
            client = DeepseekClient(provider_config=deepseek_provider_config)

            assert client.model == "deepseek-chat"
            assert client.small_model == "deepseek-coder"

    @pytest.mark.asyncio
    async def test_get_model_for_size_small(self, deepseek_provider_config):
        """Test getting small model."""
        with patch("src.infrastructure.llm.deepseek.deepseek_client.AsyncOpenAI"):
            client = DeepseekClient(provider_config=deepseek_provider_config)

            model = client._get_model_for_size(ModelSize.small)
            assert model == "deepseek-coder"

    @pytest.mark.asyncio
    async def test_get_model_for_size_medium(self, deepseek_provider_config):
        """Test getting medium model (uses default large model)."""
        with patch("src.infrastructure.llm.deepseek.deepseek_client.AsyncOpenAI"):
            client = DeepseekClient(provider_config=deepseek_provider_config)

            model = client._get_model_for_size(ModelSize.medium)
            assert model == "deepseek-chat"

    def test_get_provider_type(self, deepseek_provider_config):
        """Test provider type identifier."""
        with patch("src.infrastructure.llm.deepseek.deepseek_client.AsyncOpenAI"):
            client = DeepseekClient(provider_config=deepseek_provider_config)

            assert client._get_provider_type() == "deepseek"


@pytest.mark.unit
class TestDeepseekEmbedder:
    """Test cases for DeepseekEmbedder."""

    @pytest.mark.asyncio
    async def test_initialize_with_fallback(
        self, deepseek_provider_config, qwen_fallback_provider_config
    ):
        """Test DeepseekEmbedder initialization with fallback provider."""
        with patch("src.infrastructure.llm.qwen.qwen_embedder.QwenEmbedder"):
            embedder = DeepseekEmbedder(
                provider_config=deepseek_provider_config,
                fallback_provider_config=qwen_fallback_provider_config,
                embedding_dim=1024,
            )

            assert embedder.embedding_dim == 1024
            assert embedder.fallback_embedder is not None

    @pytest.mark.asyncio
    async def test_initialize_without_fallback(self, deepseek_provider_config):
        """Test DeepseekEmbedder initialization without fallback."""
        with patch("src.infrastructure.llm.qwen.qwen_embedder.QwenEmbedder"):
            embedder = DeepseekEmbedder(
                provider_config=deepseek_provider_config,
                fallback_provider_config=None,
                embedding_dim=1024,
            )

            assert embedder.fallback_embedder is None

    @pytest.mark.asyncio
    async def test_create_with_fallback(
        self, deepseek_provider_config, qwen_fallback_provider_config
    ):
        """Test create method using fallback embedder."""
        from unittest.mock import AsyncMock

        with patch("src.infrastructure.llm.qwen.qwen_embedder.QwenEmbedder") as mock_embedder:
            mock_instance = mock_embedder.return_value
            mock_instance.create = AsyncMock(return_value=[0.1] * 1024)

            embedder = DeepseekEmbedder(
                provider_config=deepseek_provider_config,
                fallback_provider_config=qwen_fallback_provider_config,
                embedding_dim=1024,
            )

            result = await embedder.create("test text")

            assert len(result) == 1024

    @pytest.mark.asyncio
    async def test_create_without_fallback_raises_error(self, deepseek_provider_config):
        """Test create without fallback raises ValueError."""
        with patch("src.infrastructure.llm.qwen.qwen_embedder.QwenEmbedder"):
            embedder = DeepseekEmbedder(
                provider_config=deepseek_provider_config,
                fallback_provider_config=None,
                embedding_dim=1024,
            )

            with pytest.raises(ValueError, match="does not provide embedding API"):
                await embedder.create("test text")


@pytest.mark.unit
class TestDeepseekReranker:
    """Test cases for DeepseekReranker."""

    @pytest.mark.asyncio
    async def test_initialize_with_provider_config(self, deepseek_provider_config):
        """Test DeepseekReranker initialization with ProviderConfig."""
        with patch("src.infrastructure.llm.deepseek.deepseek_client.AsyncOpenAI"):
            reranker = DeepseekReranker(provider_config=deepseek_provider_config)

            assert reranker.model == "deepseek-chat"

    @pytest.mark.asyncio
    async def test_rank_single_passage(self, deepseek_provider_config):
        """Test ranking with single passage returns early without API call."""
        with patch("src.infrastructure.llm.deepseek.deepseek_client.AsyncOpenAI"):
            reranker = DeepseekReranker(provider_config=deepseek_provider_config)
            result = await reranker.rank("query", ["single passage"])

            # Single passage should return 1.0 without API call
            assert result == [("single passage", 1.0)]

    @pytest.mark.asyncio
    async def test_rank_empty_passages(self, deepseek_provider_config):
        """Test ranking with empty passages list."""
        with patch("src.infrastructure.llm.deepseek.deepseek_client.AsyncOpenAI"):
            reranker = DeepseekReranker(provider_config=deepseek_provider_config)

            result = await reranker.rank("query", [])

            assert result == []

    @pytest.mark.asyncio
    async def test_score_single_passage(self, deepseek_provider_config):
        """Test scoring a single passage."""
        with patch("src.infrastructure.llm.deepseek.deepseek_client.AsyncOpenAI"):
            reranker = DeepseekReranker(provider_config=deepseek_provider_config)
            result = await reranker.score("query", "passage")

            # Single passage should return 1.0
            assert result == 1.0
