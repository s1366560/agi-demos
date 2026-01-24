"""Unit tests for Z.AI (ZhipuAI) native SDK client."""

from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel

from src.domain.llm_providers.llm_types import ModelSize
from src.infrastructure.llm.zai import (
    ZAIClient,
    ZAIEmbedder,
    ZAIReranker,
)
from src.infrastructure.llm.zai.zai_client import (
    _generate_example_from_model,
    _is_schema_response,
)

pytestmark = pytest.mark.unit

# Patch path for the official Z.AI SDK
ZAI_CLIENT_PATCH = "zai.ZhipuAiClient"


@pytest.mark.unit
class TestZAIClient:
    """Test cases for ZAIClient."""

    @pytest.mark.asyncio
    async def test_initialize_with_provider_config(self, zai_provider_config):
        """Test ZAIClient initialization with ProviderConfig."""
        with patch(ZAI_CLIENT_PATCH):
            client = ZAIClient(provider_config=zai_provider_config)

            assert client.model == "glm-4-plus"
            assert client.small_model == "glm-4-flash"

    @pytest.mark.asyncio
    async def test_initialize_with_defaults(self, zai_provider_config):
        """Test ZAIClient initialization with default models."""
        zai_provider_config.llm_model = None
        zai_provider_config.llm_small_model = None

        with patch(ZAI_CLIENT_PATCH):
            client = ZAIClient(provider_config=zai_provider_config)

            # Should use defaults
            assert client.model == "glm-4-plus"
            assert client.small_model == "glm-4-flash"

    @pytest.mark.asyncio
    async def test_get_model_for_size_small(self, zai_provider_config):
        """Test getting small model."""
        with patch(ZAI_CLIENT_PATCH):
            client = ZAIClient(provider_config=zai_provider_config)

            model = client._get_model_for_size(ModelSize.small)
            assert model == "glm-4-flash"

    @pytest.mark.asyncio
    async def test_get_model_for_size_medium(self, zai_provider_config):
        """Test getting medium model (uses default large model)."""
        with patch(ZAI_CLIENT_PATCH):
            client = ZAIClient(provider_config=zai_provider_config)

            model = client._get_model_for_size(ModelSize.medium)
            assert model == "glm-4-plus"

    def test_get_provider_type(self, zai_provider_config):
        """Test provider type identifier."""
        with patch(ZAI_CLIENT_PATCH):
            client = ZAIClient(provider_config=zai_provider_config)

            assert client._get_provider_type() == "zai"


@pytest.mark.unit
class TestZAIEmbedder:
    """Test cases for ZAIEmbedder."""

    @pytest.mark.asyncio
    async def test_initialize_with_provider_config(self, zai_provider_config):
        """Test ZAIEmbedder initialization with ProviderConfig."""
        with patch(ZAI_CLIENT_PATCH):
            embedder = ZAIEmbedder(provider_config=zai_provider_config)

            assert embedder.embedding_model == "embedding-3"

    @pytest.mark.asyncio
    async def test_initialize_with_defaults(self, zai_provider_config):
        """Test ZAIEmbedder initialization with default embedding model."""
        zai_provider_config.embedding_model = None

        with patch(ZAI_CLIENT_PATCH):
            embedder = ZAIEmbedder(provider_config=zai_provider_config)

            # Should use default
            assert embedder.embedding_model == "embedding-3"

    def test_embedding_dim_property_embedding3(self, zai_provider_config):
        """Test embedding_dim property for embedding-3 model."""
        with patch(ZAI_CLIENT_PATCH):
            embedder = ZAIEmbedder(provider_config=zai_provider_config)

            # embedding-3 has 4096 dimensions (per Z.AI API docs)
            assert embedder.embedding_dim == 4096

    def test_embedding_dim_property_embedding2(self, zai_provider_config):
        """Test embedding_dim property for embedding-2 model."""
        zai_provider_config.embedding_model = "embedding-2"

        with patch(ZAI_CLIENT_PATCH):
            embedder = ZAIEmbedder(provider_config=zai_provider_config)

            # embedding-2 has 1024 dimensions
            assert embedder.embedding_dim == 1024

    def test_embedding_dim_property_embedding1(self, zai_provider_config):
        """Test embedding_dim property for embedding-1 model."""
        zai_provider_config.embedding_model = "embedding-1"

        with patch(ZAI_CLIENT_PATCH):
            embedder = ZAIEmbedder(provider_config=zai_provider_config)

            # embedding-1 has 1024 dimensions
            assert embedder.embedding_dim == 1024

    def test_embedding_dim_property_unknown_model(self, zai_provider_config):
        """Test embedding_dim property for unknown model uses default."""
        zai_provider_config.embedding_model = "unknown-model"

        with patch(ZAI_CLIENT_PATCH):
            embedder = ZAIEmbedder(provider_config=zai_provider_config)

            # Unknown models should use default 1024
            assert embedder.embedding_dim == 1024

    @pytest.mark.asyncio
    async def test_create_raises_value_error_on_empty_input(self, zai_provider_config):
        """Test that create raises ValueError on empty input."""
        with patch(ZAI_CLIENT_PATCH):
            embedder = ZAIEmbedder(provider_config=zai_provider_config)

            with pytest.raises(ValueError, match="No texts provided"):
                await embedder.create([])


