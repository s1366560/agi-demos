from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import pytest

from src.infrastructure.agent.core.subagent_tools import (
    SubAgentToolBuilder,
    SubAgentToolBuilderDeps,
)
from src.infrastructure.agent.processor.processor import ToolDefinition
from src.infrastructure.agent.subagent.run_registry import SubAgentRunRegistry
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.define import ToolInfo
from src.infrastructure.agent.tools.delegate_subagent import make_nested_delegate_tool_defs
from src.infrastructure.agent.tools.subagent_sessions import make_nested_session_tool_defs
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error


def _context(conversation_id: str) -> ToolContext:
    return ToolContext(
        session_id=conversation_id,
        message_id=f"message-{conversation_id}",
        call_id=f"call-{conversation_id}",
        agent_name="leader",
        conversation_id=conversation_id,
        abort_signal=asyncio.Event(),
        messages=[],
    )


async def _spawn_callback(
    _subagent_name: str,
    _task: str,
    run_id: str,
    **_options: Any,
) -> str:
    return run_id


async def _cancel_callback(_run_id: str) -> bool:
    return True


def _build_tools(
    *,
    conversation_id: str,
    delegate_callback: Callable[..., Awaitable[str]] | None,
    registry: SubAgentRunRegistry | None = None,
) -> list[ToolDefinition]:
    resolved_registry = registry or SubAgentRunRegistry()
    builder = SubAgentToolBuilder(
        SubAgentToolBuilderDeps(subagent_run_registry_resolver=lambda: resolved_registry)
    )
    return builder.build_subagent_tool_definitions(
        subagent_map={"worker": object()},
        subagent_descriptions={"worker": "Does bounded work"},
        enabled_subagents=[object()],
        delegate_callback=delegate_callback,
        spawn_callback=_spawn_callback,
        cancel_callback=_cancel_callback,
        conversation_id=conversation_id,
        tools_to_use=[],
    )


async def _execute_with_context(
    tool: ToolDefinition,
    ctx: ToolContext,
    **kwargs: Any,
) -> Any:
    instance = tool._tool_instance
    if isinstance(instance, ToolInfo):
        return await instance.execute(ctx, **kwargs)
    return await tool.execute(ctx=ctx, **kwargs)


@pytest.mark.unit
def test_top_level_builder_does_not_read_decorator_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_registry_lookup() -> dict[str, ToolInfo]:
        raise AssertionError("production SubAgent tools must not use the decorator registry")

    monkeypatch.setattr(
        "src.infrastructure.agent.tools.define.get_registered_tools",
        fail_registry_lookup,
    )

    tools = _build_tools(
        conversation_id="conversation-a",
        delegate_callback=_spawn_callback,
    )

    assert {tool.name for tool in tools} == {
        "delegate_to_subagent",
        "sessions_spawn",
        "sessions_list",
        "sessions_history",
        "sessions_timeline",
        "sessions_overview",
        "sessions_wait",
        "sessions_ack",
        "sessions_send",
        "subagents",
    }


