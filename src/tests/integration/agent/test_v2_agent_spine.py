"""End-to-end evidence for the generation-pinned V2 Agent spine."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.domain.model.agent.skill import Skill
from src.domain.model.agent.subagent import SubAgent
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.agent.actor import execution
from src.infrastructure.agent.core.llm_stream import StreamEventType
from src.infrastructure.agent.core.react_agent import ReActAgent
from src.infrastructure.agent.core.react_agent_stream_mixin import (
    _resolve_agent_capabilities_from_runtime_v2,
    _resolve_current_tools_from_runtime_v2,
)
from src.infrastructure.agent.plugins.selection_pipeline import ToolSelectionContext
from src.infrastructure.agent.processor.factory import ProcessorFactory
from src.infrastructure.agent.processor.processor import ProcessorConfig
from src.infrastructure.agent.processor.run_context import RunContext
from src.infrastructure.plugins.v2 import session_event_log_store as store_module
from src.infrastructure.plugins.v2.agent_runtime_dispatcher import (
    AGENT_RUNTIME_DISPATCHER_SERVICE_V2,
)
from src.infrastructure.plugins.v2.boundary import pin_operation_context_v2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import ProfileDocumentV2
from src.infrastructure.plugins.v2.darwinian_evolver_capability import (
    DARWINIAN_EVOLVER_SKILL_MODULE_V2,
)
from src.infrastructure.plugins.v2.docker_compose_capabilities import (
    DOCKER_COMPOSE_SKILL_MODULE_V2,
    DOCKER_COMPOSE_TOOL_MODULE_V2,
)
from src.infrastructure.plugins.v2.drone_capabilities import (
    DRONE_SKILL_MODULE_V2,
    DRONE_TOOL_MODULE_V2,
)
from src.infrastructure.plugins.v2.github_capabilities import (
    GITHUB_SKILL_MODULE_V2,
    GITHUB_TOOL_MODULE_V2,
)
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2
from src.infrastructure.plugins.v2.session_event_log import (
    MODEL_MESSAGE_COMMITTED_EVENT_V2,
    SESSION_EVENT_LOG_SERVICE_V2,
    TURN_ADMITTED_EVENT_V2,
    SessionEventCursorV2,
    SessionEventLogServiceV2,
    SessionEventRecordV2,
)

_ROOT = Path(__file__).resolve().parents[4]
_SCOPE = ScopeV2(
    kind=ScopeKindV2.SESSION,
    tenant_id="tenant-a",
    project_id="project-a",
    session_id="conversation-a",
)
_OPTIONAL_AGENT_CAPABILITY_MODULES = frozenset(
    {
        GITHUB_TOOL_MODULE_V2,
        GITHUB_SKILL_MODULE_V2,
        DOCKER_COMPOSE_TOOL_MODULE_V2,
        DOCKER_COMPOSE_SKILL_MODULE_V2,
        DRONE_TOOL_MODULE_V2,
        DRONE_SKILL_MODULE_V2,
        DARWINIAN_EVOLVER_SKILL_MODULE_V2,
    }
)


def _agent_spine_test_profile(document: ProfileDocumentV2) -> ProfileDocumentV2:
    """Explicitly disable optional capabilities outside this spine scenario."""
    return replace(
        document,
        entries=tuple(
            replace(entry, enabled=False)
            if entry.module_ref in _OPTIONAL_AGENT_CAPABILITY_MODULES
            else entry
            for entry in document.entries
        ),
    )


@dataclass
class _MemorySessionEventLogStore:
    records: list[SessionEventRecordV2] = field(default_factory=list)

    async def append_stream_events(
        self,
        *,
        conversation_id: str,
        message_id: str,
        events: list[dict[str, Any]],
        correlation_id: str | None,
    ) -> None:
        _ = correlation_id
        for event in events:
            sequence = len(self.records)
            self.records.append(
                SessionEventRecordV2(
                    event_id=f"{message_id}:{sequence}",
                    conversation_id=conversation_id,
                    message_id=message_id,
                    event_type=event["type"],
                    event_data=dict(event["data"]),
                    cursor=SessionEventCursorV2(
                        event_time_us=1_000 + sequence,
                        event_counter=0,
                    ),
                )
            )

    async def read_events(
        self,
        *,
        conversation_id: str,
        after: SessionEventCursorV2 | None,
        limit: int,
    ) -> list[SessionEventRecordV2]:
        records = [record for record in self.records if record.conversation_id == conversation_id]
        if after is not None:
            records = [record for record in records if record.cursor > after]
        return sorted(records, key=lambda record: record.cursor)[:limit]

    async def last_cursor(self, *, conversation_id: str) -> SessionEventCursorV2:
        return max(
            (record.cursor for record in self.records if record.conversation_id == conversation_id),
            default=SessionEventCursorV2(),
        )


class _EchoTool:
    name = "echo"
    description = "Return the supplied value."

    def __init__(self) -> None:
        self.calls: list[str] = []

    def get_parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
            "additionalProperties": False,
        }

    async def execute(self, *, value: str) -> str:
        self.calls.append(value)
        return f"echo:{value}"


def _skill() -> Skill:
    return Skill.create(
        tenant_id="tenant-a",
        project_id="project-a",
        name="echo-skill",
        description="Use the echo tool.",
        tools=["echo"],
    )


def _subagent() -> SubAgent:
    return SubAgent.create(
        tenant_id="tenant-a",
        project_id="project-a",
        name="echo-reviewer",
        display_name="Echo Reviewer",
        system_prompt="Review echo results.",
        trigger_description="Use for echo result review.",
    )


@pytest.mark.integration
async def test_v2_generation_drives_tool_turn_capabilities_and_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _MemorySessionEventLogStore()
    monkeypatch.setattr(store_module, "SqlSessionEventLogStoreV2", lambda: store)
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=11,
        version=11,
        nonce="agent-spine-integration",
        profile_projector=_agent_spine_test_profile,
    )

    llm_messages: list[list[dict[str, Any]]] = []

    async def fake_generate(
        _self: object,
        messages: list[dict[str, Any]],
        **_kwargs: object,
    ):
        llm_messages.append(messages)
        if len(llm_messages) == 1:
            yield SimpleNamespace(
                type=StreamEventType.TOOL_CALL_START,
                data={"call_id": "call-echo", "name": "echo"},
            )
            yield SimpleNamespace(
                type=StreamEventType.TOOL_CALL_END,
                data={
                    "call_id": "call-echo",
                    "name": "echo",
                    "arguments": {"value": "ready"},
                },
            )
            yield SimpleNamespace(
                type=StreamEventType.FINISH,
                data={"reason": "tool_calls"},
            )
            return
        yield SimpleNamespace(
            type=StreamEventType.TEXT_END,
            data={"full_text": "Echo completed."},
        )
        yield SimpleNamespace(
            type=StreamEventType.FINISH,
            data={"reason": "stop"},
        )

    monkeypatch.setattr(
        "src.infrastructure.agent.processor.processor.LLMStream.generate",
        fake_generate,
    )

    try:
        async with pin_operation_context_v2(
            host,
            operation_id="agent-spine-turn",
            scope=_SCOPE,
        ) as operation:
            event_log = operation.require(SESSION_EVENT_LOG_SERVICE_V2)
            assert isinstance(event_log, SessionEventLogServiceV2)
            await event_log.append(
                conversation_id="conversation-a",
                message_id="message-a",
                events=[
                    {
                        "type": TURN_ADMITTED_EVENT_V2,
                        "data": {"model_message": {"role": "user", "content": "Run echo."}},
                    }
                ],
            )

            echo = _EchoTool()
            agent = ReActAgent(
                model="test-model",
                provider_id="test-provider",
                tools={"echo": echo},
                skills=[_skill()],
                subagents=[_subagent()],
            )
            raw_tools, tool_definitions = _resolve_current_tools_from_runtime_v2(
                agent,
                ToolSelectionContext(),
            )
            capabilities = await _resolve_agent_capabilities_from_runtime_v2(
                agent,
                tenant_id="tenant-a",
                project_id="project-a",
            )
            tool_definitions = agent._stream_inject_subagent_tools(
                tools_to_use=tool_definitions,
                available_subagents=capabilities.subagents,
                conversation_context=[],
                project_id="project-a",
                tenant_id="tenant-a",
                conversation_id="conversation-a",
                abort_signal=None,
            )

            assert list(raw_tools) == ["echo"]
            assert [skill.name for skill in capabilities.skills] == ["echo-skill"]
            assert [subagent.name for subagent in capabilities.subagents] == ["echo-reviewer"]
            assert "delegate_to_subagent" in {tool.name for tool in tool_definitions}

            processor = ProcessorFactory().create_for_main(
                ProcessorConfig(
                    model="test-model",
                    provider_id="test-provider",
                    plugin_event_dispatcher=operation.require(AGENT_RUNTIME_DISPATCHER_SERVICE_V2),
                    runtime_context={
                        "tenant_id": "tenant-a",
                        "project_id": "project-a",
                        "conversation_id": "conversation-a",
                    },
                ),
                tool_definitions,
            )
            run_context = RunContext(conversation_id="conversation-a")
            processor_events = [
                event
                async for event in processor.process(
                    session_id="conversation-a",
                    messages=[{"role": "user", "content": "Run echo."}],
                    run_ctx=run_context,
                )
            ]
            committed = [
                event
                for event in processor_events
                if isinstance(event, dict) and event.get("type") == MODEL_MESSAGE_COMMITTED_EVENT_V2
            ]
            await execution._persist_events(
                conversation_id="conversation-a",
                message_id="message-a",
                events=committed,
            )
            replayed = await event_log.materialize_model_messages(conversation_id="conversation-a")

            assert echo.calls == ["ready"]
            assert len(llm_messages) == 2
            assert any(message.get("role") == "tool" for message in llm_messages[1])
            assert run_context.plugin_generation == operation.descriptor
            assert replayed == [
                {"role": "user", "content": "Run echo."},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call-echo",
                            "type": "function",
                            "function": {
                                "name": "echo",
                                "arguments": '{"value": "ready"}',
                            },
                        }
                    ],
                },
                {"role": "tool", "tool_call_id": "call-echo", "content": "echo:ready"},
                {"role": "assistant", "content": "Echo completed."},
            ]
            assert all(
                record.event_data["plugin_generation"] == operation.descriptor.to_payload()
                for record in store.records
            )
    finally:
        await host.close()
