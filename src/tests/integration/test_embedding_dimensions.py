"""Integration tests for embedding dimension validation and compatibility.

These tests ensure that:
1. ValidatedEmbedder wrapper correctly validates and fixes embedding dimensions
2. Embeddings from different providers are automatically adjusted to expected dimensions
3. Switching providers doesn't cause dimension mismatch errors
"""

import pytest

from src.domain.llm_providers.llm_types import EmbedderClient, EmbedderConfig
from src.infrastructure.llm.validated_embedder import ValidatedEmbedder

# Test Constants
DIM_768 = 768  # Gemini
DIM_1024 = 1024  # Qwen, Deepseek, ZAI
DIM_1536 = 1536  # OpenAI


class MockEmbedder(EmbedderClient):
    """Mock embedder for testing dimension validation."""

    def __init__(self, config: EmbedderConfig, return_dimension: int) -> None:
        """Initialize mock embedder with specific return dimension."""
        self.config = config
        self._return_dimension = return_dimension

    async def create(self, input_data: str | list) -> list[float]:
        """Return embedding with specified dimension."""
        return [0.1] * self._return_dimension

    async def create_batch(self, input_data_list: list[str]) -> list[list[float]]:
        """Return batch of embeddings with specified dimension."""
        return [[0.1] * self._return_dimension for _ in input_data_list]


@pytest.mark.integration
class TestValidatedEmbedder:
    """Integration tests for ValidatedEmbedder wrapper."""

    @pytest.mark.asyncio
    async def test_validated_embedder_correct_dimension_passthrough(self):
        """Test that embeddings with correct dimension pass through unchanged."""
        config = EmbedderConfig(embedding_dim=DIM_1024)
        base_embedder = MockEmbedder(config=config, return_dimension=DIM_1024)

        validated_embedder = ValidatedEmbedder(base_embedder=base_embedder, config=config)

        # Test single embedding
        result = await validated_embedder.create("test text")
        assert len(result) == DIM_1024
        assert result == [0.1] * DIM_1024

    @pytest.mark.asyncio
    async def test_validated_embedder_truncates_overdimensional_embedding(self):
        """Test that embeddings larger than expected are truncated."""
        config = EmbedderConfig(embedding_dim=DIM_768)
        # Mock returns 1024 dims but config expects 768
        base_embedder = MockEmbedder(config=config, return_dimension=DIM_1024)

        validated_embedder = ValidatedEmbedder(base_embedder=base_embedder, config=config)

        result = await validated_embedder.create("test text")

        # Should be truncated to 768
        assert len(result) == DIM_768
        assert result == [0.1] * DIM_768

    @pytest.mark.asyncio
    async def test_validated_embedder_pads_underdimensional_embedding(self):
        """Test that embeddings smaller than expected are padded with zeros."""
        config = EmbedderConfig(embedding_dim=DIM_1024)
        # Mock returns 768 dims but config expects 1024
        base_embedder = MockEmbedder(config=config, return_dimension=DIM_768)

        validated_embedder = ValidatedEmbedder(base_embedder=base_embedder, config=config)

        result = await validated_embedder.create("test text")

        # Should be padded to 1024
        assert len(result) == DIM_1024
        # First 768 values are 0.1, rest are 0.0
        assert result[:768] == [0.1] * DIM_768
        assert result[768:] == [0.0] * (DIM_1024 - DIM_768)

    @pytest.mark.asyncio
    async def test_validated_embedder_batch_consistency(self):
        """Test that batch embeddings all have consistent dimensions."""
        config = EmbedderConfig(embedding_dim=DIM_1024)

        # Create embedder that returns inconsistent dimensions
        class InconsistentMockEmbedder(EmbedderClient):
            def __init__(self, config: EmbedderConfig) -> None:
                self.config = config
                self._call_count = 0

            async def create(self, input_data: str) -> list[float]:
                # Return 768 dims for single create
                return [0.1] * DIM_768

            async def create_batch(self, input_data_list: list[str]) -> list[list[float]]:
                # Return inconsistent dimensions: 768, 1024, 1536
                dims = [DIM_768, DIM_1024, DIM_1536]
                results = []
                for i in range(len(input_data_list)):
                    dim = dims[i % len(dims)]
                    results.append([0.1] * dim)
                return results

        base_embedder = InconsistentMockEmbedder(config=config)
        validated_embedder = ValidatedEmbedder(base_embedder=base_embedder, config=config)

        # Create batch of 6 texts (will hit all dimension variations)
        texts = [f"text_{i}" for i in range(6)]
        results = await validated_embedder.create_batch(texts)

        # All should be 1024 after validation
        assert len(results) == 6
        for result in results:
            assert len(result) == DIM_1024, f"Expected {DIM_1024} dims, got {len(result)}"

    @pytest.mark.asyncio
    async def test_validated_embedder_empty_embedding_returns_zero_vector(self):
        """Test that empty embeddings are replaced with zero vector."""
        config = EmbedderConfig(embedding_dim=DIM_1024)

        class EmptyMockEmbedder(EmbedderClient):
            def __init__(self, config: EmbedderConfig) -> None:
                self.config = config

            async def create(self, input_data: str) -> list[float]:
                return []  # Empty embedding

        base_embedder = EmptyMockEmbedder(config=config)
        validated_embedder = ValidatedEmbedder(base_embedder=base_embedder, config=config)

        result = await validated_embedder.create("test text")

        # Should return zero vector of correct dimension
        assert len(result) == DIM_1024
        assert result == [0.0] * DIM_1024

    @pytest.mark.asyncio
    async def test_validated_embedder_preserves_config_attributes(self):
        """Test that ValidatedEmbedder preserves base embedder's config."""
        config = EmbedderConfig(embedding_dim=DIM_1024)
        base_embedder = MockEmbedder(config=config, return_dimension=DIM_1024)

        validated_embedder = ValidatedEmbedder(base_embedder=base_embedder, config=config)

        # Check config is accessible
        assert validated_embedder.config == config
        assert validated_embedder.embedding_dim == DIM_1024


