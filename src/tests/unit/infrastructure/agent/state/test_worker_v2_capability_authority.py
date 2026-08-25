"""V2-only capability authority coverage for Agent worker composition."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.domain.model.agent.skill.skill_source import SkillSource
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.agent.state import agent_session_pool, agent_worker_state

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
        "_configure_skill_evolution_capture",
        "_add_model_awareness_tools",
        "_add_register_mcp_server_tool",
        "_add_session_comm_tools",
        "_add_session_status_tool",
        "_add_cron_tool",
        "_add_canvas_tools",
        "_add_agent_tools",
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
async def test_builtin_tool_builder_does_not_publish_partial_generation_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    descriptor = _descriptor()
    marker = object()

    def _noop(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(
        "src.infrastructure.agent.tools.clarification.configure_clarification",
        _noop,
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.tools.decision.configure_decision",
        _noop,
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.tools.web_scrape.configure_web_scrape",
        _noop,
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.tools.web_search.configure_web_search",
        _noop,
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.tools.define.get_registered_tools",
        lambda: {
            "web_search": marker,
            "web_scrape": marker,
            "ask_clarification": marker,
            "request_decision": marker,
        },
    )

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
