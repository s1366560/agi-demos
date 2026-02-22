"""Channel message router - routes IM messages to Agent system.

This module provides the routing logic to bridge incoming channel messages
(Feishu, DingTalk, WeCom, etc.) to the Agent conversation system.
"""

import asyncio
import collections
import logging
import math
import re
import time
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from src.domain.model.channels.message import ChatType, Message, MessageType

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# LRU cache max size for session key -> conversation mapping
_MAX_CACHE_SIZE = 10_000


class _SlidingWindowRateLimiter:
    """Per-key sliding window rate limiter."""

    def __init__(self, default_limit: int = 60, window_seconds: int = 60) -> None:
        self._default_limit = default_limit
        self._window = window_seconds
        self._buckets: Dict[str, List[float]] = {}

    def is_allowed(self, key: str, limit: int = 0) -> bool:
        effective_limit = limit if limit > 0 else self._default_limit
        if effective_limit <= 0:
            return True

        now = time.monotonic()
        cutoff = now - self._window
        bucket = self._buckets.get(key)
        if bucket is None:
            bucket = []
            self._buckets[key] = bucket

        # Prune expired timestamps
        while bucket and bucket[0] < cutoff:
            bucket.pop(0)

        if len(bucket) >= effective_limit:
            return False

        bucket.append(now)
        return True


