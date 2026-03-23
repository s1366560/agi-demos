"""DingTalk channel plugin template.

Registers the ``dingtalk`` channel type with the MemStack plugin runtime.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from src.domain.model.channels.message import (
    ChannelConfig,
    Message,
    MessageContent,
)
from src.infrastructure.agent.plugins.registry import ChannelAdapterBuildContext
from src.infrastructure.agent.plugins.runtime_api import PluginRuntimeApi

logger = logging.getLogger(__name__)

MessageHandler = Callable[[Message], None]
ErrorHandler = Callable[[Exception], None]


class DingTalkAdapter:
    """DingTalk channel adapter (stub).

    Implements the ChannelAdapter protocol for DingTalk.
    """

    def __init__(self, config: ChannelConfig) -> None:
        self._config = config
        self._connected = False
        self._message_handlers: list[MessageHandler] = []
        self._error_handlers: list[ErrorHandler] = []

    @property
    def id(self) -> str:
        return "dingtalk"

    @property
    def name(self) -> str:
        return "DingTalk"

    @property
    def connected(self) -> bool:
        return self._connected

    async def connect(self) -> None:
        """Connect to DingTalk webhook."""
        logger.info("[DingTalk] Connecting via webhook (stub)...")
        self._connected = True
        logger.info("[DingTalk] Connected successfully")

    async def disconnect(self) -> None:
        """Disconnect from DingTalk."""
        self._connected = False
        logger.info("[DingTalk] Disconnected")

    def on_message(self, handler: MessageHandler) -> None:
        """Register message handler."""
        self._message_handlers.append(handler)

    def on_error(self, handler: ErrorHandler) -> None:
        """Register error handler."""
        self._error_handlers.append(handler)

    async def send_message(
        self, to: str, content: MessageContent, reply_to: str | None = None
    ) -> str:
        """Send a message to DingTalk."""
        logger.info(f"[DingTalk] send_message stub called -- to={to} type={content.type}")
        return "msg_stub_id"

    async def send_text(self, to: str, text: str, reply_to: str | None = None) -> str:
        """Send a text message."""
        logger.info(f"[DingTalk] send_text stub called -- to={to}")
        return "msg_stub_id"

    async def send_card(
        self,
        to: str,
        card: dict[str, Any],
        reply_to: str | None = None,
    ) -> str:
        """Send an interactive card message."""
        logger.info(f"[DingTalk] send_card stub called -- to={to}")
        return "msg_stub_id"

    def verify_webhook(self, signature: str, timestamp: str, body: str) -> bool:
        """Verify DingTalk webhook signature.

        TODO: Implement actual HMAC-SHA256 signature verification using sign_token.
        """
        logger.info("[DingTalk] Verifying webhook signature")
        return True

    def handle_webhook_event(self, event_data: dict[str, Any]) -> None:
        """Handle incoming webhook event.

        TODO: Parse event_data into Message object and notify handlers.
        """
        logger.info("[DingTalk] Handling webhook event")


class DingTalkChannelPlugin:
    name = "dingtalk-channel-plugin"

    def setup(self, api: PluginRuntimeApi) -> None:
        def _factory(context: ChannelAdapterBuildContext) -> object:
            return DingTalkAdapter(context.channel_config)

        api.register_channel_type(
            "dingtalk",
            _factory,
            config_schema={
                "type": "object",
                "properties": {
                    "app_key": {"type": "string", "title": "App Key", "minLength": 1},
                    "app_secret": {"type": "string", "title": "App Secret", "minLength": 1},
                    "agent_id": {"type": "string", "title": "Agent ID", "minLength": 1},
                    "webhook_url": {"type": "string", "title": "Webhook URL"},
                    "sign_token": {"type": "string", "title": "Sign Token"},
                },
                "required": ["app_key", "app_secret", "agent_id"],
                "additionalProperties": False,
            },
            config_ui_hints={
                "app_secret": {"sensitive": True},
                "sign_token": {"sensitive": True, "advanced": True},
                "webhook_url": {"advanced": True},
            },
            defaults={
                "webhook_url": "/api/v1/channels/events/dingtalk",
            },
            secret_paths=["app_secret", "sign_token"],
        )


plugin = DingTalkChannelPlugin()
