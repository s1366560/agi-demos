"""Feishu channel plugin registration for plugin runtime."""

from __future__ import annotations

from src.infrastructure.agent.plugins.registry import ChannelAdapterBuildContext
from src.infrastructure.agent.plugins.runtime_api import PluginRuntimeApi

from .adapter import FeishuAdapter


class FeishuChannelPlugin:
    """Plugin that contributes Feishu channel adapter factory."""

    name = "feishu-channel-plugin"

    def setup(self, api: PluginRuntimeApi) -> None:
        """Register Feishu adapter factory under channel_type=feishu."""

        def _factory(context: ChannelAdapterBuildContext):
            return FeishuAdapter(context.channel_config)

        api.register_channel_type(
            "feishu",
            _factory,
            config_schema={
                "type": "object",
                "properties": {
                    "app_id": {"type": "string", "title": "App ID", "minLength": 1},
                    "app_secret": {"type": "string", "title": "App Secret", "minLength": 1},
                    "encrypt_key": {"type": "string", "title": "Encrypt Key"},
                    "verification_token": {"type": "string", "title": "Verification Token"},
                    "domain": {"type": "string", "title": "Domain", "default": "feishu"},
                    "connection_mode": {
                        "type": "string",
                        "title": "Connection Mode",
                        "enum": ["websocket", "webhook"],
                        "default": "websocket",
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
                "required": ["app_id", "app_secret"],
                "additionalProperties": False,
            },
            config_ui_hints={
                "app_secret": {"sensitive": True},
                "encrypt_key": {"sensitive": True, "advanced": True},
                "verification_token": {"sensitive": True, "advanced": True},
                "webhook_port": {"advanced": True},
                "webhook_path": {"advanced": True},
            },
            defaults={
                "domain": "feishu",
                "connection_mode": "websocket",
                "webhook_path": "/api/v1/channels/events/feishu",
                "webhook_port": 8000,
            },
            secret_paths=["app_secret", "encrypt_key", "verification_token"],
        )
