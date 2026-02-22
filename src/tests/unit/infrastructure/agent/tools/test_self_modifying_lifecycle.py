"""Tests for self-modifying lifecycle orchestration."""

import pytest

from src.infrastructure.agent.tools.self_modifying_lifecycle import (
    SelfModifyingLifecycleOrchestrator,
)


@pytest.mark.unit
def test_run_post_change_invalidation_and_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    """Lifecycle should run invalidation hooks and probe expected tools."""
    captured = {
        "skill_cache_args": [],
        "project_cache_args": [],
    }

    def _invalidate_skill_loader_cache(tenant_id=None):
        captured["skill_cache_args"].append(tenant_id)

    def _invalidate_all_caches_for_project(*, project_id, tenant_id, clear_tool_definitions):
        captured["project_cache_args"].append((project_id, tenant_id, clear_tool_definitions))
        return {"invalidated": {"tools_cache": True}}

    def _get_cached_tools_for_project(_project_id):
        return {"mcp__demo__echo": object()}

    monkeypatch.setattr(
        "src.infrastructure.agent.state.agent_worker_state.invalidate_skill_loader_cache",
        _invalidate_skill_loader_cache,
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.state.agent_worker_state.invalidate_all_caches_for_project",
        _invalidate_all_caches_for_project,
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.state.agent_worker_state.get_cached_tools_for_project",
        _get_cached_tools_for_project,
    )

    result = SelfModifyingLifecycleOrchestrator.run_post_change(
        source="register_mcp_server",
        tenant_id="tenant-1",
        project_id="project-1",
        expected_tool_names=["mcp__demo__echo", "mcp__demo__missing"],
        metadata={"server_name": "demo"},
    )

    assert captured["skill_cache_args"] == ["tenant-1"]
    assert captured["project_cache_args"] == [("project-1", "tenant-1", True)]
    assert result["probe"]["status"] == "missing_tools"
    assert result["probe"]["missing_tools"] == ["mcp__demo__missing"]


@pytest.mark.unit
def test_run_post_change_global_skill_cache_when_no_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lifecycle should invalidate global skill cache when tenant is absent."""
    captured = {"skill_cache_args": []}

    def _invalidate_skill_loader_cache(tenant_id=None):
        captured["skill_cache_args"].append(tenant_id)

    monkeypatch.setattr(
        "src.infrastructure.agent.state.agent_worker_state.invalidate_skill_loader_cache",
        _invalidate_skill_loader_cache,
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.state.agent_worker_state.invalidate_all_caches_for_project",
        lambda **kwargs: {"invalidated": {}},
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.state.agent_worker_state.get_cached_tools_for_project",
        lambda _project_id: None,
    )

    result = SelfModifyingLifecycleOrchestrator.run_post_change(
        source="skill_installer",
        tenant_id=None,
        project_id=None,
        expected_tool_names=None,
    )

    assert captured["skill_cache_args"] == [None]
    assert result["probe"]["status"] == "skipped"
