"""V2-only capability authority coverage for Agent worker composition."""

from __future__ import annotations

import asyncio
import importlib.util
import inspect
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.domain.model.agent.skill.skill_source import SkillSource
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.agent.state import agent_session_pool, agent_worker_state
from src.infrastructure.agent.tools.define import ToolInfo

_ROOT = Path(__file__).resolve().parents[6]
_WORKER_SOURCE = _ROOT / "src/infrastructure/agent/state/agent_worker_state.py"


def _descriptor() -> PluginGenerationDescriptorV2:
    return PluginGenerationDescriptorV2(
        profile_id="memstack-default-v2",
        generation=7,
        digest="a" * 64,
    )


@pytest.fixture(autouse=True)
def _clear_worker_capability_caches() -> None:
    agent_worker_state._tools_cache.clear()
    agent_worker_state._skills_cache.clear()
    yield
    agent_worker_state._tools_cache.clear()
    agent_worker_state._skills_cache.clear()


@pytest.mark.unit
def test_worker_has_no_v1_plugin_capability_authority() -> None:
    source = _WORKER_SOURCE.read_text(encoding="utf-8")

    for forbidden in (
        "get_plugin_runtime_manager",
        "get_plugin_registry",
        "_add_plugin_tools",
        "_add_sandbox_plugin_tools",
        "_add_plugin_skills",
        "src.infrastructure.plugins.agent_tools",
        "_publish_scoped_tool_generation",
    ):
        assert forbidden not in source


@pytest.mark.unit
def test_legacy_workspace_chat_tool_fallback_is_removed() -> None:
    assert "_add_workspace_chat_tools" not in vars(agent_worker_state)
    assert importlib.util.find_spec("src.infrastructure.agent.tools.workspace_chat_tool") is None


@pytest.mark.unit
def test_builtin_memory_tool_source_preserves_memory_capabilities() -> None:
    from src.infrastructure.agent.tools.memory_tool_provider import build_memory_tools

    with patch(
        "src.configuration.config.get_settings",
        return_value=SimpleNamespace(agent_memory_tool_provider_mode="enabled"),
    ):
        tools = build_memory_tools(
            tenant_id="tenant-a",
            project_id="project-a",
            graph_service=SimpleNamespace(embedder=None),
            redis_client=None,
            session_factory=lambda: None,
        )

    assert set(tools) == {
        "memory_create",
        "memory_delete",
        "memory_get",
        "memory_search",
        "memory_update",
    }


@pytest.mark.unit
def test_builtin_workspace_skill_source_preserves_task_harness() -> None:
    from src.infrastructure.agent.workspace.skill_provider import (
        WORKSPACE_TASK_HARNESS_SKILL_NAME,
        build_workspace_task_harness_skill,
    )

    skill = build_workspace_task_harness_skill(
        tenant_id="tenant-a",
        project_id="project-a",
    )

    assert skill.name == WORKSPACE_TASK_HARNESS_SKILL_NAME
    assert skill.tenant_id == "tenant-a"
    assert skill.project_id == "project-a"
    assert skill.source is SkillSource.PLUGIN
    assert "workspace_report_complete" in skill.tools


@pytest.mark.unit
def test_cached_tool_read_uses_exact_v2_generation_descriptor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    descriptor = _descriptor()
    cache_key = agent_session_pool.generation_cache_key_v2(
        "project-a",
        generation_descriptor=descriptor,
    )
    expected = {"read": object()}
    agent_worker_state._tools_cache[cache_key] = expected
    monkeypatch.setattr(
        agent_worker_state,
        "resolve_generation_cache_descriptor_v2",
        lambda explicit=None: explicit,
    )

    result = agent_worker_state.get_cached_tools_for_project("project-a", descriptor)

    assert result == expected


