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


class FailingLLMClient:
    """Mock LLM client that raises a provider-style error."""

    async def generate(self, **_kwargs):
        raise RuntimeError("provider echoed reflexion-secret-1357")


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

    async def test_check_missed_entities_redacts_llm_exception_details(self, caplog):
        checker = ReflexionChecker(
            llm_client=FailingLLMClient(),
            embedding_service=MockEmbeddingService(),
        )

        with caplog.at_level(
            "ERROR",
            logger="src.infrastructure.graph.extraction.reflexion",
        ):
            result = await checker.check_missed_entities(
                content="Grace mentioned reflexion-secret-1357",
                extracted_entities=[{"name": "Grace", "entity_type": "Person"}],
            )

        assert result == []
        assert "reflexion-secret-1357" not in caplog.text
        assert "error_type=RuntimeError" in caplog.text

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
