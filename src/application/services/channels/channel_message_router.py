"""Channel message router - routes IM messages to Agent system.

This module provides the routing logic to bridge incoming channel messages
(Feishu, DingTalk, WeCom, etc.) to the Agent conversation system.
"""

import logging
from typing import TYPE_CHECKING, Any, Dict, Optional

from src.domain.model.channels.message import Message, ChatType

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

        # Create a composite key for the chat
        chat_key = f"{message.project_id}:{message.channel}:{message.chat_id}"

        # Check cache first
        if chat_key in self._chat_to_conversation:
            return self._chat_to_conversation[chat_key]

        # Look up or create conversation in database
        try:
            from src.infrastructure.adapters.secondary.persistence.database import (
                async_session_factory,
            )

            async with async_session_factory() as session:
                conversation_id = await self._find_or_create_conversation_db(
                    session, message, chat_key
                )
                await session.commit()

                if conversation_id:
                    self._chat_to_conversation[chat_key] = conversation_id

                return conversation_id

        except Exception as e:
            logger.error(f"[MessageRouter] Database error: {e}")
            return None

    async def _find_or_create_conversation_db(
        self,
        session: "AsyncSession",
        message: Message,
        chat_key: str,
    ) -> Optional[str]:
        """Find or create conversation in database.

        Args:
            session: Database session.
            message: The incoming message.
            chat_key: Composite key for the chat.

        Returns:
            The conversation ID.
        """
        from sqlalchemy import select

        from src.infrastructure.adapters.secondary.persistence.models import (
            Conversation,
        )

        # Try to find existing conversation with matching metadata
        # We store the channel chat info in conversation metadata
        query = select(Conversation).where(
            Conversation.project_id == message.project_id,
        )
        result = await session.execute(query)
        conversations = result.scalars().all()

        # Look for conversation with matching channel metadata
        for conv in conversations:
            if conv.meta:
                conv_chat_key = conv.meta.get("channel_chat_key")
                if conv_chat_key == chat_key:
                    return conv.id

        # Create new conversation
        title = self._generate_conversation_title(message)

        new_conversation = Conversation(
            project_id=message.project_id,
            title=title,
            meta={
                "channel_chat_key": chat_key,
                "channel_type": message.channel,
                "chat_id": message.chat_id,
                "chat_type": message.chat_type.value,
                "sender_id": message.sender.id,
                "sender_name": message.sender.name,
            },
        )

        session.add(new_conversation)
        await session.flush()

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

                channel_message = ChannelMessageModel(
                    channel_config_id=message.channel,  # This should be the config ID
                    project_id=message.project_id or "",
                    channel_message_id="",  # Original message ID if available
                    chat_id=message.chat_id,
                    chat_type=message.chat_type.value,
                    sender_id=message.sender.id,
                    sender_name=message.sender.name,
                    message_type=message.content.type.value,
                    content_text=message.content.text,
                    content_data={
                        "conversation_id": conversation_id,
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
            from src.application.services.agent_service import AgentService
            from src.infrastructure.adapters.secondary.persistence.database import (
                async_session_factory,
            )

            # Get the message text
            text = message.content.text or ""

            if not text.strip():
                logger.debug("[MessageRouter] Empty message, skipping agent invocation")
                return

            async with async_session_factory() as session:
                agent_service = AgentService(session)

                # Call agent chat
                # Note: This is a simplified implementation
                # In production, you might want to:
                # 1. Stream the response
                # 2. Send the response back to the channel
                # 3. Handle errors gracefully

                logger.info(
                    f"[MessageRouter] Invoking agent for conversation {conversation_id}"
                )

                # For now, just log that we would invoke the agent
                # The actual implementation depends on how you want to handle
                # agent responses in the channel context
                logger.info(
                    f"[MessageRouter] Would process message: {text[:100]}..."
                )

                # TODO: Implement actual agent invocation and response handling
                # response = await agent_service.chat(
                #     conversation_id=conversation_id,
                #     message=text,
                #     project_id=message.project_id,
                # )
                #
                # # Send response back to channel
                # await self._send_response(message, response)

        except Exception as e:
            logger.error(f"[MessageRouter] Agent invocation error: {e}", exc_info=True)

    async def _send_response(self, message: Message, response: str) -> None:
        """Send agent response back to the channel.

        Args:
            message: The original message (contains sender info).
            response: The agent's response text.
        """
        try:
            from src.infrastructure.adapters.primary.web.startup import get_channel_manager

            channel_manager = get_channel_manager()
            if not channel_manager:
                logger.warning("[MessageRouter] No channel manager available")
                return

            # Find the connection for this channel
            # Note: This is a simplified implementation
            # In production, you'd need to map channel type to config ID

            logger.info(
                f"[MessageRouter] Would send response to {message.chat_id}: "
                f"{response[:100]}..."
            )

            # TODO: Implement actual response sending
            # connection = channel_manager.connections.get(config_id)
            # if connection and connection.adapter:
            #     await connection.adapter.send_text(message.chat_id, response)

        except Exception as e:
            logger.error(f"[MessageRouter] Error sending response: {e}")


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