@pytest.mark.unit
def test_top_level_builder_rejects_missing_delegate_runtime() -> None:
    with pytest.raises(RuntimeV2Error) as exc_info:
        _build_tools(conversation_id="conversation-a", delegate_callback=None)

    assert exc_info.value.code == "missing_subagent_tool_runtime"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_top_level_tools_keep_conversation_callbacks_and_registries_isolated() -> None:
    registry_a = SubAgentRunRegistry()
    registry_b = SubAgentRunRegistry()
    calls_a: list[tuple[str, str]] = []
    calls_b: list[tuple[str, str]] = []

    async def callback_a(subagent_name: str, task: str, **_kwargs: Any) -> str:
        calls_a.append((subagent_name, task))
        await asyncio.sleep(0)
        return "result-a"

    async def callback_b(subagent_name: str, task: str, **_kwargs: Any) -> str:
        calls_b.append((subagent_name, task))
        await asyncio.sleep(0)
        return "result-b"

    tools_a = _build_tools(
        conversation_id="conversation-a",
        delegate_callback=callback_a,
        registry=registry_a,
    )
    tools_b = _build_tools(
        conversation_id="conversation-b",
        delegate_callback=callback_b,
        registry=registry_b,
    )
    delegate_a = next(tool for tool in tools_a if tool.name == "delegate_to_subagent")
    delegate_b = next(tool for tool in tools_b if tool.name == "delegate_to_subagent")

    result_a, result_b = await asyncio.gather(
        _execute_with_context(
            delegate_a,
            _context("conversation-a"),
            subagent_name="worker",
            task="task-a",
        ),
        _execute_with_context(
            delegate_b,
            _context("conversation-b"),
            subagent_name="worker",
            task="task-b",
        ),
    )

    assert result_a.output == "result-a"
    assert result_b.output == "result-b"
    assert calls_a == [("worker", "task-a")]
    assert calls_b == [("worker", "task-b")]
    assert registry_a.list_runs("conversation-b") == []
    assert registry_b.list_runs("conversation-a") == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_nested_delegate_tools_are_isolated_across_await_boundaries() -> None:
    registry_a = SubAgentRunRegistry()
    registry_b = SubAgentRunRegistry()
    entered_a = asyncio.Event()
    entered_b = asyncio.Event()
    release_a = asyncio.Event()
    release_b = asyncio.Event()

    async def callback_a(_name: str, _task: str, **_kwargs: Any) -> str:
        entered_a.set()
        await release_a.wait()
        return "nested-a"

    async def callback_b(_name: str, _task: str, **_kwargs: Any) -> str:
        entered_b.set()
        await release_b.wait()
        return "nested-b"

    tool_a = make_nested_delegate_tool_defs(
        subagent_names=["worker"],
        subagent_descriptions={"worker": "Does bounded work"},
        execute_callback=callback_a,
        run_registry=registry_a,
        conversation_id="conversation-a",
        delegation_depth=1,
        max_active_runs=4,
    )[0]
    tool_b = make_nested_delegate_tool_defs(
        subagent_names=["worker"],
        subagent_descriptions={"worker": "Does bounded work"},
        execute_callback=callback_b,
        run_registry=registry_b,
        conversation_id="conversation-b",
        delegation_depth=1,
        max_active_runs=4,
    )[0]

    task_a = asyncio.create_task(
        _execute_with_context(
            tool_a,
            _context("conversation-a"),
            subagent_name="worker",
            task="nested-task-a",
        )
    )
    await entered_a.wait()
    task_b = asyncio.create_task(
        _execute_with_context(
            tool_b,
            _context("conversation-b"),
            subagent_name="worker",
            task="nested-task-b",
        )
    )
    await entered_b.wait()

    release_a.set()
    result_a = await task_a
    release_b.set()
    result_b = await task_b

    assert result_a.output == "nested-a"
    assert result_b.output == "nested-b"
    assert [run.status.value for run in registry_a.list_runs("conversation-a")] == ["completed"]
    assert [run.status.value for run in registry_b.list_runs("conversation-b")] == ["completed"]
    assert registry_a.list_runs("conversation-b") == []
    assert registry_b.list_runs("conversation-a") == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_nested_wait_tools_are_isolated_across_poll_boundaries() -> None:
    registry_a = SubAgentRunRegistry()
    registry_b = SubAgentRunRegistry()
    run_a = registry_a.create_run(
        conversation_id="conversation-a",
        subagent_name="worker",
        task="wait-a",
    )
    run_b = registry_b.create_run(
        conversation_id="conversation-b",
        subagent_name="worker",
        task="wait-b",
    )
    registry_a.mark_running("conversation-a", run_a.run_id)
    registry_b.mark_running("conversation-b", run_b.run_id)

    async def cancel_callback(_run_id: str) -> bool:
        return True

    def wait_tool(registry: SubAgentRunRegistry, conversation_id: str) -> ToolDefinition:
        tools = make_nested_session_tool_defs(
            run_registry=registry,
            conversation_id=conversation_id,
            requester_session_key=conversation_id,
            visibility_default="tree",
            observability_stats_provider=None,
            subagent_names=["worker"],
            subagent_descriptions={"worker": "Does bounded work"},
            cancel_callback=cancel_callback,
            restart_callback=None,
            max_active_runs=4,
            max_active_runs_per_lineage=4,
            max_children_per_requester=4,
            delegation_depth=1,
            max_delegation_depth=2,
        )
        return next(tool for tool in tools if tool.name == "sessions_wait")

    wait_a = asyncio.create_task(
        _execute_with_context(
            wait_tool(registry_a, "conversation-a"),
            _context("conversation-a"),
            run_id=run_a.run_id,
            timeout_seconds=1,
            poll_interval_ms=10,
        )
    )
    wait_b = asyncio.create_task(
        _execute_with_context(
            wait_tool(registry_b, "conversation-b"),
            _context("conversation-b"),
            run_id=run_b.run_id,
            timeout_seconds=1,
            poll_interval_ms=10,
        )
    )
    await asyncio.sleep(0.02)
    registry_a.mark_completed("conversation-a", run_a.run_id, summary="done-a")
    registry_b.mark_completed("conversation-b", run_b.run_id, summary="done-b")

    result_a, result_b = await asyncio.gather(wait_a, wait_b)

    assert '"conversation_id": "conversation-a"' in result_a.output
    assert '"conversation_id": "conversation-b"' in result_b.output
    assert '"is_terminal": true' in result_a.output
    assert '"is_terminal": true' in result_b.output


@pytest.mark.unit
def test_legacy_process_global_dependency_slots_are_removed() -> None:
    from src.infrastructure.agent.tools import delegate_subagent, subagent_sessions

    assert not hasattr(delegate_subagent, "_delegate_execute_callback")
    assert not hasattr(delegate_subagent, "_delegate_run_registry")
    assert not hasattr(subagent_sessions, "_sess_run_registry")
    assert not hasattr(subagent_sessions, "_sess_send_run_registry")
    assert not hasattr(subagent_sessions, "_ctrl_run_registry")
