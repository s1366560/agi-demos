"""Tests for Phase 6: ReActAgent integration with SubAgent modules.

Tests that ReActAgent correctly wires MemoryAccessor, BackgroundExecutor,
and TemplateRegistry when graph_service is available.
"""

import json
from types import MappingProxyType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.domain.model.agent.subagent import SubAgent
from src.infrastructure.agent.model_route import ModelRouteRef
from src.infrastructure.agent.orchestration.orchestrator import AgentOrchestrator
from src.infrastructure.agent.processor import ToolDefinition
from src.infrastructure.plugins.v2.agent_runtime_dispatcher import (
    AgentRuntimeDispatchResultV2,
    PinnedAgentRuntimeDispatcherV2,
)
from src.infrastructure.plugins.v2.agent_worker_runtime import (
    AGENT_OPERATION_ORCHESTRATOR_SERVICE_V2,
)
from src.infrastructure.plugins.v2.tool_set import ToolSetV2


def _turn_tool_set(*names: str) -> ToolSetV2:
    raw_tools = {name: object() for name in names}
    definitions = tuple(ToolDefinition(name, "", {}, lambda **_: None) for name in names)
    return ToolSetV2(
        tools=MappingProxyType(raw_tools),
        definitions=definitions,
    )


def _make_subagent(name: str = "test-agent") -> SubAgent:
    return SubAgent.create(
        tenant_id="tenant-1",
        name=name,
        display_name=name,
        system_prompt=f"You are {name}.",
        trigger_description=f"Trigger for {name}",
        trigger_keywords=[name],
    )


def _make_react_agent(**kwargs):
    """Create a ReActAgent with minimal config for testing."""
    from src.infrastructure.agent.core.react_agent import ReActAgent

    defaults = {
        "model": "test-model",
        "tools": {"test_tool": MagicMock()},
        "provider_id": "test-provider",
    }
    defaults.update(kwargs)
    return ReActAgent(**defaults)


def _make_processor_mock() -> MagicMock:
    processor = MagicMock()
    processor.add_runtime_guidance = AsyncMock()
    return processor


def _make_runtime_profile(**overrides):
    from src.domain.model.agent.tenant_agent_config import TenantAgentConfig
    from src.infrastructure.agent.core.react_agent import AgentRuntimeProfile

    defaults = {
        "selected_agent": None,
        "available_skills": [],
        "allow_tools": [],
        "deny_tools": [],
        "tenant_agent_config": TenantAgentConfig.create_default("tenant-1"),
        "agent_definition_prompt": "",
        "effective_model_route": ModelRouteRef(
            provider_id="test-provider",
            model_id="test-model",
        ),
        "effective_temperature": 0.2,
        "effective_max_tokens": 1024,
        "effective_max_steps": 4,
    }
    defaults.update(overrides)
    return AgentRuntimeProfile(**defaults)


def _make_operation_context(dispatcher):
    session_registry = MagicMock()
    session_registry.register = AsyncMock()
    orchestrator = AgentOrchestrator(
        agent_registry=MagicMock(),
        session_registry=session_registry,
        spawn_manager=MagicMock(),
        message_bus=MagicMock(),
    )

    def _require(service_key: str):
        if service_key == AGENT_OPERATION_ORCHESTRATOR_SERVICE_V2:
            return orchestrator
        return dispatcher

    return SimpleNamespace(require=_require)


@pytest.mark.unit
class TestReActAgentGraphServiceInit:
    """Test ReActAgent initialization with graph_service."""

    def test_init_without_graph_service(self):
        agent = _make_react_agent()
        assert agent._graph_service is None

    def test_init_with_graph_service(self):
        graph = MagicMock()
        agent = _make_react_agent(graph_service=graph)
        assert agent._graph_service is graph

    def test_background_executor_initialized(self):
        agent = _make_react_agent()
        assert agent._background_executor is not None

    def test_template_registry_initialized(self):
        agent = _make_react_agent()
        assert agent._template_registry is not None


