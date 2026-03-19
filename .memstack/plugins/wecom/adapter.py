"""WeCom (企业微信) channel adapter implementation."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
import xml.etree.ElementTree as ET
from base64 import b64decode, b64encode
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast
from urllib.parse import parse_qs, quote, urljoin

import aiohttp

from src.domain.model.channels.message import (
    ChannelConfig,
    ChatType,
    Message,
    MessageContent,
    MessageType,
    SenderInfo,
)

logger = logging.getLogger(__name__)


MessageHandler = Callable[[Message], None]
ErrorHandler = Callable[[Exception], None]


class WeComAdapter:
    """WeCom channel adapter.

    Implements the ChannelAdapter protocol for WeCom integration.
    Supports Webhook connection mode only.

    Usage:
        config = ChannelConfig(
            corp_id="wwxxx",
            agent_id="100000",
            secret="xxx",
            connection_mode="webhook"
        )
        adapter = WeComAdapter(config)
        await adapter.connect()

        # Send message
        await adapter.send_text("userid", "Hello!")

        # Handle incoming messages
        adapter.on_message(lambda msg: print(msg.content.text))
    """

    _ACCESS_TOKEN_EXPIRES_SECONDS = 7200  # 2 hours

    def __init__(self, config: ChannelConfig) -> None:
        self._config = config
        self._connected = False
        self._message_handlers: list[MessageHandler] = []
        self._error_handlers: list[ErrorHandler] = []
        self._access_token: str | None = None
        self._access_token_expires_at: float = 0
        self._message_history: dict[str, bool] = {}
        self._sender_name_cache: dict[str, str] = {}

        self._validate_config()

    @property
    def id(self) -> str:
        return "wecom"

    @property
    def name(self) -> str:
        return "WeCom"

    @property
    def connected(self) -> bool:
        return self._connected

    def _validate_config(self) -> None:
        """Validate configuration."""
        if not self._config.corp_id:
            raise ValueError("WeCom adapter: corp_id is required")
        if not self._config.agent_id:
            raise ValueError("WeCom adapter: agent_id is required")
        if not self._config.secret:
            raise ValueError("WeCom adapter: secret is required")

    async def connect(self) -> None:
        """Connect to WeCom."""
        if self._connected:
            logger.info("[WeCom] Already connected")
            return

        mode = self._config.connection_mode
        if mode == "webhook":
            await self._connect_webhook()
            self._connected = True
            logger.info("[WeCom] Connected successfully")
        else:
            raise ValueError(f"WeCom adapter: unsupported connection mode: {mode}")

    async def _connect_webhook(self) -> None:
        """Start webhook server."""
        from .webhook import WeComWebhookHandler

        port = self._config.webhook_port or 8000
        path = self._config.webhook_path or "/api/v1/channels/events/wecom"

        handler = WeComWebhookHandler(
            token=self._config.token,
            encoding_aes_key=self._config.encoding_aes_key,
            corp_id=self._config.corp_id,
            agent_id=self._config.agent_id,
        )

        handler.register_handler("event", self._on_webhook_event)
        handler.register_handler("message", self._on_webhook_event)

        try:
            import uvicorn
            from fastapi import FastAPI, Request as FastAPIRequest

            app = FastAPI(title="WeCom Webhook Receiver")

            @app.get(path)
            async def _webhook_verify(request: FastAPIRequest) -> str:
                return handler.verify_request(request)

            @app.post(path)
            async def _webhook_endpoint(request: FastAPIRequest) -> str:
                return await handler.handle_request(request)

            config = uvicorn.Config(
                app,
                host="0.0.0.0",
                port=port,
                log_level="warning",
            )
            server = uvicorn.Server(config)

            task = asyncio.create_task(server.serve())
            task.add_done_callback(lambda t: logger.info("[WeCom] Webhook server stopped"))
            logger.info(
                "[WeCom] Webhook server started on port %d at path %s",
                port,
                path,
            )
        except ImportError:
            logger.error(
                "[WeCom] uvicorn is required for webhook mode. "
                "Install it with: pip install uvicorn"
            )
            raise

    def _on_webhook_event(self, event_data: dict[str, Any]) -> None:
        """Handle incoming webhook event."""
        try:
            msg_type = event_data.get("msg_type", "text")
            msg_id = event_data.get("msg_id")
            if not msg_id:
                logger.warning("[WeCom] Webhook event has no msg_id, skipping")
                return

            # Deduplication
            if msg_id in self._message_history:
                logger.debug(f"[WeCom] Duplicate message {msg_id}, skipping")
                return
            self._message_history[msg_id] = True
            if len(self._message_history) > 10000:
                oldest = next(iter(self._message_history))
                del self._message_history[oldest]

            # Parse message
            message = self._parse_message(event_data)
            for handler in self._message_handlers:
                try:
                    handler(message)
                except Exception as exc:
                    logger.error("[WeCom] Message handler error: %s", exc)
        except Exception as exc:
            logger.error("[WeCom] Error processing webhook event: %s", exc)
            self._handle_error(exc)

    def _parse_message(self, msg_data: dict[str, Any]) -> Message:
        """Parse WeCom message to unified format."""
        msg_type = msg_data.get("msg_type", "text")
        content = msg_data.get("content", "")
        from_user = msg_data.get("from_user_name", msg_data.get("from_user_name", ""))
        user_id = msg_data.get("from_user_name", "")

        # Resolve sender name
        sender_name = self._resolve_sender_name(user_id, from_user)

        # Parse content based on message type
        parsed_content = self._parse_content(content, msg_type)
        if parsed_content is not None:
            message_content = parsed_content
        else:
            message_content = MessageContent(type=MessageType.TEXT, text=str(content))

        # Determine chat type
        agent_id = msg_data.get("agent_id", "")
        chat_type = ChatType.P2P if agent_id else ChatType.GROUP

        return Message(
            channel="wecom",
            chat_type=chat_type,
            chat_id=msg_data.get("to_user_name", ""),
            sender=SenderInfo(id=user_id, name=sender_name),
            sender_type="user",
            content=message_content,
            reply_to=msg_data.get("root_id"),
            thread_id=msg_data.get("root_id"),
            mentions=[],
            raw_data={"event": msg_data},
        )

    def _resolve_sender_name(self, user_id: str, fallback_name: str) -> str:
        """Resolve sender display name with cache."""
        if user_id in self._sender_name_cache:
            return self._sender_name_cache[user_id]
        name = fallback_name or user_id
        if user_id and name:
            self._sender_name_cache[user_id] = name
        return name

    def _parse_content(self, content: Any, msg_type: str) -> MessageContent | None:
        """Parse message content based on type."""
        if msg_type == "text":
            text = content if isinstance(content, str) else str(content or "")
            return MessageContent(type=MessageType.TEXT, text=text)
        elif msg_type == "image":
            # Content is pic url, need to fetch separately
            return MessageContent(type=MessageType.IMAGE, image_key=str(content), text="[图片消息]")
        elif msg_type == "voice":
            # Content contains media_id
            return MessageContent(type=MessageType.AUDIO, file_key=str(content), text="[语音消息]")
        elif msg_type == "video":
            return MessageContent(type=MessageType.VIDEO, file_key=str(content), text="[视频消息]")
        elif msg_type == "file":
            return MessageContent(type=MessageType.FILE, file_key=str(content), text="[文件消息]")
        elif msg_type == "textcard":
            # Rich text card
            try:
                if isinstance(content, str):
                    data = json.loads(content)
                else:
                    data = content
                title = data.get("title", "")
                description = data.get("description", "")
                url = data.get("url", "")
                return MessageContent(
                    type=MessageType.TEXT,
                    text=f"{title}\n{description}\n{url}",
                )
            except (json.JSONDecodeError, TypeError):
                return MessageContent(type=MessageType.TEXT, text=str(content))
        return None

    async def disconnect(self) -> None:
        """Disconnect from WeCom."""
        self._connected = False
        self._access_token = None
        logger.info("[WeCom] Disconnected")

    async def _get_access_token(self) -> str:
        """Get or refresh access token."""
        now = time.time()
        if self._access_token and now < self._access_token_expires_at - 300:
            return self._access_token

        url = (
            f"https://qyapi.weixin.qq.com/cgi-bin/gettoken?"
            f"corpid={self._config.corp_id}&corpsecret={self._config.secret}"
        )

        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                data = await resp.json()
                if data.get("errcode") != 0:
                    raise RuntimeError(
                        f"WeCom gettoken failed: {data.get('errmsg', 'unknown error')}"
                    )
                self._access_token = data["access_token"]
                self._access_token_expires_at = now + self._ACCESS_TOKEN_EXPIRES_SECONDS
                return self._access_token

    async def send_message(
        self, to: str, content: MessageContent, reply_to: str | None = None
    ) -> str:
        """Send a message using WeCom API."""
        if not self._connected:
            raise RuntimeError("WeCom adapter not connected")

        token = await self._get_access_token()
        url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={token}"

        # Build message payload based on content type
        if content.type == MessageType.TEXT:
            msg_data = {
                "touser": to,
                "msgtype": "text",
                "agentid": self._config.agent_id,
                "text": {"content": content.text},
            }
        elif content.type == MessageType.IMAGE:
            msg_data = {
                "touser": to,
                "msgtype": "image",
                "agentid": self._config.agent_id,
                "image": {"media_id": content.image_key},
            }
        elif content.type == MessageType.FILE:
            msg_data = {
                "touser": to,
                "msgtype": "file",
                "agentid": self._config.agent_id,
                "file": {"media_id": content.file_key},
            }
        elif content.type == MessageType.CARD:
            # Interactive card
            msg_data = {
                "touser": to,
                "msgtype": "textcard",
                "agentid": self._config.agent_id,
                "textcard": content.card or {"title": "消息", "description": "Card message"},
            }
        else:
            msg_data = {
                "touser": to,
                "msgtype": "text",
                "agentid": self._config.agent_id,
                "text": {"content": str(content.text)},
            }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=msg_data) as resp:
                data = await resp.json()
                if data.get("errcode") != 0:
                    raise RuntimeError(
                        f"WeCom send failed: {data.get('errmsg', 'unknown error')}"
                    )
                return str(data.get("msgid", ""))

    async def send_text(self, to: str, text: str, reply_to: str | None = None) -> str:
        """Send a text message."""
        content = MessageContent(type=MessageType.TEXT, text=text)
        return await self.send_message(to, content, reply_to)

    async def send_card(
        self,
        to: str,
        card: dict[str, Any],
        reply_to: str | None = None,
    ) -> str:
        """Send an interactive card message."""
        content = MessageContent(type=MessageType.CARD, card=card)
        return await self.send_message(to, content, reply_to)

    async def send_post(
        self,
        to: str,
        title: str,
        content: list[list[dict[str, Any]]],
        reply_to: str | None = None,
    ) -> str:
        """Send a rich text (post) message."""
        # WeCom doesn't have native post message, send as text
        text = f"{title}\n" + "\n".join(
            "".join(elem.get("text", "") for elem in para)
            for para in content
        )
        return await self.send_text(to, text)

    def on_message(self, handler: MessageHandler) -> None:
        """Register a message handler."""
        self._message_handlers.append(handler)

    def on_error(self, handler: ErrorHandler) -> None:
        """Register an error handler."""
        self._error_handlers.append(handler)

    def _handle_error(self, error: Exception) -> None:
        """Handle error by notifying error handlers."""
        for handler in self._error_handlers:
            try:
                handler(error)
            except Exception as e:
                logger.error("[WeCom] Error handler error: %s", e)

    # === Media operations ===

    async def upload_media(self, file_path: str, media_type: str = "image") -> str:
        """Upload media file and return media_id."""
        token = await self._get_access_token()
        url = (
            f"https://qyapi.weixin.qq.com/cgi-bin/media/upload?"
            f"access_token={token}&type={media_type}"
        )

        form = aiohttp.FormData()
        form.add_field(
            "media",
            open(file_path, "rb"),
            filename=file_path.split("/")[-1],
            content_type="application/octet-stream",
        )

        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=form) as resp:
                data = await resp.json()
                if data.get("errcode") != 0:
                    raise RuntimeError(
                        f"WeCom upload failed: {data.get('errmsg', 'unknown error')}"
                    )
                return data["media_id"]

    async def get_media(self, media_id: str) -> bytes:
        """Download media file content."""
        token = await self._get_access_token()
        url = (
            f"https://qyapi.weixin.qq.com/cgi-bin/media/get?"
            f"access_token={token}&media_id={media_id}"
        )

        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.content_type == "application/json":
                    data = await resp.json()
                    raise RuntimeError(
                        f"WeCom get media failed: {data.get('errmsg', 'unknown error')}"
                    )
                return await resp.read()
