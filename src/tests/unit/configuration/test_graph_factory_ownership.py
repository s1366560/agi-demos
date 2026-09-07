"""Construction failure ownership at the real native graph factory boundary."""

from types import SimpleNamespace

import pytest

from src.configuration import factories
from src.infrastructure import graph as graph_module
from src.infrastructure.graph import neo4j_client as neo4j_module
from src.infrastructure.graph.embedding import embedding_service as embedding_module
from src.infrastructure.llm import provider_factory as provider_module

pytestmark = pytest.mark.unit


@pytest.fixture
def graph_dependencies(monkeypatch):
    state = SimpleNamespace(
        stage=None, failure=ValueError("construction failed"), closes=0, cleanup_error=None
    )

    def fail(stage):
        if state.stage == stage:
            raise state.failure

    class Client:
        def __init__(self, **_kwargs):
            pass

        async def build_indices(self):
            fail("indices")

        async def create_vector_index(self, **_kwargs):
            fail("vector")

        async def close(self):
            state.closes += 1
            if state.cleanup_error is not None:
                raise state.cleanup_error

    class Factory:
        async def resolve_provider(self, **_kwargs):
            fail("provider")
            return object()

        def create_embedder(self, _provider):
            fail("embedder")
            return object()

    async def llm(_tenant):
        fail("llm")
        return object()

    def adapter(**kwargs):
        fail("adapter")
        return SimpleNamespace(**kwargs)

    monkeypatch.setattr(
        factories,
        "get_settings",
        lambda: SimpleNamespace(
            effective_graph_store_uri="bolt://unused-test",
            effective_graph_store_user="test",
            effective_graph_store_password="test-placeholder",
            embedding_dimension=3,
            graph_reflexion_enabled=False,
            graph_reflexion_max_iterations=1,
            auto_clear_mismatched_embeddings=False,
        ),
    )
    monkeypatch.setattr(neo4j_module, "Neo4jClient", Client)
    monkeypatch.setattr(factories, "create_llm_client", llm)
    monkeypatch.setattr(provider_module, "get_ai_service_factory", Factory)
    monkeypatch.setattr(
        embedding_module, "EmbeddingService", lambda **_kwargs: SimpleNamespace(embedding_dim=3)
    )
    monkeypatch.setattr(graph_module, "NativeGraphAdapter", adapter)
    return state, Client


@pytest.mark.parametrize("stage", ["indices", "llm", "provider", "embedder", "vector", "adapter"])
@pytest.mark.parametrize("external", [False, True])
async def test_failure_closes_only_newly_constructed_client(graph_dependencies, stage, external):
    state, client_type = graph_dependencies
    state.stage = stage
    with pytest.raises(ValueError) as error:
        await factories.create_native_graph_adapter("tenant-a", client_type() if external else None)
    assert error.value is state.failure
    assert state.closes == (0 if external else 1)


@pytest.mark.parametrize("external", [False, True])
async def test_success_transfers_client_without_premature_close(graph_dependencies, external):
    state, client_type = graph_dependencies
    client = client_type() if external else None
    result = await factories.create_native_graph_adapter("tenant-a", client)
    assert isinstance(result.neo4j_client, client_type)
    if external:
        assert result.neo4j_client is client
    assert state.closes == 0


async def test_cleanup_failure_preserves_both_original_errors(graph_dependencies):
    state, _client_type = graph_dependencies
    state.stage = "provider"
    state.cleanup_error = RuntimeError("close failed")
    with pytest.raises(BaseExceptionGroup) as error:
        await factories.create_native_graph_adapter("tenant-a")
    assert error.value.exceptions == (state.failure, state.cleanup_error)
    assert state.closes == 1


async def test_cancelled_construction_still_releases_owned_client(graph_dependencies):
    import asyncio

    state, _client_type = graph_dependencies
    state.stage = "llm"
    state.failure = asyncio.CancelledError("construction cancelled")
    with pytest.raises(asyncio.CancelledError) as error:
        await factories.create_native_graph_adapter("tenant-a")
    assert error.value is state.failure
    assert state.closes == 1
