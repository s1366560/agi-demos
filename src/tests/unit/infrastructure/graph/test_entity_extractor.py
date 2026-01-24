"""Unit tests for EntityExtractor JSON parsing."""

import pytest

from src.infrastructure.graph.extraction.entity_extractor import EntityExtractor


class MockEmbeddingService:
    """Mock embedding service for testing."""

    embedding_dim = 768

    async def embed_text(self, text: str):
        return [0.1] * 768

    async def embed_batch(self, texts: list):
        return [[0.1] * 768 for _ in texts]


class MockLLMClient:
    """Mock LLM client for testing."""

    async def generate_response(self, prompt: str):
        return '{"entities": []}'


@pytest.fixture
def extractor():
    """Create EntityExtractor with mocked dependencies."""
    return EntityExtractor(
        llm_client=MockLLMClient(),
        embedding_service=MockEmbeddingService(),
    )


@pytest.mark.unit
class TestEntityExtractorJsonParsing:
    """Tests for JSON extraction from LLM responses."""

    def test_extract_json_simple_object(self, extractor):
        """Test extracting simple JSON object with entities."""
        text = '{"entities": [{"name": "John", "entity_type": "Person"}]}'
        result = extractor._extract_json_from_text(text)

        assert len(result) == 1
        assert result[0]["name"] == "John"

    def test_extract_json_with_markdown_code_block(self, extractor):
        """Test extracting JSON from markdown code block."""
        text = """Here is the result:
```json
{"entities": [{"name": "Acme Corp", "entity_type": "Organization"}]}
```
"""
        result = extractor._extract_json_from_text(text)

        assert len(result) == 1
        assert result[0]["name"] == "Acme Corp"

    def test_extract_json_nested_objects(self, extractor):
        """Test extracting JSON with nested attributes."""
        text = """
{
    "entities": [
        {
            "name": "John Smith",
            "entity_type": "Person",
            "attributes": {
                "profile": {
                    "age": 30,
                    "department": "Engineering"
                }
            }
        }
    ]
}
"""
        result = extractor._extract_json_from_text(text)

        assert len(result) == 1
        assert result[0]["name"] == "John Smith"
        assert result[0]["attributes"]["profile"]["age"] == 30

    def test_extract_json_array_format(self, extractor):
        """Test extracting JSON array without wrapper object."""
        text = '[{"name": "Entity1", "entity_type": "Concept"}, {"name": "Entity2", "entity_type": "Concept"}]'
        result = extractor._extract_json_from_text(text)

        assert len(result) == 2
        assert result[0]["name"] == "Entity1"
        assert result[1]["name"] == "Entity2"

    def test_extract_json_with_surrounding_text(self, extractor):
        """Test extracting JSON with surrounding prose text."""
        text = """I found the following entities in the text:

{"entities": [{"name": "Machine Learning", "entity_type": "Concept"}]}

These are the main entities mentioned."""
        result = extractor._extract_json_from_text(text)

        assert len(result) == 1
        assert result[0]["name"] == "Machine Learning"

    def test_extract_json_empty_response(self, extractor):
        """Test handling empty or invalid response."""
        text = "No valid JSON here"
        result = extractor._extract_json_from_text(text)

        assert result == []

    def test_extract_json_complex_nested_structure(self, extractor):
        """Test complex nested JSON with multiple levels."""
        text = """```json
{
    "entities": [
        {
            "name": "Project Alpha",
            "entity_type": "Project",
            "attributes": {
                "metadata": {
                    "tags": ["important", "urgent"],
                    "config": {
                        "enabled": true,
                        "settings": {"level": 5}
                    }
                }
            }
        }
    ]
}
```"""
        result = extractor._extract_json_from_text(text)

        assert len(result) == 1
        assert result[0]["name"] == "Project Alpha"
        assert result[0]["attributes"]["metadata"]["tags"] == ["important", "urgent"]
        assert result[0]["attributes"]["metadata"]["config"]["settings"]["level"] == 5

    def test_extract_json_chinese_content(self, extractor):
        """Test JSON with Chinese content."""
        text = '{"entities": [{"name": "李明", "entity_type": "人物", "summary": "软件工程师"}]}'
        result = extractor._extract_json_from_text(text)

        assert len(result) == 1
        assert result[0]["name"] == "李明"
        assert result[0]["entity_type"] == "人物"


