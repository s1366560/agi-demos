from __future__ import annotations

from typing import Any

import pytest


@pytest.mark.unit
async def test_create_native_graph_adapter_uses_reflexion_settings(monkeypatch: pytest.MonkeyPatch):
    from src.configuration import factories
    from src.infrastructure import graph as graph_module
    from src.infrastructure.graph import neo4j_client as neo4j_module
    from src.infrastructure.graph.embedding import embedding_service as embedding_module
    from src.infrastructure.llm import provider_factory as provider_factory_module

    captured: dict[str, Any] = {}

    class Settings:
        neo4j_uri = "bolt://neo4j"
        neo4j_user = "neo4j"
        neo4j_password = "password"
        embedding_dimension = None
        graph_reflexion_enabled = True
        graph_reflexion_max_iterations = 4
        auto_clear_mismatched_embeddings = False

    class FakeNeo4jClient:
        def __init__(self, *, uri: str, user: str, password: str) -> None:
            captured["neo4j"] = (uri, user, password)

        async def build_indices(self) -> None:
            captured["build_indices"] = True

        async def create_vector_index(self, **kwargs: Any) -> None:
            captured.setdefault("vector_indices", []).append(kwargs)

    class FakeEmbeddingService:
        embedding_dim = 321

        def __init__(self, *, embedder: object) -> None:
            captured["embedder"] = embedder

    class FakeFactory:
        async def resolve_provider(self, **kwargs: Any) -> object:
            captured["resolve_provider"] = kwargs
            return object()

        def create_embedder(self, provider_config: object) -> object:
            captured["provider_config"] = provider_config
            return object()

    class FakeNativeGraphAdapter:
        def __init__(self, **kwargs: Any) -> None:
            captured["adapter_kwargs"] = kwargs

    async def create_llm_client(tenant_id: str | None = None) -> object:
        captured["tenant_id"] = tenant_id
        return object()

    monkeypatch.setattr(factories, "get_settings", Settings)
    monkeypatch.setattr(factories, "create_llm_client", create_llm_client)
    monkeypatch.setattr(neo4j_module, "Neo4jClient", FakeNeo4jClient)
    monkeypatch.setattr(provider_factory_module, "get_ai_service_factory", FakeFactory)
    monkeypatch.setattr(embedding_module, "EmbeddingService", FakeEmbeddingService)
    monkeypatch.setattr(graph_module, "NativeGraphAdapter", FakeNativeGraphAdapter)

    adapter = await factories.create_native_graph_adapter(tenant_id="tenant-1")

    assert isinstance(adapter, FakeNativeGraphAdapter)
    assert captured["neo4j"] == ("bolt://neo4j", "neo4j", "password")
    assert captured["build_indices"] is True
    assert captured["tenant_id"] == "tenant-1"
    assert captured["resolve_provider"]["tenant_id"] == "tenant-1"
    assert captured["adapter_kwargs"]["enable_reflexion"] is True
    assert captured["adapter_kwargs"]["reflexion_max_iterations"] == 4
    assert captured["adapter_kwargs"]["auto_clear_embeddings"] is False
    assert captured["vector_indices"][0]["dimensions"] == 321