@pytest.mark.unit
async def test_complete_worker_tool_set_is_cached_by_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    descriptor = _descriptor()

    async def _noop_async(*_args: object, **_kwargs: object) -> None:
        return None

    async def _empty_tools(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {}

    def _noop(*_args: object, **_kwargs: object) -> None:
        return None

    def _add_memory(tools: dict[str, object], *_args: object, **_kwargs: object) -> None:
        tools["memory_search"] = object()

    def _add_custom(tools: dict[str, object], *_args: object, **_kwargs: object) -> None:
        tools["custom_tool"] = object()

    monkeypatch.setattr(
        agent_worker_state,
        "resolve_generation_cache_descriptor_v2",
        lambda explicit=None: explicit,
    )
    monkeypatch.setattr(
        agent_worker_state,
        "_get_or_create_builtin_tools",
        _empty_tools,
    )
    monkeypatch.setattr(agent_worker_state, "_add_sandbox_tools", _noop_async)
    monkeypatch.setattr(agent_worker_state, "_add_skill_loader_tool", _noop_async)
    monkeypatch.setattr(agent_worker_state, "_add_memory_tools", _add_memory)
    monkeypatch.setattr(agent_worker_state, "_add_custom_tools", _add_custom)
    for name in (
        "_add_skill_installer_tools",
        "_add_skill_sync_tool",
        "_add_env_var_tools",
        "_add_system_api_tool",
        "_add_hitl_tools",
        "_add_todo_tools",
        "_add_model_awareness_tools",
        "_add_register_mcp_server_tool",
        "_add_session_comm_tools",
        "_add_session_status_tool",
        "_add_cron_tool",
        "_add_canvas_tools",
    ):
        monkeypatch.setattr(agent_worker_state, name, _noop)
    monkeypatch.setattr(agent_worker_state, "_add_plugin_tools", _noop_async, raising=False)
    monkeypatch.setattr(
        agent_worker_state,
        "_add_sandbox_plugin_tools",
        _noop_async,
        raising=False,
    )

    tools = await agent_worker_state.get_or_create_tools(
        project_id="project-a",
        tenant_id="tenant-a",
        graph_service=object(),
        redis_client=None,
        generation_descriptor=descriptor,
    )
    cache_key = agent_session_pool.generation_cache_key_v2(
        "project-a",
        generation_descriptor=descriptor,
    )

    assert set(tools) == {"custom_tool", "memory_search"}
    assert agent_worker_state._tools_cache[cache_key] == tools


@pytest.mark.unit
async def test_builtin_tool_builder_does_not_publish_partial_generation_cache() -> None:
    descriptor = _descriptor()

    tools = await agent_worker_state._get_or_create_builtin_tools(
        "project-a",
        redis_client=None,
        generation_descriptor=descriptor,
    )

    assert set(tools) == {
        "web_search",
        "web_scrape",
        "ask_clarification",
        "request_decision",
    }
    assert agent_worker_state._tools_cache == {}


@pytest.mark.unit
async def test_builtin_tool_builder_does_not_use_global_registry_or_configurators(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("worker base tools must not use process-global configuration")

    for target in ("src.infrastructure.agent.tools.define.get_registered_tools",):
        monkeypatch.setattr(target, _forbidden)

    tools = await agent_worker_state._get_or_create_builtin_tools(
        "project-a",
        redis_client=None,
        generation_descriptor=_descriptor(),
    )

    assert set(tools) == {
        "web_search",
        "web_scrape",
        "ask_clarification",
        "request_decision",
    }


@pytest.mark.unit
async def test_builtin_web_search_runtime_isolated_between_generations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_entered = asyncio.Event()
    release_first = asyncio.Event()

    class _CachedRedis:
        def __init__(self, title: str, *, wait: bool) -> None:
            self._title = title
            self._wait = wait

        async def get(self, _key: str) -> str:
            if self._wait:
                first_entered.set()
                await release_first.wait()
            else:
                await first_entered.wait()
                release_first.set()
            return json.dumps(
                {
                    "query": "shared query",
                    "results": [
                        {
                            "title": self._title,
                            "url": "https://example.com",
                            "content": "cached content",
                            "score": 1.0,
                        }
                    ],
                    "total_results": 1,
                    "timestamp": "2026-08-26T00:00:00+00:00",
                }
            )

    monkeypatch.setattr(
        "src.infrastructure.agent.tools.web_search.get_settings",
        lambda: SimpleNamespace(
            tavily_api_key="test-key",
            tavily_search_depth="basic",
        ),
    )
    first_tools = await agent_worker_state._get_or_create_builtin_tools(
        "project-a",
        redis_client=_CachedRedis("generation-a", wait=True),
        generation_descriptor=_descriptor(),
    )
    second_tools = await agent_worker_state._get_or_create_builtin_tools(
        "project-b",
        redis_client=_CachedRedis("generation-b", wait=False),
        generation_descriptor=PluginGenerationDescriptorV2(
            profile_id="memstack-default-v2",
            generation=8,
            digest="b" * 64,
        ),
    )

    from src.infrastructure.agent.tools.context import ToolContext

    first_task = asyncio.create_task(
        first_tools["web_search"].execute(
            ToolContext(
                session_id="session-a",
                message_id="message-a",
                call_id="call-a",
                agent_name="agent-a",
                conversation_id="conversation-a",
            ),
            query="shared query",
        )
    )
    await first_entered.wait()
    second_result = await second_tools["web_search"].execute(
        ToolContext(
            session_id="session-b",
            message_id="message-b",
            call_id="call-b",
            agent_name="agent-b",
            conversation_id="conversation-b",
        ),
        query="shared query",
    )
    first_result = await first_task

    assert "generation-a" in first_result.output
    assert "generation-b" in second_result.output


@pytest.mark.unit
def test_worker_skill_loader_builder_has_no_global_registry_or_configurator() -> None:
    source = inspect.getsource(agent_worker_state.get_or_create_skill_loader_tool)

    assert "get_registered_tools" not in source
    assert "configure_skill_loader_tool" not in source
    assert "make_skill_loader_tool" in source


@pytest.mark.unit
def test_worker_skill_loader_builder_has_no_process_global_availability_cache() -> None:
    source = inspect.getsource(agent_worker_state.get_or_create_skill_loader_tool)

    assert "get_available_skills" not in source
    assert "set_available_skills" not in source


@pytest.mark.unit
async def test_worker_skill_loader_binds_sandbox_without_global_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = object()
    captured: dict[str, object] = {}

    async def _get_skill_loader(**kwargs: object) -> object:
        captured.update(kwargs)
        return marker

    monkeypatch.setattr(
        agent_worker_state,
        "get_or_create_skill_loader_tool",
        _get_skill_loader,
    )

    tools: dict[str, object] = {"bash": SimpleNamespace(sandbox_id="sandbox-a")}
    await agent_worker_state._add_skill_loader_tool(
        tools,
        tenant_id="tenant-a",
        project_id="project-a",
        agent_mode="react",
        generation_descriptor=_descriptor(),
    )

    assert tools["skill_loader"] is marker
    assert captured == {
        "tenant_id": "tenant-a",
        "project_id": "project-a",
        "agent_mode": "react",
        "generation_descriptor": _descriptor(),
        "sandbox_id": "sandbox-a",
    }


@pytest.mark.unit
def test_worker_skill_installer_binds_project_without_global_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = object()
    captured: dict[str, object] = {}

    def _make_skill_installer(**kwargs: object) -> object:
        captured.update(kwargs)
        return marker

    def _forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("worker skill installer must not mutate module-level runtime state")

    monkeypatch.setattr(
        "src.infrastructure.agent.tools.skill_installer.make_skill_installer_tool",
        _make_skill_installer,
        raising=False,
    )
    monkeypatch.setattr(
        agent_worker_state,
        "resolve_project_base_path",
        lambda project_id: Path(f"/projects/{project_id}"),
    )

    tools: dict[str, object] = {}
    agent_worker_state._add_skill_installer_tools(
        tools,
        tenant_id="tenant-a",
        project_id="project-a",
    )

    assert tools["skill_installer"] is marker
    assert captured == {
        "project_path": Path("/projects/project-a"),
        "tenant_id": "tenant-a",
        "project_id": "project-a",
    }


@pytest.mark.unit
def test_worker_session_comm_uses_bound_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_factory = object()
    bound_tools = {
        "peer_sessions_list": object(),
        "peer_sessions_history": object(),
        "peer_sessions_send": object(),
    }
    captured: dict[str, object] = {}

    def _make_session_comm_tools(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return bound_tools

    def _forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("worker session comm must not mutate module-level runtime state")

    monkeypatch.setattr(
        "src.infrastructure.adapters.secondary.persistence.database.async_session_factory",
        session_factory,
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.tools.session_comm_tools.make_session_comm_tools",
        _make_session_comm_tools,
        raising=False,
    )
    tools: dict[str, object] = {}
    agent_worker_state._add_session_comm_tools(
        tools,
        project_id="project-a",
        redis_client=object(),
    )

    assert tools == bound_tools
    assert captured == {"session_factory": session_factory}


@pytest.mark.unit
def test_worker_session_status_uses_bound_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_factory = object()
    marker = object()
    captured: dict[str, object] = {}

    def _make_session_status_tool(**kwargs: object) -> object:
        captured.update(kwargs)
        return marker

    def _forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("worker session status must not mutate module-level runtime state")

    monkeypatch.setattr(
        "src.infrastructure.adapters.secondary.persistence.database.async_session_factory",
        session_factory,
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.tools.session_status.make_session_status_tool",
        _make_session_status_tool,
        raising=False,
    )
    tools: dict[str, object] = {}
    agent_worker_state._add_session_status_tool(tools, project_id="project-a")

    assert tools["session_status"] is marker
    assert captured == {"session_factory": session_factory}


@pytest.mark.unit
def test_worker_cron_uses_bound_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_factory = object()
    marker = object()
    captured: dict[str, object] = {}

    def _make_cron_tool(**kwargs: object) -> object:
        captured.update(kwargs)
        return marker

    monkeypatch.setattr(
        "src.infrastructure.adapters.secondary.persistence.database.async_session_factory",
        session_factory,
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.tools.cron_tool.make_cron_tool",
        _make_cron_tool,
        raising=False,
    )

    tools: dict[str, object] = {}
    agent_worker_state._add_cron_tool(tools, project_id="project-a")

    assert tools["cron"] is marker
    assert captured == {"session_factory": session_factory}


@pytest.mark.unit
def test_worker_canvas_uses_v2_manager_and_bound_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = object()
    bound_tools = {
        "canvas_create": object(),
        "canvas_create_interactive": object(),
        "canvas_update": object(),
        "canvas_delete": object(),
    }
    captured: dict[str, object] = {}

    def _make_canvas_tools(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return bound_tools

    def _forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("worker canvas must not use process-global manager authority")

    monkeypatch.setattr(
        "src.infrastructure.plugins.v2.agent_worker_runtime.current_agent_canvas_manager_v2",
        lambda: manager,
        raising=False,
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.canvas.tools.make_canvas_tools",
        _make_canvas_tools,
        raising=False,
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.canvas.tools.get_canvas_manager",
        _forbidden,
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.canvas.manager.CanvasManager",
        _forbidden,
    )

    tools: dict[str, object] = {}
    agent_worker_state._add_canvas_tools(tools)

    assert tools == bound_tools
    assert captured == {"manager": manager}


@pytest.mark.unit
def test_worker_hitl_tools_use_declared_tool_infos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError(
            "worker HITL tools must not use global configuration or registry lookup"
        )

    monkeypatch.setattr(
        "src.infrastructure.agent.tools.define.get_registered_tools",
        _forbidden,
    )

    tools: dict[str, object] = {}
    agent_worker_state._add_hitl_tools(tools, project_id="project-a")

    from src.infrastructure.agent.tools.clarification import clarification_tool
    from src.infrastructure.agent.tools.decision import decision_tool

    assert set(tools) == {"ask_clarification", "request_decision"}
    for name, template in {
        "ask_clarification": clarification_tool,
        "request_decision": decision_tool,
    }.items():
        bound_tool = tools[name]
        assert isinstance(bound_tool, ToolInfo)
        assert bound_tool.name == template.name
        assert bound_tool.parameters == template.parameters
        assert bound_tool.execute is not template.execute


@pytest.mark.unit
def test_worker_model_awareness_tools_use_declared_tool_infos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bound_tools = {
        "list_available_models": object(),
        "switch_model_next_turn": object(),
    }
    captured: dict[str, object] = {}

    def _make_model_awareness_tools(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return bound_tools

    def _forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("worker model tools must not use global runtime authority")

    monkeypatch.setattr(
        "src.infrastructure.agent.tools.define.get_registered_tools",
        _forbidden,
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.tools.model_availability_tool.make_model_awareness_tools",
        _make_model_awareness_tools,
        raising=False,
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.tools.model_availability_tool.list_available_models_tool",
        _forbidden,
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.tools.model_availability_tool.switch_model_next_turn_tool",
        _forbidden,
    )
    session_factory = object()
    model_catalog = object()
    monkeypatch.setattr(
        "src.infrastructure.adapters.secondary.persistence.database.async_session_factory",
        session_factory,
    )
    monkeypatch.setattr(
        "src.infrastructure.llm.model_catalog.get_model_catalog_service",
        lambda: model_catalog,
    )

    tools: dict[str, object] = {}
    agent_worker_state._add_model_awareness_tools(
        tools,
        tenant_id="tenant-a",
        project_id="project-a",
    )

    assert tools == bound_tools
    assert captured == {
        "session_factory": session_factory,
        "model_catalog": model_catalog,
    }


@pytest.mark.unit
def test_worker_skill_sync_uses_bound_tool_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = object()
    captured: dict[str, object] = {}

    def _make_skill_sync_tool(**kwargs: object) -> object:
        captured.update(kwargs)
        return marker

    def _forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("worker skill sync must not use global configuration or registry")

    session_factory = object()
    sandbox_adapter = object()
    skill_loader_tool = SimpleNamespace(name="skill_loader", sandbox_id="sandbox-a")
    monkeypatch.setattr(
        "src.infrastructure.adapters.secondary.persistence.database.async_session_factory",
        session_factory,
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.tools.skill_sync.make_skill_sync_tool",
        _make_skill_sync_tool,
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.tools.define.get_registered_tools",
        _forbidden,
    )
    monkeypatch.setattr(
        agent_worker_state,
        "current_mcp_sandbox_adapter_v2",
        lambda: sandbox_adapter,
    )

    tools: dict[str, object] = {"skill_loader": skill_loader_tool}
    agent_worker_state._add_skill_sync_tool(
        tools,
        tenant_id="tenant-a",
        project_id="project-a",
    )

    assert tools["skill_sync"] is marker
    assert captured == {
        "tenant_id": "tenant-a",
        "project_id": "project-a",
        "sandbox_adapter": sandbox_adapter,
        "sandbox_id": "sandbox-a",
        "session_factory": session_factory,
        "skill_loader_tool": skill_loader_tool,
    }


@pytest.mark.unit
def test_worker_env_var_tools_use_bound_tool_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bound_tools = {
        "get_env_var": object(),
        "request_env_var": object(),
        "check_env_vars": object(),
    }
    captured: dict[str, object] = {}

    def _make_env_var_tools(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return bound_tools

    def _forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("worker env-var tools must not use global configuration or registry")

    session_factory = object()
    encryption_service = object()
    monkeypatch.setattr(
        "src.infrastructure.adapters.secondary.persistence.database.async_session_factory",
        session_factory,
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.tools.env_var_tools.make_env_var_tools",
        _make_env_var_tools,
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.tools.define.get_registered_tools",
        _forbidden,
    )
    monkeypatch.setattr(
        "src.infrastructure.security.encryption_service.get_encryption_service",
        lambda: encryption_service,
    )

    tools: dict[str, object] = {}
    agent_worker_state._add_env_var_tools(
        tools,
        tenant_id="tenant-a",
        project_id="project-a",
    )

    assert tools == bound_tools
    assert captured == {
        "encryption_service": encryption_service,
        "session_factory": session_factory,
    }
