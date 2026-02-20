"""Feishu (Lark) channel adapter implementation."""

import asyncio
import json
import logging
from typing import Any, Callable, Dict, List, Optional, cast

from src.domain.model.channels.message import (
    Message,
    MessageContent,
    MessageType,
    SenderInfo,
    ChatType,
    ChannelConfig,
    ChannelAdapter,
)

logger = logging.getLogger(__name__)

MessageHandler = Callable[[Message], None]
ErrorHandler = Callable[[Exception], None]


class FeishuAdapter:
    """Feishu/Lark channel adapter.
    
    Implements the ChannelAdapter protocol for Feishu integration.
    Supports both WebSocket and Webhook connection modes.
    
    Usage:
        config = ChannelConfig(
            app_id="cli_xxx",
            app_secret="xxx",
            connection_mode="websocket"
        )
        adapter = FeishuAdapter(config)
        await adapter.connect()
        
        # Send message
        await adapter.send_text("oc_xxx", "Hello!")
        
        # Handle incoming messages
        adapter.on_message(lambda msg: print(msg.content.text))
    """
    
    def __init__(self, config: ChannelConfig) -> None:
        self._config = config
        self._client: Optional[Any] = None
        self._ws_client: Optional[Any] = None
        self._event_dispatcher: Optional[Any] = None
        self._connected = False
        self._message_handlers: List[MessageHandler] = []
        self._error_handlers: List[ErrorHandler] = []
        self._message_history: Dict[str, bool] = {}
        self._bot_open_id: Optional[str] = None
        
        self._validate_config()
    
    @property
    def id(self) -> str:
        return "feishu"
    
    @property
    def name(self) -> str:
        return "Feishu"
    
    @property
    def connected(self) -> bool:
        return self._connected
    
    def _validate_config(self) -> None:
        """Validate configuration."""
        if not self._config.app_id:
            raise ValueError("Feishu adapter: app_id is required")
        if not self._config.app_secret:
            raise ValueError("Feishu adapter: app_secret is required")
    
    async def connect(self) -> None:
        """Connect to Feishu."""
        if self._connected:
            logger.info("[Feishu] Already connected")
            return
        
        try:
            mode = self._config.connection_mode
            if mode == "webhook":
                await self._connect_webhook()
            else:
                await self._connect_websocket()
            
            self._connected = True
            logger.info("[Feishu] Connected successfully")
        except Exception as e:
            logger.error(f"[Feishu] Connection failed: {e}")
            self._handle_error(e)
            raise
    
    async def _connect_websocket(self) -> None:
        """Connect via WebSocket."""
        try:
            from larksuiteoapi import WSClient, EventDispatcher, LoggerLevel
            
            self._ws_client = WSClient(
                app_id=self._config.app_id,
                app_secret=self._config.app_secret,
                logger_level=LoggerLevel.INFO,
            )
            
            self._event_dispatcher = EventDispatcher(
                encrypt_key=self._config.encrypt_key,
                verification_token=self._config.verification_token,
            )
            
            self._register_event_handlers()
            
            # Start WebSocket in background
            asyncio.create_task(self._run_websocket())
            
        except ImportError:
            raise ImportError(
                "Feishu SDK not installed. "
                "Install with: pip install larksuiteoapi"
            )
    
    async def _run_websocket(self) -> None:
        """Run WebSocket client."""
        try:
            self._ws_client.start({"eventDispatcher": self._event_dispatcher})
        except Exception as e:
            logger.error(f"[Feishu] WebSocket error: {e}")
            self._handle_error(e)
    
    async def _connect_webhook(self) -> None:
        """Connect via Webhook (HTTP server mode)."""
        logger.warning("[Feishu] Webhook mode not yet implemented")
        # TODO: Implement HTTP server for receiving webhooks
    
    def _register_event_handlers(self) -> None:
        """Register Feishu event handlers."""
        if not self._event_dispatcher:
            return
        
        @self._event_dispatcher.register("im.message.receive_v1")
        def on_message(data: Dict[str, Any]) -> None:
            self._process_message_event(data)
        
        @self._event_dispatcher.register("im.message.updated_v1")
        def on_message_updated(data: Dict[str, Any]) -> None:
            logger.debug(f"[Feishu] Message edited: {data.get('message', {}).get('message_id')}")
        
        @self._event_dispatcher.register("im.message.deleted_v1")
        def on_message_deleted(data: Dict[str, Any]) -> None:
            logger.debug(f"[Feishu] Message deleted: {data.get('message_id')}")
        
        @self._event_dispatcher.register("im.chat.member.bot.added_v1")
        def on_bot_added(data: Dict[str, Any]) -> None:
            logger.info(f"[Feishu] Bot added to chat: {data.get('chat_id')}")
        
        @self._event_dispatcher.register("im.chat.member.bot.deleted_v1")
        def on_bot_deleted(data: Dict[str, Any]) -> None:
            logger.info(f"[Feishu] Bot removed from chat: {data.get('chat_id')}")
    
    def _process_message_event(self, data: Dict[str, Any]) -> None:
        """Process incoming message event."""
        try:
            event = data.get("event", {})
            message_data = event.get("message", {})
            sender_data = event.get("sender", {})
            
            message_id = message_data.get("message_id")
            
            # Deduplication
            if message_id in self._message_history:
                return
            self._message_history[message_id] = True
            
            # Limit history size
            if len(self._message_history) > 10000:
                oldest = next(iter(self._message_history))
                del self._message_history[oldest]
            
            # Parse message
            message = self._parse_message(message_data, sender_data)
            
            # Notify handlers
            for handler in self._message_handlers:
                try:
                    handler(message)
                except Exception as e:
                    logger.error(f"[Feishu] Message handler error: {e}")
        
        except Exception as e:
            logger.error(f"[Feishu] Error processing message: {e}")
            self._handle_error(e)
    
    def _parse_message(
        self,
        message_data: Dict[str, Any],
        sender_data: Dict[str, Any]
    ) -> Message:
        """Parse Feishu message to unified format."""
        content = self._parse_content(
            message_data.get("content", ""),
            message_data.get("message_type", "text")
        )
        
        sender_id = sender_data.get("sender_id", {}).get("open_id", "")
        sender_name = sender_data.get("sender_type", "")
        
        return Message(
            channel="feishu",
            chat_type=ChatType(message_data.get("chat_type", "p2p")),
            chat_id=message_data.get("chat_id", ""),
            sender=SenderInfo(id=sender_id, name=sender_name),
            content=content,
            reply_to=message_data.get("parent_id"),
            mentions=[m.get("id", {}).get("open_id", "") 
                     for m in message_data.get("mentions", [])],
            raw_data={"event": {"message": message_data, "sender": sender_data}}
        )
    
    def _parse_content(self, content_str: str, message_type: str) -> MessageContent:
        """Parse message content based on type."""
        try:
            parsed = json.loads(content_str) if content_str else {}
        except json.JSONDecodeError:
            parsed = {"text": content_str}
        
        if message_type == "text":
            return MessageContent(type=MessageType.TEXT, text=parsed.get("text", ""))
        
        elif message_type == "image":
            return MessageContent(
                type=MessageType.IMAGE,
                image_key=parsed.get("image_key")
            )
        
        elif message_type == "file":
            return MessageContent(
                type=MessageType.FILE,
                file_key=parsed.get("file_key"),
                file_name=parsed.get("file_name")
            )
        
        elif message_type == "post":
            # Rich text post
            text = self._parse_post_content(parsed)
            return MessageContent(type=MessageType.POST, text=text)
        
        else:
            return MessageContent(type=MessageType.TEXT, text=str(content_str))
    
    def _parse_post_content(self, content: Dict[str, Any]) -> str:
        """Parse rich text post content."""
        title = content.get("title", "")
        content_blocks = content.get("content", [])
        
        text_parts = [title] if title else []
        
        for paragraph in content_blocks:
            if isinstance(paragraph, list):
                para_text = ""
                for element in paragraph:
                    tag = element.get("tag", "")
                    if tag == "text":
                        para_text += element.get("text", "")
                    elif tag == "a":
                        para_text += element.get("text", element.get("href", ""))
                    elif tag == "at":
                        para_text += f"@{element.get('user_name', '')}"
                    elif tag == "img":
                        para_text += "[图片]"
                text_parts.append(para_text)
        
        return "\n".join(text_parts) or "[富文本消息]"
    
    async def disconnect(self) -> None:
        """Disconnect from Feishu."""
        self._connected = False
        
        if self._ws_client:
            # WebSocket client doesn't have explicit close in this SDK
            self._ws_client = None
        
        logger.info("[Feishu] Disconnected")
    
    async def send_message(
        self,
        to: str,
        content: MessageContent,
        reply_to: Optional[str] = None
    ) -> str:
        """Send a message."""
        if not self._connected:
            raise RuntimeError("Feishu adapter not connected")
        
        try:
            from larksuiteoapi import Client
            
            client = Client(
                app_id=self._config.app_id,
                app_secret=self._config.app_secret,
            )
            
            # Determine recipient type
            receive_id_type = "open_id" if to.startswith("ou_") else "chat_id"
            
            # Build message payload
            if content.type == MessageType.TEXT:
                msg_type = "text"
                msg_content = json.dumps({"text": content.text})
            elif content.type == MessageType.IMAGE:
                msg_type = "image"
                msg_content = json.dumps({"image_key": content.image_key})
            elif content.type == MessageType.FILE:
                msg_type = "file"
                msg_content = json.dumps({
                    "file_key": content.file_key,
                    "file_name": content.file_name
                })
            else:
                msg_type = "text"
                msg_content = json.dumps({"text": str(content.text)})
            
            # Send via API
            response = client.im.message.create(
                {"receive_id_type": receive_id_type},
                {
                    "receive_id": to,
                    "msg_type": msg_type,
                    "content": msg_content,
                }
            )
            
            message_id = response.get("data", {}).get("message_id")
            if not message_id:
                raise RuntimeError("No message_id in response")
            
            return message_id
        
        except ImportError:
            raise ImportError(
                "Feishu SDK not installed. "
                "Install with: pip install larksuiteoapi"
            )
    
    async def send_text(self, to: str, text: str, reply_to: Optional[str] = None) -> str:
        """Send a text message."""
        content = MessageContent(type=MessageType.TEXT, text=text)
        return await self.send_message(to, content, reply_to)
    
    def on_message(self, handler: MessageHandler) -> Callable[[], None]:
        """Register message handler."""
        self._message_handlers.append(handler)
        
        def unregister():
            self._message_handlers.remove(handler)
        
        return unregister
    
    def on_error(self, handler: ErrorHandler) -> Callable[[], None]:
        """Register error handler."""
        self._error_handlers.append(handler)
        
        def unregister():
            self._error_handlers.remove(handler)
        
        return unregister
    
    def _handle_error(self, error: Exception) -> None:
        """Handle errors."""
        for handler in self._error_handlers:
            try:
                handler(error)
            except Exception:
                pass
    
    async def get_chat_members(self, chat_id: str) -> List[SenderInfo]:
        """Get chat members."""
        try:
            from larksuiteoapi import Client
            
            client = Client(
                app_id=self._config.app_id,
                app_secret=self._config.app_secret,
            )
            
            response = client.im.chatMembers.get(
                {"chat_id": chat_id},
                {"member_id_type": "open_id"}
            )
            
            members = response.get("data", {}).get("items", [])
            return [
                SenderInfo(id=m.get("member_id"), name=m.get("name"))
                for m in members
            ]
        
        except ImportError:
            raise ImportError("Feishu SDK not installed")
    
    async def get_user_info(self, user_id: str) -> Optional[SenderInfo]:
        """Get user info."""
        try:
            from larksuiteoapi import Client
            
            client = Client(
                app_id=self._config.app_id,
                app_secret=self._config.app_secret,
            )
            
            response = client.contact.user.get(
                {"user_id": user_id},
                {"user_id_type": "open_id"}
            )
            
            user = response.get("data", {}).get("user", {})
            return SenderInfo(
                id=user.get("open_id", user_id),
                name=user.get("name"),
                avatar=user.get("avatar", {}).get("avatar_origin")
            )
        
        except ImportError:
            raise ImportError("Feishu SDK not installed")


# Make FeishuAdapter implement ChannelAdapter protocol
if hasattr(FeishuAdapter, '__init__'):
    pass  # Class is complete