@pytest.mark.unit
class TestReActAgentMemoryIntegration:
    """Test that _execute_subagent integrates MemoryAccessor."""

    async def test_execute_subagent_with_graph_service(self):
        """When graph_service is available, memory should be searched."""
        graph = AsyncMock()
        graph.search.return_value = [
            {"content": "User prefers concise output", "type": "entity", "score": 0.9},
        ]

        sa = _make_subagent("researcher")
        agent = _make_react_agent(
            graph_service=graph,
            subagents=[sa],
        )

        # Mock SubAgentProcess to avoid real execution
        with patch("src.infrastructure.agent.subagent.process.SubAgentProcess") as MockProcess:
            mock_result = MagicMock()
            mock_result.final_content = "Research result"
            mock_result.to_event_data.return_value = {"summary": "done"}

            instance = MockProcess.return_value
            instance.result = mock_result

            async def mock_execute():
                yield {"type": "subagent_started", "data": {}, "timestamp": "t"}
                yield {"type": "subagent_completed", "data": {}, "timestamp": "t"}

            instance.execute = mock_execute

            events = []
            async for event in agent._execute_subagent(
                subagent=sa,
                available_subagents=agent.subagents,
                user_message="Research AI trends",
                conversation_context=[],
                project_id="proj-1",
                tenant_id="tenant-1",
            ):
                events.append(event)

        # Verify graph.search was called
        graph.search.assert_called_once_with(
            query="Research AI trends",
            project_id="proj-1",
            limit=5,
        )

        # Verify SubAgentProcess received memory_context in its context
        call_kwargs = MockProcess.call_args[1]
        context = call_kwargs.get("context")
        assert context is not None
        assert (
            "memory" in context.memory_context.lower()
            or "knowledge" in context.memory_context.lower()
        )

    async def test_execute_subagent_without_graph_service(self):
        """When no graph_service, memory_context should be empty."""
        sa = _make_subagent("researcher")
        agent = _make_react_agent(subagents=[sa])

        with patch("src.infrastructure.agent.subagent.process.SubAgentProcess") as MockProcess:
            mock_result = MagicMock()
            mock_result.final_content = "Output"
            mock_result.to_event_data.return_value = {}

            instance = MockProcess.return_value
            instance.result = mock_result

            async def mock_execute():
                yield {"type": "subagent_started", "data": {}, "timestamp": "t"}
                yield {"type": "subagent_completed", "data": {}, "timestamp": "t"}

            instance.execute = mock_execute

            async for _ in agent._execute_subagent(
                subagent=sa,
                available_subagents=agent.subagents,
                user_message="Do work",
                conversation_context=[],
                project_id="proj-1",
                tenant_id="tenant-1",
            ):
                pass

        # Verify SubAgentProcess context has empty memory_context
        call_kwargs = MockProcess.call_args[1]
        context = call_kwargs.get("context")
        assert context.memory_context == ""

    async def test_execute_subagent_memory_search_error_graceful(self):
        """Memory search failure should not block SubAgent execution."""
        graph = AsyncMock()
        graph.search.side_effect = RuntimeError("Graph unavailable")

        sa = _make_subagent("researcher")
        agent = _make_react_agent(
            graph_service=graph,
            subagents=[sa],
        )

        with patch("src.infrastructure.agent.subagent.process.SubAgentProcess") as MockProcess:
            mock_result = MagicMock()
            mock_result.final_content = "Still works"
            mock_result.to_event_data.return_value = {}

            instance = MockProcess.return_value
            instance.result = mock_result

            async def mock_execute():
                yield {"type": "subagent_started", "data": {}, "timestamp": "t"}
                yield {"type": "subagent_completed", "data": {}, "timestamp": "t"}

            instance.execute = mock_execute

            events = []
            async for event in agent._execute_subagent(
                subagent=sa,
                available_subagents=agent.subagents,
                user_message="Do work",
                conversation_context=[],
                project_id="proj-1",
                tenant_id="tenant-1",
            ):
                events.append(event)

        # Should complete without error despite graph failure
        event_types = [e["type"] for e in events]
        assert "subagent_started" in event_types
        assert "complete" in event_types

    async def test_execute_subagent_no_project_id_skips_memory(self):
        """When project_id is empty, memory search should be skipped."""
        graph = AsyncMock()

        sa = _make_subagent("researcher")
        agent = _make_react_agent(
            graph_service=graph,
            subagents=[sa],
        )

        with patch("src.infrastructure.agent.subagent.process.SubAgentProcess") as MockProcess:
            mock_result = MagicMock()
            mock_result.final_content = "Output"
            mock_result.to_event_data.return_value = {}

            instance = MockProcess.return_value
            instance.result = mock_result

            async def mock_execute():
                yield {"type": "subagent_started", "data": {}, "timestamp": "t"}
                yield {"type": "subagent_completed", "data": {}, "timestamp": "t"}

            instance.execute = mock_execute

            async for _ in agent._execute_subagent(
                subagent=sa,
                available_subagents=agent.subagents,
                user_message="Do work",
                conversation_context=[],
                project_id="",
                tenant_id="tenant-1",
            ):
                pass

        # graph.search should NOT have been called
        graph.search.assert_not_called()

    async def test_execute_subagent_injects_nested_delegate_tool(self):
        """Nested SubAgent execution should include delegate_to_subagent tool."""
        researcher = _make_subagent("researcher")
        coder = _make_subagent("coder")
        agent = _make_react_agent(
            subagents=[researcher, coder],
            enable_subagent_as_tool=True,
        )

        with patch("src.infrastructure.agent.subagent.process.SubAgentProcess") as MockProcess:
            mock_result = MagicMock()
            mock_result.final_content = "Output"
            mock_result.to_event_data.return_value = {}

            instance = MockProcess.return_value
            instance.result = mock_result

            async def mock_execute():
                yield {"type": "subagent_started", "data": {}, "timestamp": "t"}
                yield {"type": "subagent_completed", "data": {}, "timestamp": "t"}

            instance.execute = mock_execute

            async for _ in agent._execute_subagent(
                subagent=researcher,
                available_subagents=agent.subagents,
                user_message="Do work",
                conversation_context=[],
                project_id="proj-1",
                tenant_id="tenant-1",
            ):
                pass

        tool_names = [tool.name for tool in MockProcess.call_args.kwargs["tools"]]
        assert "delegate_to_subagent" in tool_names

    async def test_execute_subagent_skips_nested_delegate_tool_at_max_depth(self):
        """Nested delegation tools should not be injected at max recursion depth."""
        researcher = _make_subagent("researcher")
        coder = _make_subagent("coder")
        agent = _make_react_agent(
            subagents=[researcher, coder],
            enable_subagent_as_tool=True,
        )

        with patch("src.infrastructure.agent.subagent.process.SubAgentProcess") as MockProcess:
            mock_result = MagicMock()
            mock_result.final_content = "Output"
            mock_result.to_event_data.return_value = {}

            instance = MockProcess.return_value
            instance.result = mock_result

            async def mock_execute():
                yield {"type": "subagent_started", "data": {}, "timestamp": "t"}
                yield {"type": "subagent_completed", "data": {}, "timestamp": "t"}

            instance.execute = mock_execute

            async for _ in agent._execute_subagent(
                subagent=researcher,
                available_subagents=agent.subagents,
                user_message="Do work",
                conversation_context=[],
                project_id="proj-1",
                tenant_id="tenant-1",
                delegation_depth=2,
            ):
                pass

        tool_names = [tool.name for tool in MockProcess.call_args.kwargs["tools"]]
        assert "delegate_to_subagent" not in tool_names


