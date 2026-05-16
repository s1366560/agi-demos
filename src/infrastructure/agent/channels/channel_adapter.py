"""Abstract channel adapter interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from src.infrastructure.agent.channels.channel_message import ChannelMessage


class TransportChannelAdapter(ABC):
    """Base class that every channel adapter must implement.

    A channel adapter translates between a specific transport protocol
    (WebSocket, REST, Feishu webhook, ...) and the unified
    :class:`ChannelMessage` representation consumed by the
    :class:`ChannelRouter`.

    Lifecycle::

        adapter = MyAdapter(...)
        await adapter.connect()
        try:
            async for msg in adapter.receive():
                response = process(msg)
                await adapter.send(response)
        finally:
            await adapter.disconnect()
    """

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------

    @property
    @abstractmethod
    def channel_type(self) -> str:
        """Return the channel type this adapter handles."""

    @property
    @abstractmethod
    def channel_id(self) -> str:
        """Return an opaque id that uniquely identifies this adapter instance."""

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @abstractmethod
    async def connect(self) -> None:
        """Establish the underlying transport connection (if any)."""

    @abstractmethod
    async def disconnect(self) -> None:
        """Tear down the transport connection and release resources."""

    # ------------------------------------------------------------------
    # Messaging
    # ------------------------------------------------------------------

    @abstractmethod
    def receive(self) -> AsyncIterator[ChannelMessage]:
        """Yield incoming messages from the transport.

        Implementations should ``yield`` each normalised
        :class:`ChannelMessage` as it arrives.  The iterator should
        terminate when the transport is closed or :meth:`disconnect`
        is called.
        """
        raise NotImplementedError

    @abstractmethod
    async def send(self, message: ChannelMessage) -> None:
        """Push a message back to the transport."""
