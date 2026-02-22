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
                .register_p2_im_chat_access_event_bot_p2p_chat_entered_v1(
                    self._on_bot_p2p_chat_entered
                )
                .register_p2_card_action_trigger(self._on_card_action)
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
            # DEBUG: Log raw event
            logger.info(f"[FeishuAdapter] Raw event received - event_type={type(event).__name__}")

            message_data = event.event.message if hasattr(event, "event") else {}
            sender_data = event.event.sender if hasattr(event, "event") else {}

            message_id = message_data.message_id if hasattr(message_data, "message_id") else None

            if not message_id:
                logger.warning("[FeishuAdapter] No message_id in event, skipping")
                return

            # DEBUG: Log message details
            message_type = getattr(message_data, "message_type", "unknown")
            logger.info(
                f"[FeishuAdapter] Message received - "
                f"id={message_id}, type={message_type}, "
                f"chat_id={getattr(message_data, 'chat_id', 'N/A')}"
            )

            # Deduplication
            if message_id in self._message_history:
                logger.debug(f"[FeishuAdapter] Duplicate message {message_id}, skipping")
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

    def _on_bot_p2p_chat_entered(self, event: Any) -> None:
        """Handle user entering bot P2P chat (no-op, suppresses SDK warning)."""
        logger.debug("[Feishu] User entered bot P2P chat")

    def _on_card_action(self, event: Any) -> Any:
        """Handle interactive card button click (card.action.trigger callback).

        The lark_oapi SDK deserializes the callback into typed objects:
        - ``event.event``: P2CardActionTriggerData
        - ``event.event.action``: CallBackAction (value, tag, name, ...)
        - ``event.event.operator``: CallBackOperator (open_id, user_id, ...)
        - ``event.event.context``: CallBackContext (open_message_id, open_chat_id)

        Response must be returned within 3 seconds. We return both a toast
        and an updated card (with buttons replaced by confirmation text).
        """
        from lark_oapi.event.callback.model.p2_card_action_trigger import (
            P2CardActionTriggerResponse,
        )

        try:
            event_data = event.event
            if event_data is None:
                logger.warning("[Feishu] Card action event has no event data")
                return P2CardActionTriggerResponse()

            # Extract action value — SDK parses it as a typed CallBackAction object
            action = event_data.action
            value = action.value if action and action.value else {}

            hitl_request_id = value.get("hitl_request_id") if isinstance(value, dict) else None
            if not hitl_request_id:
                logger.debug("[Feishu] Card action without hitl_request_id, ignoring")
                return P2CardActionTriggerResponse()

            response_data_raw = (
                value.get("response_data", "{}") if isinstance(value, dict) else "{}"
            )
            if isinstance(response_data_raw, str):
                try:
                    response_data = json.loads(response_data_raw)
                except (json.JSONDecodeError, TypeError):
                    response_data = {"answer": response_data_raw}
            else:
                response_data = response_data_raw if isinstance(response_data_raw, dict) else {}

            # For form submissions, form_value contains input field values
            form_value = getattr(action, "form_value", None)
            if form_value and isinstance(form_value, dict):
                response_data = {"values": form_value}

            hitl_type = (
                value.get("hitl_type", "clarification")
                if isinstance(value, dict)
                else "clarification"
            )
            tenant_id = value.get("tenant_id", "") if isinstance(value, dict) else ""
            project_id = value.get("project_id", "") if isinstance(value, dict) else ""

            # Extract operator info
            operator = event_data.operator
            user_id = operator.open_id if operator and operator.open_id else ""

            # Extract context info (message_id, chat_id)
            context = event_data.context
            message_id = context.open_message_id if context else ""
            chat_id = context.open_chat_id if context else ""

            logger.info(
                f"[Feishu] Card action: request_id={hitl_request_id}, "
                f"hitl_type={hitl_type}, user={user_id}, "
                f"message_id={message_id}, response={response_data}"
            )

            # Schedule async HITL response on the event loop
            import asyncio

            from src.application.services.channels.hitl_responder import (
                HITLChannelResponder,
            )

            responder = HITLChannelResponder()
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(
                    responder.respond(
                        request_id=hitl_request_id,
                        hitl_type=hitl_type,
                        response_data=response_data,
                        tenant_id=tenant_id,
                        project_id=project_id,
                        responder_id=user_id,
                    )
                )
            except RuntimeError:
                logger.warning("[Feishu] No running event loop for card action")

            # Build updated card showing "response submitted" state
            selected_label = self._extract_selected_label(response_data)
            responded_card = self._build_responded_card(
                hitl_type=hitl_type,
                selected_label=selected_label,
            )

            # Return toast + updated card per Feishu callback docs
            resp = {
                "toast": {
                    "type": "success",
                    "content": "Response submitted",
                    "i18n": {
                        "zh_cn": "Response submitted",
                        "en_us": "Response submitted",
                    },
                },
            }
            if responded_card:
                resp["card"] = {
                    "type": "raw",
                    "data": responded_card,
                }
            return P2CardActionTriggerResponse(resp)

        except Exception as e:
            logger.error(f"[Feishu] Card action handling failed: {e}", exc_info=True)

        return P2CardActionTriggerResponse(
            {
                "toast": {
                    "type": "error",
                    "content": "Processing failed, please try again",
                }
            }
        )

    def _extract_selected_label(self, response_data: Dict[str, Any]) -> str:
        """Extract a human-readable label from the HITL response data."""
        if not response_data:
            return ""
        answer = response_data.get("answer", "")
        if answer:
            return str(answer)
        action = response_data.get("action", "")
        if action:
            return str(action).capitalize()
        # Form submissions: show field names
        values = response_data.get("values")
        if isinstance(values, dict) and values:
            names = ", ".join(values.keys())
            return f"Provided: {names}"
        return str(next(iter(response_data.values()), ""))

    def _build_responded_card(
        self,
        hitl_type: str,
        selected_label: str = "",
    ) -> Optional[Dict[str, Any]]:
        """Build a confirmation card after user responds to HITL request."""
        from src.infrastructure.adapters.secondary.channels.feishu.hitl_cards import (
            HITLCardBuilder,
        )

        return HITLCardBuilder().build_responded_card(hitl_type, selected_label)

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

        logger.info(
            f"[FeishuAdapter] Creating Message - "
            f"message_id={message_data.get('message_id')}, "
            f"content_type={content.type.value}, "
            f"raw_data_keys={list(message_data.keys())}"
        )

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

    def _resolve_sender_name(self, sender_data: Dict[str, Any], sender_id: str) -> str:
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
        logger.info(
            f"[FeishuAdapter] Parsing message - type={message_type}, "
            f"content_data={str(content_data)[:200]}"
        )

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
            image_key = parsed.get("image_key")
            return MessageContent(
                type=MessageType.IMAGE,
                image_key=image_key,
                text=f"[图片消息: key={image_key}]",
            )

        elif message_type == "file":
            file_key = parsed.get("file_key")
            file_name = parsed.get("file_name", "unknown")
            logger.info(
                f"[FeishuAdapter] Parsing file message - "
                f"file_key={file_key}, file_name={file_name}, "
                f"parsed_content={str(parsed)[:300]}"
            )
            return MessageContent(
                type=MessageType.FILE,
                file_key=file_key,
                file_name=file_name,
                text=f"[文件: {file_name}, key={file_key}]",
            )

        elif message_type == "audio":
            file_key = parsed.get("file_key")
            duration_ms = parsed.get("duration", 0)
            return MessageContent(
                type=MessageType.AUDIO,
                file_key=file_key,
                duration=duration_ms // 1000,  # Convert to seconds
                text=f"[语音消息: {duration_ms // 1000}秒]",
            )

        elif message_type == "video":
            file_key = parsed.get("file_key")
            duration_ms = parsed.get("duration", 0)
            thumbnail_key = parsed.get("thumbnail", {}).get("file_key")
            return MessageContent(
                type=MessageType.VIDEO,
                file_key=file_key,
                duration=duration_ms // 1000,  # Convert to seconds
                thumbnail_key=thumbnail_key,
                text=f"[视频消息: {duration_ms // 1000}秒]",
            )

        elif message_type == "sticker":
            file_key = parsed.get("file_key")
            return MessageContent(
                type=MessageType.STICKER,
                file_key=file_key,
                text="[表情消息]",
            )

        elif message_type == "post":
            # Rich text post - may contain images and text
            # Always preserve the text content, and extract image_key if present
            text, image_key = self._parse_post_content(parsed)
            return MessageContent(
                type=MessageType.POST,
                text=text if text.strip() else None,
                image_key=image_key,  # Will be used for media import if present
            )

    def _parse_post_content(self, content: Dict[str, Any]) -> tuple:
        """Parse rich text post content. Returns (text, image_key)."""
        title = content.get("title", "")
        content_blocks = content.get("content", [])

        text_parts = [title] if title else []
        extracted_image_key = None

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
                        # Extract image_key from img tag - don't add placeholder text
                        # The image will be imported separately via image_key
                        img_key = element.get("image_key")
                        if img_key and not extracted_image_key:
                            extracted_image_key = img_key
                        # No text placeholder - image is handled separately
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

        return ("\n".join(text_parts) or "[rich text message]", extracted_image_key)

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
                    response = await client.im.v1.message.areply(request)
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
            response = await client.im.v1.message.acreate(request)

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

    async def send_post(
        self,
        to: str,
        title: str,
        content: List[List[Dict[str, Any]]],
        reply_to: Optional[str] = None,
    ) -> str:
        """Send a rich text (post) message.

        Args:
            to: Recipient chat_id or open_id
            title: Post title
            content: Post content as list of paragraphs, each paragraph is a list of elements.
                     Each element is a dict with "tag" and tag-specific fields:
                     - text: {"tag": "text", "text": "content"}
                     - link: {"tag": "a", "text": "display", "href": "url"}
                     - at: {"tag": "at", "user_id": "ou_xxx", "user_name": "name"}
                     - image: {"tag": "img", "image_key": "img_xxx"}
                     - media: {"tag": "media", "file_key": "file_xxx", "image_key": "img_xxx"}
            reply_to: Optional message_id to reply in thread

        Returns:
            Message ID

        Example:
            await adapter.send_post(
                to="oc_xxx",
                title="Report",
                content=[
                    [{"tag": "text", "text": "Here is the result:"}],
                    [{"tag": "img", "image_key": "img_xxx"}],
                    [{"tag": "text", "text": "End of report."}]
                ]
            )
        """
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
            msg_type = "post"
            msg_content = json.dumps({"title": title, "content": content})

            receive_id_type = "open_id" if to.startswith("ou_") else "chat_id"

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
                    response = await client.im.v1.message.areply(request)
                    if response.success() and response.data and response.data.message_id:
                        return response.data.message_id
                except Exception as e:
                    logger.warning(f"[Feishu] Post reply failed, fallback to create: {e}")

            request = (
                CreateMessageRequest.builder()
                .params(CreateMessageRequest.Params(receive_id_type=receive_id_type))
                .request_body(
                    CreateMessageRequestBody.builder()
                    .receive_id(to)
                    .msg_type(msg_type)
                    .content(msg_content)
                    .build()
                )
                .build()
            )
            response = await client.im.v1.message.acreate(request)
            if response.success() and response.data and response.data.message_id:
                return response.data.message_id
            raise RuntimeError(f"Failed to send post: code={response.code}, msg={response.msg}")

        except Exception as e:
            logger.error(f"[Feishu] Send post error: {e}")
            raise

    async def upload_file(
        self,
        file_data: bytes,
        file_name: str,
        file_type: Optional[str] = None,
    ) -> str:
        """Upload a file to Feishu and return file_key.

        Args:
            file_data: File content as bytes
            file_name: File name with extension
            file_type: File type (opus, mp4, pdf, doc, xls, ppt, stream).
                      Auto-detected from extension if not provided.

        Returns:
            file_key for sending the file
        """
        if not self._connected:
            raise RuntimeError("Feishu adapter not connected")

        try:
            client = self._build_rest_client()

            if file_type is None:
                file_type = self._detect_file_type(file_name)

            response = await client.im.file.acreate(
                request={
                    "file_type": file_type,
                    "file_name": file_name,
                    "file": file_data,
                }
            )

            if response.success() and response.data and response.data.file_key:
                logger.info(f"[Feishu] File uploaded: {file_name}, key={response.data.file_key}")
                return response.data.file_key

            raise RuntimeError(f"File upload failed: code={response.code}, msg={response.msg}")

        except Exception as e:
            logger.error(f"[Feishu] Upload file error: {e}")
            raise

    async def upload_image(
        self,
        image_data: bytes,
        image_type: str = "message",
    ) -> str:
        """Upload an image to Feishu and return image_key.

        Args:
            image_data: Image content as bytes
            image_type: "message" or "avatar"

        Returns:
            image_key for sending the image
        """
        if not self._connected:
            raise RuntimeError("Feishu adapter not connected")

        try:
            client = self._build_rest_client()

            response = await client.im.image.acreate(
                request={
                    "image_type": image_type,
                    "image": image_data,
                }
            )

            if response.success() and response.data and response.data.image_key:
                logger.info(f"[Feishu] Image uploaded: key={response.data.image_key}")
                return response.data.image_key

            raise RuntimeError(f"Image upload failed: code={response.code}, msg={response.msg}")

        except Exception as e:
            logger.error(f"[Feishu] Upload image error: {e}")
            raise

    async def upload_and_send_file(
        self,
        to: str,
        file_data: bytes,
        file_name: str,
        reply_to: Optional[str] = None,
    ) -> str:
        """Upload a file and send it as a message.

        Args:
            to: Recipient chat_id or open_id
            file_data: File content as bytes
            file_name: File name with extension
            reply_to: Optional message_id to reply in thread

        Returns:
            Message ID
        """
        file_key = await self.upload_file(file_data, file_name)
        content = MessageContent(type=MessageType.FILE, file_key=file_key, file_name=file_name)
        return await self.send_message(to, content, reply_to)

    async def upload_and_send_image(
        self,
        to: str,
        image_data: bytes,
        reply_to: Optional[str] = None,
    ) -> str:
        """Upload an image and send it as a message.

        Args:
            to: Recipient chat_id or open_id
            image_data: Image content as bytes
            reply_to: Optional message_id to reply in thread

        Returns:
            Message ID
        """
        image_key = await self.upload_image(image_data)
        content = MessageContent(type=MessageType.IMAGE, image_key=image_key)
        return await self.send_message(to, content, reply_to)

    async def upload_and_send_post_with_image(
        self,
        to: str,
        text: str,
        image_data: Optional[bytes] = None,
        title: str = "",
        reply_to: Optional[str] = None,
    ) -> str:
        """Upload an image and send it embedded in a rich text message.

        Args:
            to: Recipient chat_id or open_id
            text: Text content
            image_data: Optional image content as bytes
            title: Post title
            reply_to: Optional message_id to reply in thread

        Returns:
            Message ID
        """
        content_elements = []

        # Add text paragraph
        if text.strip():
            content_elements.append([{"tag": "text", "text": text}])

        # Add image if provided
        if image_data:
            image_key = await self.upload_image(image_data)
            content_elements.append([{"tag": "img", "image_key": image_key}])

        if not content_elements:
            content_elements.append([{"tag": "text", "text": "(empty message)"}])

        return await self.send_post(to, title, content_elements, reply_to)

    def _detect_file_type(self, file_name: str) -> str:
        """Detect file type from extension for Feishu upload."""
        from pathlib import Path

        ext = Path(file_name).suffix.lower()
        type_map = {
            ".opus": "opus",
            ".ogg": "opus",
            ".mp4": "mp4",
            ".mov": "mp4",
            ".avi": "mp4",
            ".pdf": "pdf",
            ".doc": "doc",
            ".docx": "doc",
            ".xls": "xls",
            ".xlsx": "xls",
            ".ppt": "ppt",
            ".pptx": "ppt",
        }
        return type_map.get(ext, "stream")

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
            response = await client.im.v1.message.aupdate(request)
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
            response = await client.im.v1.message.adelete(request)
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
                GetChatMembersRequest.builder().chat_id(chat_id).member_id_type("open_id").build()
            )
            response = await client.im.v1.chat_members.aget(request)
            if not response.success() or not response.data:
                return []
            items = response.data.items or []
            return [SenderInfo(id=m.member_id or "", name=m.name) for m in items if m.member_id]
        except Exception as e:
            logger.warning(f"[Feishu] Get chat members failed: {e}")
            return []

    async def get_user_info(self, user_id: str) -> Optional[SenderInfo]:
        """Get user info using lark_oapi v2 SDK."""
        try:
            from lark_oapi.api.contact.v3 import GetUserRequest

            client = self._build_rest_client()
            request = GetUserRequest.builder().user_id(user_id).user_id_type("open_id").build()
            response = await client.contact.v3.user.aget(request)
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
            response = await client.im.v1.chat.alist(request)
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
                .request_body(PatchMessageRequestBody.builder().content(card_content).build())
                .build()
            )
            response = await client.im.v1.message.apatch(request)
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

    # ------------------------------------------------------------------
    # CardKit API (card entity management)
    # ------------------------------------------------------------------

    async def create_card_entity(self, card_data: Dict[str, Any]) -> Optional[str]:
        """Create a card entity via CardKit API.

        The card entity is a server-side object that can be independently
        updated (add/remove elements, change settings) after creation.
        Returns the ``card_id`` on success, ``None`` on failure.

        Args:
            card_data: Card JSON 2.0 structure (must include ``schema: "2.0"``).
        """
        try:
            from lark_oapi.api.cardkit.v1 import (
                CreateCardRequest,
                CreateCardRequestBody,
            )

            client = self._build_rest_client()
            request = (
                CreateCardRequest.builder()
                .request_body(
                    CreateCardRequestBody.builder()
                    .type("card_json")
                    .data(json.dumps(card_data))
                    .build()
                )
                .build()
            )
            response = await client.cardkit.v1.card.acreate(request)
            if not response.success():
                logger.warning(
                    f"[Feishu] Create card entity failed: code={response.code}, msg={response.msg}"
                )
                return None
            card_id = response.data.card_id
            logger.info(f"[Feishu] Created card entity: {card_id}")
            return card_id
        except Exception as e:
            logger.error(f"[Feishu] Create card entity error: {e}")
            return None

    async def add_card_elements(
        self,
        card_id: str,
        elements: List[Dict[str, Any]],
        *,
        position: str = "append",
        target_element_id: str = "",
        sequence: int = 1,
    ) -> bool:
        """Add elements to an existing card entity via CardKit API.

        Args:
            card_id: The card entity ID from ``create_card_entity()``.
            elements: List of element dicts (card JSON 2.0 components).
            position: ``"append"`` | ``"insert_before"`` | ``"insert_after"``.
            target_element_id: Required for insert_before/insert_after.
            sequence: Strictly increasing operation sequence number.

        Returns:
            True on success, False on failure.
        """
        try:
            import uuid as uuid_mod

            from lark_oapi.api.cardkit.v1 import (
                CreateCardElementRequest,
                CreateCardElementRequestBody,
            )

            client = self._build_rest_client()
            body_builder = (
                CreateCardElementRequestBody.builder()
                .type(position)
                .sequence(sequence)
                .elements(json.dumps(elements))
                .uuid(str(uuid_mod.uuid4()))
            )
            if target_element_id:
                body_builder = body_builder.target_element_id(target_element_id)

            request = (
                CreateCardElementRequest.builder()
                .card_id(card_id)
                .request_body(body_builder.build())
                .build()
            )
            response = await client.cardkit.v1.card_element.acreate(request)
            if not response.success():
                logger.warning(
                    f"[Feishu] Add card elements failed: code={response.code}, msg={response.msg}"
                )
                return False
            logger.info(f"[Feishu] Added {len(elements)} element(s) to card {card_id}")
            return True
        except Exception as e:
            logger.error(f"[Feishu] Add card elements error: {e}")
            return False

    async def send_card_entity_message(
        self,
        to: str,
        card_id: str,
        reply_to: Optional[str] = None,
    ) -> str:
        """Send a card entity as a message.

        Uses ``msg_type: "card"`` with ``content: {"card_id": "..."}``
        to reference a server-side card entity created by CardKit.

        Args:
            to: Chat ID or user open_id.
            card_id: The card entity ID.
            reply_to: Optional message_id to reply in thread.

        Returns:
            The message_id of the sent message.
        """
        from lark_oapi.api.im.v1 import (
            CreateMessageRequest,
            CreateMessageRequestBody,
            ReplyMessageRequest,
            ReplyMessageRequestBody,
        )

        client = self._build_rest_client()
        msg_content = json.dumps({"card_id": card_id})

        if reply_to:
            try:
                request = (
                    ReplyMessageRequest.builder()
                    .message_id(reply_to)
                    .request_body(
                        ReplyMessageRequestBody.builder()
                        .msg_type("interactive")
                        .content(msg_content)
                        .build()
                    )
                    .build()
                )
                response = await client.im.v1.message.areply(request)
                if response.success() and response.data and response.data.message_id:
                    return response.data.message_id
                logger.warning(
                    f"[Feishu] Card entity reply failed, fallback: "
                    f"code={response.code}, msg={response.msg}"
                )
            except Exception as e:
                logger.warning(f"[Feishu] Card entity reply error, fallback: {e}")

        receive_id_type = "open_id" if to.startswith("ou_") else "chat_id"
        request = (
            CreateMessageRequest.builder()
            .receive_id_type(receive_id_type)
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(to)
                .msg_type("interactive")
                .content(msg_content)
                .build()
            )
            .build()
        )
        response = await client.im.v1.message.acreate(request)
        if not response.success():
            raise RuntimeError(
                f"Feishu card entity send failed (code={response.code}): {response.msg}"
            )
        if not response.data or not response.data.message_id:
            raise RuntimeError("No message_id in card entity response")
        return response.data.message_id

    async def send_hitl_card_via_cardkit(
        self,
        chat_id: str,
        hitl_type: str,
        request_id: str,
        event_data: Dict[str, Any],
        reply_to: Optional[str] = None,
        *,
        tenant_id: str = "",
        project_id: str = "",
    ) -> Optional[str]:
        """Send an HITL card using CardKit API for dynamic element management.

        Creates a card entity with the question/description, adds interactive
        buttons via the CardKit Add Elements API, then sends the card entity
        as a message.

        Args:
            chat_id: Target chat ID.
            hitl_type: HITL event type (clarification_asked, decision_asked, etc.).
            request_id: The HITL request ID for routing responses.
            event_data: Event data containing question, options, fields, etc.
            reply_to: Optional message_id for threaded reply.
            tenant_id: Tenant ID to embed in button values.
            project_id: Project ID to embed in button values.

        Returns:
            The message_id on success, None on failure.
        """
        try:
            from src.infrastructure.adapters.secondary.channels.feishu.hitl_cards import (
                HITLCardBuilder,
            )

            builder = HITLCardBuilder()

            # 1. Build base card (header + question, no buttons)
            base_card = builder.build_card_entity_data(hitl_type, request_id, event_data)
            if not base_card:
                logger.warning(f"[Feishu] CardKit HITL: no base card for type={hitl_type}")
                return None

            # 2. Create card entity
            card_id = await self.create_card_entity(base_card)
            if not card_id:
                logger.warning("[Feishu] CardKit HITL: card entity creation failed")
                return None

            # 3. Add interactive buttons
            button_elements = builder.build_hitl_action_elements(
                hitl_type,
                request_id,
                event_data,
                tenant_id=tenant_id,
                project_id=project_id,
            )
            if button_elements:
                added = await self.add_card_elements(
                    card_id,
                    button_elements,
                    position="append",
                    sequence=1,
                )
                if not added:
                    logger.warning(
                        "[Feishu] CardKit HITL: add buttons failed, card sent without buttons"
                    )

            # 4. Send card entity message
            message_id = await self.send_card_entity_message(chat_id, card_id, reply_to)
            logger.info(
                f"[Feishu] Sent HITL card via CardKit: card_id={card_id}, message_id={message_id}"
            )
            return message_id
        except Exception as e:
            logger.error(f"[Feishu] CardKit HITL send failed: {e}")
            return None

    # ------------------------------------------------------------------
    # CardKit streaming & element operations
    # ------------------------------------------------------------------

    async def update_card_settings(
        self,
        card_id: str,
        settings: Dict[str, Any],
        sequence: int,
    ) -> bool:
        """Update card entity settings (e.g. streaming_mode).

        Args:
            card_id: Card entity ID.
            settings: Settings dict, e.g. ``{"config": {"streaming_mode": true}}``.
            sequence: Strictly increasing operation sequence number.

        Returns:
            True on success.
        """
        try:
            import uuid as uuid_mod

            from lark_oapi.api.cardkit.v1 import (
                SettingsCardRequest,
                SettingsCardRequestBody,
            )

            client = self._build_rest_client()
            request = (
                SettingsCardRequest.builder()
                .card_id(card_id)
                .request_body(
                    SettingsCardRequestBody.builder()
                    .settings(json.dumps(settings))
                    .uuid(str(uuid_mod.uuid4()))
                    .sequence(sequence)
                    .build()
                )
                .build()
            )
            response = await client.cardkit.v1.card.asettings(request)
            if not response.success():
                logger.warning(
                    f"[Feishu] Update card settings failed: "
                    f"code={response.code}, msg={response.msg}"
                )
                return False
            return True
        except Exception as e:
            logger.error(f"[Feishu] Update card settings error: {e}")
            return False

    async def stream_text_content(
        self,
        card_id: str,
        element_id: str,
        content: str,
        sequence: int,
    ) -> bool:
        """Stream text content to a card element (typewriter effect).

        Sends full text content; Feishu calculates the diff and renders
        new characters with typewriter effect if the new text is a
        prefix-extension of the old text.

        Args:
            card_id: Card entity ID.
            element_id: The ``element_id`` of a plain_text or markdown element.
            content: Full text content (not a delta).
            sequence: Strictly increasing operation sequence number.

        Returns:
            True on success.
        """
        try:
            import uuid as uuid_mod

            from lark_oapi.api.cardkit.v1 import (
                ContentCardElementRequest,
                ContentCardElementRequestBody,
            )

            client = self._build_rest_client()
            request = (
                ContentCardElementRequest.builder()
                .card_id(card_id)
                .element_id(element_id)
                .request_body(
                    ContentCardElementRequestBody.builder()
                    .content(content)
                    .uuid(str(uuid_mod.uuid4()))
                    .sequence(sequence)
                    .build()
                )
                .build()
            )
            response = await client.cardkit.v1.card_element.acontent(request)
            if not response.success():
                logger.warning(
                    f"[Feishu] Stream text content failed: code={response.code}, msg={response.msg}"
                )
                return False
            return True
        except Exception as e:
            logger.error(f"[Feishu] Stream text content error: {e}")
            return False

    async def delete_card_element(
        self,
        card_id: str,
        element_id: str,
        sequence: int,
    ) -> bool:
        """Delete an element from a card entity.

        Args:
            card_id: Card entity ID.
            element_id: The ``element_id`` to delete.
            sequence: Strictly increasing operation sequence number.

        Returns:
            True on success.
        """
        try:
            import uuid as uuid_mod

            from lark_oapi.api.cardkit.v1 import (
                DeleteCardElementRequest,
                DeleteCardElementRequestBody,
            )

            client = self._build_rest_client()
            request = (
                DeleteCardElementRequest.builder()
                .card_id(card_id)
                .element_id(element_id)
                .request_body(
                    DeleteCardElementRequestBody.builder()
                    .uuid(str(uuid_mod.uuid4()))
                    .sequence(sequence)
                    .build()
                )
                .build()
            )
            response = await client.cardkit.v1.card_element.adelete(request)
            if not response.success():
                logger.warning(
                    f"[Feishu] Delete card element failed: code={response.code}, msg={response.msg}"
                )
                return False
            logger.info(f"[Feishu] Deleted element {element_id} from card {card_id}")
            return True
        except Exception as e:
            logger.error(f"[Feishu] Delete card element error: {e}")
            return False
