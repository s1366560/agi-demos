"""Generation lease coverage for long-lived channel connections."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.domain.model.channels.message import ChannelConfig
from src.infrastructure.channels.connection_manager import ChannelConnectionManager
from src.infrastructure.plugins.v2.boundary import (
    clear_process_generation_host_v2,
    install_process_generation_host_v2,
)
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.runtime import FiberPhaseV2
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

_ROOT = Path(__file__).resolve().parents[5]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


class _Adapter:
    def __init__(self, config: ChannelConfig) -> None:
        self.config = config
        self.connected = False

    def on_message(self, _handler: object) -> None:
        return None

    async def connect(self) -> None:
        self.connected = True

    async def disconnect(self) -> None:
        self.connected = False


def _channel_config() -> object:
    return SimpleNamespace(
        id="channel-generation-lease",
        project_id="project-a",
        channel_type="feishu",
        enabled=True,
        app_id="app-id",
        app_secret="app-secret",
        encrypt_key=None,
        verification_token=None,
        connection_mode="websocket",
        webhook_port=None,
        webhook_path=None,
        domain="feishu",
        extra_settings={},
    )


@pytest.mark.unit
async def test_channel_connection_lease_keeps_retired_generation_active_until_stop() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    first = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=1,
        version=1,
    )
    assert first.accepted
    previous = host.manager.current
    assert previous is not None
    manager = ChannelConnectionManager()
    install_process_generation_host_v2(host)

    try:
        with patch(
            "src.infrastructure.adapters.secondary.channels.channel_plugin_loader.load_channel_module",
            return_value=SimpleNamespace(FeishuAdapter=_Adapter),
        ):
            connection = await manager.add_connection(_channel_config())  # type: ignore[arg-type]

        second = await host.bootstrap(
            profile_path=_PROFILE_PATH,
            manifest_paths=(_MANIFEST_PATH,),
            generation=2,
            version=2,
        )
        assert second.accepted
        assert all(fiber.phase is FiberPhaseV2.ACTIVE for fiber in previous.fibers)

        assert await manager.remove_connection(connection.config_id)

        assert all(fiber.phase is FiberPhaseV2.DISPOSED for fiber in previous.fibers)
    finally:
        if manager.connections:
            await manager.shutdown_all()
        clear_process_generation_host_v2(host)
        await host.close()
