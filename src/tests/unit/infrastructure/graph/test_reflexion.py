"""Unit tests for ReflexionChecker LLM response handling."""

import pytest

from src.infrastructure.graph.extraction.reflexion import ReflexionChecker


class MockEmbeddingService:
    """Mock embedding service for ReflexionChecker construction."""

    embedding_dim = 768

    async def embed_text(self, _text):
        return [0.1] * 768

    async def embed_batch(self, texts: list):
        return [[0.1] * 768 for _ in texts]


class FailingEmbeddingService(MockEmbeddingService):
    """Mock embedding service that raises a provider-style error."""

    async def embed_batch(self, texts: list):
        raise RuntimeError("provider echoed reflexion-embedding-secret-8642")


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

    def test_parse_reflexion_response_redacts_invalid_json_details(self, caplog):
        """Invalid JSON warnings should not write response text to logs."""
        checker = ReflexionChecker(
            llm_client=GenerateOnlyLLMClient(),
            embedding_service=MockEmbeddingService(),
        )
        secret = "reflexion-json-secret-2468"
        response = (
            f"provider preface {secret}\n"
            '{"missed_entities": [{"name": "Grace", "entity_type": "Person"}]}'
        )

        with caplog.at_level(
            "WARNING",
            logger="src.infrastructure.graph.extraction.reflexion",
        ):
            result = checker._parse_reflexion_response(response)

        assert result == [{"name": "Grace", "entity_type": "Person"}]
        assert secret not in caplog.text
        assert "error_type=JSONDecodeError" in caplog.text
        assert "response_length=" in caplog.text

    async def test_create_entity_nodes_redacts_embedding_exception_details(self, caplog):
        checker = ReflexionChecker(
            llm_client=GenerateOnlyLLMClient(),
            embedding_service=FailingEmbeddingService(),
        )

        with caplog.at_level(
            "ERROR",
            logger="src.infrastructure.graph.extraction.reflexion",
        ):
            nodes = await checker._create_entity_nodes(
                [{"name": "Grace", "entity_type": "Person"}],
            )

        assert len(nodes) == 1
        assert nodes[0].name == "Grace"
        assert nodes[0].name_embedding is None
        assert "reflexion-embedding-secret-8642" not in caplog.text
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