class ChannelMessageRouter:
    """Routes channel messages to Agent conversations.

    This service handles:
    - Looking up or creating conversations based on chat_id
    - Converting channel messages to agent messages
    - Invoking the agent service to process messages

    Usage:
        router = ChannelMessageRouter()

        # In channel manager:
        adapter.on_message(router.route_message)

        # The router will:
        # 1. Find/create conversation for the chat
        # 2. Add message to conversation
        # 3. Trigger agent processing
    """

    def __init__(self, media_import_service: Optional[Any] = None) -> None:
        self._chat_to_conversation: collections.OrderedDict[str, str] = collections.OrderedDict()
        self._rate_limiter = _SlidingWindowRateLimiter()
        self._media_import_service = media_import_service

    async def route_message(self, message: Message) -> None:
        """Route an incoming channel message to the agent system.

        This is the main entry point for handling channel messages.
        It converts the message format and routes it to the appropriate
        agent conversation.

        Args:
            message: The incoming channel message.
        """
        try:
            if self._is_bot_message(message):
                logger.debug("[MessageRouter] Skipping bot/app echo message")
                return

            # Access control check
            denied_reason = await self._check_access_control(message)
            if denied_reason:
                logger.info(
                    f"[MessageRouter] Access denied for {message.sender.id} "
                    f"in {message.chat_id}: {denied_reason}"
                )
                return

            # Rate limiting check
            if not self._check_rate_limit(message):
                logger.warning(f"[MessageRouter] Rate limited: chat_id={message.chat_id}")
                return

            logger.info(
                f"[MessageRouter] Routing message from {message.channel}: "
                f"chat_id={message.chat_id}, sender={message.sender.id}"
            )

            # Get or create conversation ID for this chat
            conversation_id = await self._get_or_create_conversation(message)

            if not conversation_id:
                logger.error(
                    f"[MessageRouter] Failed to get/create conversation for chat {message.chat_id}"
                )
                return

            # Store message in channel history
            await self._store_message_history(message, conversation_id)

            # DEBUG: Log message content details
            logger.info(
                f"[MessageRouter] Message details - "
                f"type={message.content.type.value}, "
                f"has_media={message.content.has_media_to_import()}, "
                f"image_key={message.content.image_key}, "
                f"file_key={message.content.file_key}, "
                f"file_name={message.content.file_name}"
            )

            # Import media to workspace if message contains media (including post with images)
            if message.content.has_media_to_import():
                # Lazily initialize MediaImportService if not available
                if not self._media_import_service:
                    logger.info(
                        "[MessageRouter] Lazily initializing MediaImportService for media message"
                    )
                    try:
                        from src.infrastructure.adapters.secondary.persistence.database import (
                            async_session_factory,
                        )
                        from src.application.services.channels.channel_service_factory import (
                            create_media_import_service_from_config,
                        )

                        async with async_session_factory() as init_session:
                            self._media_import_service = (
                                await create_media_import_service_from_config(init_session)
                            )
                            # Note: init_session closes here, but MediaImportService
                            # no longer holds db session references

                            if self._media_import_service:
                                logger.info(
                                    "[MessageRouter] MediaImportService initialized successfully"
                                )
                            else:
                                logger.warning(
                                    "[MessageRouter] MediaImportService initialization failed - "
                                    "no enabled Feishu channel config found"
                                )
                    except Exception as e:
                        logger.error(
                            f"[MessageRouter] Failed to initialize MediaImportService: {e}",
                            exc_info=True,
                        )

                if self._media_import_service:
                    # Each call gets fresh session and dependencies
                    try:
                        from src.infrastructure.adapters.secondary.persistence.database import (
                            async_session_factory,
                        )
                        from src.infrastructure.adapters.primary.web.startup.container import (
                            get_app_container,
                        )
                        from src.application.services.artifact_service import ArtifactService

                        async with async_session_factory() as db_session:
                            # Get container and dependencies
                            app_container = get_app_container()
                            if not app_container:
                                raise RuntimeError("Application container not initialized")

                            mcp_adapter = app_container.sandbox_adapter()

                            # Sync existing sandboxes from Docker to adapter's internal state
                            await mcp_adapter.sync_from_docker()

                            # Create artifact service
                            storage = app_container.storage_service()
                            artifact_service = ArtifactService(
                                storage_service=storage,
                                event_publisher=None,  # Not needed for channel imports
                            )

                            logger.info(
                                f"[MessageRouter] Importing media message to workspace: "
                                f"type={message.content.type.value}, message_id={message.id}"
                            )

                            # Call import with all dependencies
                            sandbox_path = (
                                await self._media_import_service.import_media_to_workspace(
                                    message=message,
                                    project_id=message.project_id,
                                    tenant_id=message.raw_data.get("tenant_id", "")
                                    if message.raw_data
                                    else "",
                                    conversation_id=conversation_id,
                                    mcp_adapter=mcp_adapter,
                                    artifact_service=artifact_service,
                                    db_session=db_session,
                                )
                            )

                            if sandbox_path:
                                logger.info(
                                    f"[MessageRouter] Media imported to sandbox: {sandbox_path}"
                                )
                                # Update message content with sandbox path
                                from dataclasses import replace

                                # For POST messages with images, preserve the original text
                                # For pure media messages, show upload info
                                original_text = message.content.text or ""
                                if (
                                    message.content.type == MessageType.POST
                                    and original_text.strip()
                                ):
                                    # Post with image and text - keep original text, add sandbox path info
                                    display_text = (
                                        f"{original_text}\n\n[图片已上传: {sandbox_path}]"
                                    )
                                elif message.content.type.value == "image":
                                    display_text = f"[图片已上传到沙箱: {sandbox_path}]"
                                elif message.content.type.value == "file":
                                    display_text = f"[文件已上传到沙箱: {sandbox_path}]"
                                else:
                                    display_text = f"[媒体已上传到沙箱: {sandbox_path}]"

                                message.content = replace(
                                    message.content,
                                    sandbox_path=sandbox_path,
                                    text=display_text,
                                )
                            else:
                                error_msg = (
                                    f"抱歉，文件导入失败。文件可能过大（超过50MB）或格式不支持。"
                                    f"文件名: {message.content.file_name or '未知'}"
                                )
                                logger.warning(f"[MessageRouter] Media import failed - {error_msg}")
                                # Send error message to user
                                await self._send_error_reply(
                                    message=message,
                                    error_message=error_msg,
                                )

                    except Exception as e:
                        logger.error(
                            f"[MessageRouter] Media import failed: {e}",
                            exc_info=True,
                        )
                        error_msg = f"抱歉，文件导入时发生错误: {str(e)}"
                        await self._send_error_reply(message, error_msg)
                else:
                    logger.warning(
                        f"[MessageRouter] MediaImportService not available - "
                        f"cannot import media message {message.id}"
                    )

            inbound_event_time_us = int(datetime.now(timezone.utc).timestamp() * 1_000_000)
            inbound_message_id = self._extract_channel_message_id(message) or (
                f"channel-{uuid.uuid4().hex}"
            )

            # Build event content with media metadata
            event_content = message.content.generate_display_text()
            event_metadata = {
                "source": "channel_inbound",
                "channel": message.channel,
                "chat_id": message.chat_id,
                "message_type": message.content.type.value,
            }

            # Add media-specific metadata
            if message.content.is_media():
                event_metadata.update(
                    {
                        "file_name": message.content.file_name,
                        "sandbox_path": message.content.sandbox_path,
                        "artifact_id": message.content.artifact_id,
                        "duration": message.content.duration,
                        "size": message.content.size,
                        "mime_type": message.content.mime_type,
                    }
                )

            await self._broadcast_workspace_event(
                conversation_id=conversation_id,
                event_type="message",
                event_data={
                    "id": inbound_message_id,
                    "role": "user",
                    "content": event_content,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "event_time_us": inbound_event_time_us,
                    "event_counter": 0,
                    "metadata": event_metadata,
                },
                raw_event={},
            )

            # Build file_metadata for agent if media was imported to sandbox
            file_metadata = None
            if message.content.is_media() and message.content.sandbox_path:
                file_metadata = [
                    {
                        "filename": message.content.file_name or "unknown",
                        "sandbox_path": message.content.sandbox_path,
                        "mime_type": message.content.mime_type or "application/octet-stream",
                        "size_bytes": message.content.size or 0,
                    }
                ]
                logger.info(
                    f"[MessageRouter] Passing file_metadata to agent: "
                    f"filename={message.content.file_name}, "
                    f"sandbox_path={message.content.sandbox_path}"
                )

            # Route to agent system
            await self._invoke_agent(message, conversation_id, file_metadata)

            logger.info(f"[MessageRouter] Message routed to conversation {conversation_id}")

        except Exception as e:
            logger.error(f"[MessageRouter] Error routing message: {e}", exc_info=True)

    async def _get_or_create_conversation(self, message: Message) -> Optional[str]:
        """Get or create an agent conversation for the channel chat.

        For channel messages, we use a composite key based on:
        - project_id
        - channel type
        - chat_id (from the IM platform)

        This ensures each IM chat has its own conversation thread.

        Args:
            message: The incoming message.

        Returns:
            The conversation ID, or None if failed.
        """
        if not message.project_id:
            logger.error("[MessageRouter] Message has no project_id")
            return None

        channel_config_id = self._extract_channel_config_id(message)
        if not channel_config_id:
            logger.warning(
                "[MessageRouter] Missing channel_config_id in routing metadata, "
                "cannot resolve deterministic channel session"
            )
            return None

        session_key = self._build_session_key(message, channel_config_id)

        # Check cache first
        if session_key in self._chat_to_conversation:
            return self._chat_to_conversation[session_key]

        # Look up or create conversation in database
        try:
            from src.infrastructure.adapters.secondary.persistence.database import (
                async_session_factory,
            )

            async with async_session_factory() as session:
                conversation_id = await self._find_or_create_conversation_db(
                    session=session,
                    message=message,
                    session_key=session_key,
                    channel_config_id=channel_config_id,
                )
                await session.commit()

                if conversation_id:
                    self._cache_conversation(session_key, conversation_id)

                return conversation_id

        except Exception as e:
            logger.error(f"[MessageRouter] Database error: {e}")
            return None

    async def _find_or_create_conversation_db(
        self,
        session: "AsyncSession",
        message: Message,
        session_key: str,
        channel_config_id: Optional[str],
    ) -> Optional[str]:
        """Find or create conversation in database.

        Args:
            session: Database session.
            message: The incoming message.
            session_key: Deterministic session key for the chat/thread.

        Returns:
            The conversation ID.
        """

        from src.infrastructure.adapters.secondary.persistence.channel_models import (
            ChannelConfigModel,
        )
        from src.infrastructure.adapters.secondary.persistence.channel_repository import (
            ChannelSessionBindingRepository,
        )
        from src.infrastructure.adapters.secondary.persistence.models import (
            Conversation,
            Project,
        )

        project = await session.get(Project, message.project_id)
        if not project:
            logger.error(f"[MessageRouter] Project not found: {message.project_id}")
            return None

        if not channel_config_id:
            logger.error("[MessageRouter] Missing channel_config_id when creating conversation")
            return None

        config = await session.get(ChannelConfigModel, channel_config_id)
        if not config or config.project_id != project.id:
            logger.error(
                f"[MessageRouter] Invalid channel config for project routing: {channel_config_id}"
            )
            return None

        binding_repo = ChannelSessionBindingRepository(session)
        existing_binding = await binding_repo.get_by_session_key(project.id, session_key)
        if existing_binding:
            conversation = await session.get(Conversation, existing_binding.conversation_id)
            if conversation:
                return conversation.id

        effective_user_id = project.owner_id
        if config.created_by:
            effective_user_id = config.created_by

        # Create new conversation
        title = self._generate_conversation_title(message)

        new_conversation = Conversation(
            id=str(uuid.uuid4()),
            project_id=message.project_id,
            tenant_id=project.tenant_id,
            user_id=effective_user_id,
            title=title,
            meta={
                "channel_session_key": session_key,
                "channel_type": message.channel,
                "channel_config_id": channel_config_id,
                "chat_id": message.chat_id,
                "chat_type": message.chat_type.value,
                "thread_id": self._extract_thread_id(message),
                "topic_id": self._extract_topic_id(message),
                "sender_id": message.sender.id,
                "sender_name": message.sender.name,
            },
        )

        session.add(new_conversation)
        await session.flush()
        binding = await binding_repo.upsert(
            project_id=project.id,
            channel_config_id=config.id,
            channel_type=message.channel,
            chat_id=message.chat_id,
            chat_type=message.chat_type.value,
            thread_id=self._extract_thread_id(message),
            topic_id=self._extract_topic_id(message),
            session_key=session_key,
            conversation_id=new_conversation.id,
        )
        if binding.conversation_id != new_conversation.id:
            await session.delete(new_conversation)
            await session.flush()
            return binding.conversation_id

        logger.info(
            f"[MessageRouter] Created new conversation {new_conversation.id} "
            f"for chat {message.chat_id}"
        )

        return new_conversation.id

    def _generate_conversation_title(self, message: Message) -> str:
        """Generate a title for the conversation.

        Args:
            message: The incoming message.

        Returns:
            A human-readable title.
        """
        channel_name = message.channel.capitalize()

        if message.chat_type == ChatType.P2P:
            sender = message.sender.name or message.sender.id
            return f"{channel_name}: Chat with {sender}"
        else:
            return f"{channel_name}: Group Chat"

    async def _store_message_history(
        self,
        message: Message,
        conversation_id: str,
    ) -> None:
        """Store the message in channel history.

        Args:
            message: The incoming message.
            conversation_id: The associated conversation ID.
        """
        try:
            from sqlalchemy import select

            from src.infrastructure.adapters.secondary.persistence.channel_models import (
                ChannelMessageModel,
            )
            from src.infrastructure.adapters.secondary.persistence.channel_repository import (
                ChannelMessageRepository,
            )
            from src.infrastructure.adapters.secondary.persistence.database import (
                async_session_factory,
            )

            async with async_session_factory() as session:
                repo = ChannelMessageRepository(session)
                channel_config_id = await self._resolve_channel_config_id(session, message)

                if not channel_config_id:
                    logger.warning(
                        "[MessageRouter] Skip storing message history: no channel config id resolved"
                    )
                    return

                channel_message_id = self._extract_channel_message_id(message)
                if not channel_message_id:
                    channel_message_id = f"generated-{uuid.uuid4().hex}"
                    logger.warning(
                        "[MessageRouter] Missing channel_message_id in inbound payload; "
                        f"using synthetic id {channel_message_id}"
                    )

                dedupe_query = select(ChannelMessageModel.id).where(
                    ChannelMessageModel.channel_config_id == channel_config_id,
                    ChannelMessageModel.channel_message_id == channel_message_id,
                    ChannelMessageModel.direction == "inbound",
                )
                dedupe_result = await session.execute(dedupe_query)
                if dedupe_result.scalar_one_or_none():
                    logger.debug(
                        "[MessageRouter] Duplicate inbound message skipped: "
                        f"{channel_config_id}/{channel_message_id}"
                    )
                    return

                safe_mentions = self._to_json_safe(message.mentions)
                mentions = safe_mentions if isinstance(safe_mentions, list) else []
                raw_data = self._to_json_safe(message.raw_data)

                # Build content_data with media metadata
                content_data_dict = {
                    "conversation_id": conversation_id,
                    "channel_config_id": channel_config_id,
                    "reply_to": message.reply_to,
                    "mentions": mentions,
                }

                # Add media-specific fields
                if message.content.is_media():
                    content_data_dict.update(
                        {
                            "image_key": message.content.image_key,
                            "file_key": message.content.file_key,
                            "file_name": message.content.file_name,
                            "duration": message.content.duration,
                            "size": message.content.size,
                            "mime_type": message.content.mime_type,
                            "thumbnail_key": message.content.thumbnail_key,
                            "sandbox_path": message.content.sandbox_path,
                            "artifact_id": message.content.artifact_id,
                            "extra_media_data": self._to_json_safe(
                                message.content.extra_media_data
                            ),
                        }
                    )

                channel_message = ChannelMessageModel(
                    channel_config_id=channel_config_id,
                    project_id=message.project_id or "",
                    channel_message_id=channel_message_id,
                    chat_id=message.chat_id,
                    chat_type=message.chat_type.value,
                    sender_id=str(message.sender.id),
                    sender_name=message.sender.name,
                    message_type=message.content.type.value,
                    content_text=message.content.generate_display_text(),
                    content_data=self._to_json_safe(content_data_dict),
                    reply_to=message.reply_to,
                    mentions=mentions,
                    direction="inbound",
                    raw_data=raw_data,
                )

                await repo.create(channel_message)
                await session.commit()

        except Exception as e:
            logger.warning(f"[MessageRouter] Failed to store message history: {e}")

    def _to_json_safe(self, value: Any, *, _depth: int = 0) -> Any:
        """Convert payload value into JSON-serializable primitives."""
        if _depth > 8:
            return str(value)

        if isinstance(value, float):
            if not math.isfinite(value):
                return None
            return value

        if value is None or isinstance(value, (str, int, bool)):
            return value

        if isinstance(value, dict):
            return {
                str(key): self._to_json_safe(item, _depth=_depth + 1) for key, item in value.items()
            }

        if isinstance(value, (list, tuple, set)):
            return [self._to_json_safe(item, _depth=_depth + 1) for item in value]

        if hasattr(value, "to_dict"):
            try:
                return self._to_json_safe(value.to_dict(), _depth=_depth + 1)
            except Exception:
                return str(value)

        dict_method = getattr(value, "dict", None)
        if callable(dict_method):
            try:
                return self._to_json_safe(dict_method(), _depth=_depth + 1)
            except Exception:
                return str(value)

        if hasattr(value, "__dict__"):
            try:
                return self._to_json_safe(vars(value), _depth=_depth + 1)
            except Exception:
                return str(value)

        return str(value)

    async def _invoke_agent(
        self,
        message: Message,
        conversation_id: str,
        file_metadata: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """Invoke the agent and send the final response to the channel.

        Event flow from ``stream_chat_v2``::

            message -> [thought -> act -> observe]* -> text_delta* -> text_end -> complete

        Key design decisions:

        * The **authoritative** final answer comes from the ``complete`` event's
          ``content`` field (which uses ``text_end.full_text`` internally).
          Accumulated ``text_delta`` is only a fallback.
        * A background ``asyncio.Task`` handles streaming card updates so the
          main loop never awaits Feishu HTTP calls.
        * A global **timeout** (180 s) prevents the loop from blocking forever
          if the agent or sandbox hangs.
        * During tool execution the card shows status (``Running: tool_name``)
          so the user knows the agent is working, not stuck.
        """
        try:
            from src.configuration.factories import create_llm_client
            from src.infrastructure.adapters.primary.web.startup.container import get_app_container
            from src.infrastructure.adapters.secondary.persistence.database import (
                async_session_factory,
            )
            from src.infrastructure.adapters.secondary.persistence.models import Conversation

            text = message.content.generate_display_text()
            if not text.strip():
                logger.debug("[MessageRouter] Empty message, skipping agent invocation")
                return

            async with async_session_factory() as session:
                conversation = await session.get(Conversation, conversation_id)
                if not conversation:
                    logger.error(f"[MessageRouter] Conversation not found: {conversation_id}")
                    return

                app_container = get_app_container()
                if not app_container:
                    logger.error("[MessageRouter] App container is not initialized")
                    return

                llm = await create_llm_client(conversation.tenant_id)
                container = app_container.with_db(session)
                agent_service = container.agent_service(llm)

                logger.info(f"[MessageRouter] Invoking agent for conversation {conversation_id}")

                # --- Shared state between main loop and card updater ---------
                _delta_text = ""  # accumulated text_delta (preview)
                _card_status = ""  # tool-execution status line
                _final_content = ""  # authoritative answer from complete
                error_message: Optional[str] = None
                _stream_done = False

                _SKIP_BROADCAST = {"assistant_message"}
                _STREAM_TIMEOUT = 180.0

                # --- Background card updater (Feishu streaming) --------------
                streaming_adapter = self._get_streaming_adapter(message)
                _card_msg_id: Optional[str] = None
                _card_updater_task: Optional[asyncio.Task] = None
                _card_stream_state: Any = None  # CardStreamState when using CardKit

                if streaming_adapter:

                    async def _card_updater() -> None:
                        nonlocal _card_msg_id, _card_stream_state

                        reply_to = self._extract_channel_message_id(message)
                        use_cardkit = self._supports_cardkit_streaming(streaming_adapter)
                        cardkit_mgr = None
                        cardkit_state = None

                        # Try CardKit streaming first
                        if use_cardkit:
                            try:
                                from src.infrastructure.adapters.secondary.channels.feishu.cardkit_streaming import (
                                    CardKitStreamingManager,
                                )

                                cardkit_mgr = CardKitStreamingManager(streaming_adapter)
                                cardkit_state = await cardkit_mgr.start_streaming(
                                    message.chat_id,
                                    reply_to=reply_to,
                                )
                            except Exception as e:
                                logger.warning(f"[MessageRouter] CardKit start failed: {e}")

                        if cardkit_state:
                            # CardKit streaming path
                            _card_msg_id = cardkit_state.message_id
                            _card_stream_state = cardkit_state

                            # Register with event bridge for unified HITL
                            try:
                                from src.application.services.channels.event_bridge import (
                                    get_channel_event_bridge,
                                )

                                get_channel_event_bridge().register_card_state(
                                    conversation_id, cardkit_state
                                )
                            except Exception:
                                pass

                            last_snapshot = ""
                            while not _stream_done:
                                await asyncio.sleep(0.5)
                                display = _delta_text
                                if _card_status and not _delta_text:
                                    display = f"_{_card_status}_"
                                elif _card_status:
                                    display = f"_{_card_status}_\n\n{_delta_text}"
                                if display != last_snapshot and display.strip():
                                    ok = await cardkit_mgr.update_text(cardkit_state, display)
                                    if ok:
                                        last_snapshot = display
                            # Finalize
                            final_display = _final_content or _delta_text
                            if final_display.strip():
                                await cardkit_mgr.finish_streaming(cardkit_state, final_display)
                            else:
                                await cardkit_mgr.finish_streaming(cardkit_state, last_snapshot)

                            # Unregister card state
                            try:
                                from src.application.services.channels.event_bridge import (
                                    get_channel_event_bridge,
                                )

                                get_channel_event_bridge().unregister_card_state(conversation_id)
                            except Exception:
                                pass

                        else:
                            # Legacy streaming fallback
                            _card_msg_id = await self._send_initial_streaming_card(
                                streaming_adapter,
                                message,
                            )
                            if not _card_msg_id:
                                return
                            last_snapshot = ""
                            while not _stream_done:
                                await asyncio.sleep(1.5)
                                display = _delta_text
                                if _card_status and not _delta_text:
                                    display = f"_{_card_status}_"
                                elif _card_status:
                                    display = f"_{_card_status}_\n\n{_delta_text}"
                                if display != last_snapshot and display.strip():
                                    ok = await self._patch_streaming_card(
                                        streaming_adapter,
                                        _card_msg_id,
                                        display,
                                        loading=True,
                                    )
                                    if ok:
                                        last_snapshot = display
                            final_display = _final_content or _delta_text
                            if final_display.strip():
                                await self._patch_streaming_card(
                                    streaming_adapter,
                                    _card_msg_id,
                                    final_display,
                                    loading=False,
                                )

                    _card_updater_task = asyncio.create_task(_card_updater())

                # --- Consume agent stream (with timeout) ---------------------
                try:
                    async with asyncio.timeout(_STREAM_TIMEOUT):
                        async for event in agent_service.stream_chat_v2(
                            conversation_id=conversation_id,
                            user_message=text,
                            project_id=conversation.project_id,
                            user_id=conversation.user_id,
                            tenant_id=conversation.tenant_id,
                            file_metadata=file_metadata,
                            app_model_context=self._build_app_model_context(message),
                        ):
                            event_type = event.get("type")
                            event_data = event.get("data") or {}

                            if event_type not in _SKIP_BROADCAST:
                                await self._broadcast_workspace_event(
                                    conversation_id=conversation_id,
                                    event_type=event_type,
                                    event_data=(event_data if isinstance(event_data, dict) else {}),
                                    raw_event=event,
                                    tenant_id=conversation.tenant_id,
                                    project_id=conversation.project_id,
                                )

                            if event_type == "text_delta":
                                delta = event_data.get("delta", "")
                                if isinstance(delta, str):
                                    _delta_text += delta
                            elif event_type == "text_end":
                                # text_end carries the complete text for this turn;
                                # reset delta accumulator so multi-turn planning
                                # text doesn't leak into the final response.
                                full = event_data.get("full_text", "")
                                if isinstance(full, str) and full.strip():
                                    _delta_text = full
                                _card_status = ""
                            elif event_type == "thought":
                                _card_status = "Thinking..."
                            elif event_type == "act":
                                tool = event_data.get("tool_name", "tool")
                                _card_status = f"Running: {tool}"
                            elif event_type == "observe":
                                _card_status = ""
                            elif event_type == "complete":
                                content = event_data.get("content") or event_data.get("result")
                                if isinstance(content, str) and content.strip():
                                    _final_content = content
                            elif event_type == "error":
                                error_message = event_data.get("message") or "Unknown agent error"

                except asyncio.TimeoutError:
                    logger.warning(
                        f"[MessageRouter] Stream timeout ({_STREAM_TIMEOUT}s) "
                        f"for conversation {conversation_id}"
                    )

                # --- Finalize ------------------------------------------------
                _stream_done = True
                response = _final_content or _delta_text

                if _card_updater_task:
                    try:
                        await asyncio.wait_for(_card_updater_task, timeout=15.0)
                    except (asyncio.TimeoutError, Exception) as e:
                        logger.warning(f"[MessageRouter] Card updater error: {e}")
                        _card_updater_task.cancel()

                # If streaming card was used successfully, we're done
                if _card_msg_id and response.strip():
                    await self._record_streaming_outbox(
                        message,
                        conversation_id,
                        response,
                        _card_msg_id,
                    )
                    if error_message:
                        logger.warning(
                            f"[MessageRouter] Agent error after streaming: {error_message}"
                        )
                    return

                # Fallback: regular send
                if error_message:
                    logger.warning(
                        f"[MessageRouter] Agent error for {conversation_id}: {error_message}"
                    )
                    if response.strip():
                        await self._send_response(message, conversation_id, response)
                    else:
                        await self._send_error_feedback(message, conversation_id)
                    return

                if response.strip():
                    await self._send_response(message, conversation_id, response)
                else:
                    logger.warning(
                        f"[MessageRouter] Agent produced empty response for {conversation_id}"
                    )
                    await self._send_error_feedback(message, conversation_id)

        except Exception as e:
            logger.error(f"[MessageRouter] Agent invocation error: {e}", exc_info=True)

    # ------------------------------------------------------------------
    # Public push API
    # ------------------------------------------------------------------

    async def send_to_channel(
        self,
        conversation_id: str,
        content: str,
        *,
        content_type: str = "text",
        card: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Send a message to the channel bound to a conversation.

        This is the public API for agent-initiated (push) messages,
        e.g. proactive notifications, task summaries, artifact links.

        Args:
            conversation_id: The conversation whose bound channel will receive the message.
            content: Text content to send (used for text/markdown types).
            content_type: One of ``text``, ``markdown``, ``card``.
            card: Card JSON payload (required when content_type is ``card``).

        Returns:
            True if the message was sent successfully.
        """
        try:
            from src.application.services.channels.event_bridge import (
                get_channel_event_bridge,
            )

            bridge = get_channel_event_bridge()
            binding = await bridge._lookup_binding(conversation_id)
            if not binding:
                logger.debug(
                    f"[MessageRouter] No channel binding for conversation {conversation_id}"
                )
                return False

            adapter = bridge._get_adapter(binding.channel_config_id)
            if not adapter:
                logger.warning(f"[MessageRouter] No adapter for config {binding.channel_config_id}")
                return False

            chat_id = binding.chat_id

            if content_type == "card" and card:
                await adapter.send_card(chat_id, card)
            elif content_type == "markdown":
                await adapter.send_markdown_card(chat_id, content)
            else:
                await adapter.send_text(chat_id, content)

            # Track in outbox
            await self._track_push_outbox(
                conversation_id=conversation_id,
                channel_config_id=binding.channel_config_id,
                chat_id=chat_id,
                content=content,
                content_type=content_type,
            )

            logger.info(
                f"[MessageRouter] Push message sent to {chat_id} "
                f"(conversation={conversation_id}, type={content_type})"
            )
            return True
        except Exception as e:
            logger.error(
                f"[MessageRouter] Push message failed for {conversation_id}: {e}",
                exc_info=True,
            )
            return False

    async def _track_push_outbox(
        self,
        conversation_id: str,
        channel_config_id: str,
        chat_id: str,
        content: str,
        content_type: str,
    ) -> None:
        """Record a push message in the outbox for observability."""
        try:
            from src.infrastructure.adapters.secondary.persistence.channel_repository import (
                ChannelOutboxRepository,
            )
            from src.infrastructure.adapters.secondary.persistence.database import (
                async_session_factory,
            )

            async with async_session_factory() as session:
                repo = ChannelOutboxRepository(session)
                await repo.create(
                    channel_config_id=channel_config_id,
                    conversation_id=conversation_id,
                    chat_id=chat_id,
                    message_type=content_type,
                    content=content[:500],
                    status="sent",
                )
                await session.commit()
        except Exception as e:
            logger.debug(f"[MessageRouter] Outbox tracking failed: {e}")

    async def _broadcast_workspace_event(
        self,
        conversation_id: str,
        event_type: Optional[str],
        event_data: Dict[str, Any],
        raw_event: Dict[str, Any],
        *,
        tenant_id: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> None:
        """Forward agent stream events to subscribed workspace WebSocket sessions."""
        if not event_type:
            return

        try:
            from src.infrastructure.adapters.primary.web.websocket.connection_manager import (
                get_connection_manager,
            )

            safe_data = self._to_json_safe(event_data)
            if not isinstance(safe_data, dict):
                safe_data = {"value": safe_data}

            ws_event: Dict[str, Any] = {
                "type": event_type,
                "data": safe_data,
                "conversation_id": conversation_id,
                "timestamp": raw_event.get("timestamp") or datetime.now(timezone.utc).isoformat(),
            }
            if "event_time_us" in raw_event:
                ws_event["event_time_us"] = raw_event["event_time_us"]
            if "event_counter" in raw_event:
                ws_event["event_counter"] = raw_event["event_counter"]

            await get_connection_manager().broadcast_to_conversation(conversation_id, ws_event)
        except Exception as e:
            logger.warning(
                f"[MessageRouter] Failed to broadcast event to workspace: {event_type}, error={e}"
            )

        # Forward to channel event bridge (non-blocking)
        try:
            from src.application.services.channels.event_bridge import (
                get_channel_event_bridge,
            )

            bridge = get_channel_event_bridge()
            await bridge.on_agent_event(
                conversation_id,
                raw_event,
                tenant_id=tenant_id,
                project_id=project_id,
            )
        except Exception as e:
            logger.debug(f"[MessageRouter] Channel bridge forward failed: {e}")

    async def _send_response(self, message: Message, conversation_id: str, response: str) -> None:
        """Send agent response back to the channel.

        Args:
            message: The original message (contains sender info).
            conversation_id: The associated conversation ID.
            response: The agent's response text.
        """
        outbox_id: Optional[str] = None
        try:
            from src.infrastructure.adapters.primary.web.startup import get_channel_manager

            channel_config_id = self._extract_channel_config_id(message)
            if not channel_config_id:
                channel_config_id = await self._get_conversation_channel_config_id(conversation_id)

            if not channel_config_id:
                logger.warning(
                    "[MessageRouter] Missing channel_config_id; refusing outbound response to "
                    "avoid ambiguous routing"
                )
                return

            inbound_message_id = self._extract_channel_message_id(message)
            outbox_id = await self._create_outbox_record(
                message=message,
                conversation_id=conversation_id,
                channel_config_id=channel_config_id,
                response=response,
                reply_to=inbound_message_id,
            )

            channel_manager = get_channel_manager()
            if not channel_manager:
                if outbox_id:
                    await self._mark_outbox_failed(outbox_id, "channel manager unavailable")
                logger.warning("[MessageRouter] No channel manager available")
                return

            connection = channel_manager.connections.get(channel_config_id)
            if not connection:
                if outbox_id:
                    await self._mark_outbox_failed(outbox_id, "no active connection")
                logger.warning(
                    "[MessageRouter] No active connection for outbound response: "
                    f"channel_config_id={channel_config_id}"
                )
                return

            sent_message_id = await self._smart_send(
                connection.adapter,
                message.chat_id,
                response,
                reply_to=inbound_message_id,
            )
            if outbox_id:
                await self._mark_outbox_sent(outbox_id, sent_message_id)
            logger.info(
                f"[MessageRouter] Sent response to chat {message.chat_id}, "
                f"message_id={sent_message_id}"
            )
            await self._store_outbound_message_history(
                message=message,
                conversation_id=conversation_id,
                response=response,
                channel_config_id=connection.config_id,
                outbound_message_id=sent_message_id,
            )

        except Exception as e:
            if outbox_id:
                await self._mark_outbox_failed(outbox_id, str(e))
            logger.error(f"[MessageRouter] Error sending response: {e}")

    # Patterns that indicate rich markdown (code fences, tables, headers, lists)
    _RICH_MD_RE = re.compile(
        r"```|"  # code fences
        r"^\|.*\|.*\|$|"  # table rows
        r"^#{1,6}\s|"  # headings
        r"^\s*[-*]\s|"  # unordered lists
        r"^\s*\d+\.\s",  # ordered lists
        re.MULTILINE,
    )

    async def _smart_send(
        self,
        adapter: Any,
        chat_id: str,
        text: str,
        reply_to: Optional[str] = None,
    ) -> Optional[str]:
        """Send response as card when it contains rich markdown, otherwise as text."""
        if self._contains_rich_markdown(text) and hasattr(adapter, "send_markdown_card"):
            try:
                return await adapter.send_markdown_card(chat_id, text, reply_to=reply_to)
            except Exception:
                logger.debug("[MessageRouter] Card send failed, falling back to text")
        return await adapter.send_text(chat_id, text, reply_to=reply_to)

    def _contains_rich_markdown(self, text: str) -> bool:
        """Return True if text contains markdown structures that benefit from card rendering."""
        return bool(self._RICH_MD_RE.search(text))

    # ------------------------------------------------------------------
    # Streaming card helpers
    # ------------------------------------------------------------------

    def _get_streaming_adapter(self, message: Message) -> Any:
        """Return the channel adapter if it supports streaming card updates."""
        try:
            from src.infrastructure.adapters.primary.web.startup import get_channel_manager

            channel_config_id = self._extract_channel_config_id(message)
            if not channel_config_id:
                return None

            channel_manager = get_channel_manager()
            if not channel_manager:
                return None

            connection = channel_manager.connections.get(channel_config_id)
            if not connection:
                return None

            adapter = connection.adapter
            # CardKit streaming (preferred) or legacy patch streaming
            if self._supports_cardkit_streaming(adapter):
                return adapter
            if hasattr(adapter, "send_streaming_card") and hasattr(adapter, "patch_card"):
                return adapter
            return None
        except Exception:
            return None

    @staticmethod
    def _supports_cardkit_streaming(adapter: Any) -> bool:
        """Check if adapter supports CardKit streaming APIs."""
        return (
            hasattr(adapter, "create_card_entity")
            and hasattr(adapter, "update_card_settings")
            and hasattr(adapter, "stream_text_content")
            and hasattr(adapter, "send_card_entity_message")
        )

    async def _send_initial_streaming_card(self, adapter: Any, message: Message) -> Optional[str]:
        """Send the initial 'Thinking...' card and return its message_id."""
        try:
            reply_to = self._extract_channel_message_id(message)
            msg_id = await adapter.send_streaming_card(
                message.chat_id,
                initial_text="",
                reply_to=reply_to,
            )
            if msg_id:
                logger.debug(f"[MessageRouter] Streaming card sent: {msg_id}")
            return msg_id
        except Exception as e:
            logger.warning(f"[MessageRouter] Failed to send streaming card: {e}")
            return None

    async def _patch_streaming_card(
        self,
        adapter: Any,
        message_id: str,
        text: str,
        *,
        loading: bool = False,
    ) -> bool:
        """Patch the streaming card with accumulated text. Returns True on success."""
        try:
            card_json = adapter._build_streaming_card(text, loading=loading)
            return await adapter.patch_card(message_id, card_json)
        except Exception as e:
            logger.debug(f"[MessageRouter] Streaming card patch failed: {e}")
            return False

    async def _record_streaming_outbox(
        self,
        message: Message,
        conversation_id: str,
        response_text: str,
        streaming_msg_id: str,
    ) -> None:
        """Record the streaming response in outbox and history for traceability."""
        try:
            channel_config_id = self._extract_channel_config_id(message)
            if not channel_config_id:
                channel_config_id = await self._get_conversation_channel_config_id(conversation_id)
            if channel_config_id:
                outbox_id = await self._create_outbox_record(
                    message=message,
                    conversation_id=conversation_id,
                    channel_config_id=channel_config_id,
                    response=response_text,
                    reply_to=self._extract_channel_message_id(message),
                )
                if outbox_id:
                    await self._mark_outbox_sent(outbox_id, streaming_msg_id)
                await self._store_outbound_message_history(
                    message=message,
                    conversation_id=conversation_id,
                    response=response_text,
                    channel_config_id=channel_config_id,
                    outbound_message_id=streaming_msg_id,
                )
                logger.info(
                    f"[MessageRouter] Streaming response recorded: "
                    f"chat={message.chat_id}, msg_id={streaming_msg_id}"
                )
        except Exception as e:
            logger.warning(f"[MessageRouter] Failed to record streaming outbox: {e}")

    async def _store_outbound_message_history(
        self,
        message: Message,
        conversation_id: str,
        response: str,
        channel_config_id: str,
        outbound_message_id: Optional[str],
    ) -> None:
        """Persist outbound agent response for traceability."""
        try:
            from src.infrastructure.adapters.secondary.persistence.channel_models import (
                ChannelMessageModel,
            )
            from src.infrastructure.adapters.secondary.persistence.channel_repository import (
                ChannelMessageRepository,
            )
            from src.infrastructure.adapters.secondary.persistence.database import (
                async_session_factory,
            )

            async with async_session_factory() as session:
                repo = ChannelMessageRepository(session)
                outbound_id = outbound_message_id or f"generated-{uuid.uuid4().hex}"
                inbound_message_id = self._extract_channel_message_id(message)

                channel_message = ChannelMessageModel(
                    channel_config_id=channel_config_id,
                    project_id=message.project_id or "",
                    channel_message_id=outbound_id,
                    chat_id=message.chat_id,
                    chat_type=message.chat_type.value,
                    sender_id="memstack-agent",
                    sender_name="MemStack Agent",
                    message_type="text",
                    content_text=response,
                    content_data={
                        "conversation_id": conversation_id,
                        "reply_to": inbound_message_id,
                    },
                    reply_to=inbound_message_id,
                    mentions=[],
                    direction="outbound",
                    raw_data={"source": "channel_message_router"},
                )

                await repo.create(channel_message)
                await session.commit()

        except Exception as e:
            logger.warning(f"[MessageRouter] Failed to store outbound message history: {e}")

    async def _create_outbox_record(
        self,
        message: Message,
        conversation_id: str,
        channel_config_id: str,
        response: str,
        reply_to: Optional[str],
    ) -> Optional[str]:
        """Create pending outbox record for outbound channel response."""
        try:
            from src.infrastructure.adapters.secondary.persistence.channel_models import (
                ChannelOutboxModel,
            )
            from src.infrastructure.adapters.secondary.persistence.channel_repository import (
                ChannelOutboxRepository,
            )
            from src.infrastructure.adapters.secondary.persistence.database import (
                async_session_factory,
            )

            async with async_session_factory() as session:
                repo = ChannelOutboxRepository(session)
                outbox = ChannelOutboxModel(
                    project_id=message.project_id or "",
                    channel_config_id=channel_config_id,
                    conversation_id=conversation_id,
                    chat_id=message.chat_id,
                    reply_to_channel_message_id=reply_to,
                    content_text=response,
                    status="pending",
                    metadata_json={
                        "channel": message.channel,
                        "chat_type": message.chat_type.value,
                    },
                )
                await repo.create(outbox)
                await session.commit()
                return outbox.id
        except Exception as e:
            logger.warning(f"[MessageRouter] Failed to create outbox record: {e}")
            return None

    async def _mark_outbox_sent(
        self,
        outbox_id: str,
        sent_channel_message_id: Optional[str],
    ) -> None:
        """Mark outbox record as sent."""
        try:
            from src.infrastructure.adapters.secondary.persistence.channel_repository import (
                ChannelOutboxRepository,
            )
            from src.infrastructure.adapters.secondary.persistence.database import (
                async_session_factory,
            )

            async with async_session_factory() as session:
                repo = ChannelOutboxRepository(session)
                updated = await repo.mark_sent(outbox_id, sent_channel_message_id)
                if updated:
                    await session.commit()
        except Exception as e:
            logger.warning(f"[MessageRouter] Failed to mark outbox sent: {e}")

    async def _mark_outbox_failed(self, outbox_id: str, error_message: str) -> None:
        """Mark outbox record as failed/dead-letter."""
        try:
            from src.infrastructure.adapters.secondary.persistence.channel_repository import (
                ChannelOutboxRepository,
            )
            from src.infrastructure.adapters.secondary.persistence.database import (
                async_session_factory,
            )

            async with async_session_factory() as session:
                repo = ChannelOutboxRepository(session)
                updated = await repo.mark_failed(outbox_id, error_message)
                if updated:
                    await session.commit()
        except Exception as e:
            logger.warning(f"[MessageRouter] Failed to mark outbox failed: {e}")

    async def _resolve_channel_config_id(
        self,
        session: "AsyncSession",
        message: Message,
    ) -> Optional[str]:
        """Resolve channel config ID strictly from trusted routing metadata."""

        from src.infrastructure.adapters.secondary.persistence.channel_models import (
            ChannelConfigModel,
        )

        explicit_config_id = self._extract_channel_config_id(message)
        if not explicit_config_id:
            return None

        config = await session.get(ChannelConfigModel, explicit_config_id)
        if config and config.project_id == (message.project_id or ""):
            return config.id

        logger.warning(
            "[MessageRouter] Explicit channel config id is invalid for this message: "
            f"{explicit_config_id}"
        )
        return None

    def _extract_channel_config_id(self, message: Message) -> Optional[str]:
        """Extract channel config ID from message routing metadata."""
        if not isinstance(message.raw_data, dict):
            return None

        routing_meta = message.raw_data.get("_routing")
        if isinstance(routing_meta, dict):
            config_id = routing_meta.get("channel_config_id")
            if isinstance(config_id, str) and config_id:
                return config_id
        return None

    def _extract_channel_message_id(self, message: Message) -> Optional[str]:
        """Extract source channel message ID from message payload."""
        if not isinstance(message.raw_data, dict):
            return None

        routing_meta = message.raw_data.get("_routing")
        if isinstance(routing_meta, dict):
            routed_message_id = routing_meta.get("channel_message_id")
            if isinstance(routed_message_id, str) and routed_message_id:
                return routed_message_id

        event = message.raw_data.get("event")
        if isinstance(event, dict):
            event_message = event.get("message")
            if isinstance(event_message, dict):
                event_message_id = event_message.get("message_id")
                if isinstance(event_message_id, str) and event_message_id:
                    return event_message_id

        return None

    def _is_bot_message(self, message: Message) -> bool:
        """Best-effort detection to skip bot echo messages and prevent loops."""
        if not isinstance(message.raw_data, dict):
            return False
        event = message.raw_data.get("event")
        if not isinstance(event, dict):
            return False
        sender = event.get("sender")
        if not isinstance(sender, dict):
            return False
        sender_type = sender.get("sender_type")
        if not isinstance(sender_type, str):
            return False
        return sender_type.lower() in {"app", "bot"}

    def _build_app_model_context(self, message: Message) -> Dict[str, Any]:
        """Build structured channel context for Agent runtime."""
        return {
            "source": "channel",
            "channel": message.channel,
            "chat_id": message.chat_id,
            "chat_type": message.chat_type.value,
            "sender_id": message.sender.id,
            "sender_name": message.sender.name,
            "reply_to": message.reply_to,
            "mentions": message.mentions,
            "channel_config_id": self._extract_channel_config_id(message),
            "channel_message_id": self._extract_channel_message_id(message),
            "thread_id": self._extract_thread_id(message),
            "topic_id": self._extract_topic_id(message),
        }

    async def _get_conversation_channel_config_id(self, conversation_id: str) -> Optional[str]:
        """Load channel_config_id from conversation metadata as fallback."""
        try:
            from src.infrastructure.adapters.secondary.persistence.channel_repository import (
                ChannelSessionBindingRepository,
            )
            from src.infrastructure.adapters.secondary.persistence.database import (
                async_session_factory,
            )
            from src.infrastructure.adapters.secondary.persistence.models import Conversation

            async with async_session_factory() as session:
                binding_repo = ChannelSessionBindingRepository(session)
                binding = await binding_repo.get_by_conversation_id(conversation_id)
                if binding:
                    return binding.channel_config_id
                conversation = await session.get(Conversation, conversation_id)
                if conversation and isinstance(conversation.meta, dict):
                    config_id = conversation.meta.get("channel_config_id")
                    if isinstance(config_id, str) and config_id:
                        return config_id
        except Exception as e:
            logger.warning(
                f"[MessageRouter] Failed to load channel_config_id from conversation metadata: {e}"
            )
        return None

    async def _check_access_control(self, message: Message) -> Optional[str]:
        """Check access control policies for the incoming message.

        Returns a denial reason string if access is denied, or None if allowed.
        """
        try:
            config = await self._load_channel_config(message)
            if not config:
                return None  # No config found; allow (backward compat)

            is_group = message.chat_type == ChatType.GROUP
            if is_group:
                policy = getattr(config, "group_policy", "open")
                if policy == "disabled":
                    return "group messages disabled"
                if policy == "allowlist":
                    group_allow_from = getattr(config, "group_allow_from", None) or []
                    if "*" not in group_allow_from and message.chat_id not in group_allow_from:
                        return f"group {message.chat_id} not in allowlist"
            else:
                policy = getattr(config, "dm_policy", "open")
                if policy == "disabled":
                    return "DM messages disabled"
                if policy == "allowlist":
                    allow_from = getattr(config, "allow_from", None) or []
                    if "*" not in allow_from and message.sender.id not in allow_from:
                        return f"sender {message.sender.id} not in allowlist"

        except Exception as e:
            logger.warning(f"[MessageRouter] Access control check error: {e}")
        return None

    def _check_rate_limit(self, message: Message) -> bool:
        """Check rate limit for the incoming message. Returns True if allowed."""
        config_id = self._extract_channel_config_id(message) or "default"
        key = f"{config_id}:{message.chat_id}"
        rate_limit = 0
        if isinstance(message.raw_data, dict):
            routing = message.raw_data.get("_routing") or {}
            rate_limit = routing.get("rate_limit_per_minute", 0)
        return self._rate_limiter.is_allowed(key, limit=rate_limit)

    async def _load_channel_config(self, message: Message):
        """Load the ChannelConfigModel for this message."""
        config_id = self._extract_channel_config_id(message)
        if not config_id:
            return None
        try:
            from src.infrastructure.adapters.secondary.persistence.channel_models import (
                ChannelConfigModel,
            )
            from src.infrastructure.adapters.secondary.persistence.database import (
                async_session_factory,
            )

            async with async_session_factory() as session:
                return await session.get(ChannelConfigModel, config_id)
        except Exception as e:
            logger.warning(f"[MessageRouter] Failed to load channel config: {e}")
            return None

    async def _send_error_feedback(self, message: Message, conversation_id: str) -> None:
        """Send a user-friendly error message back to the channel."""
        try:
            error_text = (
                "Sorry, I encountered an error processing your message. Please try again later."
            )
            await self._send_response(message, conversation_id, error_text)
        except Exception as e:
            logger.warning(f"[MessageRouter] Failed to send error feedback: {e}")

    def _cache_conversation(self, session_key: str, conversation_id: str) -> None:
        """Cache session_key -> conversation_id with LRU eviction."""
        if session_key in self._chat_to_conversation:
            self._chat_to_conversation.move_to_end(session_key)
            self._chat_to_conversation[session_key] = conversation_id
            return
        self._chat_to_conversation[session_key] = conversation_id
        while len(self._chat_to_conversation) > _MAX_CACHE_SIZE:
            self._chat_to_conversation.popitem(last=False)

    def _build_session_key(self, message: Message, channel_config_id: str) -> str:
        """Build deterministic session key for channel routing."""
        scope = "dm" if message.chat_type == ChatType.P2P else "group"
        session_key = (
            f"project:{message.project_id}:channel:{message.channel}:config:{channel_config_id}:"
            f"{scope}:{message.chat_id}"
        )
        topic_id = self._extract_topic_id(message)
        if topic_id:
            session_key = f"{session_key}:topic:{topic_id}"
        thread_id = self._extract_thread_id(message)
        if thread_id:
            session_key = f"{session_key}:thread:{thread_id}"
        return session_key

    def _extract_thread_id(self, message: Message) -> Optional[str]:
        """Extract thread identifier from channel message payload."""
        if not isinstance(message.raw_data, dict):
            return None
        routing_meta = message.raw_data.get("_routing")
        if isinstance(routing_meta, dict):
            routing_thread_id = routing_meta.get("thread_id")
            if isinstance(routing_thread_id, str) and routing_thread_id:
                return routing_thread_id
        event = message.raw_data.get("event")
        if isinstance(event, dict):
            event_message = event.get("message")
            if isinstance(event_message, dict):
                for key in ("thread_id", "message_thread_id"):
                    value = event_message.get(key)
                    if isinstance(value, str) and value:
                        return value
        return None

    def _extract_topic_id(self, message: Message) -> Optional[str]:
        """Extract topic identifier from channel message payload."""
        if not isinstance(message.raw_data, dict):
            return None
        routing_meta = message.raw_data.get("_routing")
        if isinstance(routing_meta, dict):
            routing_topic_id = routing_meta.get("topic_id")
            if isinstance(routing_topic_id, str) and routing_topic_id:
                return routing_topic_id
        event = message.raw_data.get("event")
        if isinstance(event, dict):
            event_message = event.get("message")
            if isinstance(event_message, dict):
                value = event_message.get("topic_id")
                if isinstance(value, str) and value:
                    return value
        return None

    async def _send_error_reply(
        self,
        message: Message,
        error_message: str,
    ) -> None:
        """Send an error reply to the user via channel adapter.

        Args:
            message: Original message that caused the error
            error_message: Error message to send to user
        """
        try:
            # Get the channel adapter from connection manager
            from src.infrastructure.adapters.primary.web.startup.channels import (
                get_channel_manager,
            )

            manager = get_channel_manager()
            if not manager:
                logger.warning("[MessageRouter] Channel manager not available for error reply")
                return

            # Find the connection for this message's channel config
            # Extract channel_config_id from message raw_data
            channel_config_id = await self._resolve_channel_config_id_from_message(message)
            if not channel_config_id:
                logger.warning(
                    f"[MessageRouter] Cannot send error reply: channel_config_id not found"
                )
                return

            connection = manager.connections.get(channel_config_id)
            if not connection or not connection.adapter:
                logger.warning(
                    f"[MessageRouter] Connection not found for config {channel_config_id}"
                )
                return

            # Send error message
            await connection.adapter.send_text(
                to=message.chat_id,
                text=error_message,
                reply_to=self._extract_channel_message_id(message),
            )
            logger.info(f"[MessageRouter] Sent error reply to user: {error_message[:50]}...")

        except Exception as e:
            logger.error(
                f"[MessageRouter] Failed to send error reply: {e}",
                exc_info=True,
            )

    async def _resolve_channel_config_id_from_message(
        self,
        message: Message,
    ) -> Optional[str]:
        """Resolve channel config ID from message raw_data.

        Args:
            message: Channel message

        Returns:
            Channel config ID or None
        """
        try:
            if not message.raw_data:
                return None

            # Try different locations based on event type
            # Location 1: routing_metadata.channel_config_id
            routing_metadata = message.raw_data.get("routing_metadata", {})
            if isinstance(routing_metadata, dict):
                config_id = routing_metadata.get("channel_config_id")
                if isinstance(config_id, str) and config_id:
                    return config_id

            # Location 2: event.header.token (webhook)
            event = message.raw_data.get("event", {})
            if isinstance(event, dict):
                header = event.get("header", {})
                if isinstance(header, dict):
                    token = header.get("token")
                    if isinstance(token, str) and token:
                        return token

            return None

        except Exception as e:
            logger.error(f"[MessageRouter] Error resolving channel_config_id: {e}")
            return None


# Singleton instance
_router_instance: Optional[ChannelMessageRouter] = None


def get_channel_message_router() -> ChannelMessageRouter:
    """Get the singleton message router instance.

    This function creates the router with MediaImportService
    if all dependencies are available.
    """
    global _router_instance
    if _router_instance is None:
        # Try to create MediaImportService
        media_import_service = None
        try:
            from src.infrastructure.adapters.secondary.persistence.database import (
                async_session_factory,
            )
            from src.application.services.channels.channel_service_factory import (
                create_media_import_service_from_config,
            )

            async def _init_media_service():
                """Initialize media import service asynchronously."""
                try:
                    async with async_session_factory() as session:
                        service = await create_media_import_service_from_config(session)
                        if service:
                            logger.info(
                                "[MessageRouter] MediaImportService initialized successfully"
                            )
                        else:
                            logger.warning(
                                "[MessageRouter] MediaImportService initialization returned None - "
                                "no enabled Feishu channel config found"
                            )
                        return service
                except Exception as e:
                    logger.error(
                        f"[MessageRouter] Failed to initialize MediaImportService: {e}",
                        exc_info=True,
                    )
                    return None

            # Try to initialize synchronously if event loop is running
            try:
                import asyncio

                loop = asyncio.get_running_loop()
                # Create task to initialize media service
                # Note: This is a best-effort initialization; if it fails, media import will be disabled
                logger.info("[MessageRouter] Attempting to initialize MediaImportService...")
                # We can't await here in sync context, so we'll initialize lazily
                logger.warning(
                    "[MessageRouter] Cannot initialize MediaImportService in sync context - "
                    "will be initialized on first media message"
                )
            except RuntimeError:
                # No event loop running
                logger.info(
                    "[MessageRouter] No event loop running - "
                    "MediaImportService will be initialized lazily"
                )

        except Exception as e:
            logger.warning(
                f"[MessageRouter] Failed to create MediaImportService: {e}. Media import disabled."
            )

        _router_instance = ChannelMessageRouter(media_import_service=media_import_service)

    return _router_instance


async def route_channel_message(message: Message) -> None:
    """Convenience function to route a channel message.

    This function can be used as the message router callback
    for the ChannelConnectionManager.

    Args:
        message: The incoming channel message.
    """
    router = get_channel_message_router()
    await router.route_message(message)
