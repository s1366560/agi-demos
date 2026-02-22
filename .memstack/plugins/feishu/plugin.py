"""Local Feishu plugin entry for .memstack/plugins discovery."""

from __future__ import annotations

from src.infrastructure.adapters.secondary.channels.feishu.plugin import FeishuChannelPlugin

# Discovery loader resolves `plugin` first.
plugin = FeishuChannelPlugin()
