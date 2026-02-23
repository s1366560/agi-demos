"""Unit tests for plugin reload planner."""

import pytest

from src.infrastructure.agent.plugins.reload_planner import build_plugin_reload_plan


@pytest.mark.unit
def test_build_plugin_reload_plan_dry_run() -> None:
    """Dry-run plan should skip runtime mutation and report inventory counts."""
    plan = build_plugin_reload_plan(
        action="reload",
        dry_run=True,
        plugin_name=None,
        tenant_id="tenant-1",
        plugins=[
            {"name": "alpha", "enabled": True, "discovered": True},
            {"name": "beta", "enabled": False, "discovered": True},
        ],
        diagnostics=[{"code": "plugin_loaded"}],
        reason="manual reload request",
    )

    assert plan["action"] == "reload"
    assert plan["dry_run"] is True
    assert plan["trigger_scope"] == "tenant"
    assert plan["inventory"]["total_plugins"] == 2
    assert plan["inventory"]["enabled_plugins"] == 1
    assert "skip-runtime-mutation" in plan["steps"]
