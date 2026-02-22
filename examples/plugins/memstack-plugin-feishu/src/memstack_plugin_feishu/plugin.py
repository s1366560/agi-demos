"""Feishu channel plugin packaged as an external entry-point plugin."""

from __future__ import annotations

from src.infrastructure.adapters.secondary.channels.feishu.adapter import FeishuAdapter


class FeishuChannelPlugin:
    """Register Feishu channel adapter factory into plugin runtime."""

    name = "feishu-channel-plugin"

    def setup(self, api) -> None:
        """Register Feishu adapter factory under channel_type=feishu."""

        def _factory(context):
            return FeishuAdapter(context.channel_config)

        api.register_channel_adapter_factory("feishu", _factory)
