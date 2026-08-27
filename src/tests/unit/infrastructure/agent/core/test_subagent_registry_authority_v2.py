# pyright: reportPrivateUsage=false
"""Pinned-generation authority tests for ReActAgent SubAgent execution."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import fields
from inspect import signature
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.domain.model.agent.subagent import SubAgent
from src.infrastructure.agent.core.react_agent import ReActAgent
from src.infrastructure.agent.core.subagent_runner import SubAgentRunnerDeps
from src.infrastructure.agent.core.subagent_tools import SubAgentToolBuilderDeps
from src.infrastructure.agent.processor.processor import ToolDefinition
from src.infrastructure.agent.subagent.run_registry import SubAgentRunRegistry
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.define import ToolInfo
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_DB_SESSION_SERVICE_V2,
    OPERATION_IDENTITY_SERVICE_V2,
    clear_process_generation_host_v2,
    current_operation_context_v2,
    install_process_generation_host_v2,
    pin_agent_turn_operation_v2,
)
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"
_TEST_REGISTRY_CONTEXT: ContextVar[SubAgentRunRegistry | None] = ContextVar(
    "test_subagent_registry_context",
    default=None,
)


def _agent(**kwargs: Any) -> ReActAgent:
    return ReActAgent(
        model="test-model",
        provider_id="test-provider",
        tools={},
        **kwargs,
    )


def _tool_context(conversation_id: str) -> ToolContext:
    return ToolContext(
        session_id=conversation_id,
        message_id=f"message-{conversation_id}",
        call_id=f"call-{conversation_id}",
        agent_name="leader",
        conversation_id=conversation_id,
        abort_signal=asyncio.Event(),
        messages=[],
    )


async def _execute_tool(tool: ToolDefinition, *, conversation_id: str, **kwargs: Any) -> Any:
    instance = tool._tool_instance
    if isinstance(instance, ToolInfo):
        return await instance.execute(_tool_context(conversation_id), **kwargs)
    return await tool.execute(ctx=_tool_context(conversation_id), **kwargs)


async def _delegate_in_generation(
    *,
    registry: SubAgentRunRegistry,
    agent: ReActAgent,
    conversation_id: str,
    result: str,
    entered: asyncio.Event,
    release: asyncio.Event,
) -> str:
    async def delegate_callback(
        _subagent_name: str,
        _task: str,
        **_kwargs: Any,
    ) -> str:
        entered.set()
        await release.wait()
        return result

    async def spawn_callback(
        _subagent_name: str,
        _task: str,
        run_id: str,
        **_kwargs: Any,
    ) -> str:
        return run_id

    async def cancel_callback(_run_id: str) -> bool:
        return True

    token = _TEST_REGISTRY_CONTEXT.set(registry)
    try:
        tools = agent._tool_builder.build_subagent_tool_definitions(
            subagent_map={"worker": object()},
            subagent_descriptions={"worker": "Does bounded work"},
            enabled_subagents=[object()],
            delegate_callback=delegate_callback,
            spawn_callback=spawn_callback,
            cancel_callback=cancel_callback,
            conversation_id=conversation_id,
            tools_to_use=[],
        )
        delegate = next(tool for tool in tools if tool.name == "delegate_to_subagent")
        tool_result = await _execute_tool(
            delegate,
            conversation_id=conversation_id,
            subagent_name="worker",
            task=f"task-{conversation_id}",
        )
        return str(tool_result.output)
    finally:
        _TEST_REGISTRY_CONTEXT.reset(token)


async def test_same_agent_keeps_concurrent_generation_registries_isolated() -> None:
    registry_a = SubAgentRunRegistry()
    registry_b = SubAgentRunRegistry()

    agent = _agent()

    def resolver() -> object:
        return _TEST_REGISTRY_CONTEXT.get()

    agent._session_runner.deps.subagent_run_registry_resolver = resolver
    agent._tool_builder.deps.subagent_run_registry_resolver = resolver
    entered_a = asyncio.Event()
    entered_b = asyncio.Event()
    release_a = asyncio.Event()
    release_b = asyncio.Event()

    try:
        task_a = asyncio.create_task(
            _delegate_in_generation(
                registry=registry_a,
                agent=agent,
                conversation_id="conversation-a",
                result="result-a",
                entered=entered_a,
                release=release_a,
            )
        )
        await entered_a.wait()
        task_b = asyncio.create_task(
            _delegate_in_generation(
                registry=registry_b,
                agent=agent,
                conversation_id="conversation-b",
                result="result-b",
                entered=entered_b,
                release=release_b,
            )
        )
        await entered_b.wait()

        release_b.set()
        result_b = await task_b
        release_a.set()
        result_a = await task_a

        assert result_a == "result-a"
        assert result_b == "result-b"
        assert [run.status.value for run in registry_a.list_runs("conversation-a")] == ["completed"]
        assert [run.status.value for run in registry_b.list_runs("conversation-b")] == ["completed"]
        assert registry_a.list_runs("conversation-b") == []
        assert registry_b.list_runs("conversation-a") == []
    finally:
        registry_b.close()
        registry_a.close()


async def test_detached_session_keeps_exact_generation_and_uses_a_new_db_session(  # noqa: PLR0915
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_registry = SubAgentRunRegistry()
    second_registry = SubAgentRunRegistry()
    registries = iter((first_registry, second_registry))
    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(
            subagent_run_registry_factory=lambda _config: next(registries),
        )
    )
    first = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=188,
        version=188,
        nonce="detached-subagent-generation-188",
    )
    assert first.accepted is True
    install_process_generation_host_v2(host)

    parent_db = object()
    child_db = object()
    child_db_closed = False

    @asynccontextmanager
    async def child_session() -> AsyncIterator[object]:
        nonlocal child_db_closed
        try:
            yield child_db
        finally:
            child_db_closed = True

    agent = _agent(session_factory=child_session)
    subagent = SubAgent.create(
        tenant_id="tenant-1",
        name="detached-worker",
        display_name="Detached Worker",
        system_prompt="Complete the detached task.",
        trigger_description="Runs detached work",
        trigger_keywords=["detached"],
    )
    entered = asyncio.Event()
    release = asyncio.Event()
    observed: dict[str, object] = {}

    async def execute_subagent(*_args: Any, **_kwargs: Any) -> Any:
        operation = current_operation_context_v2()
        observed["child_operation"] = operation
        observed["child_generation"] = operation.generation
        observed["child_db"] = operation.require(OPERATION_DB_SESSION_SERVICE_V2)
        observed["child_registry"] = agent._tool_builder.deps.subagent_run_registry
        entered.set()
        await release.wait()
        assert agent._tool_builder.deps.subagent_run_registry is first_registry
        yield {
            "type": "complete",
            "data": {
                "content": "detached complete",
                "subagent_result": {
                    "success": True,
                    "summary": "detached complete",
                    "execution_time_ms": 1,
                    "tokens_used": 1,
                },
            },
            "timestamp": "test",
        }

    monkeypatch.setattr(agent._session_runner, "execute_subagent", execute_subagent)

    try:
        async with pin_agent_turn_operation_v2(
            operation_id="agent-turn:parent",
            tenant_id="tenant-1",
            project_id="project-1",
            session_id="conversation-detached",
            services={
                OPERATION_DB_SESSION_SERVICE_V2: parent_db,
                OPERATION_IDENTITY_SERVICE_V2: {
                    "tenant_id": "tenant-1",
                    "user_id": "user-1",
                },
            },
        ) as parent_operation:
            run = first_registry.create_run(
                conversation_id="conversation-detached",
                subagent_name=subagent.name,
                task="complete after the parent operation",
                run_id="run-detached",
            )
            first_registry.mark_running("conversation-detached", run.run_id)
            await agent._launch_subagent_session(
                run_id=run.run_id,
                subagent=subagent,
                available_subagents=[subagent],
                user_message="complete after the parent operation",
                conversation_id="conversation-detached",
                conversation_context=[],
                project_id="project-1",
                tenant_id="tenant-1",
            )
            task = agent._subagent_session_tasks[run.run_id]
            await asyncio.wait_for(entered.wait(), timeout=1)
            observed["parent_operation"] = parent_operation
            observed["parent_generation"] = parent_operation.generation

            second = await host.bootstrap(
                profile_path=_PROFILE_PATH,
                manifest_paths=(_MANIFEST_PATH,),
                generation=189,
                version=189,
                nonce="detached-subagent-generation-189",
            )
            assert second.accepted is True

        assert observed["child_operation"] is not observed["parent_operation"]
        assert observed["child_generation"] is observed["parent_generation"]
        assert observed["child_db"] is child_db
        assert observed["child_db"] is not parent_db
        assert observed["child_registry"] is first_registry
        assert observed["parent_generation"]._disposed is False

        async with pin_agent_turn_operation_v2(
            operation_id="agent-turn:new-generation",
            tenant_id="tenant-1",
            project_id="project-1",
            session_id="conversation-new-generation",
        ):
            assert agent._session_runner.deps.subagent_run_registry is second_registry

        release.set()
        await asyncio.wait_for(task, timeout=1)

        final = first_registry.get_run("conversation-detached", run.run_id)
        assert final is not None
        assert final.status.value == "completed"
        assert final.summary == "detached complete"
        assert (
            final.metadata["plugin_generation"]
            == observed["parent_generation"].descriptor.to_payload()
        )
        assert child_db_closed is True
        assert observed["parent_generation"]._disposed is True
    finally:
        release.set()
        clear_process_generation_host_v2(host)
        await host.close()
        second_registry.close()
        first_registry.close()


def test_react_agent_fails_closed_without_a_pinned_operation() -> None:
    agent = _agent()

    with pytest.raises(RuntimeV2Error) as error:
        _ = agent._session_runner.deps.subagent_run_registry

    assert error.value.code == "operation_context_not_pinned"


def test_react_agent_rejects_an_invalid_registry_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _agent()
    monkeypatch.setattr(
        "src.infrastructure.agent.core.subagent_registry_authority."
        "current_agent_worker_runtime_services_v2",
        lambda: SimpleNamespace(subagent_run_registry=object()),
    )

    with pytest.raises(RuntimeV2Error) as error:
        _ = agent._tool_builder.deps.subagent_run_registry

    assert error.value.code == "invalid_agent_subagent_run_registry"


def test_react_agent_has_no_construction_time_registry_authority() -> None:
    runner_fields = {field.name for field in fields(SubAgentRunnerDeps)}
    builder_fields = {field.name for field in fields(SubAgentToolBuilderDeps)}
    constructor_fields = set(signature(ReActAgent.__init__).parameters)
    react_source = (_ROOT / "src/infrastructure/agent/core/react_agent.py").read_text(
        encoding="utf-8"
    )
    lifecycle_source = (
        _ROOT / "src/infrastructure/agent/core/react_agent_lifecycle_mixin.py"
    ).read_text(encoding="utf-8")

    assert "subagent_run_registry" not in runner_fields
    assert "subagent_run_registry" not in builder_fields
    assert "subagent_run_registry_resolver" in runner_fields
    assert "subagent_run_registry_resolver" in builder_fields
    assert (
        not {
            "subagent_run_registry_path",
            "subagent_run_postgres_dsn",
            "subagent_run_sqlite_path",
            "subagent_run_redis_cache_url",
            "subagent_run_redis_cache_ttl_seconds",
            "subagent_terminal_retention_seconds",
        }
        & constructor_fields
    )
    assert "get_shared_subagent_run_registry" not in react_source
    assert "self._subagent_run_registry" not in react_source
    assert "_init_subagent_run_registry" not in lifecycle_source
    assert "get_shared_subagent_run_registry" not in lifecycle_source
