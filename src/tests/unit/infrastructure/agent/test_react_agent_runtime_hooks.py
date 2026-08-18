from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.infrastructure.agent.plugins.registry import HookDispatchResult


@pytest.fixture(autouse=True)
def _legacy_plugin_event_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin these legacy hook-contract tests to the legacy dispatch path."""
    from src.configuration.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "platform_plugin_agent_events_v2", False)
    monkeypatch.setattr(settings, "platform_plugin_agent_events_shadow", False)
    monkeypatch.setattr(settings, "platform_plugin_agent_events_remove_legacy", False)


def _make_agent(*, registry=None):
    from src.infrastructure.agent.core.react_agent import ReActAgent

    agent = ReActAgent(
        model="test-model",
        tools={"test_tool": MagicMock()},
    )
    if registry is not None:
        agent.config.plugin_registry = registry
    return agent


def _make_registry(*, payload=None):
    registry = MagicMock()
    registry.apply_hook = AsyncMock(
        return_value=HookDispatchResult(
            payload=dict(payload or {}),
            diagnostics=[],
        )
    )
    return registry


@pytest.mark.unit
class TestReActAgentRuntimeHooks:
    @pytest.mark.asyncio
    async def test_before_prompt_build_hook_can_override_memory_context(self) -> None:
        registry = _make_registry(payload={"memory_context": "hook memory"})
        agent = _make_agent(registry=registry)
        agent._stream_memory_context = "legacy memory"

        resolved, emitted_events = await agent._apply_before_prompt_build_hook(
            processed_user_message="hello",
            conversation_context=[{"role": "user", "content": "hello"}],
            project_id="proj-1",
            tenant_id="tenant-1",
            conversation_id="conv-1",
            effective_mode="build",
            matched_skill=None,
            selected_agent=SimpleNamespace(id="agent-1", name="Atlas"),
        )

        assert resolved == "hook memory"
        assert emitted_events == []
        payload = registry.apply_hook.await_args.kwargs["payload"]
        assert payload["memory_context"] == "legacy memory"
        assert payload["tenant_id"] == "tenant-1"
        assert payload["project_id"] == "proj-1"

    @pytest.mark.asyncio
    async def test_before_prompt_build_hook_uses_initialized_default_memory_context(self) -> None:
        registry = _make_registry(payload={})
        agent = _make_agent(registry=registry)

        resolved, emitted_events = await agent._apply_before_prompt_build_hook(
            processed_user_message="hello",
            conversation_context=[{"role": "user", "content": "hello"}],
            project_id="proj-1",
            tenant_id="tenant-1",
            conversation_id="conv-1",
            effective_mode="build",
            matched_skill=None,
            selected_agent=SimpleNamespace(id="agent-1", name="Atlas"),
        )

        assert resolved is None
        assert emitted_events == []
        payload = registry.apply_hook.await_args.kwargs["payload"]
        assert payload["memory_context"] is None

    @pytest.mark.asyncio
    async def test_context_overflow_hook_fires_on_compression(self) -> None:
        registry = _make_registry()
        agent = _make_agent(registry=registry)

        context_result = SimpleNamespace(
            was_compressed=True,
            messages=[{"role": "system", "content": "system"}],
            summary="trimmed summary",
            estimated_tokens=128,
            token_budget=1024,
            budget_utilization_pct=12.5,
            summarized_message_count=4,
            original_message_count=6,
            final_message_count=2,
            compression_strategy=SimpleNamespace(value="summary"),
            metadata={"compression_level": "summary", "compression_history": {}},
            to_event_data=lambda: {
                "was_compressed": True,
                "compression_strategy": "summary",
                "original_message_count": 6,
                "final_message_count": 2,
                "estimated_tokens": 128,
                "token_budget": 1024,
                "budget_utilization_pct": 12.5,
            },
        )
        agent.context_facade = SimpleNamespace(build_context=AsyncMock(return_value=context_result))

        events = []
        async for event in agent._stream_build_context(
            system_prompt="system",
            conversation_context=[{"role": "user", "content": "a"}],
            processed_user_message="hello",
            attachment_metadata=None,
            attachment_content=None,
            context_summary_data=None,
            tenant_id="tenant-1",
            project_id="proj-1",
            conversation_id="conv-1",
        ):
            events.append(event)

        assert events[0]["type"] == "context_compressed"
        registry.apply_hook.assert_awaited_once()
        assert registry.apply_hook.await_args.args[0] == "on_context_overflow"
        payload = registry.apply_hook.await_args.kwargs["payload"]
        assert payload["compression_level"] == "summary"
        assert payload["conversation_id"] == "conv-1"

    @pytest.mark.asyncio
    async def test_after_turn_complete_hook_fires_after_post_process(self) -> None:
        registry = _make_registry()
        agent = _make_agent(registry=registry)

        events = []
        async for event in agent._stream_post_process(
            processed_user_message="hello",
            final_content="done",
            project_id="proj-1",
            tenant_id="tenant-1",
            conversation_id="conv-1",
            conversation_context=[],
            matched_skill=None,
            success=True,
        ):
            events.append(event)

        assert events[-1]["type"] == "complete"
        registry.apply_hook.assert_awaited_once()
        assert registry.apply_hook.await_args.args[0] == "after_turn_complete"
        payload = registry.apply_hook.await_args.kwargs["payload"]
        assert payload["success"] is True
        assert payload["final_content"] == "done"
