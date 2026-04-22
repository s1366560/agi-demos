from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.infrastructure.adapters.primary.web.routers.system import get_system_info


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_system_info_includes_memory_runtime_rollout_state() -> None:
    with (
        patch(
            "src.infrastructure.adapters.primary.web.routers.system.get_feature_gate",
            return_value=SimpleNamespace(
                edition="community",
                get_enabled_features=lambda: [{"name": "agent", "enabled": True}],
            ),
        ),
        patch(
            "src.infrastructure.adapters.primary.web.routers.system.get_settings",
            return_value=SimpleNamespace(
                agent_runtime_mode="auto",
                agent_memory_runtime_mode="plugin",
                agent_memory_failure_persistence_enabled=True,
            ),
        ),
    ):
        info = await get_system_info(_current_user=SimpleNamespace(id="user-1"))

    assert info["edition"] == "community"
    assert info["agent_runtime"]["mode"] == "auto"
    assert info["memory_runtime"]["mode"] == "plugin"
    assert info["memory_runtime"]["failure_persistence_enabled"] is True
