"""Feishu (Lark) channel adapter implementation."""

import asyncio
import json
import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional

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

    _WS_STARTUP_TIMEOUT_SECONDS = 8.0

    def __init__(self, config: ChannelConfig) -> None:
        self._config = config
        self._client: Optional[Any] = None
        self._ws_client: Optional[Any] = None
        self._ws_thread: Optional[threading.Thread] = None
        self._ws_loop: Optional[asyncio.AbstractEventLoop] = None
        self._ws_ready = threading.Event()
        self._ws_start_error: Optional[Exception] = None
        self._ws_stop_requested = False
        self._event_dispatcher: Optional[Any] = None
        self._connected = False
        self._message_handlers: List[MessageHandler] = []
        self._error_handlers: List[ErrorHandler] = []
        self._message_history: Dict[str, bool] = {}
        self._sender_name_cache: Dict[str, str] = {}
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

    def _build_rest_client(self) -> Any:
        """Build a lark_oapi REST Client with proper domain configuration."""
        from lark_oapi import Client, FEISHU_DOMAIN, LARK_DOMAIN

        domain = LARK_DOMAIN if self._config.domain == "lark" else FEISHU_DOMAIN
        return (
            Client.builder()
            .app_id(self._config.app_id or "")
            .app_secret(self._config.app_secret or "")
            .domain(domain)
            .build()
        )

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
                self._connected = True
            else:
                await self._connect_websocket()
                if not (self._ws_thread and self._ws_thread.is_alive() and self._ws_ready.is_set()):
                    raise RuntimeError("Feishu websocket failed to stay alive after startup")
                self._connected = True
            logger.info("[Feishu] Connected successfully")
        except Exception as e:
            logger.error(f"[Feishu] Connection failed: {e}")
            self._handle_error(e)
            raise

    async def _connect_websocket(self) -> None:
        """Connect via WebSocket."""
        try:
            from lark_oapi.event.dispatcher_handler import EventDispatcherHandlerBuilder

            # Build event handler
            event_handler = (
                EventDispatcherHandlerBuilder(
                    encrypt_key=self._config.encrypt_key or "",
                    verification_token=self._config.verification_token or "",
                )
                .register_p2_im_message_receive_v1(self._on_message_receive)
                .register_p2_im_message_recalled_v1(self._on_message_recalled)
                .register_p2_im_message_message_read_v1(self._on_message_read)
                .register_p2_im_chat_member_bot_added_v1(self._on_bot_added)
                .register_p2_im_chat_member_bot_deleted_v1(self._on_bot_deleted)
                .build()
            )

            # Determine domain based on config
            domain = "https://open.feishu.cn"
            if self._config.domain == "lark":
                domain = "https://open.larksuite.com"

            self._event_dispatcher = event_handler

            if self._ws_thread and self._ws_thread.is_alive():
                raise RuntimeError("Feishu websocket thread is already running")

            self._ws_stop_requested = False
            self._ws_start_error = None
            self._ws_ready.clear()

            # Start WebSocket client in dedicated thread because lark_oapi.ws.Client.start()
            # uses loop.run_until_complete() and cannot run inside FastAPI's running loop.
            self._ws_thread = threading.Thread(
                target=self._run_websocket,
                kwargs={
                    "event_handler": event_handler,
                    "domain": domain,
                },
                name=f"feishu-ws-{self._config.app_id}",
                daemon=True,
            )
            self._ws_thread.start()
            try:
                await self._wait_for_websocket_ready()
            except Exception:
                self._ws_stop_requested = True
                try:
                    await self.disconnect()
                except Exception as cleanup_error:
                    logger.warning(
                        "[Feishu] WebSocket startup cleanup failed: %s",
                        cleanup_error,
                    )
                raise

        except ImportError as e:
            raise ImportError(
                f"Feishu SDK not installed or import error: {e}. "
                "Install with: pip install lark_oapi"
            )

    async def _wait_for_websocket_ready(self) -> None:
        """Wait until websocket is connected or startup fails."""
        deadline = time.monotonic() + self._WS_STARTUP_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            if self._ws_start_error:
                raise RuntimeError(
                    f"Feishu websocket startup failed: {self._ws_start_error}"
                ) from self._ws_start_error

            if self._ws_ready.is_set():
                if self._ws_thread and not self._ws_thread.is_alive():
                    raise RuntimeError("Feishu websocket startup failed: thread exited")
                return

            if self._ws_thread and not self._ws_thread.is_alive():
                raise RuntimeError("Feishu websocket startup failed: thread exited")

            await asyncio.sleep(0.1)

        raise RuntimeError("Feishu websocket startup timeout")

    def _run_websocket(self, event_handler: Any, domain: str) -> None:
        """Run WebSocket client."""
        ws_loop: Optional[asyncio.AbstractEventLoop] = None
        try:
            from lark_oapi import LogLevel
            from lark_oapi.ws import Client as WSClient, client as ws_client_module

            ws_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(ws_loop)
            ws_client_module.loop = ws_loop
            self._ws_loop = ws_loop

            self._ws_client = WSClient(
                app_id=self._config.app_id,
                app_secret=self._config.app_secret,
                log_level=LogLevel.INFO,
                event_handler=event_handler,
                domain=domain,
            )

            try:
                ws_loop.run_until_complete(self._ws_client._connect())
            except Exception:
                ws_loop.run_until_complete(self._ws_client._disconnect())
                if getattr(self._ws_client, "_auto_reconnect", False):
                    ws_loop.run_until_complete(self._ws_client._reconnect())
                else:
                    raise

            self._ws_ready.set()
            ws_loop.create_task(self._ws_client._ping_loop())
            ws_loop.run_until_complete(ws_client_module._select())
        except Exception as e:
            self._ws_start_error = e
            self._ws_ready.clear()
            if self._ws_stop_requested:
                logger.info("[Feishu] WebSocket thread stopped")
            else:
                logger.error(f"[Feishu] WebSocket error: {e}")
                self._handle_error(e)
            self._connected = False
        finally:
            if ws_loop and not ws_loop.is_closed():
                ws_loop.close()
            self._ws_client = None
            self._ws_loop = None
            self._ws_ready.clear()

    def _on_message_receive(self, event: Any) -> None:
        """Handle incoming message event from WebSocket."""
        try:
            message_data = event.event.message if hasattr(event, "event") else {}
            sender_data = event.event.sender if hasattr(event, "event") else {}

            message_id = message_data.message_id if hasattr(message_data, "message_id") else None

            if not message_id:
                return

            # Deduplication
            if message_id in self._message_history:
                return
            self._message_history[message_id] = True

            # Limit history size
            if len(self._message_history) > 10000:
                oldest = next(iter(self._message_history))
                del self._message_history[oldest]

            # Convert to dict for parsing
            message_dict = {
                "message_id": message_id,
                "chat_id": getattr(message_data, "chat_id", ""),
                "chat_type": getattr(message_data, "chat_type", "p2p"),
                "content": getattr(message_data, "content", ""),
                "message_type": getattr(message_data, "message_type", "text"),
                "parent_id": getattr(message_data, "parent_id", None),
                "mentions": getattr(message_data, "mentions", []),
            }

            sender_dict = {
                "sender_id": getattr(sender_data, "sender_id", None),
                "sender_type": getattr(sender_data, "sender_type", ""),
            }

            # Parse message
            message = self._parse_message(message_dict, sender_dict)

            # Notify handlers
            for handler in self._message_handlers:
                try:
                    handler(message)
                except Exception as e:
                    logger.error(f"[Feishu] Message handler error: {e}")

        except Exception as e:
            logger.error(f"[Feishu] Error processing message: {e}")
            self._handle_error(e)

    def _on_message_recalled(self, event: Any) -> None:
        """Handle message recalled event."""
        logger.debug("[Feishu] Message recalled")

    def _on_message_read(self, event: Any) -> None:
        """Handle message read receipt event (no-op, suppresses SDK warning)."""
        logger.debug("[Feishu] Message read receipt received")

    def _on_bot_added(self, event: Any) -> None:
        """Handle bot added to chat event."""
        chat_id = getattr(event.event, "chat_id", "") if hasattr(event, "event") else ""
        logger.info(f"[Feishu] Bot added to chat: {chat_id}")

    def _on_bot_deleted(self, event: Any) -> None:
        """Handle bot removed from chat event."""
        chat_id = getattr(event.event, "chat_id", "") if hasattr(event, "event") else ""
        logger.info(f"[Feishu] Bot removed from chat: {chat_id}")

    async def _connect_webhook(self) -> None:
        """Connect via Webhook (HTTP server mode)."""
        logger.warning("[Feishu] Webhook mode not yet implemented")
        # TODO: Implement HTTP server for receiving webhooks

    def _parse_message(self, message_data: Dict[str, Any], sender_data: Dict[str, Any]) -> Message:
        """Parse Feishu message to unified format."""
        content = self._parse_content(
            message_data.get("content", ""), message_data.get("message_type", "text")
        )

        sender_id = self._extract_sender_open_id(sender_data.get("sender_id"))
        sender_type_raw = sender_data.get("sender_type", "user")
        sender_name = self._resolve_sender_name(sender_data, sender_id)
        chat_type_raw = message_data.get("chat_type", "p2p") or "p2p"
        try:
            chat_type = ChatType(chat_type_raw)
        except (TypeError, ValueError):
            logger.warning("[Feishu] Unknown chat_type '%s', fallback to p2p", chat_type_raw)
            chat_type = ChatType.P2P
        mentions = self._extract_mentions(message_data.get("mentions"))

        return Message(
            channel="feishu",
            chat_type=chat_type,
            chat_id=message_data.get("chat_id", ""),
            sender=SenderInfo(id=sender_id, name=sender_name),
            sender_type=sender_type_raw or "user",
            content=content,
            reply_to=message_data.get("parent_id"),
            thread_id=message_data.get("thread_id") or message_data.get("root_id"),
            mentions=mentions,
            raw_data={"event": {"message": message_data, "sender": sender_data}},
        )

    def _resolve_sender_name(
        self, sender_data: Dict[str, Any], sender_id: str
    ) -> str:
        """Resolve sender display name with cache."""
        if sender_id in self._sender_name_cache:
            return self._sender_name_cache[sender_id]
        # Try extracting name from sender data attributes
        name = ""
        sender_id_obj = sender_data.get("sender_id")
        if isinstance(sender_id_obj, dict):
            name = sender_id_obj.get("user_id", "")
        if not name:
            name = sender_data.get("sender_type", "")
        if sender_id and name:
            self._sender_name_cache[sender_id] = name
        return name

    def _extract_sender_open_id(self, sender_id_data: Any) -> str:
        """Extract sender open_id from SDK dict/object payloads."""
        if isinstance(sender_id_data, dict):
            open_id = sender_id_data.get("open_id")
            return open_id if isinstance(open_id, str) else ""
        if sender_id_data is None:
            return ""
        open_id = getattr(sender_id_data, "open_id", None)
        return open_id if isinstance(open_id, str) else ""

    def _extract_mention_open_id(self, mention_data: Any) -> str:
        """Extract mention open_id from SDK dict/object payloads."""
        if isinstance(mention_data, dict):
            mention_id = mention_data.get("id")
            if isinstance(mention_id, dict):
                mention_open_id = mention_id.get("open_id")
                return mention_open_id if isinstance(mention_open_id, str) else ""
            mention_open_id = mention_data.get("open_id")
            return mention_open_id if isinstance(mention_open_id, str) else ""

        mention_id = getattr(mention_data, "id", None)
        if isinstance(mention_id, dict):
            mention_open_id = mention_id.get("open_id")
            if isinstance(mention_open_id, str):
                return mention_open_id
        else:
            mention_open_id = getattr(mention_id, "open_id", None)
            if isinstance(mention_open_id, str):
                return mention_open_id

        mention_open_id = getattr(mention_data, "open_id", None)
        return mention_open_id if isinstance(mention_open_id, str) else ""

    def _extract_mentions(self, mentions_data: Any) -> List[str]:
        """Normalize mentions payload and return mentioned open_id list."""
        if not mentions_data:
            return []

        mentions_list: List[Any]
        if isinstance(mentions_data, list):
            mentions_list = mentions_data
        else:
            try:
                mentions_list = list(mentions_data)
            except TypeError:
                return []

        mention_open_ids: List[str] = []
        for mention_data in mentions_list:
            mention_open_id = self._extract_mention_open_id(mention_data)
            if mention_open_id:
                mention_open_ids.append(mention_open_id)
        return mention_open_ids

    def _parse_content(self, content_data: Any, message_type: str) -> MessageContent:
        """Parse message content based on type."""
        parsed: Dict[str, Any]
        if isinstance(content_data, dict):
            parsed = content_data
        elif isinstance(content_data, str):
            try:
                raw_parsed = json.loads(content_data) if content_data else {}
                parsed = raw_parsed if isinstance(raw_parsed, dict) else {"text": str(raw_parsed)}
            except json.JSONDecodeError:
                parsed = {"text": content_data}
        elif content_data is None:
            parsed = {}
        else:
            parsed = {"text": str(content_data)}

        if message_type == "text":
            text_value = parsed.get("text", "")
            text = (
                text_value
                if isinstance(text_value, str)
                else ("" if text_value is None else str(text_value))
            )
            return MessageContent(type=MessageType.TEXT, text=text)

        elif message_type == "image":
            return MessageContent(type=MessageType.IMAGE, image_key=parsed.get("image_key"))

        elif message_type == "file":
            return MessageContent(
                type=MessageType.FILE,
                file_key=parsed.get("file_key"),
                file_name=parsed.get("file_name"),
            )

        elif message_type == "post":
            # Rich text post
            text = self._parse_post_content(parsed)
            return MessageContent(type=MessageType.POST, text=text)

        else:
            return MessageContent(type=MessageType.TEXT, text=str(content_data or ""))

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
                        para_text += "[image]"
                    elif tag == "media":
                        para_text += "[media]"
                    elif tag in ("code_block", "code"):
                        lang = element.get("language", "")
                        code_text = element.get("text", "")
                        if lang:
                            para_text += f"\n```{lang}\n{code_text}\n```\n"
                        else:
                            para_text += f"`{code_text}`"
                    elif tag == "pre":
                        para_text += f"\n```\n{element.get('text', '')}\n```\n"
                    elif tag == "blockquote":
                        para_text += f"> {element.get('text', '')}"
                    elif tag == "mention":
                        para_text += f"@{element.get('name', element.get('key', ''))}"
                text_parts.append(para_text)

        return "\n".join(text_parts) or "[rich text message]"

    async def disconnect(self) -> None:
        """Disconnect from Feishu."""
        self._connected = False
        self._ws_stop_requested = True

        if self._ws_client and self._ws_loop and self._ws_loop.is_running():
            disconnect_coro = getattr(self._ws_client, "_disconnect", None)
            if callable(disconnect_coro):
                try:
                    future = asyncio.run_coroutine_threadsafe(disconnect_coro(), self._ws_loop)
                    future.result(timeout=3)
                except Exception:
                    pass
            try:
                self._ws_loop.call_soon_threadsafe(self._ws_loop.stop)
            except Exception:
                pass

        if self._ws_thread and self._ws_thread.is_alive():
            self._ws_thread.join(timeout=5)
            if self._ws_thread.is_alive():
                raise RuntimeError("Feishu websocket thread did not stop within timeout")

        self._ws_client = None
        self._ws_thread = None
        self._ws_loop = None
        self._ws_ready.clear()
        self._ws_start_error = None

        logger.info("[Feishu] Disconnected")

    async def send_message(
        self, to: str, content: MessageContent, reply_to: Optional[str] = None
    ) -> str:
        """Send a message using lark_oapi v2 SDK builder pattern."""
        if not self._connected:
            raise RuntimeError("Feishu adapter not connected")

        try:
            from lark_oapi.api.im.v1 import (
                CreateMessageRequest,
                CreateMessageRequestBody,
                ReplyMessageRequest,
                ReplyMessageRequestBody,
            )

            client = self._build_rest_client()

            # Determine message type and content JSON
            if content.type == MessageType.TEXT:
                msg_type = "text"
                msg_content = json.dumps({"text": content.text})
            elif content.type == MessageType.IMAGE:
                msg_type = "image"
                msg_content = json.dumps({"image_key": content.image_key})
            elif content.type == MessageType.FILE:
                msg_type = "file"
                msg_content = json.dumps(
                    {"file_key": content.file_key, "file_name": content.file_name}
                )
            elif content.type == MessageType.CARD:
                msg_type = "interactive"
                msg_content = json.dumps(content.card or {})
            else:
                msg_type = "text"
                msg_content = json.dumps({"text": str(content.text)})

            # Prefer threaded reply when reply_to is provided
            if reply_to:
                try:
                    request = (
                        ReplyMessageRequest.builder()
                        .message_id(reply_to)
                        .request_body(
                            ReplyMessageRequestBody.builder()
                            .msg_type(msg_type)
                            .content(msg_content)
                            .build()
                        )
                        .build()
                    )
                    response = client.im.v1.message.reply(request)
                    if response.success() and response.data and response.data.message_id:
                        return response.data.message_id
                    logger.warning(
                        "[Feishu] Reply API failed, fallback to create: "
                        f"code={response.code}, msg={response.msg}"
                    )
                except Exception as e:
                    logger.warning(f"[Feishu] Reply API error, fallback to create: {e}")

            # Fallback: create a new message
            receive_id_type = "open_id" if to.startswith("ou_") else "chat_id"
            request = (
                CreateMessageRequest.builder()
                .receive_id_type(receive_id_type)
                .request_body(
                    CreateMessageRequestBody.builder()
                    .receive_id(to)
                    .msg_type(msg_type)
                    .content(msg_content)
                    .build()
                )
                .build()
            )
            response = client.im.v1.message.create(request)

            if not response.success():
                raise RuntimeError(
                    f"Feishu send failed (code={response.code}): {response.msg or 'unknown error'}"
                )
            if not response.data or not response.data.message_id:
                raise RuntimeError(
                    f"No message_id in Feishu response (code={response.code}, msg={response.msg})"
                )
            return response.data.message_id

        except ImportError:
            raise ImportError("Feishu SDK not installed. Install with: pip install lark_oapi")

    async def send_text(self, to: str, text: str, reply_to: Optional[str] = None) -> str:
        """Send a text message."""
        content = MessageContent(type=MessageType.TEXT, text=text)
        return await self.send_message(to, content, reply_to)

    async def send_card(
        self,
        to: str,
        card: Dict[str, Any],
        reply_to: Optional[str] = None,
    ) -> str:
        """Send an interactive card message."""
        content = MessageContent(type=MessageType.CARD, card=card)
        return await self.send_message(to, content, reply_to)

    async def edit_message(self, message_id: str, content: MessageContent) -> bool:
        """Edit a previously sent message using lark_oapi v2 SDK."""
        try:
            from lark_oapi.api.im.v1 import UpdateMessageRequest, UpdateMessageRequestBody

            client = self._build_rest_client()
            if content.type == MessageType.TEXT:
                msg_type = "text"
                msg_content = json.dumps({"text": content.text})
            elif content.type == MessageType.CARD:
                msg_type = "interactive"
                msg_content = json.dumps(content.card or {})
            else:
                msg_type = "text"
                msg_content = json.dumps({"text": str(content.text or "")})

            request = (
                UpdateMessageRequest.builder()
                .message_id(message_id)
                .request_body(
                    UpdateMessageRequestBody.builder()
                    .msg_type(msg_type)
                    .content(msg_content)
                    .build()
                )
                .build()
            )
            response = client.im.v1.message.update(request)
            if not response.success():
                logger.warning(
                    f"[Feishu] Edit message failed: code={response.code}, msg={response.msg}"
                )
                return False
            return True
        except Exception as e:
            logger.error(f"[Feishu] Edit message error: {e}")
            return False

    async def delete_message(self, message_id: str) -> bool:
        """Delete/recall a message using lark_oapi v2 SDK."""
        try:
            from lark_oapi.api.im.v1 import DeleteMessageRequest

            client = self._build_rest_client()
            request = DeleteMessageRequest.builder().message_id(message_id).build()
            response = client.im.v1.message.delete(request)
            if not response.success():
                logger.warning(
                    f"[Feishu] Delete message failed: code={response.code}, msg={response.msg}"
                )
                return False
            return True
        except Exception as e:
            logger.error(f"[Feishu] Delete message error: {e}")
            return False

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
        """Get chat members using lark_oapi v2 SDK."""
        try:
            from lark_oapi.api.im.v1 import GetChatMembersRequest

            client = self._build_rest_client()
            request = (
                GetChatMembersRequest.builder()
                .chat_id(chat_id)
                .member_id_type("open_id")
                .build()
            )
            response = client.im.v1.chat_members.get(request)
            if not response.success() or not response.data:
                return []
            items = response.data.items or []
            return [
                SenderInfo(id=m.member_id or "", name=m.name)
                for m in items
                if m.member_id
            ]
        except Exception as e:
            logger.warning(f"[Feishu] Get chat members failed: {e}")
            return []

    async def get_user_info(self, user_id: str) -> Optional[SenderInfo]:
        """Get user info using lark_oapi v2 SDK."""
        try:
            from lark_oapi.api.contact.v3 import GetUserRequest

            client = self._build_rest_client()
            request = (
                GetUserRequest.builder()
                .user_id(user_id)
                .user_id_type("open_id")
                .build()
            )
            response = client.contact.v3.user.get(request)
            if not response.success() or not response.data or not response.data.user:
                return None
            user = response.data.user
            avatar_url = None
            if user.avatar:
                avatar_url = getattr(user.avatar, "avatar_origin", None)
            return SenderInfo(
                id=user.open_id or user_id,
                name=user.name,
                avatar=avatar_url,
            )
        except Exception as e:
            logger.warning(f"[Feishu] Get user info failed: {e}")
            return None

    async def health_check(self) -> bool:
        """Verify connection is alive by listing chats (page_size=1)."""
        try:
            from lark_oapi.api.im.v1 import ListChatRequest

            client = self._build_rest_client()
            request = ListChatRequest.builder().page_size(1).build()
            response = client.im.v1.chat.list(request)
            return response.success()
        except Exception as e:
            logger.warning(f"[Feishu] Health check failed: {e}")
            return False

    async def send_markdown_card(
        self,
        to: str,
        markdown: str,
        reply_to: Optional[str] = None,
    ) -> str:
        """Send markdown content as an interactive card."""
        card = {
            "config": {"wide_screen_mode": True},
            "elements": [{"tag": "markdown", "content": markdown}],
        }
        return await self.send_card(to, card, reply_to)

    async def patch_card(self, message_id: str, card_content: str) -> bool:
        """Update (patch) an existing interactive card message.

        Uses the lark_oapi v2 PatchMessageRequest to update card content
        in-place, enabling streaming "typing" effects for AI responses.

        Args:
            message_id: The message_id of the card to update.
            card_content: JSON string of the new card content.

        Returns:
            True on success, False on failure.
        """
        try:
            from lark_oapi.api.im.v1 import PatchMessageRequest, PatchMessageRequestBody

            client = self._build_rest_client()
            request = (
                PatchMessageRequest.builder()
                .message_id(message_id)
                .request_body(
                    PatchMessageRequestBody.builder()
                    .content(card_content)
                    .build()
                )
                .build()
            )
            response = client.im.v1.message.patch(request)
            if not response.success():
                logger.warning(
                    f"[Feishu] Patch card failed: code={response.code}, msg={response.msg}"
                )
                return False
            return True
        except Exception as e:
            logger.error(f"[Feishu] Patch card error: {e}")
            return False

    def _build_streaming_card(self, markdown: str, *, loading: bool = False) -> str:
        """Build a card JSON string for streaming updates.

        Args:
            markdown: The markdown content to display.
            loading: If True, append a loading indicator.

        Returns:
            JSON string of the interactive card.
        """
        content = markdown
        if loading:
            content += "\n\n_Generating..._"
        card = {
            "config": {"wide_screen_mode": True},
            "elements": [{"tag": "markdown", "content": content}],
        }
        return json.dumps(card)

    async def send_streaming_card(
        self,
        to: str,
        initial_text: str = "",
        reply_to: Optional[str] = None,
    ) -> Optional[str]:
        """Send an initial loading card for streaming updates.

        Returns the message_id for subsequent patch_card calls.
        """
        content = initial_text or "_Thinking..._"
        card = {
            "config": {"wide_screen_mode": True},
            "elements": [{"tag": "markdown", "content": content}],
        }
        try:
            return await self.send_card(to, card, reply_to)
        except Exception as e:
            logger.error(f"[Feishu] Send streaming card failed: {e}")
            return None
