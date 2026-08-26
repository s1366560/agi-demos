"""Generation-local runtime coverage for the builtin memory tools."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from src.infrastructure.agent.tools import memory_tools as memory_tools_module
from src.infrastructure.agent.tools.context import ToolContext


def _context(name: str) -> ToolContext:
    return ToolContext(
        session_id=f"session-{name}",
        message_id=f"message-{name}",
        call_id=f"call-{name}",
        agent_name=f"agent-{name}",
        conversation_id=f"conversation-{name}",
    )


@pytest.mark.unit
def test_memory_provider_uses_bound_factory_without_global_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.infrastructure.agent.tools.memory_tool_provider import build_memory_tools

    embedding_service = object()
    cached_embedding = object()
    chunk_search = object()
    graph_service = SimpleNamespace(embedder=embedding_service)
    redis_client = object()
    session_factory = object()
    expected = {"memory_search": object()}
    captured: dict[str, object] = {}

    def _forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("memory provider must not mutate process-global tool state")

    def _make_memory_tools(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return expected

    monkeypatch.setattr(
        "src.configuration.config.get_settings",
        lambda: SimpleNamespace(agent_memory_tool_provider_mode="enabled"),
    )
    monkeypatch.setattr(
        "src.infrastructure.memory.cached_embedding.CachedEmbeddingService",
        lambda *_args, **_kwargs: cached_embedding,
    )
    monkeypatch.setattr(
        "src.infrastructure.memory.chunk_search.ChunkHybridSearch",
        lambda *_args, **_kwargs: chunk_search,
    )
    monkeypatch.setattr(memory_tools_module, "make_memory_tools", _make_memory_tools, raising=False)
    for name in (
        "configure_memory_get",
        "configure_memory_create",
        "configure_memory_search",
    ):
        monkeypatch.setattr(memory_tools_module, name, _forbidden)

    result = build_memory_tools(
        tenant_id="tenant-a",
        project_id="project-a",
        graph_service=graph_service,
        redis_client=redis_client,
        session_factory=session_factory,  # type: ignore[arg-type]
    )

    assert result is expected
    assert captured == {
        "tenant_id": "tenant-a",
        "project_id": "project-a",
        "graph_service": graph_service,
        "chunk_search": chunk_search,
        "session_factory": session_factory,
        "embedding_service": cached_embedding,
    }


@pytest.mark.unit
async def test_memory_tool_runtime_isolated_between_concurrent_generations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_entered = asyncio.Event()
    release_first = asyncio.Event()
    captured: dict[str, dict[str, object]] = {}

    async def _execute_memory_create(
        *,
        content: str,
        title: str,
        category: str,
        tags: list[str],
        session_factory: object,
        graph_service: object,
        project_id: str,
        tenant_id: str,
        user_id: str = "",
        embedding_service: object = None,
    ) -> str:
        _ = title, category, tags, user_id
        captured[content] = {
            "session_factory": session_factory,
            "graph_service": graph_service,
            "project_id": project_id,
            "tenant_id": tenant_id,
            "embedding_service": embedding_service,
        }
        if content == "first":
            first_entered.set()
            await release_first.wait()
        else:
            await first_entered.wait()
            release_first.set()
        return json.dumps({"status": "created", "content": content})

    monkeypatch.setattr(memory_tools_module, "_execute_memory_create", _execute_memory_create)
    memory_tools_module.configure_memory_create(
        session_factory=lambda: None,
        graph_service="poison-graph",
        project_id="poison-project",
        tenant_id="poison-tenant",
        embedding_service="poison-embedding",
    )

    first_runtime = {
        "session_factory": object(),
        "graph_service": object(),
        "project_id": "project-a",
        "tenant_id": "tenant-a",
        "embedding_service": object(),
    }
    second_runtime = {
        "session_factory": object(),
        "graph_service": object(),
        "project_id": "project-b",
        "tenant_id": "tenant-b",
        "embedding_service": object(),
    }
    first_tools = memory_tools_module.make_memory_tools(
        **first_runtime,
        chunk_search=object(),
    )
    second_tools = memory_tools_module.make_memory_tools(
        **second_runtime,
        chunk_search=object(),
    )

    first_task = asyncio.create_task(
        first_tools["memory_create"].execute(_context("a"), content="first")
    )
    await first_entered.wait()
    second_result = await second_tools["memory_create"].execute(
        _context("b"),
        content="second",
    )
    first_result = await first_task

    assert json.loads(first_result.output)["content"] == "first"
    assert json.loads(second_result.output)["content"] == "second"
    assert captured == {
        "first": first_runtime,
        "second": second_runtime,
    }
