"""End-to-end evidence for the generation-pinned V2 Agent spine."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.domain.model.agent.skill import Skill
from src.domain.model.agent.subagent import SubAgent
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.agent.actor import execution
from src.infrastructure.agent.canvas.manager import CanvasManager
from src.infrastructure.agent.canvas.tools import make_canvas_tools
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
from src.infrastructure.agent.tools.clarification import make_clarification_tool
from src.infrastructure.agent.tools.cron_tool import make_cron_tool
from src.infrastructure.agent.tools.custom_tool_status import custom_tools_status
from src.infrastructure.agent.tools.decision import make_decision_tool
from src.infrastructure.agent.tools.env_var_tools import make_env_var_tools
from src.infrastructure.agent.tools.memory_tools import (
    memory_create_tool,
    memory_delete_tool,
    memory_get_tool,
    memory_search_tool,
    memory_update_tool,
)
from src.infrastructure.agent.tools.model_availability_tool import make_model_awareness_tools
from src.infrastructure.agent.tools.register_mcp_server import register_mcp_server_tool
from src.infrastructure.agent.tools.register_mcp_server_runtime import (
    make_register_mcp_server_tool,
)
from src.infrastructure.agent.tools.session_comm_tools import make_session_comm_tools
from src.infrastructure.agent.tools.session_status import make_session_status_tool
from src.infrastructure.agent.tools.skill_installer import make_skill_installer_tool
from src.infrastructure.agent.tools.skill_loader import make_skill_loader_tool
from src.infrastructure.agent.tools.skill_sync import make_skill_sync_tool
from src.infrastructure.agent.tools.system_api import make_system_api_tool
from src.infrastructure.agent.tools.todo_tools import make_todo_tools
from src.infrastructure.agent.tools.web_scrape import web_scrape_tool
from src.infrastructure.agent.tools.web_search import make_web_search_tool
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


async def _empty_provider_resolver(_tenant_id: str) -> list[object]:
    return []


async def _ignore_model_override(_conversation_id: str, _model_name: str) -> None:
    return None


_MODEL_AWARENESS_TOOLS = make_model_awareness_tools(
    model_catalog=object(),
    provider_resolver=_empty_provider_resolver,
    persist_model_override=_ignore_model_override,
)


def _system_api_client_factory(**_kwargs: object) -> object:
    return object()


_SYSTEM_API_TOOL = make_system_api_tool(
    openapi_schema_provider=dict,
    base_url="http://127.0.0.1:8000",
    client_factory=_system_api_client_factory,
)
_CANVAS_TOOLS = make_canvas_tools(manager=CanvasManager())


@asynccontextmanager
async def _unused_session_factory() -> AsyncIterator[object]:
    """Provide an I/O-free dependency for prepared tools that are not executed here."""
    yield object()


_WEB_TOOLS = {
    "web_search": make_web_search_tool(redis_client=None),
    "web_scrape": web_scrape_tool,
}
_SKILL_LOADER_TOOL = make_skill_loader_tool(
    skill_service=object(),
    tenant_id="tenant-a",
    project_id="project-a",
)
_SKILL_MANAGEMENT_TOOLS = {
    _SKILL_LOADER_TOOL.name: _SKILL_LOADER_TOOL,
    "skill_installer": make_skill_installer_tool(
        project_path=_ROOT,
        tenant_id="tenant-a",
        project_id="project-a",
    ),
    "skill_sync": make_skill_sync_tool(
        tenant_id="tenant-a",
        project_id="project-a",
        session_factory=_unused_session_factory,
        skill_loader_tool=_SKILL_LOADER_TOOL,
    ),
}
_ENV_VAR_TOOLS = make_env_var_tools(
    encryption_service=object(),
    session_factory=_unused_session_factory,
)
_MCP_REGISTRATION_TOOL = make_register_mcp_server_tool(
    template=register_mcp_server_tool,
    session_factory=_unused_session_factory,
    tenant_id="tenant-a",
    project_id="project-a",
)
_TASK_SESSION_TOOLS = {
    **make_todo_tools(session_factory=_unused_session_factory),
    **make_session_comm_tools(session_factory=_unused_session_factory),
}
_SESSION_STATUS_TOOL = make_session_status_tool(session_factory=_unused_session_factory)
_CRON_TOOL = make_cron_tool(session_factory=_unused_session_factory)


@pytest.mark.integration
async def test_v2_generation_drives_tool_turn_capabilities_and_replay(  # noqa: PLR0915
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
            clarification = make_clarification_tool(hitl_handler=None)
            decision = make_decision_tool(hitl_handler=None)
            agent = ReActAgent(
                model="test-model",
                provider_id="test-provider",
                tools={
                    "echo": echo,
                    clarification.name: clarification,
                    decision.name: decision,
                    **_MODEL_AWARENESS_TOOLS,
                    memory_search_tool.name: memory_search_tool,
                    memory_get_tool.name: memory_get_tool,
                    memory_create_tool.name: memory_create_tool,
                    memory_update_tool.name: memory_update_tool,
                    memory_delete_tool.name: memory_delete_tool,
                    _SYSTEM_API_TOOL.name: _SYSTEM_API_TOOL,
                    **_CANVAS_TOOLS,
                    custom_tools_status.name: custom_tools_status,
                    **_TASK_SESSION_TOOLS,
                    _SESSION_STATUS_TOOL.name: _SESSION_STATUS_TOOL,
                    _CRON_TOOL.name: _CRON_TOOL,
                    **_WEB_TOOLS,
                    **_SKILL_MANAGEMENT_TOOLS,
                    **_ENV_VAR_TOOLS,
                    _MCP_REGISTRATION_TOOL.name: _MCP_REGISTRATION_TOOL,
                },
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

            assert raw_tools["echo"] is echo
            assert (
                raw_tools["ask_clarification"] is clarification
                and raw_tools["request_decision"] is decision
            )
            assert all(
                raw_tools[name] is tool for name, tool in _MODEL_AWARENESS_TOOLS.items()
            ) and all(raw_tools[name] is tool for name, tool in _CANVAS_TOOLS.items())
            assert (
                raw_tools["memory_search"] is memory_search_tool
                and raw_tools[_SYSTEM_API_TOOL.name] is _SYSTEM_API_TOOL
                and raw_tools[custom_tools_status.name] is custom_tools_status
            )
            assert all(raw_tools[name] is tool for name, tool in _TASK_SESSION_TOOLS.items())
            assert (
                raw_tools[_SESSION_STATUS_TOOL.name] is _SESSION_STATUS_TOOL
                and raw_tools[_CRON_TOOL.name] is _CRON_TOOL
            )
            assert all(raw_tools[name] is tool for name, tool in _WEB_TOOLS.items())
            assert all(raw_tools[name] is tool for name, tool in _SKILL_MANAGEMENT_TOOLS.items())
            assert all(raw_tools[name] is tool for name, tool in _ENV_VAR_TOOLS.items())
            assert raw_tools[_MCP_REGISTRATION_TOOL.name] is _MCP_REGISTRATION_TOOL
            assert "agent_spawn" in raw_tools
            assert "workspace_report_complete" in raw_tools
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
