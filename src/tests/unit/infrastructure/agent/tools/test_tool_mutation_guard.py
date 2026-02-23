"""Unit tests for tool mutation guard utilities."""

import pytest

from src.infrastructure.agent.tools.tool_mutation_guard import (
    build_mutation_fingerprint,
    is_mutating_tool_call,
)


@pytest.mark.unit
def test_plugin_manager_enable_is_mutating() -> None:
    """plugin_manager enable action should be classified as mutating."""
    assert is_mutating_tool_call("plugin_manager", {"action": "enable"}) is True


@pytest.mark.unit
def test_plugin_manager_list_is_not_mutating() -> None:
    """plugin_manager list action should be read-only."""
    assert is_mutating_tool_call("plugin_manager", {"action": "list"}) is False


@pytest.mark.unit
def test_build_mutation_fingerprint_contains_stable_fields() -> None:
    """Fingerprint should include action and stable target fields."""
    fingerprint = build_mutation_fingerprint(
        "plugin_manager",
        {
            "action": "disable",
            "plugin_name": "demo-plugin",
            "tenant_id": "tenant-1",
            "project_id": "project-1",
        },
    )

    assert fingerprint is not None
    assert "tool=plugin_manager" in fingerprint
    assert "action=disable" in fingerprint
    assert "plugin_name=demo-plugin" in fingerprint
