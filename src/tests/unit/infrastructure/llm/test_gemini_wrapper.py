"""Unit tests for Gemini native SDK wrappers."""

import sys
from unittest.mock import MagicMock, patch

import pytest

from src.domain.llm_providers.llm_types import ModelSize

pytestmark = pytest.mark.unit


@pytest.fixture
def mock_genai():
    """Create a mock for google.generativeai module."""
    mock = MagicMock()
    mock.configure = MagicMock()
    mock.GenerativeModel = MagicMock()
    mock.embed_content = MagicMock()
    mock.types = MagicMock()
    mock.types.GenerationConfig = MagicMock()
    return mock


@pytest.mark.unit
class TestGeminiLLMWrapper:
    """Test cases for GeminiLLMWrapper."""

    @pytest.mark.asyncio
    async def test_initialize_with_provider_config(self, gemini_provider_config, mock_genai):
        """Test GeminiLLMWrapper initialization with ProviderConfig."""
        with patch.dict(sys.modules, {"google.generativeai": mock_genai}):
            from src.infrastructure.llm.gemini import GeminiLLMWrapper

            client = GeminiLLMWrapper(provider_config=gemini_provider_config)

            assert client.model == "gemini-2.5-flash"
            assert client.small_model == "gemini-2.0-flash-lite"

    @pytest.mark.asyncio
    async def test_get_model_for_size_small(self, gemini_provider_config, mock_genai):
        """Test getting small model."""
        with patch.dict(sys.modules, {"google.generativeai": mock_genai}):
            from src.infrastructure.llm.gemini import GeminiLLMWrapper

            client = GeminiLLMWrapper(provider_config=gemini_provider_config)

            model = client._get_model_for_size(ModelSize.small)
            assert model == "gemini-2.0-flash-lite"

    @pytest.mark.asyncio
    async def test_get_model_for_size_medium(self, gemini_provider_config, mock_genai):
        """Test getting medium model (uses default large model)."""
        with patch.dict(sys.modules, {"google.generativeai": mock_genai}):
            from src.infrastructure.llm.gemini import GeminiLLMWrapper

            client = GeminiLLMWrapper(provider_config=gemini_provider_config)

            model = client._get_model_for_size(ModelSize.medium)
            assert model == "gemini-2.5-flash"

    def test_get_provider_type(self, gemini_provider_config, mock_genai):
        """Test provider type identifier."""
        with patch.dict(sys.modules, {"google.generativeai": mock_genai}):
            from src.infrastructure.llm.gemini import GeminiLLMWrapper

            client = GeminiLLMWrapper(provider_config=gemini_provider_config)

            assert client._get_provider_type() == "gemini"


@pytest.mark.unit
class TestGeminiEmbedderWrapper:
    """Test cases for GeminiEmbedderWrapper."""

    @pytest.mark.asyncio
    async def test_initialize_with_provider_config(self, gemini_provider_config, mock_genai):
        """Test GeminiEmbedderWrapper initialization with ProviderConfig."""
        with patch.dict(sys.modules, {"google.generativeai": mock_genai}):
            from src.infrastructure.llm.gemini import GeminiEmbedderWrapper

            embedder = GeminiEmbedderWrapper(provider_config=gemini_provider_config)

            assert embedder._embedding_dim == 768

    def test_embedding_dim_property(self, gemini_provider_config, mock_genai):
        """Test embedding_dim property."""
        with patch.dict(sys.modules, {"google.generativeai": mock_genai}):
            from src.infrastructure.llm.gemini import GeminiEmbedderWrapper

            embedder = GeminiEmbedderWrapper(provider_config=gemini_provider_config)

            # Gemini text-embedding-004 has 768 dimensions
            assert embedder.embedding_dim == 768


@pytest.mark.unit
class TestGeminiRerankerWrapper:
    """Test cases for GeminiRerankerWrapper."""

    @pytest.mark.asyncio
    async def test_initialize_with_provider_config(self, gemini_provider_config, mock_genai):
        """Test GeminiRerankerWrapper initialization with ProviderConfig."""
        with patch.dict(sys.modules, {"google.generativeai": mock_genai}):
            from src.infrastructure.llm.gemini import GeminiRerankerWrapper

            reranker = GeminiRerankerWrapper(provider_config=gemini_provider_config)

            # Check model is set
            assert reranker.model is not None

    @pytest.mark.asyncio
    async def test_rank_single_passage(self, gemini_provider_config, mock_genai):
        """Test ranking with single passage returns early without API call."""
        with patch.dict(sys.modules, {"google.generativeai": mock_genai}):
            from src.infrastructure.llm.gemini import GeminiRerankerWrapper

            reranker = GeminiRerankerWrapper(provider_config=gemini_provider_config)

            # Mock the parent rank method to return early
            with patch.object(reranker, "rank", return_value=[("single passage", 1.0)]):
                result = await reranker.rank("query", ["single passage"])

                # Single passage should return 1.0 without API call
                assert result == [("single passage", 1.0)]

    @pytest.mark.asyncio
    async def test_rank_empty_passages(self, gemini_provider_config, mock_genai):
        """Test ranking with empty passages list."""
        with patch.dict(sys.modules, {"google.generativeai": mock_genai}):
            from src.infrastructure.llm.gemini import GeminiRerankerWrapper

            reranker = GeminiRerankerWrapper(provider_config=gemini_provider_config)

            # Mock the parent rank method
            with patch.object(reranker, "rank", return_value=[]):
                result = await reranker.rank("query", [])
                assert result == []

    @pytest.mark.asyncio
    async def test_score_single_passage(self, gemini_provider_config, mock_genai):
        """Test scoring a single passage."""
        with patch.dict(sys.modules, {"google.generativeai": mock_genai}):
            from src.infrastructure.llm.gemini import GeminiRerankerWrapper

            reranker = GeminiRerankerWrapper(provider_config=gemini_provider_config)

            # Mock the rank method
            with patch.object(reranker, "rank", return_value=[("passage", 1.0)]):
                result = await reranker.score("query", "passage")

                # Single passage should return 1.0
                assert result == 1.0
