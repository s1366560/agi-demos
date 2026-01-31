"""
Async Event Dispatcher for WebSocket Streaming

Solves the backpressure problem where LLM produces events faster than
WebSocket can send them.

Design:
- Dual-channel queue: Delta (high-frequency, drop-able) + Critical (low-frequency, guaranteed)
- Asynchronous sender: Non-blocking event enqueue, dedicated sender task
- Smart delta merging: Combine consecutive TEXT_DELTA events when queue is full
- Timeout protection: WebSocket send has 5s timeout
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Literal, Optional, Set

logger = logging.getLogger(__name__)


# Event type classification
EventCategory = Literal["delta", "critical", "lifecycle"]

EVENT_CATEGORIES: Dict[str, EventCategory] = {
    # High-frequency events - can be dropped/throttled
    "text_delta": "delta",
    "thought_delta": "delta",
    "tool_call_delta": "delta",

    # Critical events - must be delivered
    "text_start": "critical",
    "text_end": "critical",
    "thought_start": "critical",
    "thought_end": "critical",
    "tool_call_start": "critical",
    "tool_call_end": "critical",
    "step_start": "critical",
    "step_end": "critical",
    "complete": "critical",
    "error": "critical",

    # Lifecycle events
    "heartbeat": "lifecycle",
    "status": "lifecycle",
}


@dataclass
class DispatcherConfig:
    """Configuration for EventDispatcher."""

    # Delta channel (high-frequency, drop-able)
    delta_queue_size: int = 500
    delta_merge_threshold: int = 400  # Start merging when queue is 80% full
    delta_send_coalesce_ms: int = 50  # Max time to wait before sending deltas

    # Critical channel (low-frequency, guaranteed)
    critical_queue_size: int = 100

    # Send timeout
    send_timeout: float = 5.0  # seconds

    # Retry for critical events
    critical_max_retries: int = 3
    critical_retry_delay: float = 0.1  # seconds


@dataclass
class QueuedEvent:
    """An event waiting in queue."""

    data: Dict[str, Any]
    category: EventCategory
    enqueue_time: float = field(default_factory=asyncio.get_event_loop().time)
    retry_count: int = 0


class EventDispatcher:
    """
    Async event dispatcher with dual-channel queues.

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

        # Dual queues
        self.delta_queue: asyncio.Queue[QueuedEvent] = asyncio.Queue(
            maxsize=self.config.delta_queue_size
        )
        self.critical_queue: asyncio.Queue[QueuedEvent] = asyncio.Queue(
            maxsize=self.config.critical_queue_size
        )

        # Sender task
        self.sender_task: Optional[asyncio.Task] = None
        self.running = False

        # Statistics
        self.stats = {
            "enqueued": 0,
            "sent": 0,
            "dropped": 0,
            "merged": 0,
            "retried": 0,
            "failed": 0,
        }
        self._delta_buffer: list[QueuedEvent] = []

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

        # Try to flush critical events
        await self._flush_critical()

        logger.debug(
            f"[Dispatcher] Stopped for session {self.session_id[:8]}... "
            f"Stats: {self.stats}"
        )

    async def enqueue(self, event: Dict[str, Any]) -> bool:
        """
        Enqueue an event for sending.

        Returns:
            bool: True if enqueued, False if dropped
        """
        event_type = event.get("type", "unknown")
        category = EVENT_CATEGORIES.get(event_type, "critical")

        queued = QueuedEvent(data=event, category=category)

        if category == "delta":
            return await self._enqueue_delta(queued)
        else:
            return await self._enqueue_critical(queued)

    async def _enqueue_delta(self, event: QueuedEvent) -> bool:
        """Enqueue a delta event with drop-if-full strategy."""
        try:
            # Try to put without blocking
            self.delta_queue.put_nowait(event)
            self.stats["enqueued"] += 1
            return True
        except asyncio.QueueFull:
            # Queue full - drop oldest
            try:
                self.delta_queue.get_nowait()
                self.delta_queue.put_nowait(event)
                self.stats["dropped"] += 1
                return True
            except asyncio.QueueEmpty:
                self.stats["dropped"] += 1
                return False

    async def _enqueue_critical(self, event: QueuedEvent) -> bool:
        """Enqueue a critical event with backpressure (blocks if full)."""
        try:
            await asyncio.wait_for(
                self.critical_queue.put(event),
                timeout=30.0,  # Max 30s wait
            )
            self.stats["enqueued"] += 1
            return True
        except asyncio.TimeoutError:
            logger.error(
                f"[Dispatcher] Critical queue full for {self.session_id[:8]}..., "
                f"event type: {event.data.get('type')}"
            )
            self.stats["dropped"] += 1
            return False

    async def _sender_loop(self) -> None:
        """Main sender loop with priority handling."""
        while self.running:
            try:
                # Wait for events with timeout (for periodic flush)
                event = await self._get_next_event(timeout=0.1)
                if event:
                    await self._send_event(event)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[Dispatcher] Sender loop error: {e}", exc_info=True)
                await asyncio.sleep(0.1)

    async def _get_next_event(
        self, timeout: float = 0.1
    ) -> Optional[QueuedEvent]:
        """Get next event, preferring critical over delta."""
        # Check critical queue first (non-blocking)
        try:
            return self.critical_queue.get_nowait()
        except asyncio.QueueEmpty:
            pass

        # Check delta queue (non-blocking)
        try:
            return self.delta_queue.get_nowait()
        except asyncio.QueueEmpty:
            pass

        # Wait for any event
        try:
            return await asyncio.wait_for(
                self._wait_for_any_event(),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            # Periodically flush delta buffer
            if self._delta_buffer:
                return self._flush_delta_buffer()
            return None

    async def _wait_for_any_event(self) -> QueuedEvent:
        """Wait for any event to arrive."""
        critical_done = asyncio.Event()
        delta_done = asyncio.Event()

        async def wait_critical():
            try:
                await self.critical_queue.get()
            except asyncio.CancelledError:
                pass
            else:
                critical_done.set()

        async def wait_delta():
            try:
                await self.delta_queue.get()
            except asyncio.CancelledError:
                pass
            else:
                delta_done.set()

        # Race between the two queues
        crit_task = asyncio.create_task(wait_critical())
        delta_task = asyncio.create_task(wait_delta())

        done, pending = await asyncio.wait(
            {crit_task, delta_task},
            return_when=asyncio.FIRST_COMPLETED,
        )

        # Cancel pending tasks
        for task in pending:
            task.cancel()

        # Return whichever completed first
        if critical_done.is_set():
            try:
                return self.critical_queue.get_nowait()
            except asyncio.QueueEmpty:
                pass

        try:
            return self.delta_queue.get_nowait()
        except asyncio.QueueEmpty:
            # This shouldn't happen, but return empty event
            return QueuedEvent(data={}, category="lifecycle")

    async def _send_event(self, event: QueuedEvent) -> bool:
        """Send an event with timeout and retry for critical events."""
        try:
            async with asyncio.timeout(self.config.send_timeout):
                await self.websocket.send_json(event.data)
            self.stats["sent"] += 1
            return True

        except Exception as e:
            logger.warning(
                f"[Dispatcher] Send failed for {self.session_id[:8]}...: "
                f"type={event.data.get('type')}, error={e}"
            )

            # Retry critical events
            if event.category == "critical" and event.retry_count < self.config.critical_max_retries:
                event.retry_count += 1
                await asyncio.sleep(self.config.critical_retry_delay * event.retry_count)
                return await self._send_event(event)

            self.stats["failed"] += 1
            return False

    def _flush_delta_buffer(self) -> Optional[QueuedEvent]:
        """Flush accumulated delta events as merged event."""
        if not self._delta_buffer:
            return None

        # Merge text deltas
        merged_text = ""
        for ev in self._delta_buffer:
            delta = ev.data.get("data", {}).get("delta", "")
            if isinstance(delta, str):
                merged_text += delta

        self.stats["merged"] += len(self._delta_buffer)
        self._delta_buffer.clear()

        if merged_text:
            return QueuedEvent(
                data={
                    "type": "text_delta",
                    "data": {"delta": merged_text},
                },
                category="delta",
            )
        return None

    async def _flush_critical(self) -> None:
        """Flush remaining critical events before shutdown."""
        while not self.critical_queue.empty():
            try:
                event = self.critical_queue.get_nowait()
                await self._send_event(event)
            except Exception:
                break

    def get_stats(self) -> Dict[str, Any]:
        """Get dispatcher statistics."""
        return {
            **self.stats,
            "delta_queue_size": self.delta_queue.qsize(),
            "critical_queue_size": self.critical_queue.qsize(),
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
