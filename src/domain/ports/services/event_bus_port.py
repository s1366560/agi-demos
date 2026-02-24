from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any


class EventBusPort(ABC):
    """Port for event bus operations (Pub/Sub and Stream)."""

    @abstractmethod
    async def publish(self, channel: str, message: dict[str, Any]) -> int:
        """
        Publish a message to a channel (Pub/Sub).

        Args:
            channel: Channel name
            message: Message data (will be serialized to JSON)

        Returns:
            Number of subscribers that received the message
        """

    @abstractmethod
    async def subscribe(self, channel: str) -> AsyncIterator[dict[str, Any]]:
        """
        Subscribe to a channel (Pub/Sub).

        Args:
            channel: Channel name

        Returns:
            Async iterator yielding messages
        """

    # =========================================================================
    # Redis Stream methods for reliable message delivery
    # =========================================================================

    @abstractmethod
    async def stream_add(
        self,
        stream_key: str,
        message: dict[str, Any],
        maxlen: int | None = None,
    ) -> str:
        """
        Add a message to a Redis Stream.

        Args:
            stream_key: Stream key name
            message: Message data (will be serialized to JSON)
            maxlen: Optional max length for stream trimming (approximate)

        Returns:
            Message ID assigned by Redis
        """

    @abstractmethod
    async def stream_read(
        self,
        stream_key: str,
        last_id: str = "0",
        count: int | None = None,
        block_ms: int | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """
        Read messages from a Redis Stream.

        Args:
            stream_key: Stream key name
            last_id: Last message ID to start reading from (exclusive)
            count: Max number of messages to return per call
            block_ms: Block timeout in milliseconds (None = non-blocking)

        Yields:
            Message dictionaries with 'id' and 'data' fields
        """

    @abstractmethod
    async def stream_read_group(
        self,
        stream_key: str,
        group_name: str,
        consumer_name: str,
        last_id: str = ">",
        count: int | None = None,
        block_ms: int | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """
        Read messages from a Redis Stream using consumer groups.

        Consumer groups provide:
        - Message acknowledgment
        - Pending entry list for failed consumers
        - Automatic load balancing across consumers

        Args:
            stream_key: Stream key name
            group_name: Consumer group name
            consumer_name: Consumer name within the group
            last_id: ">" for new messages only, "0" for pending messages
            count: Max number of messages to return per call
            block_ms: Block timeout in milliseconds

        Yields:
            Message dictionaries with 'id' and 'data' fields
        """

    @abstractmethod
    async def stream_ack(
        self,
        stream_key: str,
        group_name: str,
        message_ids: list[str],
    ) -> int:
        """
        Acknowledge messages in a consumer group.

        Args:
            stream_key: Stream key name
            group_name: Consumer group name
            message_ids: List of message IDs to acknowledge

        Returns:
            Number of messages acknowledged
        """

    @abstractmethod
    async def stream_create_group(
        self,
        stream_key: str,
        group_name: str,
        start_id: str = "$",
        mkstream: bool = True,
    ) -> bool:
        """
        Create a consumer group for a stream.

        Args:
            stream_key: Stream key name
            group_name: Consumer group name
            start_id: Starting message ID ("$" = only new messages, "0" = all messages)
            mkstream: Create the stream if it doesn't exist

        Returns:
            True if created successfully
        """

    @abstractmethod
    async def stream_pending(
        self,
        stream_key: str,
        group_name: str,
        count: int = 10,
    ) -> list[dict[str, Any]]:
        """
        Get pending messages for a consumer group (messages not yet acknowledged).

        Args:
            stream_key: Stream key name
            group_name: Consumer group name
            count: Max number of pending entries to return

        Returns:
            List of pending message info
        """

    @abstractmethod
    async def stream_claim(
        self,
        stream_key: str,
        group_name: str,
        consumer_name: str,
        min_idle_ms: int,
        message_ids: list[str],
    ) -> list[dict[str, Any]]:
        """
        Claim pending messages from another consumer (for recovery).

        Args:
            stream_key: Stream key name
            group_name: Consumer group name
            consumer_name: Consumer to claim messages for
            min_idle_ms: Minimum idle time for messages to be claimable
            message_ids: List of message IDs to claim

        Returns:
            List of claimed messages
        """

    @abstractmethod
    async def stream_len(self, stream_key: str) -> int:
        """
        Get the length of a stream.

        Args:
            stream_key: Stream key name

        Returns:
            Number of messages in the stream
        """

    @abstractmethod
    async def stream_trim(
        self,
        stream_key: str,
        maxlen: int,
        approximate: bool = True,
    ) -> int:
        """
        Trim a stream to a maximum length.

        Args:
            stream_key: Stream key name
            maxlen: Maximum number of messages to keep
            approximate: Use approximate trimming (faster)

        Returns:
            Number of messages removed
        """
