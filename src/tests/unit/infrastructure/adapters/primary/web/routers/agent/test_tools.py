from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.infrastructure.adapters.primary.web.routers.agent.tools import (
    get_tool_capabilities,
)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_tool_capabilities_includes_builtin_runtime_plugins() -> None:
    runtime_manager = MagicMock()
    runtime_manager.ensure_loaded = AsyncMock(return_value=[])
    runtime_manager.list_plugins.return_value = (
        [
            {"name": "sisyphus-runtime", "enabled": True},
            {"name": "memory-runtime", "enabled": False},
        ],
        [],
    )
    registry = MagicMock()
    registry.list_tool_factories.return_value = {"memory-runtime": object()}
    registry.list_channel_type_metadata.return_value = {}
    registry.list_hooks.return_value = {
        "before_response": {"sisyphus-runtime": (30, object())},
        "before_prompt_build": {"memory-runtime": (25, object())},
        "after_turn_complete": {"memory-runtime": (25, object())},
    }
    registry.list_commands.return_value = {}
    registry.list_services.return_value = {"memory-runtime": ("memory-runtime", object())}
    registry.list_providers.return_value = {}

    with (
        patch(
            "src.infrastructure.agent.plugins.manager.get_plugin_runtime_manager",
            return_value=runtime_manager,
        ),
        patch(
            "src.infrastructure.agent.plugins.registry.get_plugin_registry",
            return_value=registry,
        ),
    ):
        response = await get_tool_capabilities(
            current_user=SimpleNamespace(tenant_id="tenant-1"),
        )

    assert response.plugin_runtime.plugins_total == 2
    assert response.plugin_runtime.plugins_enabled == 1
    assert response.plugin_runtime.tool_factories == 1
    assert response.plugin_runtime.hook_handlers == 3
    assert response.plugin_runtime.services == 1
