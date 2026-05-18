"""Unit tests for ReflexionChecker LLM response handling."""

import pytest

from src.infrastructure.graph.extraction.reflexion import ReflexionChecker


class MockEmbeddingService:
    """Mock embedding service for ReflexionChecker construction."""

    embedding_dim = 768

    async def embed_text(self, _text):
        return [0.1] * 768


class GenerateOnlyLLMClient:
    """Mock the default project LLM client response shape."""

    async def generate(self, **_kwargs):
        return {"content": '{"missed_entities": [{"name": "Grace", "entity_type": "Person"}]}'}


@pytest.mark.unit
class TestReflexionCheckerLLMResponseHandling:
    """Tests for LLM response normalization."""

    async def test_call_llm_extracts_content_from_generate_dict(self):
        checker = ReflexionChecker(
            llm_client=GenerateOnlyLLMClient(),
            embedding_service=MockEmbeddingService(),
        )

        response = await checker._call_llm("Check missed entities", "Grace Hopper")

        assert response == '{"missed_entities": [{"name": "Grace", "entity_type": "Person"}]}'

    def test_resolve_localized_person_type_to_canonical_schema_type(self):
        checker = ReflexionChecker(
            llm_client=GenerateOnlyLLMClient(),
            embedding_service=MockEmbeddingService(),
        )

        result = checker._resolve_entity_type(
            {"name": "李明", "entity_type": "人物"},
            {0: "Entity", 1: "Person"},
        )

        assert result == "Person"
