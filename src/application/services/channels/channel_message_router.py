"""Channel message router - routes IM messages to Agent system.

This module provides the routing logic to bridge incoming channel messages
(Feishu, DingTalk, WeCom, etc.) to the Agent conversation system.
"""

import logging
import uuid
from typing import TYPE_CHECKING, Any, Dict, Optional

from src.domain.model.channels.message import ChatType, Message

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


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

    def __init__(self) -> None:
        self._chat_to_conversation: Dict[str, str] = {}

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

            # Route to agent system
            await self._invoke_agent(message, conversation_id)

            logger.info(
                f"[MessageRouter] Message routed to conversation {conversation_id}"
            )

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
                    self._chat_to_conversation[session_key] = conversation_id

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
        from sqlalchemy import select

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
        await binding_repo.upsert(
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

                channel_message = ChannelMessageModel(
                    channel_config_id=channel_config_id,
                    project_id=message.project_id or "",
                    channel_message_id=channel_message_id,
                    chat_id=message.chat_id,
                    chat_type=message.chat_type.value,
                    sender_id=message.sender.id,
                    sender_name=message.sender.name,
                    message_type=message.content.type.value,
                    content_text=message.content.text,
                    content_data={
                        "conversation_id": conversation_id,
                        "channel_config_id": channel_config_id,
                        "reply_to": message.reply_to,
                        "mentions": message.mentions,
                    },
                    reply_to=message.reply_to,
                    mentions=message.mentions,
                    direction="inbound",
                    raw_data=message.raw_data,
                )

                await repo.create(channel_message)
                await session.commit()

        except Exception as e:
            logger.warning(f"[MessageRouter] Failed to store message history: {e}")

    async def _invoke_agent(self, message: Message, conversation_id: str) -> None:
        """Invoke the agent to process the message.

        This method triggers the agent to process the incoming message
        and generate a response.

        Args:
            message: The incoming message.
            conversation_id: The conversation to add the message to.
        """
        try:
            from src.configuration.factories import create_llm_client
            from src.infrastructure.adapters.primary.web.startup.container import get_app_container
            from src.infrastructure.adapters.secondary.persistence.database import (
                async_session_factory,
            )
            from src.infrastructure.adapters.secondary.persistence.models import Conversation

            # Get the message text
            text = message.content.text or ""

            if not text.strip():
                logger.debug("[MessageRouter] Empty message, skipping agent invocation")
                return

            async with async_session_factory() as session:
                conversation = await session.get(Conversation, conversation_id)
                if not conversation:
                    logger.error(
                        f"[MessageRouter] Conversation not found when invoking agent: {conversation_id}"
                    )
                    return

                app_container = get_app_container()
                if not app_container:
                    logger.error("[MessageRouter] App container is not initialized")
                    return

                llm = await create_llm_client(conversation.tenant_id)
                container = app_container.with_db(session)
                agent_service = container.agent_service(llm)

                logger.info(
                    f"[MessageRouter] Invoking agent for conversation {conversation_id}"
                )

                response_text = ""
                error_message: Optional[str] = None
                async for event in agent_service.stream_chat_v2(
                    conversation_id=conversation_id,
                    user_message=text,
                    project_id=conversation.project_id,
                    user_id=conversation.user_id,
                    tenant_id=conversation.tenant_id,
                    app_model_context=self._build_app_model_context(message),
                ):
                    event_type = event.get("type")
                    event_data = event.get("data") or {}

                    if event_type == "text_delta":
                        delta = event_data.get("delta", "")
                        if isinstance(delta, str):
                            response_text += delta
                    elif event_type == "assistant_message":
                        assistant_content = event_data.get("content")
                        if isinstance(assistant_content, str) and assistant_content.strip():
                            response_text = assistant_content
                    elif event_type == "complete":
                        complete_content = event_data.get("content") or event_data.get("result")
                        if isinstance(complete_content, str) and complete_content.strip():
                            response_text = complete_content
                    elif event_type == "error":
                        error_message = event_data.get("message") or "Unknown agent error"

                if error_message:
                    logger.error(
                        f"[MessageRouter] Agent returned error for conversation "
                        f"{conversation_id}: {error_message}"
                    )
                    return

                if response_text.strip():
                    await self._send_response(message, conversation_id, response_text)
                else:
                    logger.warning(
                        f"[MessageRouter] Agent produced empty response for conversation "
                        f"{conversation_id}"
                    )

        except Exception as e:
            logger.error(f"[MessageRouter] Agent invocation error: {e}", exc_info=True)

    async def _send_response(self, message: Message, conversation_id: str, response: str) -> None:
        """Send agent response back to the channel.

        Args:
            message: The original message (contains sender info).
            conversation_id: The associated conversation ID.
            response: The agent's response text.
        """
        try:
            from src.infrastructure.adapters.primary.web.startup import get_channel_manager

            channel_manager = get_channel_manager()
            if not channel_manager:
                logger.warning("[MessageRouter] No channel manager available")
                return

            channel_config_id = self._extract_channel_config_id(message)
            if not channel_config_id:
                channel_config_id = await self._get_conversation_channel_config_id(
                    conversation_id
                )

            if not channel_config_id:
                logger.warning(
                    "[MessageRouter] Missing channel_config_id; refusing outbound response to "
                    "avoid ambiguous routing"
                )
                return

            connection = channel_manager.connections.get(channel_config_id)
            if not connection:
                logger.warning(
                    "[MessageRouter] No active connection for outbound response: "
                    f"channel_config_id={channel_config_id}"
                )
                return

            inbound_message_id = self._extract_channel_message_id(message)
            sent_message_id = await connection.adapter.send_text(
                message.chat_id,
                response,
                reply_to=inbound_message_id,
            )
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
            logger.error(f"[MessageRouter] Error sending response: {e}")

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
            from src.infrastructure.adapters.secondary.persistence.database import (
                async_session_factory,
            )
            from src.infrastructure.adapters.secondary.persistence.channel_repository import (
                ChannelSessionBindingRepository,
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
                "[MessageRouter] Failed to load channel_config_id from conversation metadata: "
                f"{e}"
            )
        return None

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


# Singleton instance
_router_instance: Optional[ChannelMessageRouter] = None


def get_channel_message_router() -> ChannelMessageRouter:
    """Get the singleton message router instance."""
    global _router_instance
    if _router_instance is None:
        _router_instance = ChannelMessageRouter()
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