@pytest.mark.integration
class TestProviderDimensionCompatibility:
    """Integration tests for provider dimension compatibility scenarios."""

    @pytest.mark.asyncio
    async def test_gemini_to_qwen_dimension_upgrade(self):
        """Test switching from Gemini (768) to Qwen (1024)."""
        # Gemini config expects 768
        gemini_config = EmbedderConfig(embedding_dim=DIM_768)

        # Simulate old embedder returning 768 dims
        old_embedder = MockEmbedder(config=gemini_config, return_dimension=DIM_768)
        old_result = await old_embedder.create("test")
        assert len(old_result) == DIM_768

        # New Qwen config expects 1024
        qwen_config = EmbedderConfig(embedding_dim=DIM_1024)

        # If API accidentally returns 768 (cached/saved), wrapper pads it
        new_embedder = MockEmbedder(config=qwen_config, return_dimension=DIM_768)
        validated_embedder = ValidatedEmbedder(base_embedder=new_embedder, config=qwen_config)

        result = await validated_embedder.create("test")

        # Should be padded to 1024
        assert len(result) == DIM_1024

    @pytest.mark.asyncio
    async def test_qwen_to_gemini_dimension_downgrade(self):
        """Test switching from Qwen (1024) to Gemini (768)."""
        # Qwen config expects 1024
        qwen_config = EmbedderConfig(embedding_dim=DIM_1024)

        # Simulate old embedder returning 1024 dims
        old_embedder = MockEmbedder(config=qwen_config, return_dimension=DIM_1024)
        old_result = await old_embedder.create("test")
        assert len(old_result) == DIM_1024

        # New Gemini config expects 768
        gemini_config = EmbedderConfig(embedding_dim=DIM_768)

        # If API accidentally returns 1024, wrapper truncates it
        new_embedder = MockEmbedder(config=gemini_config, return_dimension=DIM_1024)
        validated_embedder = ValidatedEmbedder(base_embedder=new_embedder, config=gemini_config)

        result = await validated_embedder.create("test")

        # Should be truncated to 768
        assert len(result) == DIM_768

    @pytest.mark.asyncio
    async def test_openai_to_qwen_dimension_migration(self):
        """Test switching from OpenAI (1536) to Qwen (1024)."""
        # OpenAI config expects 1536
        openai_config = EmbedderConfig(embedding_dim=DIM_1536)

        # Simulate old embedder returning 1536 dims
        old_embedder = MockEmbedder(config=openai_config, return_dimension=DIM_1536)
        old_result = await old_embedder.create("test")
        assert len(old_result) == DIM_1536

        # New Qwen config expects 1024
        qwen_config = EmbedderConfig(embedding_dim=DIM_1024)

        # If API accidentally returns 1536, wrapper truncates it
        new_embedder = MockEmbedder(config=qwen_config, return_dimension=DIM_1536)
        validated_embedder = ValidatedEmbedder(base_embedder=new_embedder, config=qwen_config)

        result = await validated_embedder.create("test")

        # Should be truncated to 1024
        assert len(result) == DIM_1024


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.skipif(True, reason="Requires valid external API credentials; cannot run in CI")
class TestValidatedEmbedderWithRealProviders:

    @pytest.mark.asyncio
    async def test_qwen_embedder_with_validated_wrapper(self):
        """Test Qwen embedder wrapped with ValidatedEmbedder via LiteLLM."""
        # Skip if no API key
        import os

        from src.domain.llm_providers.models import ProviderType
        from src.infrastructure.llm.litellm.litellm_embedder import (
            LiteLLMEmbedder,
            LiteLLMEmbedderConfig,
        )

        if not os.environ.get("DASHSCOPE_API_KEY"):
            pytest.skip("No Dashscope API key available")

        # Create LiteLLM embedder config
        config = LiteLLMEmbedderConfig(
            embedding_dim=DIM_1024,
            embedding_model="text-embedding-v3",
            provider_type=ProviderType.DASHSCOPE,
            api_key=os.environ.get("DASHSCOPE_API_KEY"),
        )

        base_embedder = LiteLLMEmbedder(config=config)
        validated_embedder = ValidatedEmbedder(base_embedder=base_embedder, config=config)

        # Test single embedding
        result = await validated_embedder.create("test text for embedding")

        assert len(result) == DIM_1024

    @pytest.mark.asyncio
    async def test_gemini_embedder_with_validated_wrapper(self):
        """Test Gemini embedder wrapped with ValidatedEmbedder via LiteLLM."""
        import os

        from src.domain.llm_providers.models import ProviderType
        from src.infrastructure.llm.litellm.litellm_embedder import (
            LiteLLMEmbedder,
            LiteLLMEmbedderConfig,
        )

        if not os.environ.get("GEMINI_API_KEY"):
            pytest.skip("No Gemini API key available")

        # Create LiteLLM embedder config for Gemini
        config = LiteLLMEmbedderConfig(
            embedding_dim=DIM_768,
            embedding_model="text-embedding-004",
            provider_type=ProviderType.GEMINI,
            api_key=os.environ.get("GEMINI_API_KEY"),
        )

        base_embedder = LiteLLMEmbedder(config=config)
        validated_embedder = ValidatedEmbedder(base_embedder=base_embedder, config=config)

        # Test single embedding
        result = await validated_embedder.create("test text for embedding")

        assert len(result) == DIM_768
