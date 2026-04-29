"""Tests for ReActAgent runtime profile max-step resolution."""

import pytest

from src.domain.model.agent.agent_definition import Agent
from src.domain.model.agent.tenant_agent_config import TenantAgentConfig
from src.infrastructure.agent.core.processor import ToolDefinition
from src.infrastructure.agent.core.react_agent import ReActAgent


def _make_agent(**overrides) -> Agent:
    return Agent.create(
        tenant_id="tenant-1",
        project_id="project-1",
        name="test-agent",
        display_name="Test Agent",
        system_prompt="You are a test agent.",
        **overrides,
    )


@pytest.mark.unit
class TestReActAgentRuntimeProfile:
    def test_uses_tenant_max_steps_for_legacy_default_agent_iterations(self) -> None:
        agent = ReActAgent(model="test-model", tools={})
        tenant_config = TenantAgentConfig.create_default("tenant-1")
        tenant_config_data = tenant_config.to_dict() | {"max_work_plan_steps": 4999}
        selected_agent = _make_agent(max_iterations=10)

        profile = agent._build_runtime_profile(
            tenant_id="tenant-1",
            tenant_agent_config_data=tenant_config_data,
            selected_agent=selected_agent,
        )

        assert profile.effective_max_steps == 4999

    def test_uses_agent_max_steps_when_explicitly_marked(self) -> None:
        agent = ReActAgent(model="test-model", tools={})
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

    def test_workspace_worker_uses_tenant_max_steps_over_explicit_agent_iterations(self) -> None:
        agent = ReActAgent(model="test-model", tools={})
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

    def test_workspace_worker_extends_restricted_agent_tool_allowlist(self) -> None:
        agent = ReActAgent(model="test-model", tools={})
        tenant_config = TenantAgentConfig.create_default("tenant-1")
        selected_agent = _make_agent(allowed_tools=["Read", "Grep", "WebSearch"])

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

    def test_workspace_worker_preserves_tenant_enabled_tool_policy_for_code_tools(self) -> None:
        agent = ReActAgent(model="test-model", tools={})
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
        agent = ReActAgent(model="test-model", tools={})
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
