"""Real graph composition must not require a configured embedding provider."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.configuration import factories
from src.domain.llm_providers.models import NoActiveProviderError
from src.domain.model.memory.episode import Episode, SourceType
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.memory_tool_provider import build_memory_tools
from src.infrastructure.plugins.v2.agent_memory_tools import AGENT_MEMORY_TOOL_NAMES_V2

pytestmark = pytest.mark.unit


@pytest.fixture
def dependencies(monkeypatch):
    client = SimpleNamespace(
        build_indices=AsyncMock(),
        create_vector_index=AsyncMock(),
        execute_query=AsyncMock(return_value=SimpleNamespace(records=[])),
        vector_search=AsyncMock(return_value=[]),
        close=AsyncMock(),
    )
    embedder = SimpleNamespace(
        embedding_dim=3,
        create=AsyncMock(return_value=[0.1, 0.2, 0.3]),
    )
    factory = SimpleNamespace(
        resolve_provider=AsyncMock(side_effect=NoActiveProviderError("not configured")),
        create_embedder=MagicMock(return_value=embedder),
    )
    monkeypatch.setattr(
        factories,
        "get_settings",
        lambda: SimpleNamespace(
            embedding_dimension=None,
            graph_reflexion_enabled=False,
            graph_reflexion_max_iterations=1,
            auto_clear_mismatched_embeddings=False,
        ),
    )
    monkeypatch.setattr(factories, "create_llm_client", AsyncMock(return_value=object()))
    monkeypatch.setattr(
        "src.infrastructure.llm.provider_factory.get_ai_service_factory", lambda: factory
    )
    monkeypatch.setattr(
        "src.configuration.config.get_settings",
        lambda: SimpleNamespace(agent_memory_tool_provider_mode="plugin"),
    )
    return client, factory, embedder


async def test_graph_reads_delete_and_prepared_memory_tools_need_no_embedding(dependencies):
    client, factory, _embedder = dependencies
    adapter = await factories.create_native_graph_adapter("tenant-a", client)

    assert await adapter.get_entity("missing") is None
    assert await adapter.get_graph_data("project-a") == {"nodes": [], "edges": []}
    assert await adapter.delete_episode("owned-fixture") is True
    tools = build_memory_tools(
        tenant_id="tenant-a",
        project_id="project-a",
        graph_service=adapter,
        redis_client=None,
        session_factory=MagicMock(),
    )

    assert set(tools) == AGENT_MEMORY_TOOL_NAMES_V2
    from src.infrastructure.plugins.v2.agent_memory_tools import _agent_memory_tool_set_v2
    from src.infrastructure.plugins.v2.tool_set import PreparedToolProviderV2

    selected = _agent_memory_tool_set_v2(
        agent=object(),
        selection_context=None,
        prepared_tool_provider=PreparedToolProviderV2(tools=tools),
    )
    assert set(selected.tools) == AGENT_MEMORY_TOOL_NAMES_V2
    assert {definition.name for definition in selected.definitions} == AGENT_MEMORY_TOOL_NAMES_V2
    factory.resolve_provider.assert_not_awaited()
    client.create_vector_index.assert_not_awaited()
    client.close.assert_not_awaited()


@pytest.mark.parametrize(
    "operation",
    [
        "text",
        "batch",
        "safe",
        "batch-safe",
        "search",
        "write",
        "process",
        "vector",
        "entities",
        "reflexion",
        "rebuild",
    ],
)
async def test_embedding_operations_reject_unconfigured_without_graph_write(
    dependencies, operation
):
    client, factory, embedder = dependencies
    adapter = await factories.create_native_graph_adapter("tenant-a", client)
    actions = {
        "text": lambda: adapter.embedder.embed_text("neutral"),
        "batch": lambda: adapter.embedder.embed_batch(["neutral"]),
        "safe": lambda: adapter.embedder.embed_text_safe("neutral"),
        "batch-safe": lambda: adapter.embedder.embed_batch_safe(["neutral"]),
        "search": lambda: adapter.search("neutral", project_id="project-a"),
        "vector": lambda: adapter.vector_search([0.1, 0.2, 0.3], project_id="project-a"),
        "process": lambda: adapter.process_episode("owned", "neutral", project_id="project-a"),
        "entities": lambda: adapter._get_entity_extractor()._create_entity_nodes(
            [{"name": "neutral"}]
        ),
        "reflexion": lambda: adapter._get_reflexion_checker()._create_entity_nodes(
            [{"name": "neutral"}]
        ),
        "rebuild": lambda: adapter.rebuild_embeddings(adapter.embedder, "project-a"),
        "write": lambda: adapter.add_episode(
            Episode(
                name="neutral",
                content="neutral",
                source_type=SourceType.TEXT,
                valid_at=datetime.now(UTC),
                project_id="project-a",
                tenant_id="tenant-a",
            )
        ),
    }
    with pytest.raises(NoActiveProviderError, match="provider_unconfigured"):
        await actions[operation]()

    factory.resolve_provider.assert_awaited_once()
    client.execute_query.assert_not_awaited()
    client.vector_search.assert_not_awaited()
    client.create_vector_index.assert_not_awaited()
    embedder.create.assert_not_awaited()


async def test_sql_memory_get_and_list_compose_without_resolving_embedding(
    dependencies, test_db, test_memory_db
):
    from src.application.use_cases.memory.get_memory import GetMemoryQuery
    from src.application.use_cases.memory.list_memories import ListMemoriesQuery
    from src.infrastructure.plugins.v2.graph_runtime import GraphRuntimeServiceV2
    from src.infrastructure.plugins.v2.memory_services import (
        MemoryApplicationResolverV2,
        SqlMemoryRepositoryProviderV2,
    )

    client, factory, _embedder = dependencies
    adapter = await factories.create_native_graph_adapter("tenant-a", client)
    resolver = MemoryApplicationResolverV2(
        graph_runtime=GraphRuntimeServiceV2(graph_service=adapter),
        repository_provider=SqlMemoryRepositoryProviderV2(strategy="request-async-session"),
    )
    services = resolver.resolve(SimpleNamespace(require=lambda _key: test_db))

    memory = await services.get_memory_use_case.execute(GetMemoryQuery(memory_id=test_memory_db.id))
    memories = await services.list_memories_use_case.execute(
        ListMemoriesQuery(project_id=test_memory_db.project_id)
    )

    assert memory.id == test_memory_db.id
    assert [item.id for item in memories] == [test_memory_db.id]
    factory.resolve_provider.assert_not_awaited()
    client.execute_query.assert_not_awaited()


@pytest.mark.parametrize("operation", ["text", "batch", "safe", "batch-safe"])
async def test_cached_embedding_cannot_hide_missing_provider_even_with_cached_vector(
    dependencies, operation
):
    from src.infrastructure.memory.cached_embedding import CachedEmbeddingService

    client, _factory, _embedder = dependencies
    adapter = await factories.create_native_graph_adapter("tenant-a", client)
    cached = CachedEmbeddingService(adapter.embedder)
    cached._l1_put(cached._cache_key("neutral"), [0.1, 0.2, 0.3])
    actions = {
        "text": lambda: cached.embed_text("neutral"),
        "batch": lambda: cached.embed_batch(["neutral"]),
        "safe": lambda: cached.embed_text_safe("neutral"),
        "batch-safe": lambda: cached.embed_batch_safe(["neutral"]),
    }

    with pytest.raises(NoActiveProviderError, match="provider_unconfigured"):
        await actions[operation]()


async def test_hybrid_search_does_not_hide_configuration_error_in_parallel_results(dependencies):
    from src.infrastructure.graph.search.hybrid_search import HybridSearch

    client, _factory, _embedder = dependencies
    adapter = await factories.create_native_graph_adapter("tenant-a", client)
    search = HybridSearch(client, adapter.embedder)

    with pytest.raises(NoActiveProviderError, match="provider_unconfigured"):
        await search.search("neutral", project_id="project-a")


@pytest.mark.parametrize("source", ["memory", "episode", "conversation"])
@pytest.mark.parametrize("cached", [False, True])
async def test_chunk_indexing_rejects_missing_provider_before_deleting_existing_chunks(
    dependencies, source, cached
):
    from src.application.services.memory_index_service import MemoryIndexService
    from src.infrastructure.memory.cached_embedding import CachedEmbeddingService

    client, _factory, _embedder = dependencies
    adapter = await factories.create_native_graph_adapter("tenant-a", client)
    repository = MagicMock()
    embedding = CachedEmbeddingService(adapter.embedder) if cached else adapter.embedder
    index = MemoryIndexService(repository, embedding)
    actions = {
        "memory": lambda: index.index_memory("owned", "neutral", "project-a"),
        "episode": lambda: index.index_episode("owned", "neutral", "project-a"),
        "conversation": lambda: index.index_conversation(
            "owned", [{"role": "user", "content": "neutral"}], "project-a"
        ),
    }

    with pytest.raises(NoActiveProviderError, match="provider_unconfigured"):
        await actions[source]()

    assert repository.mock_calls == []


async def test_deferred_resolution_failure_keeps_healthy_graph_connection(dependencies):
    client, factory, _embedder = dependencies
    factory.resolve_provider.side_effect = None
    factory.resolve_provider.return_value = object()
    client.create_vector_index.side_effect = ValueError("index unavailable")
    adapter = await factories.create_native_graph_adapter("tenant-a", client)

    with pytest.raises(ValueError, match="index unavailable"):
        await adapter.embedder.embed_text("neutral")

    assert await adapter.get_entity("missing") is None
    client.close.assert_not_awaited()
    client.create_vector_index.side_effect = None
    assert await adapter.embedder.embed_text("neutral") == [0.1, 0.2, 0.3]
    assert factory.resolve_provider.await_count == 2


async def test_cancelled_resolution_can_be_retried_without_closing_storage(dependencies):
    client, factory, _embedder = dependencies
    factory.resolve_provider.side_effect = asyncio.CancelledError()
    adapter = await factories.create_native_graph_adapter("tenant-a", client)

    with pytest.raises(asyncio.CancelledError):
        await adapter.embedder.embed_text("neutral")

    factory.resolve_provider.side_effect = None
    factory.resolve_provider.return_value = object()
    assert await adapter.embedder.embed_batch(["neutral"]) == [[0.1, 0.2, 0.3]]
    client.close.assert_not_awaited()


async def test_concurrent_first_embedding_resolves_once_and_keeps_real_dimensions(dependencies):
    client, factory, embedder = dependencies
    factory.resolve_provider.side_effect = None
    factory.resolve_provider.return_value = object()
    adapter = await factories.create_native_graph_adapter("tenant-a", client)
    factory.resolve_provider.assert_not_awaited()

    vectors = await asyncio.gather(*(adapter.embedder.embed_text("neutral") for _ in range(5)))

    assert vectors == [[0.1, 0.2, 0.3]] * 5
    assert adapter.embedder.embedding_dim == 3
    factory.resolve_provider.assert_awaited_once()
    assert factory.resolve_provider.await_args.kwargs["tenant_id"] == "tenant-a"
    assert client.create_vector_index.await_count == 2
    assert client.create_vector_index.await_args_list[0].kwargs["dimensions"] == 3
    assert embedder.create.await_count == 5


async def test_missing_provider_is_not_cached_and_later_configuration_recovers(dependencies):
    _client, factory, _embedder = dependencies
    adapter = await factories.create_native_graph_adapter("tenant-a", _client)
    with pytest.raises(NoActiveProviderError):
        await adapter.embedder.embed_text("neutral")

    factory.resolve_provider.side_effect = None
    factory.resolve_provider.return_value = object()

    assert await adapter.embedder.embed_text("neutral") == [0.1, 0.2, 0.3]
    assert factory.resolve_provider.await_count == 2


async def test_unresolved_dimension_does_not_fabricate_a_default(dependencies):
    client, factory, _embedder = dependencies
    adapter = await factories.create_native_graph_adapter("tenant-a", client)

    with pytest.raises(NoActiveProviderError, match="provider_unconfigured"):
        _ = adapter.embedder.embedding_dim

    factory.resolve_provider.assert_not_awaited()


@pytest.mark.parametrize(
    "endpoint",
    [
        "get_embedding_status",
        "check_embedding_dimensions",
        "validate_embeddings",
        "rebuild_embeddings",
    ],
)
async def test_maintenance_dimension_queries_preserve_typed_missing_provider(
    dependencies, monkeypatch, endpoint
):
    from src.infrastructure.adapters.primary.web.routers import maintenance

    client, _factory, _embedder = dependencies
    adapter = await factories.create_native_graph_adapter("tenant-a", client)
    monkeypatch.setattr(
        maintenance, "_resolve_maintenance_scope", AsyncMock(return_value=("project-a", True, []))
    )

    with pytest.raises(NoActiveProviderError, match="provider_unconfigured"):
        await getattr(maintenance, endpoint)(
            project_id="project-a",
            current_user=SimpleNamespace(tenant_id="tenant-a"),
            db=object(),
            graph_store=adapter,
        )


@pytest.mark.parametrize("name", ["memory_search", "memory_create", "memory_update"])
async def test_memory_embedding_tools_expose_config_error_before_database_write(dependencies, name):
    client, _factory, _embedder = dependencies
    adapter = await factories.create_native_graph_adapter("tenant-a", client)
    session_factory = MagicMock()
    tools = build_memory_tools(
        tenant_id="tenant-a",
        project_id="project-a",
        graph_service=adapter,
        redis_client=None,
        session_factory=session_factory,
    )
    context = ToolContext(
        session_id="session-a",
        message_id="message-a",
        call_id="call-a",
        agent_name="agent-a",
        conversation_id="conversation-a",
        project_id="project-a",
    )
    arguments = {
        "memory_search": {"query": "neutral"},
        "memory_create": {"content": "neutral"},
        "memory_update": {"memory_id": "missing", "content": "neutral"},
    }
    result = await tools[name].execute(context, **arguments[name])

    assert result.is_error is True
    assert json.loads(result.output)["code"] == "provider_unconfigured"
    session_factory.assert_not_called()
    client.execute_query.assert_not_awaited()
