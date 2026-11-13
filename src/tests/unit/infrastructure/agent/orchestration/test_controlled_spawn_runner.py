"""Spawn through the real orchestrator and execute tools with a scripted model.

The model stream is the only substitute. Spawn registration, the request
message, SessionProcessor tool execution, history, and the spawn status are
the production objects. Plugin-generation boot and a paid provider are not
started; a missing model must not be reported as a healthy executor.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest

from src.domain.model.agent.agent_role import AgentRole
from src.domain.model.agent.spawn_mode import SpawnMode
from src.domain.ports.services.agent_message_bus_port import (
    AgentMessage,
    AgentMessageBusPort,
    AgentMessageType,
)
from src.infrastructure.agent.core.llm_stream import StreamEventType
from src.infrastructure.agent.core.tool_converter import convert_tools
from src.infrastructure.agent.orchestration.orchestrator import AgentOrchestrator
from src.infrastructure.agent.orchestration.session_registry import AgentSessionRegistry
from src.infrastructure.agent.orchestration.spawn_manager import SpawnManager
from src.infrastructure.agent.processor.processor import ProcessorConfig, SessionProcessor
from src.infrastructure.agent.tools.define import tool_define
from src.infrastructure.agent.tools.result import ToolResult

pytestmark = pytest.mark.unit


class MemoryBus(AgentMessageBusPort):
    """In-process bus with the production message contract."""

    def __init__(self) -> None:
        self.messages: list[AgentMessage] = []

    async def send_message(
        self,
        from_agent_id: str,
        to_agent_id: str,
        session_id: str,
        content: str,
        message_type: AgentMessageType,
        metadata: dict[str, Any] | None = None,
        parent_message_id: str | None = None,
    ) -> str:
        message_id = str(uuid.uuid4())
        self.messages.append(
            AgentMessage(
                message_id=message_id,
                from_agent_id=from_agent_id,
                to_agent_id=to_agent_id,
                session_id=session_id,
                content=content,
                message_type=message_type,
                metadata=metadata,
                parent_message_id=parent_message_id,
            )
        )
        return message_id

    async def receive_messages(
        self,
        agent_id: str,
        session_id: str,
        since_id: str | None = None,
        limit: int = 50,
    ) -> list[AgentMessage]:
        del agent_id, since_id
        return await self.get_message_history(session_id, limit)

    def subscribe_messages(
        self,
        agent_id: str,
        session_id: str,
        timeout_ms: int = 5000,
    ) -> AsyncIterator[AgentMessage]:
        del agent_id, session_id, timeout_ms

        async def _empty() -> AsyncIterator[AgentMessage]:
            if False:
                yield AgentMessage(
                    message_id="",
                    from_agent_id="",
                    to_agent_id="",
                    session_id="",
                    content="",
                    message_type=AgentMessageType.NOTIFICATION,
                )

        return _empty()

    async def get_message_history(self, session_id: str, limit: int = 50) -> list[AgentMessage]:
        matched = [item for item in self.messages if item.session_id == session_id]
        return matched[-limit:]

    async def cleanup_session(self, session_id: str) -> None:
        self.messages = [item for item in self.messages if item.session_id != session_id]

    async def session_has_messages(self, session_id: str) -> bool:
        return any(item.session_id == session_id for item in self.messages)


def _agent(agent_id: str, *, tenant_id: str, project_id: str) -> Mock:
    agent = Mock()
    agent.id = agent_id
    agent.name = agent_id
    agent.display_name = agent_id
    agent.tenant_id = tenant_id
    agent.project_id = project_id
    agent.enabled = True
    agent.discoverable = True
    agent.agent_to_agent_enabled = True
    agent.can_spawn = True
    agent.max_spawn_depth = 3
    agent.role = AgentRole.ORCHESTRATOR
    return agent


def _echo_tool(fail: dict[str, bool] | None = None) -> Any:
    gate = fail if fail is not None else {"fail": False}

    @tool_define(
        name="echo",
        description="Return the supplied text.",
        parameters={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        permission="read",
    )
    async def echo(ctx: Any, *, text: str) -> ToolResult:
        del ctx
        if gate["fail"]:
            raise RuntimeError("controlled tool failed")
        return ToolResult(output=f"echo: {text}")

    return echo


def _step_tool(number: int) -> Any:
    @tool_define(
        name=f"step_{number}",
        description=f"Step {number} of the controlled chain.",
        parameters={
            "type": "object",
            "properties": {"prior": {"type": "string"}},
            "required": ["prior"],
        },
        permission="read",
    )
    async def step(ctx: Any, *, prior: str) -> ToolResult:
        del ctx
        return ToolResult(output=f"step-{number}:{prior}")

    step.__name__ = f"step_{number}"
    return step


def _event(event_type: StreamEventType, **data: Any) -> Any:
    return type("StreamEvent", (), {"type": event_type, "data": data})()


class ScriptedModel:
    """Yields model events. This is the only layer standing in for a provider."""

    def __init__(self, script: list[list[Any]]) -> None:
        self.script = script
        self.calls = 0

    async def generate(self, _messages: list[dict[str, Any]], **_kwargs: Any) -> Any:
        events = self.script[self.calls]
        self.calls += 1
        for event in events:
            yield event


def _tool_call(call_id: str, name: str, arguments: dict[str, Any]) -> list[Any]:
    return [
        _event(StreamEventType.TOOL_CALL_START, call_id=call_id, name=name),
        _event(
            StreamEventType.TOOL_CALL_END,
            call_id=call_id,
            name=name,
            arguments=arguments,
        ),
        _event(StreamEventType.FINISH, reason="tool_calls"),
    ]


def _text(content: str) -> list[Any]:
    return [
        _event(StreamEventType.TEXT_END, full_text=content),
        _event(StreamEventType.FINISH, reason="stop"),
    ]


async def _run_processor(processor: SessionProcessor, session_id: str, prompt: str) -> str:
    messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
    final_text = ""
    for _ in range(8):
        async for _event_item in processor._process_step(session_id, messages):
            pass
        processor._append_tool_results_to_messages(messages)
        assistant = next(
            (item for item in reversed(messages) if item.get("role") == "assistant"),
            None,
        )
        if assistant and assistant.get("content"):
            final_text = str(assistant["content"])
        if not assistant or not assistant.get("tool_calls"):
            break
    return final_text


async def _spawn_and_run(
    *,
    prompt: str,
    script: list[list[Any]],
    tools: list[Any],
    metadata: dict[str, Any] | None = None,
) -> tuple[AgentOrchestrator, str]:
    bus = MemoryBus()
    sessions = AgentSessionRegistry()
    manager = SpawnManager(sessions)
    registry = Mock()
    registry.get_by_id = AsyncMock(
        side_effect=lambda agent_id, **kwargs: _agent(
            agent_id,
            tenant_id=kwargs.get("tenant_id") or "tenant",
            project_id=kwargs.get("project_id") or "project",
        )
    )
    registry.get_by_name = AsyncMock(return_value=None)
    model = ScriptedModel(script)
    processor = SessionProcessor(
        config=ProcessorConfig(model="controlled-runner", max_steps=8),
        tools=convert_tools({tool.name: tool for tool in tools}),
    )

    async def fake_generate(_self: Any, messages: list[dict[str, Any]], **kwargs: Any) -> Any:
        async for event in model.generate(messages, **kwargs):
            yield event

    processor_box = {"processor": processor}

    async def executor(request: Any) -> None:
        import src.infrastructure.agent.processor.processor as processor_module

        original = processor_module.LLMStream.generate
        processor_module.LLMStream.generate = fake_generate  # type: ignore[method-assign]
        try:
            text = await _run_processor(
                processor_box["processor"], request.child_session_id, request.message
            )
        except Exception as exc:
            await manager.update_status(request.child_session_id, "failed")
            await bus.send_message(
                from_agent_id=request.child_agent_id,
                to_agent_id=request.parent_agent_id,
                session_id=request.child_session_id,
                content=f"failure_class=backend code={type(exc).__name__} {exc}",
                message_type=AgentMessageType.RESPONSE,
            )
            return
        finally:
            processor_module.LLMStream.generate = original  # type: ignore[method-assign]
        await manager.update_status(request.child_session_id, "completed")
        await bus.send_message(
            from_agent_id=request.child_agent_id,
            to_agent_id=request.parent_agent_id,
            session_id=request.child_session_id,
            content=text,
            message_type=AgentMessageType.RESPONSE,
            metadata={"model": "controlled-runner", "tool_steps": model.calls},
        )

    orchestrator = AgentOrchestrator(
        registry,
        sessions,
        manager,
        bus,
        spawn_executor=executor,
    )
    await sessions.register(
        agent_id="parent",
        conversation_id="parent-session",
        project_id="project",
    )
    result = await orchestrator.spawn_agent(
        parent_agent_id="parent",
        target_agent_id="child",
        message=prompt,
        mode=SpawnMode.RUN,
        parent_session_id="parent-session",
        project_id="project",
        tenant_id="tenant",
        user_id="user",
        metadata=metadata,
    )
    return orchestrator, result.session.conversation_id


@pytest.mark.asyncio
async def test_spawn_echo_runs_tool_and_parent_can_read_history() -> None:
    orchestrator, child_session = await _spawn_and_run(
        prompt="ping",
        tools=[_echo_tool()],
        script=[
            _tool_call("call-echo", "echo", {"text": "ping"}),
            _text("echo: ping"),
        ],
    )
    history = await orchestrator.get_agent_history(child_session, limit=10)
    assert [item.message_type for item in history] == [
        AgentMessageType.REQUEST,
        AgentMessageType.RESPONSE,
    ]
    assert history[0].content == "ping"
    assert history[1].content == "echo: ping"
    record = await orchestrator._spawn_manager.get_record(child_session)
    assert record is not None
    assert record.status == "completed"


@pytest.mark.asyncio
async def test_spawn_five_step_chain_records_each_tool_result() -> None:
    tools = [_step_tool(number) for number in range(1, 6)]
    script = [
        _tool_call("c1", "step_1", {"prior": "start"}),
        _tool_call("c2", "step_2", {"prior": "step-1:start"}),
        _tool_call("c3", "step_3", {"prior": "step-2:step-1:start"}),
        _tool_call("c4", "step_4", {"prior": "step-3:step-2:step-1:start"}),
        _tool_call("c5", "step_5", {"prior": "step-4:step-3:step-2:step-1:start"}),
        _text("step-5:step-4:step-3:step-2:step-1:start"),
    ]
    orchestrator, child_session = await _spawn_and_run(
        prompt="run chain",
        tools=tools,
        script=script,
    )
    history = await orchestrator.get_agent_history(child_session, limit=10)
    assert history[-1].content == "step-5:step-4:step-3:step-2:step-1:start"
    assert history[-1].metadata is not None
    assert history[-1].metadata["tool_steps"] == 6
    record = await orchestrator._spawn_manager.get_record(child_session)
    assert record is not None and record.status == "completed"


@pytest.mark.asyncio
async def test_spawn_tool_failure_is_visible_to_parent() -> None:
    orchestrator, child_session = await _spawn_and_run(
        prompt="ping",
        tools=[_echo_tool({"fail": True})],
        script=[_tool_call("call-echo", "echo", {"text": "ping"})],
    )
    history = await orchestrator.get_agent_history(child_session, limit=10)
    assert "failure_class=backend" in history[-1].content
    record = await orchestrator._spawn_manager.get_record(child_session)
    assert record is not None and record.status == "failed"


@pytest.mark.asyncio
async def test_slow_tool_is_not_failed_for_lack_of_early_text() -> None:
    import asyncio

    @tool_define(
        name="echo",
        description="Return the supplied text after a short pause.",
        parameters={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        permission="read",
    )
    async def slow_echo(ctx: Any, *, text: str) -> ToolResult:
        del ctx
        await asyncio.sleep(0.2)
        return ToolResult(output=f"echo: {text}")

    orchestrator, child_session = await _spawn_and_run(
        prompt="ping",
        tools=[slow_echo],
        script=[
            _tool_call("call-echo", "echo", {"text": "ping"}),
            _text("echo: ping"),
        ],
    )
    history = await orchestrator.get_agent_history(child_session, limit=10)
    assert history[-1].content == "echo: ping"
    record = await orchestrator._spawn_manager.get_record(child_session)
    assert record is not None and record.status == "completed"
