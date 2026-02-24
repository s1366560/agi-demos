"""Channel application service - orchestrates channel operations."""

import logging
from collections.abc import Callable
from typing import Any

from src.domain.model.channels.message import (
    ChannelAdapter,
    Message,
    MessageContent,
    SenderInfo,
)

logger = logging.getLogger(__name__)

MessageHandler = Callable[[Message], None]
ErrorHandler = Callable[[str, Exception], None]


class ChannelService:
    """Application service for managing communication channels.
    
    This service orchestrates multiple channel adapters and provides
    a unified interface for sending/receiving messages across different
    IM platforms (Feishu, DingTalk, WeCom, etc.).
    
    Usage:
        service = ChannelService()
        
        # Register adapters
        service.register_adapter(feishu_adapter)
        service.register_adapter(dingtalk_adapter)
        
        # Connect all
        await service.connect_all()
        
        # Send message
        await service.send_text("feishu", "oc_xxx", "Hello!")
        
        # Broadcast to all channels
        await service.broadcast("oc_xxx", "Hello everyone!")
    """
    
    def __init__(self) -> None:
        self._adapters: dict[str, ChannelAdapter] = {}
        self._message_handlers: list[MessageHandler] = []
        self._error_handlers: list[ErrorHandler] = []
    
    def register_adapter(self, adapter: ChannelAdapter) -> None:
        """Register a channel adapter."""
        if adapter.id in self._adapters:
            raise ValueError(f"Adapter '{adapter.id}' is already registered")
        
        self._adapters[adapter.id] = adapter
        
        # Set up message forwarding
        adapter.on_message(self._handle_message)
        adapter.on_error(lambda e: self._handle_error(adapter.id, e))
        
        logger.info(f"Registered channel adapter: {adapter.name} ({adapter.id})")
    
    def unregister_adapter(self, adapter_id: str) -> None:
        """Unregister a channel adapter."""
        if adapter_id in self._adapters:
            adapter = self._adapters.pop(adapter_id)
            logger.info(f"Unregistered channel adapter: {adapter.name}")
    
    def get_adapter(self, adapter_id: str) -> ChannelAdapter | None:
        """Get a registered adapter by ID."""
        return self._adapters.get(adapter_id)
    
    def list_adapters(self) -> list[ChannelAdapter]:
        """List all registered adapters."""
        return list(self._adapters.values())
    
    async def connect_all(self) -> None:
        """Connect all registered adapters."""
        for adapter in self._adapters.values():
            try:
                await adapter.connect()
                logger.info(f"Connected to {adapter.name}")
            except Exception as e:
                logger.error(f"Failed to connect to {adapter.name}: {e}")
                self._handle_error(adapter.id, e)
    
    async def disconnect_all(self) -> None:
        """Disconnect all registered adapters."""
        for adapter in self._adapters.values():
            try:
                await adapter.disconnect()
                logger.info(f"Disconnected from {adapter.name}")
            except Exception as e:
                logger.error(f"Error disconnecting from {adapter.name}: {e}")
    
    async def send_message(
        self,
        channel_id: str,
        to: str,
        content: MessageContent,
        reply_to: str | None = None
    ) -> str | None:
        """Send a message through a specific channel.
        
        Returns:
            Message ID if sent successfully, None otherwise.
        """
        adapter = self._adapters.get(channel_id)
        if not adapter:
            logger.error(f"Channel not found: {channel_id}")
            return None
        
        if not adapter.connected:
            logger.error(f"Channel not connected: {channel_id}")
            return None
        
        try:
            message_id = await adapter.send_message(to, content, reply_to)
            logger.debug(f"Sent message to {channel_id}: {message_id}")
            return message_id
        except Exception as e:
            logger.error(f"Failed to send message via {channel_id}: {e}")
            self._handle_error(channel_id, e)
            return None
    
    async def send_text(
        self,
        channel_id: str,
        to: str,
        text: str,
        reply_to: str | None = None
    ) -> str | None:
        """Send a text message (convenience method)."""
        content = MessageContent(type="text", text=text)
        return await self.send_message(channel_id, to, content, reply_to)
    
    async def broadcast(
        self,
        to: str,
        content: MessageContent,
        channels: list[str] | None = None
    ) -> dict[str, str | None]:
        """Broadcast a message to multiple channels.
        
        Args:
            to: Recipient ID
            content: Message content
            channels: List of channel IDs (None = all channels)
            
        Returns:
            Dict mapping channel_id to message_id (or None if failed)
        """
        target_channels = (
            [self._adapters[c] for c in channels if c in self._adapters]
            if channels
            else list(self._adapters.values())
        )
        
        results: dict[str, str | None] = {}
        for adapter in target_channels:
            if adapter.connected:
                try:
                    message_id = await adapter.send_message(to, content)
                    results[adapter.id] = message_id
                except Exception as e:
                    logger.error(f"Broadcast failed to {adapter.name}: {e}")
                    results[adapter.id] = None
            else:
                results[adapter.id] = None
        
        return results
    
    def on_message(self, handler: MessageHandler) -> Callable[[], None]:
        """Register a message handler.
        
        Returns a function to unregister the handler.
        """
        self._message_handlers.append(handler)
        
        def unregister() -> None:
            self._message_handlers.remove(handler)
        
        return unregister
    
    def on_error(self, handler: ErrorHandler) -> Callable[[], None]:
        """Register an error handler."""
        self._error_handlers.append(handler)
        
        def unregister() -> None:
            self._error_handlers.remove(handler)
        
        return unregister
    
    def _handle_message(self, message: Message) -> None:
        """Internal handler for incoming messages."""
        logger.debug(f"Received message from {message.channel}: {message.content.text[:50]}")
        
        for handler in self._message_handlers:
            try:
                handler(message)
            except Exception as e:
                logger.error(f"Message handler error: {e}")
    
    def _handle_error(self, channel_id: str, error: Exception) -> None:
        """Internal handler for channel errors."""
        logger.error(f"Channel error ({channel_id}): {error}")
        
        for handler in self._error_handlers:
            try:
                handler(channel_id, error)
            except Exception as e:
                logger.error(f"Error handler error: {e}")
    
    async def get_chat_members(
        self,
        channel_id: str,
        chat_id: str
    ) -> list[Any]:
        """Get members of a chat group."""
        adapter = self._adapters.get(channel_id)
        if not adapter:
            raise ValueError(f"Channel not found: {channel_id}")
        
        return await adapter.get_chat_members(chat_id)
    
    async def get_user_info(
        self,
        channel_id: str,
        user_id: str
    ) -> SenderInfo | None:
        """Get user information."""
        adapter = self._adapters.get(channel_id)
        if not adapter:
            raise ValueError(f"Channel not found: {channel_id}")
        
        return await adapter.get_user_info(user_id)
