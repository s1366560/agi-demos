"""Workspace prompt isolation regression tests.

Ensures workspace-scoped prompt content (workspace context block, workspace_*
tools, workspace_* skills, Plan/Build task lifecycle prose, Workspace
Authority Contract) is only injected into conversations that are explicitly
bound to a workspace turn.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar
from unittest.mock import AsyncMock, patch

import pytest

from src.infrastructure.agent.core.react_agent_prompt_mixin import PromptMixin
from src.infrastructure.agent.core.react_agent_tool_policy import (
    filter_non_workspace_conversation_tools,
)
from src.infrastructure.agent.prompts.manager import (
    PromptContext,
    PromptMode,
    SystemPromptManager,
)
from src.infrastructure.agent.workspace.runtime_role_contract import (
    is_workspace_conversation,
)


class _Tool:
    def __init__(self, name: str) -> None:
        self.name = name


class _PromptTool:
    def __init__(self, name: str, description: str) -> None:
        self.name = name
        self.description = description


class _ProjectWorkspaceManager:
    root_goal_task_id = None

    async def build_persona(self) -> None:
        return None


class _ProjectPromptAgent(PromptMixin):
    model = "claude-3"
    skills: ClassVar[list[object]] = []
    subagents: ClassVar[list[object]] = []
    project_root = Path("/tmp/memstack-project")
    max_steps = 5
    max_tokens = 4000
    agent_mode = "build"
    prompt_manager = SystemPromptManager()
    _enable_subagent_as_tool = False
    _workspace_manager = _ProjectWorkspaceManager()
    _session_factory = None
    _sisyphus_prompt_builder = None
    _tool_policy_layers: ClassVar[dict[str, dict[str, object]]] = {}
    _tool_selection_max_tools = 40
    _tool_selection_semantic_backend = "disabled"
    _stream_memory_context = None

    def _get_current_tools(
        self,
        selection_context: object | None = None,
    ) -> tuple[dict[str, object], list[_PromptTool]]:
        return {}, [_PromptTool("read", "read file")]


pytestmark = pytest.mark.unit


class TestIsWorkspaceConversationPredicate:
    def test_empty_payload_is_not_workspace(self) -> None:
        assert is_workspace_conversation(None) is False
        assert is_workspace_conversation({}) is False

    def test_project_id_alone_is_not_workspace(self) -> None:
        # The historical leaky gate (project_id + tenant_id) must not flip
        # the new authoritative predicate.
        assert (
            is_workspace_conversation({"runtime_context": {"project_id": "p1", "tenant_id": "t1"}})
            is False
        )

    def test_task_authority_workspace_marks_conversation(self) -> None:
        assert (
            is_workspace_conversation({"runtime_context": {"task_authority": "workspace"}}) is True
        )

    def test_workspace_id_with_role_marks_conversation(self) -> None:
        assert (
            is_workspace_conversation(
                {
                    "runtime_context": {
                        "workspace_id": "ws-1",
                        "workspace_session_role": "leader",
                    }
                }
            )
            is True
        )

    def test_workspace_id_without_role_does_not_mark(self) -> None:
        assert is_workspace_conversation({"runtime_context": {"workspace_id": "ws-1"}}) is False

    def test_accepts_raw_runtime_context_mapping(self) -> None:
        assert is_workspace_conversation({"task_authority": "workspace"}) is True

    def test_workspace_worker_runtime_context_type_marks_conversation(self) -> None:
        # Regression: planner_agent_decomposer / iteration_review /
        # verification_judge emit payloads where ``workspace_id`` lives inside
        # ``workspace_binding`` (not at the top level) and ``task_authority``
        # is unset. The canonical ``context_type`` marker must still classify
        # these turns as workspace, otherwise the tool filter will strip
        # ``workspace_report_complete`` and friends.
        payload = {
            "context_type": "workspace_worker_runtime",
            "workspace_session_role": "worker",
            "workspace_binding": {
                "workspace_id": "ws-1",
                "root_goal_task_id": "root-1",
            },
        }
        assert is_workspace_conversation(payload) is True


class TestNonWorkspaceConversationToolFilter:
    def test_strips_workspace_prefix_when_not_workspace(self) -> None:
        tools = [
            _Tool("read"),
            _Tool("workspace_report_complete"),
            _Tool("workspace_chat_send"),
            _Tool("agent_spawn"),
        ]
        filtered = filter_non_workspace_conversation_tools(tools, is_workspace_conversation=False)
        assert [t.name for t in filtered] == ["read", "agent_spawn"]

    def test_keeps_all_when_workspace(self) -> None:
        tools = [_Tool("read"), _Tool("workspace_report_complete")]
        filtered = filter_non_workspace_conversation_tools(tools, is_workspace_conversation=True)
        assert [t.name for t in filtered] == ["read", "workspace_report_complete"]


class TestSystemPromptIsolation:
    @pytest.mark.asyncio
    async def test_non_workspace_prompt_omits_workspace_artifacts(self) -> None:
        manager = SystemPromptManager()
        context = PromptContext(
            model_provider=SystemPromptManager.detect_model_provider("claude-3"),
            mode=PromptMode.BUILD,
            tool_definitions=[{"name": "read", "description": "read file"}],
            workspace_context=None,
            workspace_authority_active=False,
        )
        prompt = await manager.build_system_prompt(context)
        # No dynamic workspace XML/context block.
        assert "<workspace>" not in prompt
        # No workspace authority contract.
        assert "Workspace Authority Contract" not in prompt
        # No Plan/Build lifecycle prose (todowrite not in toolset).
        assert "Work Plan & Task Lifecycle" not in prompt
        assert "todowrite" not in prompt

    @pytest.mark.asyncio
    async def test_task_lifecycle_loads_when_todowrite_present(self) -> None:
        manager = SystemPromptManager()
        context = PromptContext(
            model_provider=SystemPromptManager.detect_model_provider("claude-3"),
            mode=PromptMode.BUILD,
            tool_definitions=[
                {"name": "todowrite", "description": "manage tasks"},
                {"name": "todoread", "description": "read tasks"},
            ],
            workspace_context=None,
            workspace_authority_active=False,
        )
        prompt = await manager.build_system_prompt(context)
        assert "Work Plan & Task Lifecycle" in prompt
        assert "todowrite" in prompt

    @pytest.mark.asyncio
    async def test_workspace_prompt_includes_workspace_artifacts(self) -> None:
        manager = SystemPromptManager()
        context = PromptContext(
            model_provider=SystemPromptManager.detect_model_provider("claude-3"),
            mode=PromptMode.BUILD,
            tool_definitions=[
                {"name": "workspace_report_complete", "description": "report"},
                {"name": "todowrite", "description": "manage tasks"},
            ],
            workspace_context="<workspace>\n  <id>ws-1</id>\n</workspace>",
            workspace_authority_active=True,
        )
        prompt = await manager.build_system_prompt(context)
        assert "<workspace>" in prompt
        assert "Workspace Authority Contract" in prompt
        assert "Work Plan & Task Lifecycle" in prompt


class TestPromptMixinWorkspaceContextIsolation:
    @pytest.mark.asyncio
    async def test_project_chat_with_workspace_manager_omits_dynamic_workspace_context(
        self,
    ) -> None:
        agent = _ProjectPromptAgent()
        with patch(
            "src.infrastructure.agent.workspace.workspace_context_builder.build_workspace_context",
            new_callable=AsyncMock,
        ) as build_context:
            build_context.return_value = '<cyber-workspace name="leaked" />'

            prompt = await agent._build_system_prompt(
                user_query="hi",
                conversation_context=[],
                project_id="project-1",
                tenant_id="tenant-1",
                is_workspace_conversation=False,
            )

        build_context.assert_not_awaited()
        assert "<cyber-workspace" not in prompt

    @pytest.mark.asyncio
    async def test_workspace_chat_injects_dynamic_workspace_context(self) -> None:
        agent = _ProjectPromptAgent()
        workspace_context = '<cyber-workspace name="workspace" />'
        with patch(
            "src.infrastructure.agent.workspace.workspace_context_builder.build_workspace_context",
            new_callable=AsyncMock,
        ) as build_context:
            build_context.return_value = workspace_context

            prompt = await agent._build_system_prompt(
                user_query="hi",
                conversation_context=[],
                project_id="project-1",
                tenant_id="tenant-1",
                is_workspace_conversation=True,
            )

        build_context.assert_awaited_once_with("project-1", "tenant-1")
        assert workspace_context in prompt


class TestBaseSystemPromptFilesAreClean:
    """Lock in that base provider prompts no longer hardcode workspace prose."""

    def test_anthropic_base_has_no_lifecycle_prose(self) -> None:
        from pathlib import Path

        text = (
            Path(__file__)
            .resolve()
            .parents[5]
            .joinpath("infrastructure/agent/prompts/system/anthropic.txt")
            .read_text(encoding="utf-8")
        )
        assert "Work Plan & Task Lifecycle" not in text
        assert "todowrite" not in text

    def test_default_base_has_no_lifecycle_prose(self) -> None:
        from pathlib import Path

        text = (
            Path(__file__)
            .resolve()
            .parents[5]
            .joinpath("infrastructure/agent/prompts/system/default.txt")
            .read_text(encoding="utf-8")
        )
        assert "Work Plan & Task Lifecycle" not in text
        assert "todowrite" not in text

    def test_gemini_base_has_no_lifecycle_prose(self) -> None:
        from pathlib import Path

        text = (
            Path(__file__)
            .resolve()
            .parents[5]
            .joinpath("infrastructure/agent/prompts/system/gemini.txt")
            .read_text(encoding="utf-8")
        )
        assert "Work Plan & Task Lifecycle" not in text
        assert "todowrite" not in text
