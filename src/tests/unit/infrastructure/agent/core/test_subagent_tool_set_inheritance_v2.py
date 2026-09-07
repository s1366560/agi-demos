"""Generation-bound ToolSet inheritance for attached and detached SubAgents."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from types import MappingProxyType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.domain.model.agent.subagent import SubAgent
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.agent.core.processor import ToolDefinition
from src.infrastructure.agent.core.subagent_tool_set_v2 import (
    InheritedToolSetV2,
    SubAgentToolSetBindingV2,
)
from src.infrastructure.agent.core.subagent_tools import (
    SubAgentToolBuilder,
    SubAgentToolBuilderDeps,
)
from src.infrastructure.agent.subagent.run_registry import SubAgentRunRegistry
from src.infrastructure.agent.subagent.task_decomposer import SubTask
from src.infrastructure.plugins.v2.runtime import FiberPhaseV2, RuntimeV2Error
from src.infrastructure.plugins.v2.tool_set import ToolSetV2

pytestmark = pytest.mark.unit


def _descriptor(*, generation: int = 7) -> PluginGenerationDescriptorV2:
    return PluginGenerationDescriptorV2(
        profile_id="subagent-tool-inheritance",
        generation=generation,
        digest=f"{generation:x}" * 64,
    )


async def _execute_ok(**_kwargs: object) -> str:
    return "ok"


def _tool_set(*names: str) -> ToolSetV2:
    raw_tools = {name: SimpleNamespace(description=name) for name in names}
    definitions = tuple(
        ToolDefinition(
            name=name,
            description=name,
            parameters={"type": "object", "properties": {}},
            execute=_execute_ok,
            _tool_instance=raw_tools[name],
        )
        for name in names
    )
    return ToolSetV2(tools=MappingProxyType(raw_tools), definitions=definitions)


class _Operation:
    def __init__(self, *, descriptor: PluginGenerationDescriptorV2 | None = None) -> None:
        self.operation_id = "parent-turn"
        self.descriptor = descriptor or _descriptor()
        self.phase = FiberPhaseV2.ACTIVE
        self.disposers: list[Callable[[], object | Awaitable[object]]] = []

    async def effect(
        self,
        setup: Callable[[], object | Awaitable[object]],
        *,
        label: str,
    ) -> None:
        assert label
        result = setup()
        if hasattr(result, "__await__"):
            result = await result  # type: ignore[misc]
        if callable(result):
            self.disposers.append(result)


def _subagent(name: str, *, allowed_tools: list[str] | None = None) -> SubAgent:
    return SubAgent.create(
        tenant_id="tenant-a",
        name=name,
        display_name=name.title(),
        system_prompt=f"You are {name}.",
        trigger_description=f"Use {name}",
        trigger_keywords=[name],
        allowed_tools=allowed_tools,
    )


def _react_agent(*, tools: dict[str, object], subagents: list[SubAgent]):
    from src.infrastructure.agent.core.react_agent import ReActAgent

    agent = ReActAgent(
        model="test-model",
        tools=tools,
        subagents=subagents,
        enable_subagent_as_tool=True,
    )
    registry = SubAgentRunRegistry()
    agent._session_runner.deps.subagent_run_registry_resolver = lambda: registry
    agent._tool_builder.deps.subagent_run_registry_resolver = lambda: registry
    return agent, registry


def test_binding_copies_parent_tool_set_once_and_rejects_late_or_inactive_reads() -> None:
    operation = _Operation()
    mutable_tools = {
        "visible": SimpleNamespace(description="visible"),
    }
    definition = ToolDefinition("visible", "visible", {}, _execute_ok)
    binding = SubAgentToolSetBindingV2(operation=operation)

    inherited = binding.bind(
        ToolSetV2(tools=mutable_tools, definitions=(definition,)),
        rebindable_tool_names=("visible",),
    )
    mutable_tools["late"] = SimpleNamespace(description="late")

    assert binding.require() is inherited
    assert tuple(inherited.tool_set.tools) == ("visible",)
    assert inherited.generation_descriptor == operation.descriptor
    assert inherited.owner_operation_id == operation.operation_id
    assert inherited.rebindable_tool_names == frozenset({"visible"})

    with pytest.raises(RuntimeV2Error) as duplicate:
        binding.bind(_tool_set("replacement"))
    assert duplicate.value.code == "subagent_tool_set_already_bound"

    operation.phase = FiberPhaseV2.DISPOSED
    with pytest.raises(RuntimeV2Error) as inactive:
        binding.require()
    assert inactive.value.code == "subagent_tool_set_owner_inactive"


def test_builder_policy_can_only_shrink_the_inherited_parent_tool_set() -> None:
    worker = _subagent("worker", allowed_tools=["read"])
    inherited = InheritedToolSetV2(
        tool_set=_tool_set("read", "write"),
        generation_descriptor=_descriptor(),
        owner_operation_id="parent-turn",
    )
    builder = SubAgentToolBuilder(
        SubAgentToolBuilderDeps(subagent_run_registry_resolver=lambda: SubAgentRunRegistry())
    )

    filtered, names = builder.filter_tools(worker, inherited_tool_set=inherited)

    assert [tool.name for tool in filtered] == ["read"]
    assert names == {"read"}

    class _ExpandingRouter:
        @staticmethod
        def filter_tools(_subagent: SubAgent, available: dict[str, object]) -> dict[str, object]:
            return {**available, "injected": object()}

    builder.deps.subagent_router = _ExpandingRouter()
    with pytest.raises(RuntimeV2Error) as expanded:
        builder.filter_tools(worker, inherited_tool_set=inherited)
    assert expanded.value.code == "subagent_tool_set_expansion"


@pytest.mark.asyncio
async def test_attached_child_uses_parent_snapshot_without_legacy_refresh_or_late_tools() -> None:
    researcher = _subagent("researcher", allowed_tools=["visible"])
    agent, _registry = _react_agent(
        tools={"legacy": SimpleNamespace(description="legacy")},
        subagents=[researcher],
    )
    operation = _Operation()
    inherited = SubAgentToolSetBindingV2(operation=operation).bind(_tool_set("visible"))
    agent.raw_tools["late"] = SimpleNamespace(description="late")
    legacy_refresh = MagicMock(side_effect=AssertionError("legacy refresh must not run"))
    agent._get_current_tools = legacy_refresh
    captured_names: list[str] = []

    class _Process:
        def __init__(self, **kwargs: object) -> None:
            captured_names.extend(tool.name for tool in kwargs["tools"])  # type: ignore[union-attr]
            self.result = SimpleNamespace(
                final_content="done",
                to_event_data=lambda: {"summary": "done", "success": True},
            )

        async def execute(self):
            if False:
                yield {}

    with (
        patch(
            "src.infrastructure.plugins.v2.boundary.current_operation_context_v2",
            return_value=operation,
        ),
        patch("src.infrastructure.agent.subagent.process.SubAgentProcess", _Process),
    ):
        events = [
            event
            async for event in agent._execute_subagent(
                subagent=researcher,
                available_subagents=[researcher],
                user_message="research",
                conversation_context=[],
                project_id="project-a",
                tenant_id="tenant-a",
                inherited_tool_set=inherited,
            )
        ]

    assert captured_names == ["visible"]
    legacy_refresh.assert_not_called()
    assert events[-1]["type"] == "complete"


@pytest.mark.asyncio
async def test_nested_child_rebinds_only_parent_visible_delegation_names() -> None:
    researcher = _subagent("researcher")
    coder = _subagent("coder")
    agent, _registry = _react_agent(
        tools={"legacy": SimpleNamespace(description="legacy")},
        subagents=[researcher, coder],
    )
    operation = _Operation()
    inherited = SubAgentToolSetBindingV2(operation=operation).bind(
        _tool_set("visible", "delegate_to_subagent"),
        rebindable_tool_names=("delegate_to_subagent",),
    )
    captured_names: list[str] = []

    class _Process:
        def __init__(self, **kwargs: object) -> None:
            captured_names.extend(tool.name for tool in kwargs["tools"])  # type: ignore[union-attr]
            self.result = SimpleNamespace(
                final_content="done",
                to_event_data=lambda: {"summary": "done", "success": True},
            )

        async def execute(self):
            if False:
                yield {}

    with (
        patch(
            "src.infrastructure.plugins.v2.boundary.current_operation_context_v2",
            return_value=operation,
        ),
        patch("src.infrastructure.agent.subagent.process.SubAgentProcess", _Process),
    ):
        async for _event in agent._execute_subagent(
            subagent=researcher,
            available_subagents=[researcher, coder],
            user_message="delegate",
            conversation_context=[],
            project_id="project-a",
            tenant_id="tenant-a",
            inherited_tool_set=inherited,
        ):
            pass

    assert captured_names == ["visible", "delegate_to_subagent"]
    assert "sessions_list" not in captured_names
    assert "subagents" not in captured_names


@pytest.mark.asyncio
async def test_parallel_and_chain_only_receive_the_parent_policy_intersection() -> None:
    researcher = _subagent("researcher", allowed_tools=["visible"])
    coder = _subagent("coder", allowed_tools=["visible", "coder_only"])
    agent, _registry = _react_agent(
        tools={"legacy": SimpleNamespace(description="legacy")},
        subagents=[researcher, coder],
    )
    operation = _Operation()
    inherited = SubAgentToolSetBindingV2(operation=operation).bind(
        _tool_set("visible", "coder_only", "parent_only")
    )
    legacy_refresh = MagicMock(side_effect=AssertionError("legacy refresh must not run"))
    agent._get_current_tools = legacy_refresh
    subtasks = [
        SubTask(id="research", description="Research", target_subagent="researcher"),
        SubTask(id="code", description="Code", target_subagent="coder"),
    ]
    captured: dict[str, list[str]] = {}

    class _Scheduler:
        async def execute(self, **kwargs: object):
            captured["parallel"] = [tool.name for tool in kwargs["tools"]]  # type: ignore[union-attr]
            if False:
                yield {}

    class _Chain:
        def __init__(self, **_kwargs: object) -> None:
            self.result = SimpleNamespace(final_summary="done")

        async def execute(self, **kwargs: object):
            captured["chain"] = [tool.name for tool in kwargs["tools"]]  # type: ignore[union-attr]
            if False:
                yield {}

    agent._result_aggregator.aggregate_with_llm = AsyncMock(
        return_value=SimpleNamespace(
            summary="done",
            all_succeeded=True,
            total_tokens=0,
            failed_agents=(),
        )
    )
    with (
        patch("src.infrastructure.agent.subagent.parallel_scheduler.ParallelScheduler", _Scheduler),
        patch("src.infrastructure.agent.subagent.chain.SubAgentChain", _Chain),
    ):
        _ = [
            event
            async for event in agent._execute_parallel(
                subtasks=subtasks,
                available_subagents=[researcher, coder],
                user_message="parallel",
                conversation_context=[],
                project_id="project-a",
                tenant_id="tenant-a",
                inherited_tool_set=inherited,
            )
        ]
        _ = [
            event
            async for event in agent._execute_chain(
                subtasks=subtasks,
                available_subagents=[researcher, coder],
                user_message="chain",
                conversation_context=[],
                project_id="project-a",
                tenant_id="tenant-a",
                inherited_tool_set=inherited,
            )
        ]

    assert captured == {"parallel": ["visible"], "chain": ["visible"]}
    legacy_refresh.assert_not_called()


@pytest.mark.asyncio
async def test_background_path_receives_a_policy_subset_of_the_parent_snapshot() -> None:
    researcher = _subagent("researcher", allowed_tools=["visible"])
    agent, _registry = _react_agent(
        tools={"legacy": SimpleNamespace(description="legacy")},
        subagents=[researcher],
    )
    operation = _Operation()
    inherited = SubAgentToolSetBindingV2(operation=operation).bind(
        _tool_set("visible", "parent_only")
    )
    captured_names: list[str] = []

    def _launch(**kwargs: object) -> str:
        captured_names.extend(tool.name for tool in kwargs["tools"])  # type: ignore[union-attr]
        return "background-a"

    agent._background_executor.launch = _launch
    agent._get_current_tools = MagicMock(
        side_effect=AssertionError("background path must not refresh tools")
    )

    events = [
        event
        async for event in agent._execute_background(
            subagent=researcher,
            user_message="background",
            conversation_id="conversation-a",
            conversation_context=[],
            project_id="project-a",
            tenant_id="tenant-a",
            inherited_tool_set=inherited,
        )
    ]

    assert captured_names == ["visible"]
    assert events[0]["data"]["execution_id"] == "background-a"


@pytest.mark.asyncio
async def test_detached_launch_rejects_a_generation_mismatch_without_fallback() -> None:
    researcher = _subagent("researcher")
    agent, registry = _react_agent(
        tools={"legacy": SimpleNamespace(description="legacy")},
        subagents=[researcher],
    )
    operation = _Operation()
    inherited = SubAgentToolSetBindingV2(operation=operation).bind(_tool_set("visible"))
    run = registry.create_run(
        conversation_id="conversation-a",
        subagent_name=researcher.name,
        task="detached",
    )

    class _Reservation:
        descriptor = _descriptor(generation=8)

        def __init__(self) -> None:
            self.released = False

        async def release(self) -> None:
            self.released = True

    reservation = _Reservation()

    async def _reserve() -> _Reservation:
        return reservation

    agent._session_runner.deps.operation_reserver = _reserve
    agent._get_current_tools = MagicMock(
        side_effect=AssertionError("detached launch must not refresh tools")
    )

    with pytest.raises(RuntimeV2Error) as mismatch:
        await agent._launch_subagent_session(
            run_id=run.run_id,
            subagent=researcher,
            available_subagents=[researcher],
            user_message="detached",
            conversation_id="conversation-a",
            conversation_context=[],
            project_id="project-a",
            tenant_id="tenant-a",
            inherited_tool_set=inherited,
        )

    assert mismatch.value.code == "subagent_tool_set_generation_mismatch"
    assert reservation.released is True
