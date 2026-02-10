"""
Async Event Dispatcher for WebSocket Streaming

Solves the backpressure problem where LLM produces events faster than
WebSocket can send them.

Design:
- Single unified queue with configurable size
- Asynchronous sender: Non-blocking event enqueue, dedicated sender task
- Drop oldest strategy when queue is full
- Timeout protection: WebSocket send has 5s timeout
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class DispatcherConfig:
    """Configuration for EventDispatcher."""

    # Queue size
    queue_size: int = 1000

    # Send timeout
    send_timeout: float = 5.0  # seconds

    # Retry settings
    max_retries: int = 3
    retry_delay: float = 0.1  # seconds


@dataclass
class QueuedEvent:
    """An event waiting in queue."""

    data: Dict[str, Any]
    enqueue_time: float = field(default_factory=lambda: asyncio.get_event_loop().time())
    retry_count: int = 0


class EventDispatcher:
    """
    Async event dispatcher with single queue.

    Usage:
        dispatcher = EventDispatcher(session_id, websocket, config)
        await dispatcher.start()

        # Enqueue events (non-blocking)
        await dispatcher.enqueue(event)

        # Stop when done
        await dispatcher.stop()
    """

    def __init__(
        self,
        session_id: str,
        websocket: Any,
        config: Optional[DispatcherConfig] = None,
    ):
        self.session_id = session_id
        self.websocket = websocket
        self.config = config or DispatcherConfig()

        # Single queue
        self.queue: asyncio.Queue[QueuedEvent] = asyncio.Queue(maxsize=self.config.queue_size)

        # Sender task
        self.sender_task: Optional[asyncio.Task] = None
        self.running = False

        # Statistics
        self.stats = {
            "enqueued": 0,
            "sent": 0,
            "dropped": 0,
            "retried": 0,
            "failed": 0,
        }

    async def start(self) -> None:
        """Start the sender loop."""
        if self.sender_task and not self.sender_task.done():
            return

        self.running = True
        self.sender_task = asyncio.create_task(self._sender_loop())
        logger.debug(f"[Dispatcher] Started for session {self.session_id[:8]}...")

    async def stop(self) -> None:
        """Stop the dispatcher and flush remaining events."""
        self.running = False

        if self.sender_task:
            sender_task = self.sender_task
            self.sender_task = None
            sender_task.cancel()
            try:
                await sender_task
            except asyncio.CancelledError:
                pass

        # Try to flush remaining events
        await self._flush_remaining()

        logger.debug(
            f"[Dispatcher] Stopped for session {self.session_id[:8]}... Stats: {self.stats}"
        )

    async def enqueue(self, event: Dict[str, Any]) -> bool:
        """
        Enqueue an event for sending.

        Returns:
            bool: True if enqueued, False if dropped
        """
        queued = QueuedEvent(data=event)

        try:
            # Try to put without blocking
            self.queue.put_nowait(queued)
            self.stats["enqueued"] += 1
            return True
        except asyncio.QueueFull:
            # Queue full - drop oldest to make room
            try:
                self.queue.get_nowait()
                self.queue.put_nowait(queued)
                self.stats["dropped"] += 1
                self.stats["enqueued"] += 1
                return True
            except asyncio.QueueEmpty:
                self.stats["dropped"] += 1
                return False

    async def _sender_loop(self) -> None:
        """Main sender loop."""
        while self.running:
            try:
                # Wait for event with timeout
                try:
                    event = await asyncio.wait_for(self.queue.get(), timeout=0.1)
                    await self._send_event(event)
                except asyncio.TimeoutError:
                    # No events, continue loop
                    pass
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[Dispatcher] Sender loop error: {e}", exc_info=True)
                await asyncio.sleep(0.1)

    async def _send_event(self, event: QueuedEvent) -> bool:
        """Send an event with timeout and retry."""
        try:
            async with asyncio.timeout(self.config.send_timeout):
                await self.websocket.send_json(event.data)
            self.stats["sent"] += 1
            return True

        except RuntimeError as e:
            # WebSocket already closed - no point retrying
            if "websocket.close" in str(e) or "already completed" in str(e):
                logger.debug(
                    f"[Dispatcher] WebSocket closed for {self.session_id[:8]}..., "
                    f"dropping event type={event.data.get('type')}"
                )
                self.stats["failed"] += 1
                return False
            raise

        except asyncio.TimeoutError:
            # Delta events are ephemeral — drop on timeout instead of retrying
            event_type = event.data.get("type", "")
            if "delta" in event_type:
                self.stats["failed"] += 1
                return False

            # Non-delta events: retry
            if event.retry_count < self.config.max_retries:
                event.retry_count += 1
                self.stats["retried"] += 1
                await asyncio.sleep(self.config.retry_delay * event.retry_count)
                return await self._send_event(event)

            logger.warning(
                f"[Dispatcher] Send timeout for {self.session_id[:8]}...: type={event_type}"
            )
            self.stats["failed"] += 1
            return False

        except Exception as e:
            logger.warning(
                f"[Dispatcher] Send failed for {self.session_id[:8]}...: "
                f"type={event.data.get('type')}, error={type(e).__name__}: {e}"
            )

            # Retry on failure
            if event.retry_count < self.config.max_retries:
                event.retry_count += 1
                self.stats["retried"] += 1
                await asyncio.sleep(self.config.retry_delay * event.retry_count)
                return await self._send_event(event)

            self.stats["failed"] += 1
            return False

    async def _flush_remaining(self) -> None:
        """Flush remaining events before shutdown."""
        while not self.queue.empty():
            try:
                event = self.queue.get_nowait()
                await self._send_event(event)
            except Exception:
                break

    def get_stats(self) -> Dict[str, Any]:
        """Get dispatcher statistics."""
        return {
            **self.stats,
            "queue_size": self.queue.qsize(),
        }


class DispatcherManager:
    """Manages multiple EventDispatcher instances."""

    def __init__(self):
        self.dispatchers: Dict[str, EventDispatcher] = {}

    async def get_dispatcher(
        self,
        session_id: str,
        websocket: Any,
        config: Optional[DispatcherConfig] = None,
    ) -> EventDispatcher:
        """Get or create a dispatcher for the session."""
        if session_id not in self.dispatchers:
            dispatcher = EventDispatcher(session_id, websocket, config)
            await dispatcher.start()
            self.dispatchers[session_id] = dispatcher
        return self.dispatchers[session_id]

    async def remove_dispatcher(self, session_id: str) -> None:
        """Remove and stop a dispatcher."""
        if session_id in self.dispatchers:
            await self.dispatchers[session_id].stop()
            del self.dispatchers[session_id]

    async def cleanup_session(self, session_id: str) -> None:
        """Clean up dispatcher for a session."""
        await self.remove_dispatcher(session_id)

    def get_all_stats(self) -> Dict[str, Dict[str, Any]]:
        """Get stats for all dispatchers."""
        return {
            session_id: dispatcher.get_stats()
            for session_id, dispatcher in self.dispatchers.items()
        }


# Global singleton
_dispatcher_manager: Optional[DispatcherManager] = None


def get_dispatcher_manager() -> DispatcherManager:
    """Get the global dispatcher manager."""
    global _dispatcher_manager
    if _dispatcher_manager is None:
        _dispatcher_manager = DispatcherManager()
    return _dispatcher_manager
