"""Unit tests for plugin control-plane service."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.infrastructure.agent.plugins.control_plane import PluginControlPlaneService


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_runtime_plugins_enriches_channel_types() -> None:
    """Runtime list should include channel_types grouped by plugin ownership."""
    runtime_manager = SimpleNamespace(
        ensure_loaded=AsyncMock(return_value=[]),
        list_plugins=lambda **_kwargs: (
            [
                {
                    "name": "plugin-a",
                    "enabled": True,
                    "discovered": True,
                }
            ],
            [],
        ),
    )
    registry = SimpleNamespace(
        list_channel_adapter_factories=lambda: {"feishu": ("plugin-a", object())},
        list_channel_type_metadata=lambda: {},
        list_tool_factories=lambda: {},
        list_hooks=lambda: {},
        list_commands=lambda: {},
        list_services=lambda: {},
        list_providers=lambda: {},
    )
    service = PluginControlPlaneService(runtime_manager=runtime_manager, registry=registry)

    records, diagnostics, channel_types_by_plugin = await service.list_runtime_plugins()

    assert diagnostics == []
    assert records[0]["channel_types"] == ["feishu"]
    assert channel_types_by_plugin == {"plugin-a": ["feishu"]}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_set_plugin_enabled_attaches_reload_plan_and_control_trace() -> None:
    """Enable/disable actions should include reconcile plan and control-plane trace."""
    runtime_manager = SimpleNamespace(
        set_plugin_enabled=AsyncMock(return_value=[]),
    )
    registry = SimpleNamespace(
        list_channel_type_metadata=lambda: {"feishu": object()},
        list_tool_factories=lambda: {"plugin-a": object()},
        list_hooks=lambda: {"before_tool_selection": {"plugin-a": object()}},
        list_commands=lambda: {"echo": ("plugin-a", object())},
        list_services=lambda: {"skill-index": ("plugin-a", object())},
        list_providers=lambda: {"embedding": ("plugin-a", object())},
    )
    service = PluginControlPlaneService(
        runtime_manager=runtime_manager,
        registry=registry,
        reconcile_channel_runtime=AsyncMock(return_value={"restart": 1}),
    )

    result = await service.set_plugin_enabled(
        "plugin-a",
        enabled=True,
        tenant_id="tenant-1",
    )

    assert result.success is True
    assert result.details["channel_reload_plan"]["restart"] == 1
    assert result.details["control_plane_trace"]["action"] == "enable"
    runtime_manager.set_plugin_enabled.assert_awaited_once_with(
        "plugin-a",
        enabled=True,
        tenant_id="tenant-1",
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_install_plugin_returns_failure_result_without_raise() -> None:
    """Install failures should be returned as structured control-plane failures."""
    runtime_manager = SimpleNamespace(
        install_plugin=AsyncMock(return_value={"success": False, "error": "invalid requirement"}),
    )
    registry = SimpleNamespace(
        list_channel_type_metadata=lambda: {},
        list_tool_factories=lambda: {},
        list_hooks=lambda: {},
        list_commands=lambda: {},
        list_services=lambda: {},
        list_providers=lambda: {},
    )
    service = PluginControlPlaneService(runtime_manager=runtime_manager, registry=registry)

    result = await service.install_plugin("bad-package")

    assert result.success is False
    assert result.message == "invalid requirement"
    assert result.details["control_plane_trace"]["action"] == "install"
