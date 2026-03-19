"""WeCom (企业微信) Channel Plugin."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

from src.infrastructure.agent.plugins.registry import ChannelAdapterBuildContext
from src.infrastructure.agent.plugins.runtime_api import PluginRuntimeApi

_PLUGIN_DIR = Path(__file__).resolve().parent


def _load_sibling(module_file: str) -> ModuleType:
    file_path = _PLUGIN_DIR / module_file
    module_name = f"wecom_{file_path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load sibling module: {file_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class WeComChannelPlugin:
    name = "wecom-channel-plugin"

    def setup(self, api: PluginRuntimeApi) -> None:

        _adapter_mod = _load_sibling("adapter.py")
        WeComAdapter = _adapter_mod.WeComAdapter  # noqa: N806

        def _factory(context: ChannelAdapterBuildContext) -> object:
            return WeComAdapter(context.channel_config)

        api.register_channel_type(
            "wecom",
            _factory,
            config_schema={
                "type": "object",
                "properties": {
                    "corp_id": {"type": "string", "title": "Corp ID", "minLength": 1},
                    "agent_id": {"type": "string", "title": "Agent ID", "minLength": 1},
                    "secret": {"type": "string", "title": "Secret", "minLength": 1},
                    "token": {"type": "string", "title": "Token"},
                    "encoding_aes_key": {"type": "string", "title": "Encoding AES Key"},
                    "connection_mode": {
                        "type": "string",
                        "title": "Connection Mode",
                        "enum": ["webhook"],
                        "default": "webhook",
                    },
                    "webhook_url": {"type": "string", "title": "Webhook URL"},
                    "webhook_port": {
                        "type": "integer",
                        "title": "Webhook Port",
                        "minimum": 1,
                        "maximum": 65535,
                    },
                    "webhook_path": {"type": "string", "title": "Webhook Path"},
                },
                "required": ["corp_id", "agent_id", "secret"],
                "additionalProperties": False,
            },
            config_ui_hints={
                "secret": {"sensitive": True},
                "token": {"sensitive": True, "advanced": True},
                "encoding_aes_key": {"sensitive": True, "advanced": True},
                "webhook_port": {"advanced": True},
                "webhook_path": {"advanced": True},
            },
            defaults={
                "connection_mode": "webhook",
                "webhook_path": "/api/v1/channels/events/wecom",
                "webhook_port": 8000,
            },
            secret_paths=["secret", "token", "encoding_aes_key"],
        )


plugin = WeComChannelPlugin()
