"""Tests for ReActAgent runtime profile max-step resolution."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.domain.model.agent.agent_definition import Agent
from src.domain.model.agent.spawn_policy import SpawnPolicy
from src.domain.model.agent.subagent import AgentModel, AgentTrigger, SubAgent
from src.domain.model.agent.tenant_agent_config import TenantAgentConfig
from src.domain.model.agent.tool_policy import ToolPolicy, ToolPolicyPrecedence
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.agent.core.processor import ToolDefinition
from src.infrastructure.agent.core.react_agent import ReActAgent
from src.infrastructure.agent.core.subagent_tool_set_v2 import SubAgentToolSetBindingV2
from src.infrastructure.agent.model_route import ModelRouteRef
from src.infrastructure.agent.sisyphus.builtin_agent import (
    build_builtin_all_access_agent,
    build_builtin_workspace_iteration_reviewer_agent,
    build_builtin_workspace_planner_agent,
    build_builtin_workspace_verifier_agent,
    list_builtin_agents,
)
from src.infrastructure.agent.subagent.run_registry import SubAgentRunRegistry
from src.infrastructure.plugins.v2.runtime import FiberPhaseV2
from src.infrastructure.plugins.v2.runtime_context import RuntimeV2Error

_TEST_GENERATION_DESCRIPTOR = PluginGenerationDescriptorV2(
    profile_id="react-agent-runtime-profile",
    generation=1,
    digest="1" * 64,
)


def _make_tool_set_binding() -> SubAgentToolSetBindingV2:
    return SubAgentToolSetBindingV2(
        operation=SimpleNamespace(
            operation_id="react-agent-runtime-profile-turn",
            descriptor=_TEST_GENERATION_DESCRIPTOR,
            phase=FiberPhaseV2.ACTIVE,
        )
    )


def _make_react_agent(**overrides) -> ReActAgent:
    defaults = {
        "model": "test-model",
        "tools": {},
        "provider_id": "test-provider",
    }
    defaults.update(overrides)
    agent = ReActAgent(**defaults)
    registry = SubAgentRunRegistry()

    def resolver() -> SubAgentRunRegistry:
        return registry

    agent._session_runner.deps.subagent_run_registry_resolver = resolver
    agent._tool_builder.deps.subagent_run_registry_resolver = resolver
    return agent


def _make_agent(**overrides) -> Agent:
    return Agent.create(
        tenant_id="tenant-1",
        project_id="project-1",
        name="test-agent",
        display_name="Test Agent",
        system_prompt="You are a test agent.",
        **overrides,
    )


def _make_subagent(name: str, **overrides) -> SubAgent:
    return SubAgent(
        id=f"{name}-id",
        tenant_id="tenant-1",
        name=name,
        display_name=name.title(),
        system_prompt=f"You are {name}.",
        trigger=AgentTrigger(description=f"Use {name}."),
        **overrides,
    )


@pytest.mark.unit
class TestModelRouteRef:
    def test_strips_but_does_not_infer_route_identity(self) -> None:
        route = ModelRouteRef(provider_id="  zhipuai_coding  ", model_id="  glm-4.5  ")

        assert route.provider_id == "zhipuai_coding"
        assert route.model_id == "glm-4.5"

    @pytest.mark.parametrize(
        ("provider_id", "model_id", "expected_code"),
        [
            (" ", "glm-4.5", "model_route_provider_missing"),
            ("zhipuai_coding", " ", "model_route_model_missing"),
        ],
    )
    def test_rejects_empty_route_identity(
        self,
        provider_id: str,
        model_id: str,
        expected_code: str,
    ) -> None:
        with pytest.raises(RuntimeV2Error) as exc_info:
            ModelRouteRef(provider_id=provider_id, model_id=model_id)

        assert exc_info.value.code == expected_code


@pytest.mark.unit
class TestReActAgentRuntimeProfile:
    async def test_load_selected_agent_scopes_orchestrator_lookup(self, monkeypatch) -> None:
        from src.infrastructure.plugins.v2 import agent_worker_runtime

        agent = _make_react_agent()
        selected_agent = SimpleNamespace(id="agent-123", name="Scoped Agent")
        orchestrator = SimpleNamespace(get_agent=AsyncMock(return_value=selected_agent))
        monkeypatch.setattr(
            agent_worker_runtime,
            "current_agent_orchestrator_v2",
            lambda: orchestrator,
        )

        result = await agent._load_selected_agent_native(
            agent_id="agent-123",
            tenant_id="tenant-1",
            project_id="project-1",
        )

        assert result is selected_agent
        orchestrator.get_agent.assert_awaited_once_with(
            "agent-123",
            tenant_id="tenant-1",
            project_id="project-1",
        )

    def test_uses_tenant_max_steps_for_legacy_default_agent_iterations(self) -> None:
        agent = _make_react_agent()
        tenant_config = TenantAgentConfig.create_default("tenant-1")
        tenant_config_data = tenant_config.to_dict() | {"max_work_plan_steps": 4999}
        selected_agent = _make_agent(max_iterations=10)

        profile = agent._build_runtime_profile(
            tenant_id="tenant-1",
            tenant_agent_config_data=tenant_config_data,
            selected_agent=selected_agent,
        )

        assert profile.effective_max_steps == 4999
        assert profile.effective_model_route == ModelRouteRef(
            provider_id="test-provider",
            model_id="auto",
        )

    def test_explicit_selected_agent_model_requires_structured_route(self) -> None:
        agent = _make_react_agent()
        tenant_config = TenantAgentConfig.create_default("tenant-1")
        selected_agent = _make_agent(model=AgentModel.GPT4O)

        with pytest.raises(RuntimeV2Error) as exc_info:
            agent._build_runtime_profile(
                tenant_id="tenant-1",
                tenant_agent_config_data=tenant_config.to_dict(),
                selected_agent=selected_agent,
            )

        assert exc_info.value.code == "agent_model_route_missing"

    def test_explicit_selected_agent_model_uses_structured_route(self) -> None:
        agent = _make_react_agent()
        tenant_config = TenantAgentConfig.create_default("tenant-1")
        selected_agent = _make_agent(model=AgentModel.GPT4O)
        route = ModelRouteRef(provider_id="openai", model_id=AgentModel.GPT4O.value)

        profile = agent._build_runtime_profile(
            tenant_id="tenant-1",
            tenant_agent_config_data=tenant_config.to_dict(),
            selected_agent=selected_agent,
            selected_agent_model_route=route,
        )

        assert profile.effective_model_route is route
        assert profile.effective_model == AgentModel.GPT4O.value
        assert profile.effective_provider_id == "openai"

    def test_explicit_selected_agent_route_model_must_match_definition(self) -> None:
        agent = _make_react_agent()
        tenant_config = TenantAgentConfig.create_default("tenant-1")
        selected_agent = _make_agent(model=AgentModel.GPT4O)

        with pytest.raises(RuntimeV2Error) as exc_info:
            agent._build_runtime_profile(
                tenant_id="tenant-1",
                tenant_agent_config_data=tenant_config.to_dict(),
                selected_agent=selected_agent,
                selected_agent_model_route=ModelRouteRef(
                    provider_id="openai",
                    model_id="gpt-4.1-mini",
                ),
            )

        assert exc_info.value.code == "agent_model_route_mismatch"

    def test_uses_agent_max_steps_when_explicitly_marked(self) -> None:
        agent = _make_react_agent()
        tenant_config = TenantAgentConfig.create_default("tenant-1")
        tenant_config_data = tenant_config.to_dict() | {"max_work_plan_steps": 4999}
        selected_agent = _make_agent(
            max_iterations=10,
            metadata={"max_iterations_explicit": True},
        )

        profile = agent._build_runtime_profile(
            tenant_id="tenant-1",
            tenant_agent_config_data=tenant_config_data,
            selected_agent=selected_agent,
        )

        assert profile.effective_max_steps == 10

    def test_database_agent_runtime_parameters_remain_explicit_by_default(self) -> None:
        agent = _make_react_agent(max_tokens=1234)
        tenant_config = TenantAgentConfig.create_default("tenant-1")
        tenant_config_data = tenant_config.to_dict() | {
            "llm_temperature": 1.1,
            "max_work_plan_steps": 4999,
        }
        selected_agent = _make_agent(
            temperature=0.3,
            max_tokens=2048,
            max_iterations=42,
        )

        profile = agent._build_runtime_profile(
            tenant_id="tenant-1",
            tenant_agent_config_data=tenant_config_data,
            selected_agent=selected_agent,
        )

        assert profile.effective_temperature == 0.3
        assert profile.effective_max_tokens == 2048
        assert profile.effective_max_steps == 42

    def test_agi_stack_inherits_tenant_runtime_parameters(self) -> None:
        agent = _make_react_agent(max_tokens=1234)
        tenant_config = TenantAgentConfig.create_default("tenant-1")
        tenant_config_data = tenant_config.to_dict() | {
            "llm_temperature": 1.1,
            "max_work_plan_steps": 4999,
        }
        selected_agent = build_builtin_all_access_agent("tenant-1", project_id="project-1")

        profile = agent._build_runtime_profile(
            tenant_id="tenant-1",
            tenant_agent_config_data=tenant_config_data,
            selected_agent=selected_agent,
        )

        assert profile.effective_temperature == 1.1
        assert profile.effective_max_tokens == 1234
        assert profile.effective_max_steps == 4999

    def test_workspace_plan_team_worker_inherits_tenant_max_steps(self) -> None:
        agent = _make_react_agent()
        tenant_config = TenantAgentConfig.create_default("tenant-1")
        tenant_config_data = tenant_config.to_dict() | {"max_work_plan_steps": 4999}
        selected_agent = _make_agent(
            max_iterations=80,
            metadata={
                "created_by": "workspace_plan_team_setup",
                "max_iterations_explicit": True,
            },
        )

        profile = agent._build_runtime_profile(
            tenant_id="tenant-1",
            tenant_agent_config_data=tenant_config_data,
            selected_agent=selected_agent,
            is_workspace_worker_runtime=True,
        )

        assert profile.effective_max_steps == 4999

    def test_builtin_workspace_contract_agents_inherit_tenant_max_steps(self) -> None:
        agent = _make_react_agent()
        tenant_config = TenantAgentConfig.create_default("tenant-1")
        tenant_config_data = tenant_config.to_dict() | {"max_work_plan_steps": 4999}

        for selected_agent in (
            build_builtin_workspace_planner_agent("tenant-1", project_id="project-1"),
            build_builtin_workspace_verifier_agent("tenant-1", project_id="project-1"),
            build_builtin_workspace_iteration_reviewer_agent("tenant-1", project_id="project-1"),
        ):
            profile = agent._build_runtime_profile(
                tenant_id="tenant-1",
                tenant_agent_config_data=tenant_config_data,
                selected_agent=selected_agent,
                is_workspace_worker_runtime=True,
            )

            assert profile.effective_max_steps == 4999

    def test_builtin_agents_declare_runtime_config_inheritance_metadata(self) -> None:
        for selected_agent in list_builtin_agents("tenant-1", project_id="project-1"):
            assert selected_agent.has_explicit_temperature() is False
            assert selected_agent.has_explicit_max_tokens() is False
            assert selected_agent.has_explicit_max_iterations() is False

    def test_workspace_worker_extends_restricted_agent_tool_allowlist(self) -> None:
        agent = _make_react_agent()
        tenant_config = TenantAgentConfig.create_default("tenant-1")
        selected_agent = _make_agent(
            allowed_tools=["Read", "Grep", "WebSearch", "plugin_tool_exec"]
        )

        profile = agent._build_runtime_profile(
            tenant_id="tenant-1",
            tenant_agent_config_data=tenant_config.to_dict(),
            selected_agent=selected_agent,
        )
        workspace_profile = agent._with_workspace_worker_tool_allowlist(profile)

        assert {"read", "grep", "web_search"}.issubset(workspace_profile.allow_tools)
        assert {
            "bash",
            "write",
            "workspace_report_complete",
            "workspace_report_blocked",
            "workspace_report_progress",
        }.issubset(workspace_profile.allow_tools)
        assert "workspace_submit_planning_contract" not in workspace_profile.allow_tools
        assert "plugin_tool_exec" in workspace_profile.deny_tools

        tools = [
            ToolDefinition("read", "", {}, lambda **_: None),
            ToolDefinition("bash", "", {}, lambda **_: None),
            ToolDefinition("plugin_tool_exec", "", {}, lambda **_: None),
        ]
        filtered = agent._filter_tools_by_name_policy(
            tools,
            allow_tools=workspace_profile.allow_tools,
            deny_tools=workspace_profile.deny_tools,
        )

        assert [tool.name for tool in filtered] == ["read", "bash"]

    def test_agent_tool_policy_contributes_to_runtime_allow_and_deny_lists(self) -> None:
        agent = _make_react_agent()
        tenant_config = TenantAgentConfig.create_default("tenant-1")
        tenant_config.disabled_tools = ["Grep"]
        selected_agent = _make_agent(
            allowed_tools=["Read", "Bash", "Grep"],
            tool_policy=ToolPolicy(
                allow=("Read", "Bash"),
                deny=("Bash", "Grep"),
                precedence=ToolPolicyPrecedence.ALLOW_FIRST,
            ),
        )

        profile = agent._build_runtime_profile(
            tenant_id="tenant-1",
            tenant_agent_config_data=tenant_config.to_dict(),
            selected_agent=selected_agent,
        )
        tools = [
            ToolDefinition("read", "", {}, lambda **_: None),
            ToolDefinition("bash", "", {}, lambda **_: None),
            ToolDefinition("grep", "", {}, lambda **_: None),
        ]

        filtered = agent._filter_tools_by_name_policy(
            tools,
            allow_tools=profile.allow_tools,
            deny_tools=profile.deny_tools,
        )

        assert profile.allow_tools == ["bash", "read"]
        assert profile.deny_tools == ["grep"]
        assert [tool.name for tool in filtered] == ["read", "bash"]

    def test_selected_agent_without_spawn_permission_gets_no_subagent_tools(self) -> None:
        agent = _make_react_agent(
            subagents=[_make_subagent("planner")],
        )
        selected_agent = _make_agent(can_spawn=False)
        tools = [ToolDefinition("read", "", {}, lambda **_: None)]

        result = agent._stream_inject_subagent_tools(
            tools_to_use=tools,
            conversation_context=[],
            project_id="project-1",
            tenant_id="tenant-1",
            conversation_id="conversation-1",
            abort_signal=None,
            selected_agent=selected_agent,
            available_subagents=agent.subagents,
            tool_set_binding=_make_tool_set_binding(),
        )

        assert result == tools
        assert [tool.name for tool in result] == ["read"]

    def test_selected_agent_spawn_policy_filters_subagents_and_limits_sessions(self) -> None:
        agent = _make_react_agent(
            subagents=[_make_subagent("planner"), _make_subagent("reviewer")],
            max_subagent_delegation_depth=5,
            max_subagent_active_runs=10,
            max_subagent_active_runs_per_lineage=9,
            max_subagent_children_per_requester=8,
        )
        selected_agent = _make_agent(
            can_spawn=True,
            max_spawn_depth=4,
            spawn_policy=SpawnPolicy(
                max_depth=2,
                max_active_runs=3,
                max_children_per_requester=1,
                allowed_subagents=frozenset({"planner-id"}),
            ),
        )

        result = agent._stream_inject_subagent_tools(
            tools_to_use=[ToolDefinition("read", "", {}, lambda **_: None)],
            conversation_context=[],
            project_id="project-1",
            tenant_id="tenant-1",
            conversation_id="conversation-1",
            abort_signal=None,
            selected_agent=selected_agent,
            available_subagents=agent.subagents,
            tool_set_binding=_make_tool_set_binding(),
        )

        assert "delegate_to_subagent" in {tool.name for tool in result}
        sessions_list = next(tool for tool in result if tool.name == "sessions_list")
        runtime = sessions_list._tool_instance.execute.runtime
        assert runtime.core.subagent_names == ("planner",)
        assert runtime.core.max_delegation_depth == 2
        assert runtime.core.max_active_runs == 3
        assert runtime.core.max_active_runs_per_lineage == 3
        assert runtime.core.max_children_per_requester == 1

    def test_subagent_injection_binds_runtime_without_static_fallback(self) -> None:
        agent = _make_react_agent(
            subagents=[_make_subagent("static-agent")],
        )
        selected_agent = _make_agent(can_spawn=True)

        result = agent._stream_inject_subagent_tools(
            tools_to_use=[ToolDefinition("read", "", {}, lambda **_: None)],
            conversation_context=[],
            project_id="project-1",
            tenant_id="tenant-1",
            conversation_id="conversation-1",
            abort_signal=None,
            selected_agent=selected_agent,
            available_subagents=[_make_subagent("runtime-agent")],
            tool_set_binding=_make_tool_set_binding(),
        )

        assert "delegate_to_subagent" in {tool.name for tool in result}
        sessions_list = next(tool for tool in result if tool.name == "sessions_list")
        runtime = sessions_list._tool_instance.execute.runtime
        assert runtime.core.subagent_names == ("runtime-agent",)

    def test_workspace_worker_preserves_tenant_enabled_tool_policy_for_code_tools(self) -> None:
        agent = _make_react_agent()
        tenant_config = TenantAgentConfig.create_default("tenant-1")
        tenant_config.enabled_tools = ["Read"]
        selected_agent = _make_agent(allowed_tools=["Read", "Grep"])

        profile = agent._build_runtime_profile(
            tenant_id="tenant-1",
            tenant_agent_config_data=tenant_config.to_dict(),
            selected_agent=selected_agent,
        )
        workspace_profile = agent._with_workspace_worker_tool_allowlist(profile)

        assert "read" in workspace_profile.allow_tools
        assert "workspace_report_complete" in workspace_profile.allow_tools
        assert "write" not in workspace_profile.allow_tools
        assert "bash" not in workspace_profile.allow_tools

    def test_workspace_leader_replan_restricts_tools_to_task_ledger(self) -> None:
        agent = _make_react_agent()
        tenant_config = TenantAgentConfig.create_default("tenant-1")
        tenant_config.disabled_tools = ["TodoRead", "Bash"]
        selected_agent = _make_agent(allowed_tools=["Read", "Bash", "TodoRead", "TodoWrite"])

        profile = agent._build_runtime_profile(
            tenant_id="tenant-1",
            tenant_agent_config_data=tenant_config.to_dict(),
            selected_agent=selected_agent,
        )
        replan_profile = agent._with_workspace_leader_replan_tool_allowlist(profile)
        tools = [
            ToolDefinition("bash", "", {}, lambda **_: None),
            ToolDefinition("read", "", {}, lambda **_: None),
            ToolDefinition("todoread", "", {}, lambda **_: None),
            ToolDefinition("todowrite", "", {}, lambda **_: None),
        ]

        filtered = agent._filter_tools_by_name_policy(
            tools,
            allow_tools=replan_profile.allow_tools,
            deny_tools=replan_profile.deny_tools,
        )

        assert replan_profile.allow_tools == ["todoread", "todowrite"]
        assert "todoread" not in replan_profile.deny_tools
        assert [tool.name for tool in filtered] == ["todoread", "todowrite"]