@pytest.mark.unit
class TestEntityTypeResolution:
    """Tests for _resolve_entity_type method (Graphiti-compatible)."""

    def test_resolve_entity_type_from_id(self, extractor):
        """Should resolve entity_type_id to name using mapping."""
        entity_data = {"name": "John", "entity_type_id": 1}
        id_to_name = {0: "Entity", 1: "Person", 2: "Organization"}

        result = extractor._resolve_entity_type(entity_data, id_to_name)

        assert result == "Person"

    def test_resolve_entity_type_id_zero_is_entity(self, extractor):
        """entity_type_id 0 should resolve to 'Entity' (default type)."""
        entity_data = {"name": "Unknown Thing", "entity_type_id": 0}
        id_to_name = {0: "Entity", 1: "Person"}

        result = extractor._resolve_entity_type(entity_data, id_to_name)

        assert result == "Entity"

    def test_resolve_unknown_id_falls_back_to_entity(self, extractor):
        """Unknown entity_type_id should fall back to 'Entity' (ID 0)."""
        entity_data = {"name": "Mystery", "entity_type_id": 999}
        id_to_name = {0: "Entity", 1: "Person"}

        result = extractor._resolve_entity_type(entity_data, id_to_name)

        assert result == "Entity"

    def test_resolve_falls_back_to_string_entity_type(self, extractor):
        """Should fall back to entity_type string when no ID mapping."""
        entity_data = {"name": "John", "entity_type": "Person"}

        result = extractor._resolve_entity_type(entity_data, None)

        assert result == "Person"

    def test_resolve_falls_back_to_type_field(self, extractor):
        """Should fall back to 'type' field (legacy format)."""
        entity_data = {"name": "Acme", "type": "Organization"}

        result = extractor._resolve_entity_type(entity_data, None)

        assert result == "Organization"

    def test_resolve_empty_entity_type_returns_entity(self, extractor):
        """Empty entity_type should return 'Entity' (not 'Unknown')."""
        entity_data = {"name": "Something", "entity_type": ""}

        result = extractor._resolve_entity_type(entity_data, None)

        assert result == "Entity"

    def test_resolve_no_type_fields_returns_entity(self, extractor):
        """No type fields should return 'Entity' as default."""
        entity_data = {"name": "NoType"}

        result = extractor._resolve_entity_type(entity_data, None)

        assert result == "Entity"

    def test_resolve_prefers_id_over_string(self, extractor):
        """entity_type_id should take precedence over entity_type string."""
        entity_data = {
            "name": "John",
            "entity_type_id": 2,
            "entity_type": "Person",  # Should be ignored
        }
        id_to_name = {0: "Entity", 1: "Person", 2: "Organization"}

        result = extractor._resolve_entity_type(entity_data, id_to_name)

        # ID 2 = Organization, string says Person, ID wins
        assert result == "Organization"

    def test_resolve_with_string_id_ignores_invalid_type(self, extractor):
        """String entity_type_id (invalid) should fall back to default."""
        entity_data = {"name": "Bad", "entity_type_id": "not-an-int"}
        id_to_name = {0: "Entity", 1: "Person"}

        result = extractor._resolve_entity_type(entity_data, id_to_name)

        # Invalid ID type, falls back to Entity (ID 0)
        assert result == "Entity"

    def test_resolve_custom_type_id(self, extractor):
        """Should resolve custom type IDs (7+)."""
        entity_data = {"name": "Widget", "entity_type_id": 7}
        id_to_name = {
            0: "Entity",
            1: "Person",
            7: "Product",  # Custom type
            8: "Service",  # Custom type
        }

        result = extractor._resolve_entity_type(entity_data, id_to_name)

        assert result == "Product"