@pytest.mark.unit
class TestReActAgentBackgroundExecutor:
    """Test BackgroundExecutor access from ReActAgent."""

    def test_background_executor_accessible(self):
        agent = _make_react_agent()
        from src.infrastructure.agent.subagent.background_executor import BackgroundExecutor

        assert isinstance(agent._background_executor, BackgroundExecutor)

    def test_template_registry_accessible(self):
        agent = _make_react_agent()
        from src.infrastructure.agent.subagent.template_registry import TemplateRegistry

        assert isinstance(agent._template_registry, TemplateRegistry)


@pytest.mark.unit
class TestReActAgentWorkspaceDelegation:
    @pytest.fixture(autouse=True)
    def _project_agent_capabilities(self):
        async def _resolve(agent, **_kwargs):
            return SimpleNamespace(
                skills=tuple(agent.skills),
                subagents=tuple(agent.subagents),
            )

        with (
            patch(
                "src.infrastructure.agent.core.react_agent_stream_mixin."
                "_resolve_agent_capabilities_from_runtime_v2",
                new=AsyncMock(side_effect=_resolve),
            ),
            patch(
                "src.infrastructure.plugins.v2.boundary.current_operation_context_v2",
                return_value=_make_operation_context(PinnedAgentRuntimeDispatcherV2()),
            ),
        ):
            yield

    def test_workspace_binding_from_runtime_context_parses_json_header(self):
        agent = _make_react_agent()
        context = [
            {
                "role": "system",
                "content": (
                    "[Workspace Runtime Context]\n"
                    + json.dumps(
                        {
                            "context_type": "workspace_worker_runtime",
                            "workspace_binding": {
                                "workspace_id": "ws-bound",
                                "workspace_task_id": "task-bound",
                                "root_goal_task_id": "root-bound",
                                "attempt_id": "attempt-bound",
                                "leader_agent_id": "leader-bound",
                            },
                        }
                    )
                ),
            }
        ]

        binding = agent._workspace_binding_from_context(context)

        assert binding == {
            "workspace_id": "ws-bound",
            "workspace_task_id": "task-bound",
            "root_goal_task_id": "root-bound",
            "attempt_id": "attempt-bound",
            "leader_agent_id": "leader-bound",
        }

    def test_workspace_runtime_context_prefers_latest_json_header(self):
        agent = _make_react_agent()
        context = [
            {
                "role": "system",
                "content": (
                    "[Workspace Runtime Context]\n"
                    + json.dumps(
                        {
                            "context_type": "workspace_worker_runtime",
                            "workspace_binding": {
                                "workspace_id": "ws-old",
                                "workspace_task_id": "task-old",
                            },
                            "workspace_verification_integrity": {
                                "iteration_phase": "test",
                                "protected_script_changes": True,
                            },
                        }
                    )
                ),
            },
            {"role": "assistant", "content": "repair turn starts"},
            {
                "role": "system",
                "content": (
                    "[Workspace Runtime Context]\n"
                    + json.dumps(
                        {
                            "context_type": "workspace_worker_runtime",
                            "workspace_binding": {
                                "workspace_id": "ws-new",
                                "workspace_task_id": "task-new",
                            },
                            "workspace_verification_integrity": {
                                "iteration_phase": "test",
                                "allow_verification_script_changes": True,
                                "protected_script_changes": False,
                            },
                        }
                    )
                ),
            },
        ]

        payload = agent._workspace_runtime_context(context)
        binding = agent._workspace_binding_from_context(context)

        assert payload is not None
        assert payload["workspace_binding"]["workspace_id"] == "ws-new"
        assert (
            payload["workspace_verification_integrity"]["allow_verification_script_changes"] is True
        )
        assert binding == {"workspace_id": "ws-new", "workspace_task_id": "task-new"}

    def test_workspace_binding_from_text_parses_worker_brief_block(self):
        agent = _make_react_agent()

        binding = agent._workspace_binding_from_text(
            "\n".join(
                [
                    "Task brief",
                    "[workspace-task-binding]",
                    "workspace_id=ws-text",
                    "workspace_task_id=task-text",
                    "root_goal_task_id=root-text",
                    "attempt_id=attempt-text",
                    "[/workspace-task-binding]",
                    "Do the work.",
                ]
            )
        )

        assert binding == {
            "workspace_id": "ws-text",
            "workspace_task_id": "task-text",
            "root_goal_task_id": "root-text",
            "attempt_id": "attempt-text",
        }

    async def test_delegate_callback_returns_candidate_report_for_leader_adjudication(self):
        researcher = _make_subagent("researcher")
        agent = _make_react_agent(
            subagents=[researcher],
            enable_subagent_as_tool=True,
        )
        workspace_root_task = MagicMock(id="root-1", workspace_id="ws-1")
        captured: dict[str, object] = {}

        def capture_build(**kwargs):
            captured.update(kwargs)
            return kwargs["tools_to_use"]

        async def fake_execute_subagent(**kwargs):
            del kwargs
            yield {
                "type": "complete",
                "data": {
                    "content": "Draft complete",
                    "subagent_result": {
                        "summary": "Checklist drafted",
                        "success": True,
                        "tokens_used": 42,
                    },
                },
            }

        with (
            patch.object(agent, "_build_subagent_tool_definitions", side_effect=capture_build),
            patch.object(agent, "_execute_subagent", side_effect=fake_execute_subagent),
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.prepare_workspace_subagent_delegation",
                new=AsyncMock(
                    return_value={
                        "workspace_task_id": "child-1",
                        "workspace_id": "ws-1",
                        "root_goal_task_id": "root-1",
                        "actor_user_id": "u-1",
                        "leader_agent_id": "leader-agent",
                    }
                ),
            ),
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.apply_workspace_worker_report",
                new=AsyncMock(return_value=MagicMock(id="child-1")),
            ) as apply_mock,
        ):
            agent._stream_inject_subagent_tools(
                tools_to_use=[],
                available_subagents=agent.subagents,
                conversation_context=[],
                project_id="proj-1",
                tenant_id="tenant-1",
                conversation_id="conv-1",
                abort_signal=None,
                workspace_root_task=workspace_root_task,
                leader_agent_id="leader-agent",
                actor_user_id="u-1",
            )

            delegate_callback = captured["delegate_callback"]
            result = await delegate_callback(  # type: ignore[misc]
                subagent_name="researcher",
                task="Draft checklist",
                workspace_task_id="child-1",
            )

        assert apply_mock.await_args.kwargs["report_type"] == "completed"
        assert "workspace_task_id=child-1" in result
        assert "Leader adjudication required" in result
        assert "Tokens used: 42" in result

    async def test_workspace_authority_skips_non_forced_skill_matching(self):
        agent = _make_react_agent()
        workspace_root_task = MagicMock(id="root-1", workspace_id="ws-1")

        async def _empty_async_gen(*args, **kwargs):
            if False:
                yield args, kwargs

        async def _process_events(**kwargs):
            del kwargs
            agent._stream_final_content = "done"
            agent._stream_success = True
            yield {"type": "complete", "data": {"content": "done"}}

        with (
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.should_activate_workspace_authority",
                return_value=True,
            ),
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.maybe_materialize_workspace_goal_candidate",
                new=AsyncMock(return_value=workspace_root_task),
            ),
            patch.object(agent, "_stream_detect_plan_mode", side_effect=_empty_async_gen),
            patch.object(
                agent,
                "_stream_decide_route",
                return_value=(SimpleNamespace(), None, None, {}, None, None),
            ),
            patch.object(
                agent,
                "_load_selected_agent",
                new=AsyncMock(
                    return_value=SimpleNamespace(id="agent-1", name="Atlas", allowed_skills=[])
                ),
            ),
            patch.object(
                agent,
                "_build_runtime_profile",
                return_value=_make_runtime_profile(
                    available_skills=[MagicMock()],
                ),
            ),
            patch.object(agent, "_build_runtime_workspace_manager", return_value=None),
            patch.object(
                agent,
                "_stream_match_skill",
                side_effect=AssertionError("skill matching should be skipped"),
            ),
            patch.object(
                agent,
                "_stream_resolve_mode",
                return_value=("build", SimpleNamespace(metadata={})),
            ),
            patch.object(
                agent,
                "_apply_before_prompt_build_hook",
                new=AsyncMock(return_value=("", [])),
            ),
            patch.object(agent, "_build_primary_agent_prompt", return_value=""),
            patch.object(agent, "_build_system_prompt", new=AsyncMock(return_value="system")),
            patch.object(agent, "_stream_build_context", side_effect=_empty_async_gen),
            patch(
                "src.infrastructure.agent.core.react_agent_stream_mixin."
                "_resolve_current_tools_from_runtime_v2",
                return_value=_turn_tool_set(),
            ),
            patch.object(agent, "_stream_prepare_tools", return_value=[]),
            patch.object(agent, "_stream_process_events", side_effect=_process_events),
            patch.object(agent, "_stream_post_process", side_effect=_empty_async_gen),
            patch.object(agent, "_stream_record_skill_usage", return_value=None),
            patch.object(
                agent,
                "_processor_factory",
                new=SimpleNamespace(create_for_main=lambda **kwargs: _make_processor_mock()),
            ),
        ):
            agent._stream_messages = [{"role": "system", "content": "system"}]
            agent._stream_tools_to_use = []
            agent._stream_memory_context = ""
            events = []
            async for event in agent.stream(
                conversation_id="conv-1",
                user_message="Please decompose and execute this workspace goal.",
                project_id="proj-1",
                user_id="user-1",
                tenant_id="tenant-1",
                conversation_context=[],
                agent_id="agent-1",
            ):
                events.append(event)

        assert events[-1]["type"] == "complete"

    async def test_worker_runtime_binding_does_not_materialize_project_root(self):
        agent = _make_react_agent()
        captured: dict[str, object] = {}
        runtime_context = {
            "context_type": "workspace_worker_runtime",
            "workspace_binding": {
                "workspace_id": "ws-bound",
                "workspace_task_id": "task-bound",
                "root_goal_task_id": "root-bound",
                "attempt_id": "attempt-bound",
                "leader_agent_id": "leader-bound",
            },
            "code_context": {
                "sandbox_code_root": "/workspace/my-game",
                "loaded_agents_files": [],
            },
        }

        async def _empty_async_gen(*args, **kwargs):
            if False:
                yield args, kwargs

        async def _process_events(**kwargs):
            del kwargs
            agent._stream_final_content = "done"
            agent._stream_success = True
            yield {"type": "complete", "data": {"content": "done"}}

        def _capture_processor(**kwargs):
            captured["config"] = kwargs["config"]
            return _make_processor_mock()

        with (
            patch(
                "src.infrastructure.agent.workspace.orchestrator."
                "WorkspaceAutonomyOrchestrator.materialize_goal_candidate",
                new=AsyncMock(side_effect=AssertionError("should not materialize root")),
            ),
            patch.object(agent, "_stream_detect_plan_mode", side_effect=_empty_async_gen),
            patch.object(
                agent,
                "_stream_decide_route",
                return_value=(SimpleNamespace(), None, None, {}, None, None),
            ),
            patch.object(
                agent,
                "_load_selected_agent",
                new=AsyncMock(
                    return_value=SimpleNamespace(id="agent-1", name="Atlas", allowed_skills=[])
                ),
            ),
            patch.object(
                agent,
                "_build_runtime_profile",
                return_value=_make_runtime_profile(
                    available_skills=[MagicMock()],
                ),
            ),
            patch.object(agent, "_build_runtime_workspace_manager", return_value=None),
            patch.object(
                agent,
                "_stream_match_skill",
                side_effect=AssertionError("skill matching should be skipped"),
            ),
            patch.object(
                agent,
                "_stream_resolve_mode",
                return_value=("build", SimpleNamespace(metadata={})),
            ),
            patch.object(
                agent,
                "_apply_before_prompt_build_hook",
                new=AsyncMock(return_value=("", [])),
            ),
            patch.object(agent, "_build_primary_agent_prompt", return_value=""),
            patch.object(agent, "_build_system_prompt", new=AsyncMock(return_value="system")),
            patch.object(agent, "_stream_build_context", side_effect=_empty_async_gen),
            patch(
                "src.infrastructure.agent.core.react_agent_stream_mixin."
                "_resolve_current_tools_from_runtime_v2",
                return_value=_turn_tool_set(),
            ),
            patch.object(agent, "_stream_prepare_tools", return_value=[]),
            patch.object(agent, "_stream_process_events", side_effect=_process_events),
            patch.object(agent, "_stream_post_process", side_effect=_empty_async_gen),
            patch.object(agent, "_stream_record_skill_usage", return_value=None),
            patch.object(
                agent,
                "_processor_factory",
                new=SimpleNamespace(create_for_main=_capture_processor),
            ),
        ):
            agent._stream_messages = [{"role": "system", "content": "system"}]
            agent._stream_tools_to_use = []
            agent._stream_memory_context = ""
            events = []
            async for event in agent.stream(
                conversation_id="conv-1",
                user_message="Execute bound worker task.",
                project_id="proj-1",
                user_id="user-1",
                tenant_id="tenant-1",
                conversation_context=[
                    {
                        "role": "system",
                        "content": (
                            "[Workspace Runtime Context]\n"
                            + json.dumps(runtime_context, ensure_ascii=False)
                        ),
                    }
                ],
                agent_id="agent-1",
            ):
                events.append(event)

        config = captured["config"]
        assert events[-1]["type"] == "complete"
        assert config.runtime_context["workspace_id"] == "ws-bound"
        assert config.runtime_context["root_goal_task_id"] == "root-bound"
        assert config.runtime_context["workspace_task_id"] == "task-bound"
        assert config.runtime_context["attempt_id"] == "attempt-bound"
        assert config.runtime_context["leader_agent_id"] == "leader-bound"
        assert config.runtime_context["workspace_session_role"] == "worker"
        assert config.runtime_context["sandbox_code_root"] == "/workspace/my-game"
        assert config.runtime_context["code_context"]["sandbox_code_root"] == "/workspace/my-game"

    async def test_worker_runtime_code_context_survives_activation_miss(self):
        agent = _make_react_agent()
        captured: dict[str, object] = {}
        profile_skill = MagicMock()
        runtime_context = {
            "context_type": "workspace_worker_runtime",
            "workspace_binding": {
                "workspace_id": "ws-bound",
                "workspace_task_id": "task-bound",
                "root_goal_task_id": "root-bound",
                "attempt_id": "attempt-bound",
                "leader_agent_id": "leader-bound",
            },
            "code_context": {
                "sandbox_code_root": "/workspace/my-game",
                "loaded_agents_files": [],
            },
        }

        async def _empty_async_gen(*args, **kwargs):
            if False:
                yield args, kwargs

        async def _process_events(**kwargs):
            del kwargs
            agent._stream_final_content = "done"
            agent._stream_success = True
            yield {"type": "complete", "data": {"content": "done"}}

        def _match_skill(*args, **kwargs):
            del args
            captured["matched_skills"] = kwargs["available_skills"]
            agent._stream_skill_state = {
                "matched_skill": None,
                "skill_score": 0.0,
                "is_forced": False,
                "should_inject_prompt": False,
            }
            return []

        def _capture_processor(**kwargs):
            captured["config"] = kwargs["config"]
            return _make_processor_mock()

        with (
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime."
                "should_activate_workspace_authority",
                return_value=False,
            ),
            patch.object(agent, "_stream_detect_plan_mode", side_effect=_empty_async_gen),
            patch.object(
                agent,
                "_stream_decide_route",
                return_value=(SimpleNamespace(), None, None, {}, None, None),
            ),
            patch.object(
                agent,
                "_load_selected_agent",
                new=AsyncMock(
                    return_value=SimpleNamespace(id="agent-1", name="Atlas", allowed_skills=[])
                ),
            ),
            patch.object(
                agent,
                "_build_runtime_profile",
                return_value=_make_runtime_profile(
                    available_skills=[profile_skill],
                ),
            ),
            patch.object(agent, "_build_runtime_workspace_manager", return_value=None),
            patch.object(agent, "_stream_match_skill", side_effect=_match_skill),
            patch.object(
                agent,
                "_stream_resolve_mode",
                return_value=("build", SimpleNamespace(metadata={})),
            ),
            patch.object(
                agent,
                "_apply_before_prompt_build_hook",
                new=AsyncMock(return_value=("", [])),
            ),
            patch.object(agent, "_build_primary_agent_prompt", return_value=""),
            patch.object(agent, "_build_system_prompt", new=AsyncMock(return_value="system")),
            patch.object(agent, "_stream_build_context", side_effect=_empty_async_gen),
            patch(
                "src.infrastructure.agent.core.react_agent_stream_mixin."
                "_resolve_current_tools_from_runtime_v2",
                return_value=_turn_tool_set(),
            ),
            patch.object(agent, "_stream_prepare_tools", return_value=[]),
            patch.object(agent, "_stream_process_events", side_effect=_process_events),
            patch.object(agent, "_stream_post_process", side_effect=_empty_async_gen),
            patch.object(agent, "_stream_record_skill_usage", return_value=None),
            patch.object(
                agent,
                "_processor_factory",
                new=SimpleNamespace(create_for_main=_capture_processor),
            ),
        ):
            agent._stream_messages = [{"role": "system", "content": "system"}]
            agent._stream_tools_to_use = []
            agent._stream_memory_context = ""
            events = []
            async for event in agent.stream(
                conversation_id="conv-1",
                user_message="Execute bound worker task.",
                project_id="proj-1",
                user_id="user-1",
                tenant_id="tenant-1",
                conversation_context=[
                    {
                        "role": "system",
                        "content": (
                            "[Workspace Runtime Context]\n"
                            + json.dumps(runtime_context, ensure_ascii=False)
                        ),
                    }
                ],
                agent_id="agent-1",
            ):
                events.append(event)

        config = captured["config"]
        assert events[-1]["type"] == "complete"
        assert captured["matched_skills"] == [profile_skill]
        assert config.runtime_context["workspace_id"] == "ws-bound"
        assert config.runtime_context["root_goal_task_id"] == "root-bound"
        assert config.runtime_context["workspace_task_id"] == "task-bound"
        assert config.runtime_context["sandbox_code_root"] == "/workspace/my-game"
        assert config.runtime_context["code_context"]["sandbox_code_root"] == "/workspace/my-game"

    async def test_leader_replan_runtime_context_restricts_tools_to_task_ledger(self):
        from src.domain.model.agent.tenant_agent_config import TenantAgentConfig
        from src.infrastructure.agent.core.react_agent import AgentRuntimeProfile
        from src.infrastructure.agent.workspace.runtime_role_contract import (
            WORKSPACE_ROLE_LEADER,
            WORKSPACE_SESSION_ROLE_KEY,
            WORKSPACE_TOOL_MODE_KEY,
            WORKSPACE_TOOL_MODE_TASK_LEDGER_ONLY,
            WORKSPACE_TURN_TYPE_KEY,
            WORKSPACE_TURN_TYPE_LEADER_REPLAN,
        )

        agent = _make_react_agent()
        tenant_config = TenantAgentConfig.create_default("tenant-1")
        captured: dict[str, object] = {}
        runtime_context = {
            "context_type": "workspace_worker_runtime",
            "workspace_binding": {
                "workspace_id": "ws-bound",
                "root_goal_task_id": "root-bound",
            },
            WORKSPACE_SESSION_ROLE_KEY: WORKSPACE_ROLE_LEADER,
            WORKSPACE_TURN_TYPE_KEY: WORKSPACE_TURN_TYPE_LEADER_REPLAN,
            WORKSPACE_TOOL_MODE_KEY: WORKSPACE_TOOL_MODE_TASK_LEDGER_ONLY,
        }

        async def _empty_async_gen(*args, **kwargs):
            if False:
                yield args, kwargs

        async def _process_events(**kwargs):
            del kwargs
            agent._stream_final_content = "done"
            agent._stream_success = True
            yield {"type": "complete", "data": {"content": "done"}}

        def _capture_processor(**kwargs):
            captured["config"] = kwargs["config"]
            captured["tools"] = kwargs["tools"]
            return _make_processor_mock()

        with (
            patch(
                "src.infrastructure.agent.workspace.orchestrator."
                "WorkspaceAutonomyOrchestrator.materialize_goal_candidate",
                new=AsyncMock(side_effect=AssertionError("should not materialize root")),
            ),
            patch.object(agent, "_stream_detect_plan_mode", side_effect=_empty_async_gen),
            patch.object(
                agent,
                "_stream_decide_route",
                return_value=(SimpleNamespace(), None, None, {}, None, None),
            ),
            patch.object(
                agent,
                "_load_selected_agent",
                new=AsyncMock(
                    return_value=SimpleNamespace(id="agent-1", name="Atlas", allowed_skills=[])
                ),
            ),
            patch.object(
                agent,
                "_build_runtime_profile",
                return_value=AgentRuntimeProfile(
                    selected_agent=None,
                    tenant_agent_config=tenant_config,
                    available_skills=[],
                    allow_tools=["bash", "read", "sessions_list", "todoread", "todowrite"],
                    deny_tools=[],
                    effective_model_route=ModelRouteRef(
                        provider_id="test-provider",
                        model_id="test-model",
                    ),
                    effective_temperature=0.2,
                    effective_max_tokens=1024,
                    effective_max_steps=4,
                ),
            ),
            patch.object(agent, "_build_runtime_workspace_manager", return_value=None),
            patch.object(
                agent,
                "_stream_match_skill",
                side_effect=AssertionError("skill matching should be skipped"),
            ),
            patch.object(
                agent,
                "_stream_resolve_mode",
                return_value=("build", SimpleNamespace(metadata={})),
            ),
            patch.object(
                agent,
                "_apply_before_prompt_build_hook",
                new=AsyncMock(return_value=("", [])),
            ),
            patch.object(agent, "_build_primary_agent_prompt", return_value=""),
            patch.object(agent, "_build_system_prompt", new=AsyncMock(return_value="system")),
            patch.object(agent, "_stream_build_context", side_effect=_empty_async_gen),
            patch(
                "src.infrastructure.agent.core.react_agent_stream_mixin."
                "_resolve_current_tools_from_runtime_v2",
                return_value=_turn_tool_set(
                    "bash",
                    "read",
                    "sessions_list",
                    "todoread",
                    "todowrite",
                ),
            ),
            patch.object(agent, "_stream_prepare_tools", return_value=[]),
            patch.object(agent, "_stream_process_events", side_effect=_process_events),
            patch.object(agent, "_stream_post_process", side_effect=_empty_async_gen),
            patch.object(agent, "_stream_record_skill_usage", return_value=None),
            patch.object(
                agent,
                "_processor_factory",
                new=SimpleNamespace(create_for_main=_capture_processor),
            ),
        ):
            agent._stream_messages = [{"role": "system", "content": "system"}]
            agent._stream_tools_to_use = []
            agent._stream_memory_context = ""
            events = []
            async for event in agent.stream(
                conversation_id="conv-1",
                user_message="Replan blocked workspace tasks.",
                project_id="proj-1",
                user_id="user-1",
                tenant_id="tenant-1",
                conversation_context=[
                    {
                        "role": "system",
                        "content": (
                            "[Workspace Runtime Context]\n"
                            + json.dumps(runtime_context, ensure_ascii=False)
                        ),
                    }
                ],
                agent_id="agent-1",
            ):
                events.append(event)

        config = captured["config"]
        tools = captured["tools"]
        assert events[-1]["type"] == "complete"
        assert [tool.name for tool in tools] == ["todoread", "todowrite"]
        assert config.provider_options["tool_choice"] == "required"
        assert config.runtime_context["allowed_tools"] == ["todoread", "todowrite"]
        assert config.runtime_context[WORKSPACE_SESSION_ROLE_KEY] == WORKSPACE_ROLE_LEADER
        assert config.runtime_context[WORKSPACE_TURN_TYPE_KEY] == WORKSPACE_TURN_TYPE_LEADER_REPLAN
        assert config.runtime_context[WORKSPACE_TOOL_MODE_KEY] == (
            WORKSPACE_TOOL_MODE_TASK_LEDGER_ONLY
        )

    async def test_stream_does_not_inject_retired_v1_runtime_hook_overrides(self):
        agent = _make_react_agent()
        dispatcher = MagicMock()
        dispatcher.dispatch = AsyncMock(
            return_value=AgentRuntimeDispatchResultV2(
                payload={"memory_context": "", "emitted_events": []},
            )
        )
        agent._stream_skill_state = {
            "matched_skill": None,
            "is_forced": False,
            "should_inject_prompt": False,
        }
        runtime_hook = SimpleNamespace(
            to_dict=lambda: {
                "plugin_name": "memory-runtime",
                "hook_name": "before_prompt_build",
                "enabled": True,
                "priority": 5,
            }
        )
        from src.domain.model.agent.tenant_agent_config import TenantAgentConfig

        tenant_config = TenantAgentConfig.create_default("tenant-1").update_runtime_hooks(
            [runtime_hook]
        )

        async def _empty_async_gen(*args, **kwargs):
            if False:
                yield args, kwargs

        async def _process_events(**kwargs):
            del kwargs
            agent._stream_final_content = "done"
            agent._stream_success = True
            yield {"type": "complete", "data": {"content": "done"}}

        with (
            patch.object(agent, "_stream_detect_plan_mode", side_effect=_empty_async_gen),
            patch.object(
                agent,
                "_stream_decide_route",
                return_value=(SimpleNamespace(), None, None, {}, None, None),
            ),
            patch.object(
                agent,
                "_load_selected_agent",
                new=AsyncMock(
                    return_value=SimpleNamespace(
                        id="agent-1",
                        name="Atlas",
                        allowed_skills=[],
                    )
                ),
            ),
            patch.object(
                agent,
                "_build_runtime_profile",
                return_value=_make_runtime_profile(tenant_agent_config=tenant_config),
            ),
            patch.object(agent, "_build_runtime_workspace_manager", return_value=None),
            patch.object(agent, "_stream_match_skill", return_value=iter(())),
            patch.object(
                agent,
                "_stream_resolve_mode",
                return_value=("build", SimpleNamespace(metadata={})),
            ),
            patch.object(agent, "_build_primary_agent_prompt", return_value=""),
            patch.object(agent, "_build_system_prompt", new=AsyncMock(return_value="system")),
            patch.object(agent, "_stream_build_context", side_effect=_empty_async_gen),
            patch(
                "src.infrastructure.agent.core.react_agent_stream_mixin."
                "_resolve_current_tools_from_runtime_v2",
                return_value=_turn_tool_set(),
            ),
            patch.object(agent, "_stream_prepare_tools", return_value=[]),
            patch.object(agent, "_stream_process_events", side_effect=_process_events),
            patch.object(agent, "_stream_post_process", side_effect=_empty_async_gen),
            patch.object(agent, "_stream_record_skill_usage", return_value=None),
            patch.object(
                agent,
                "_processor_factory",
                new=SimpleNamespace(create_for_main=lambda **kwargs: _make_processor_mock()),
            ),
            patch(
                "src.infrastructure.plugins.v2.boundary.current_operation_context_v2",
                return_value=_make_operation_context(dispatcher),
            ),
        ):
            agent._stream_messages = [{"role": "system", "content": "system"}]
            agent._stream_tools_to_use = []
            agent._stream_memory_context = ""
            events = []
            async for event in agent.stream(
                conversation_id="conv-1",
                user_message="Use runtime overrides.",
                project_id="proj-1",
                user_id="user-1",
                tenant_id="tenant-1",
                conversation_context=[],
                agent_id="agent-1",
            ):
                events.append(event)

        assert events[-1]["type"] == "complete"
        assert dispatcher.dispatch.await_args.args[0] == "before_prompt_build"
        assert "runtime_hook_overrides" not in dispatcher.dispatch.await_args.kwargs

    async def test_stream_resets_stale_memory_context_before_before_prompt_build(self):
        agent = _make_react_agent()
        dispatcher = MagicMock()
        dispatcher.dispatch = AsyncMock(
            return_value=AgentRuntimeDispatchResultV2(
                payload={"memory_context": "", "emitted_events": []},
            )
        )

        async def _empty_async_gen(*args, **kwargs):
            if False:
                yield args, kwargs

        async def _process_events(**kwargs):
            del kwargs
            agent._stream_final_content = "done"
            agent._stream_success = True
            yield {"type": "complete", "data": {"content": "done"}}

        with (
            patch.object(agent, "_stream_detect_plan_mode", side_effect=_empty_async_gen),
            patch.object(
                agent,
                "_stream_decide_route",
                return_value=(SimpleNamespace(), None, None, {}, None, None),
            ),
            patch.object(
                agent,
                "_load_selected_agent",
                new=AsyncMock(
                    return_value=SimpleNamespace(
                        id="agent-1",
                        name="Atlas",
                        allowed_skills=[],
                    )
                ),
            ),
            patch.object(
                agent,
                "_build_runtime_profile",
                return_value=_make_runtime_profile(
                    available_skills=[],
                ),
            ),
            patch.object(agent, "_build_runtime_workspace_manager", return_value=None),
            patch.object(agent, "_stream_match_skill", return_value=iter(())),
            patch.object(
                agent,
                "_stream_resolve_mode",
                return_value=("build", SimpleNamespace(metadata={})),
            ),
            patch.object(agent, "_build_primary_agent_prompt", return_value=""),
            patch.object(agent, "_build_system_prompt", new=AsyncMock(return_value="system")),
            patch.object(agent, "_stream_build_context", side_effect=_empty_async_gen),
            patch(
                "src.infrastructure.agent.core.react_agent_stream_mixin."
                "_resolve_current_tools_from_runtime_v2",
                return_value=_turn_tool_set(),
            ),
            patch.object(agent, "_stream_prepare_tools", return_value=[]),
            patch.object(agent, "_stream_process_events", side_effect=_process_events),
            patch.object(agent, "_stream_post_process", side_effect=_empty_async_gen),
            patch.object(agent, "_stream_record_skill_usage", return_value=None),
            patch.object(
                agent,
                "_processor_factory",
                new=SimpleNamespace(create_for_main=lambda **kwargs: _make_processor_mock()),
            ),
            patch(
                "src.infrastructure.plugins.v2.boundary.current_operation_context_v2",
                return_value=_make_operation_context(dispatcher),
            ),
        ):
            agent._stream_memory_context = "stale memory"
            async for _event in agent.stream(
                conversation_id="conv-1",
                user_message="Reset stale memory state.",
                project_id="proj-1",
                user_id="user-1",
                tenant_id="tenant-1",
                conversation_context=[],
                agent_id="agent-1",
            ):
                pass

        payload = dispatcher.dispatch.await_args.kwargs["payload"]
        assert payload["memory_context"] is None

    def test_filter_workspace_root_tools_removes_generic_agent_bypass_tools(self):
        from src.infrastructure.agent.core.processor import ToolDefinition

        tools = [
            ToolDefinition(
                name="agent_spawn",
                description="",
                parameters={"type": "object"},
                execute=AsyncMock(),
            ),
            ToolDefinition(
                name="agent_send",
                description="",
                parameters={"type": "object"},
                execute=AsyncMock(),
            ),
            ToolDefinition(
                name="agent_sessions",
                description="",
                parameters={"type": "object"},
                execute=AsyncMock(),
            ),
            ToolDefinition(
                name="workspace_chat_send",
                description="",
                parameters={"type": "object"},
                execute=AsyncMock(),
            ),
            ToolDefinition(
                name="todoread", description="", parameters={"type": "object"}, execute=AsyncMock()
            ),
        ]

        filtered = _make_react_agent()._filter_workspace_root_tools(
            tools,
            workspace_root_task=MagicMock(id="root-1"),
        )

        assert [tool.name for tool in filtered] == ["todoread"]

    def test_filter_workspace_root_tools_noop_without_workspace_root(self):
        from src.infrastructure.agent.core.processor import ToolDefinition

        tools = [
            ToolDefinition(
                name="agent_spawn",
                description="",
                parameters={"type": "object"},
                execute=AsyncMock(),
            ),
            ToolDefinition(
                name="todoread", description="", parameters={"type": "object"}, execute=AsyncMock()
            ),
        ]

        filtered = _make_react_agent()._filter_workspace_root_tools(
            tools,
            workspace_root_task=None,
        )

        assert [tool.name for tool in filtered] == ["agent_spawn", "todoread"]
