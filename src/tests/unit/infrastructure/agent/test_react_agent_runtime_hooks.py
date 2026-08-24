from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.infrastructure.plugins.v2.agent_runtime_dispatcher import (
    AGENT_RUNTIME_DISPATCHER_SERVICE_V2,
    AgentRuntimeDispatchResultV2,
)


def _make_agent():
    from src.infrastructure.agent.core.react_agent import ReActAgent

    return ReActAgent(
        model="test-model",
        tools={"test_tool": MagicMock()},
    )


def _make_dispatcher(*, payload=None):
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(
        return_value=AgentRuntimeDispatchResultV2(
            payload=dict(payload or {}),
        )
    )
    return dispatcher


def _operation_context(dispatcher):
    operation = SimpleNamespace(
        require=lambda service: (
            dispatcher
            if service == AGENT_RUNTIME_DISPATCHER_SERVICE_V2
            else (_ for _ in ()).throw(AssertionError(f"unexpected service: {service}"))
        )
    )
    return patch(
        "src.infrastructure.plugins.v2.boundary.current_operation_context_v2",
        return_value=operation,
    )


@pytest.mark.unit
class TestReActAgentRuntimeHooks:
    @pytest.mark.asyncio
    async def test_before_prompt_build_hook_can_override_memory_context(self) -> None:
        dispatcher = _make_dispatcher(payload={"memory_context": "hook memory"})
        agent = _make_agent()
        agent._stream_memory_context = "legacy memory"

        with _operation_context(dispatcher):
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
        dispatcher.dispatch.assert_awaited_once()
        assert dispatcher.dispatch.await_args.args[0] == "before_prompt_build"
        payload = dispatcher.dispatch.await_args.kwargs["payload"]
        assert payload["memory_context"] == "legacy memory"
        assert payload["tenant_id"] == "tenant-1"
        assert payload["project_id"] == "proj-1"

    @pytest.mark.asyncio
    async def test_before_prompt_build_hook_uses_initialized_default_memory_context(self) -> None:
        dispatcher = _make_dispatcher(payload={})
        agent = _make_agent()

        with _operation_context(dispatcher):
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
        payload = dispatcher.dispatch.await_args.kwargs["payload"]
        assert payload["memory_context"] is None

    @pytest.mark.asyncio
    async def test_context_overflow_hook_fires_on_compression(self) -> None:
        dispatcher = _make_dispatcher()
        agent = _make_agent()

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
        with _operation_context(dispatcher):
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
        dispatcher.dispatch.assert_awaited_once()
        assert dispatcher.dispatch.await_args.args[0] == "on_context_overflow"
        payload = dispatcher.dispatch.await_args.kwargs["payload"]
        assert payload["compression_level"] == "summary"
        assert payload["conversation_id"] == "conv-1"

    @pytest.mark.asyncio
    async def test_after_turn_complete_hook_fires_after_post_process(self) -> None:
        dispatcher = _make_dispatcher()
        agent = _make_agent()

        events = []
        with _operation_context(dispatcher):
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
        dispatcher.dispatch.assert_awaited_once()
        assert dispatcher.dispatch.await_args.args[0] == "after_turn_complete"
        payload = dispatcher.dispatch.await_args.kwargs["payload"]
        assert payload["success"] is True
        assert payload["final_content"] == "done"