@pytest.mark.unit
class TestZAIReranker:
    """Test cases for ZAIReranker."""

    @pytest.mark.asyncio
    async def test_initialize_with_provider_config(self, zai_provider_config):
        """Test ZAIReranker initialization with ProviderConfig."""
        with patch(ZAI_CLIENT_PATCH):
            reranker = ZAIReranker(provider_config=zai_provider_config)

            # Model is now "rerank" for the official Rerank API
            assert reranker.model == "rerank"

    @pytest.mark.asyncio
    async def test_initialize_with_default_model(self, zai_provider_config):
        """Test ZAIReranker initialization with default reranker model."""
        zai_provider_config.reranker_model = None

        with patch(ZAI_CLIENT_PATCH):
            reranker = ZAIReranker(provider_config=zai_provider_config)

            # Should use "rerank" model for official API
            assert reranker.model == "rerank"

    @pytest.mark.asyncio
    async def test_rank_single_passage(self, zai_provider_config):
        """Test ranking with single passage returns early without API call."""
        with patch(ZAI_CLIENT_PATCH):
            reranker = ZAIReranker(provider_config=zai_provider_config)
            result = await reranker.rank("query", ["single passage"])

            # Single passage should return 1.0 without API call
            assert result == [("single passage", 1.0)]

    @pytest.mark.asyncio
    async def test_rank_empty_passages(self, zai_provider_config):
        """Test ranking with empty passages list."""
        with patch(ZAI_CLIENT_PATCH):
            reranker = ZAIReranker(provider_config=zai_provider_config)

            result = await reranker.rank("query", [])

            assert result == []

    @pytest.mark.asyncio
    async def test_score_single_passage(self, zai_provider_config):
        """Test scoring a single passage."""
        with patch(ZAI_CLIENT_PATCH):
            reranker = ZAIReranker(provider_config=zai_provider_config)
            result = await reranker.score("query", "passage")

            # Single passage should return 1.0
            assert result == 1.0

    @pytest.mark.asyncio
    async def test_rank_with_multiple_passages(self, zai_provider_config):
        """Test ranking with multiple passages uses the Rerank API."""
        mock_response = {
            "results": [
                {"index": 1, "relevance_score": 0.95},
                {"index": 0, "relevance_score": 0.72},
                {"index": 2, "relevance_score": 0.34},
            ]
        }

        mock_client = MagicMock()
        mock_client.post.return_value = mock_response

        with patch(ZAI_CLIENT_PATCH, return_value=mock_client):
            reranker = ZAIReranker(provider_config=zai_provider_config)
            passages = ["passage 0", "passage 1", "passage 2"]
            result = await reranker.rank("query", passages)

            # Should return sorted by relevance score
            assert result == [
                ("passage 1", 0.95),
                ("passage 0", 0.72),
                ("passage 2", 0.34),
            ]

    @pytest.mark.asyncio
    async def test_rank_api_error_fallback(self, zai_provider_config):
        """Test that API errors fall back to neutral scores."""
        mock_client = MagicMock()
        mock_client.post.side_effect = Exception("API error")

        with patch(ZAI_CLIENT_PATCH, return_value=mock_client):
            reranker = ZAIReranker(provider_config=zai_provider_config)
            passages = ["passage 0", "passage 1"]
            result = await reranker.rank("query", passages)

            # Should return passages with neutral 0.5 scores
            assert result == [("passage 0", 0.5), ("passage 1", 0.5)]


class TestExtractedEntitiesModel(BaseModel):
    """Test model matching Graphiti's ExtractedEntities structure."""

    extracted_entities: list[dict]


class TestSchemaDetection:
    """Test cases for schema detection helper functions."""

    def test_is_schema_response_detects_json_schema_with_defs(self):
        """Test that _is_schema_response detects JSON Schema with $defs."""
        # This is what the error log showed
        schema_response = {
            "$defs": {
                "ExtractedEntity": {"properties": {"name": {"type": "string"}}, "type": "object"}
            },
            "properties": {"extracted_entities": {"type": "array"}},
            "type": "object",
        }
        assert _is_schema_response(schema_response) is True

    def test_is_schema_response_detects_properties_with_type_object(self):
        """Test detection of schema with properties at top level."""
        schema_response = {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Entity name"},
                "age": {"type": "integer", "title": "Age"},
            },
        }
        assert _is_schema_response(schema_response) is True

    def test_is_schema_response_returns_false_for_actual_data(self):
        """Test that actual data is not identified as schema."""
        actual_data = {
            "extracted_entities": [
                {"name": "Alice", "entity_type_id": 1},
                {"name": "Bob", "entity_type_id": 2},
            ]
        }
        assert _is_schema_response(actual_data) is False

    def test_is_schema_response_returns_false_for_simple_dict(self):
        """Test that simple dictionaries are not identified as schema."""
        simple_data = {"name": "Alice", "age": 30}
        assert _is_schema_response(simple_data) is False

    def test_is_schema_response_handles_non_dict(self):
        """Test that non-dict values return False."""
        assert _is_schema_response("string") is False
        assert _is_schema_response([1, 2, 3]) is False
        assert _is_schema_response(None) is False

    def test_generate_example_from_model_with_list_field(self):
        """Test _generate_example_from_model generates correct example."""
        example = _generate_example_from_model(TestExtractedEntitiesModel)

        assert "extracted_entities" in example
        assert isinstance(example["extracted_entities"], list)

    def test_generate_example_from_model_with_nested_model(self):
        """Test example generation with nested Pydantic model."""

        class NestedModel(BaseModel):
            inner_field: str

        class OuterModel(BaseModel):
            nested: NestedModel
            items: list[str]

        example = _generate_example_from_model(OuterModel)

        assert "nested" in example
        assert "items" in example
        assert isinstance(example["items"], list)

    def test_generate_example_from_model_returns_empty_for_none(self):
        """Test that None model returns empty dict."""
        example = _generate_example_from_model(None)
        assert example == {}
