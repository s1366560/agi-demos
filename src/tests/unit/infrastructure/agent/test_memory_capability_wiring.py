from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.unit
class TestProjectMemoryCapabilityInit:
    @pytest.mark.asyncio
    async def test_enables_memory_runtime_without_redis(self) -> None:
        from src.infrastructure.agent.core.project_react_agent import ProjectReActAgent

        agent = ProjectReActAgent.__new__(ProjectReActAgent)
        agent.config = SimpleNamespace(
            tenant_id="tenant-1",
            project_id="proj-1",
            agent_mode="default",
        )
        agent._get_session_factory = MagicMock(return_value="session-factory")
        graph_service = SimpleNamespace(embedder=object())

        with patch(
            "src.infrastructure.agent.memory.runtime.DefaultMemoryRuntime",
            return_value="memory-runtime",
        ) as runtime_cls:
            memory_runtime, session_factory = agent._init_memory_runtime(
                graph_service,
                None,
                object(),
            )

        assert memory_runtime == "memory-runtime"
        assert session_factory == "session-factory"
        runtime_cls.assert_called_once()


@pytest.mark.unit
class TestMemoryToolWiring:
    @pytest.mark.asyncio
    async def test_get_or_create_tools_uses_plugin_path_for_memory_tools(self) -> None:
        plugin_tools_adder = AsyncMock(
            side_effect=lambda tools, tenant_id, project_id, **kwargs: tools.update(
                {"memory_search": "plugin-memory-search"}
            )
        )

        with (
            patch(
                "src.infrastructure.agent.state.agent_worker_state._get_or_create_builtin_tools",
                AsyncMock(return_value={}),
            ),
            patch(
                "src.infrastructure.agent.state.agent_worker_state._add_sandbox_tools",
                AsyncMock(return_value=None),
            ),
            patch(
                "src.infrastructure.agent.state.agent_worker_state._add_skill_loader_tool",
                AsyncMock(return_value=None),
            ),
            patch(
                "src.infrastructure.agent.state.agent_worker_state._add_skill_installer_tools",
                MagicMock(),
            ),
            patch(
                "src.infrastructure.agent.state.agent_worker_state._add_skill_sync_tool",
                MagicMock(),
            ),
            patch(
                "src.infrastructure.agent.state.agent_worker_state._add_env_var_tools",
                MagicMock(),
            ),
            patch(
                "src.infrastructure.agent.state.agent_worker_state._add_hitl_tools",
                MagicMock(),
            ),
            patch(
                "src.infrastructure.agent.state.agent_worker_state._add_todo_tools",
                MagicMock(),
            ),
            patch(
                "src.infrastructure.agent.state.agent_worker_state._add_model_awareness_tools",
                MagicMock(),
            ),
            patch(
                "src.infrastructure.agent.state.agent_worker_state._add_register_mcp_server_tool",
                MagicMock(),
            ),
            patch(
                "src.infrastructure.agent.state.agent_worker_state._add_plugin_tools",
                plugin_tools_adder,
            ),
            patch(
                "src.infrastructure.agent.state.agent_worker_state._add_sandbox_plugin_tools",
                AsyncMock(return_value=None),
            ),
            patch(
                "src.infrastructure.agent.state.agent_worker_state._add_custom_tools",
                MagicMock(),
            ),
            patch(
                "src.infrastructure.agent.state.agent_worker_state._add_session_comm_tools",
                MagicMock(),
            ),
            patch(
                "src.infrastructure.agent.state.agent_worker_state._add_session_status_tool",
                MagicMock(),
            ),
            patch(
                "src.infrastructure.agent.state.agent_worker_state._add_cron_tool",
                MagicMock(),
            ),
            patch(
                "src.infrastructure.agent.state.agent_worker_state._add_canvas_tools",
                MagicMock(),
            ),
            patch(
                "src.infrastructure.agent.state.agent_worker_state._add_agent_tools",
                MagicMock(),
            ),
            patch(
                "src.infrastructure.agent.state.agent_worker_state._add_workspace_chat_tools",
                AsyncMock(return_value=None),
            ),
        ):
            from src.infrastructure.agent.state.agent_worker_state import get_or_create_tools

            tools = await get_or_create_tools(
                project_id="proj-1",
                tenant_id="tenant-1",
                graph_service=SimpleNamespace(embedder=None),
                redis_client=None,
            )

        assert tools["memory_search"] == "plugin-memory-search"
        plugin_tools_adder.assert_awaited_once()
