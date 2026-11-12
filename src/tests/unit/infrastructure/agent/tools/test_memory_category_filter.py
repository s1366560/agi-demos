"""Category filters must not keep differently labeled memory hits."""

import json

import pytest

from src.infrastructure.agent.tools.memory_tools import memory_result_matches_category

pytestmark = pytest.mark.unit


def test_preference_filter_drops_fact_and_graph_hits() -> None:
    preference = {"category": "preference", "content": "use Chinese"}
    fact = {"category": "fact", "content": "other"}
    graph = {"category": "fact", "source_type": "knowledge_graph", "content": "graph"}
    kept = [
        item
        for item in (preference, fact, graph)
        if memory_result_matches_category(item, "preference")
    ]
    assert kept == [preference]


def test_unfiltered_search_keeps_every_category() -> None:
    items = [{"category": "fact"}, {"category": "preference"}]
    assert [item for item in items if memory_result_matches_category(item, None)] == items


@pytest.mark.asyncio
async def test_preference_search_keeps_pending_chunks_and_skips_graph_facts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from src.infrastructure.agent.tools.context import ToolContext
    from src.infrastructure.agent.tools.memory_tools import memory_search_tool

    chunk = SimpleNamespace(
        content="prefer Chinese",
        score=0.91,
        category="preference",
        source_type="memory",
        source_id="mem-1",
        created_at=None,
        processing_status="PENDING",
    )

    async def search(**_kwargs: object) -> list[SimpleNamespace]:
        return [chunk]

    async def graph(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("graph facts must not join a preference search")

    monkeypatch.setattr(
        "src.infrastructure.agent.tools.memory_tools._current_memory_search_runtime",
        lambda: (SimpleNamespace(search=search), object(), "project-1"),
    )

    async def ready(_embedder: object) -> None:
        return None

    monkeypatch.setattr(
        "src.infrastructure.agent.tools.memory_tools.ensure_embedding_available",
        ready,
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.tools.memory_tools._search_graph_for_tool",
        graph,
    )
    result = await memory_search_tool.execute(
        ToolContext(
            session_id="session-1",
            message_id="message-1",
            call_id="call-1",
            agent_name="tester",
            conversation_id="conversation-1",
            project_id="project-1",
        ),
        query="language",
        category="preference",
    )
    payload = json.loads(result.output)
    assert payload["category"] == "preference"
    assert payload["results"] == [
        {
            "content": "prefer Chinese",
            "score": 0.91,
            "category": "preference",
            "source_type": "memory",
            "source_id": "mem-1",
            "created_at": "",
            "processing_status": "PENDING",
            "citation": "[preference | memory:mem-1 | ]",
        }
    ]
