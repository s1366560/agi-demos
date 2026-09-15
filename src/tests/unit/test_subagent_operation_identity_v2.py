"""Real SubAgent loop entry preserves scope and independent execution identity."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from src.domain.model.agent.subagent import SubAgent
from src.domain.model.agent.subagent_run import SubAgentRun
from src.infrastructure.adapters.primary.web.routers.agent.trace_router import run_to_response
from src.infrastructure.agent.processor.processor import ProcessorConfig, SessionProcessor
from src.infrastructure.agent.subagent.context_bridge import SubAgentContext
from src.infrastructure.agent.subagent.process import SubAgentProcess
from src.infrastructure.plugins.v2.agent_runtime_dispatcher import _validate_event_scope_v2


@pytest.mark.parametrize("conversation_id", ["conversation-a", "conversation-other"])
async def test_sibling_processes_use_conversation_scope_and_distinct_trace_ids(conversation_id):
    observed = []

    class Dispatcher:
        async def dispatch(self, event, payload):
            _validate_event_scope_v2(payload, required_scope={"session_id": "conversation-a"})
            observed.append((event, payload["session_id"]))
            return SimpleNamespace(diagnostics=[], payload=payload)

    subagent = SubAgent.create(
        tenant_id="tenant-a",
        name="qa",
        display_name="QA",
        system_prompt="QA",
        trigger_description="QA",
        allowed_tools=[],
    )
    contexts = []
    for run_id in ("child-a", "child-b"):
        processor = SessionProcessor(
            ProcessorConfig(
                model="test",
                plugin_event_dispatcher=Dispatcher(),
            ),
            tools=[],
        )
        processor._try_intercept_command = AsyncMock(return_value=[])

        async def loop_entry(*, session_id, messages, run_ctx):
            contexts.append(run_ctx)
            async for event in processor._run_native_loop(session_id, messages):
                yield event

        child = SubAgentProcess(
            subagent=subagent,
            context=SubAgentContext(
                task_description="QA",
                system_prompt="QA",
                metadata={"conversation_id": conversation_id},
            ),
            tools=[],
            base_model="test",
            run_id=run_id,
        )
        with patch.object(
            child, "_build_processor", return_value=SimpleNamespace(process=loop_entry)
        ):
            _events = [event async for event in child.execute()]
        if conversation_id != "conversation-a":
            assert not child.result.success
            assert "differs from the pinned operation" in child.result.error
            continue
        assert child.result.success, child.result.error
    if conversation_id != "conversation-a":
        assert observed == []
        return
    assert observed == [("on_session_start", "conversation-a")] * 2
    assert [context.trace_id for context in contexts] == ["child-a", "child-b"]
    assert all(context.conversation_id == "conversation-a" for context in contexts)


def test_trace_response_supports_nested_json_metadata_and_redaction():
    metadata = {
        "plugin_generation": {"generation": 15, "digest": "digest"},
        "announce_events": [{"run_id": "child-a", "payload": [True, None, 1.5]}],
    }
    run = SubAgentRun(
        conversation_id="conversation-a", subagent_name="qa", task="QA", metadata=metadata
    )
    response = run_to_response(run)
    assert response.model_dump(mode="json")["metadata"] == metadata
    assert run_to_response(run, redact_sensitive_fields=True).metadata == {}


def test_trace_response_rejects_non_json_objects():
    run = SubAgentRun(
        conversation_id="conversation-a",
        subagent_name="qa",
        task="QA",
        metadata={"nested": {"invalid": object()}},
    )
    with pytest.raises(ValidationError):
        run_to_response(run)
