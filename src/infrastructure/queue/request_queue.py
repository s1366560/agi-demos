"""
Request queuing for expensive operations.

Provides a queue-based system for handling expensive operations (like LLM calls)
to prevent overwhelming the system during high load.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional
from uuid import uuid

from src.configuration.config import get_settings

logger = logging.getLogger(__name__)


class QueuedRequest:
    """A request waiting in the queue."""

    def __init__(
        self,
        request_id: str,
        func: Callable[..., Awaitable[Any]],
        args: tuple,
        kwargs: dict,
        priority: int = 0,
    ):
        self.request_id = request_id
        self.func = func
        self.args = args
        self.kwargs = kwargs
        self.priority = priority  # Higher = processed first
        self.created_at = datetime.now(timezone.utc)
        self.future: asyncio.Future[Any] = asyncio.Future()
        self.started_at: Optional[datetime] = None
        self.completed_at: Optional[datetime] = None


class RequestQueue:
    """
    Queue for managing expensive requests.

    Features:
    - Priority-based processing
    - Concurrent worker limit
    - Queue size limits with rejection
    - Timeout support
    """

    def __init__(
        self,
        max_concurrent: int = 10,
        max_queue_size: int = 100,
        request_timeout: int = 300,  # 5 minutes
    ):
        """
        Initialize the request queue.

        Args:
            max_concurrent: Maximum concurrent requests being processed
            max_queue_size: Maximum requests waiting in queue
            request_timeout: Default timeout for queued requests
        """
        self._queue: list[QueuedRequest] = []
        self._processing: dict[str, QueuedRequest] = {}
        self._max_concurrent = max_concurrent
        self._max_queue_size = max_queue_size
        self._request_timeout = request_timeout
        self._workers: list[asyncio.Task] = []
        self._running = False

    def _get_next_request(self) -> Optional[QueuedRequest]:
        """Get the next highest-priority request from the queue."""
        if not self._queue:
            return None
        # Sort by priority (higher first) then creation time (older first)
        self._queue.sort(key=lambda r: (-r.priority, r.created_at))
        return self._queue.pop(0)

    async def _worker(self, worker_id: int) -> None:
        """Worker that processes queued requests."""
        logger.info(f"Request queue worker {worker_id} started")

        while self._running:
            # Check if we can process more
            if len(self._processing) >= self._max_concurrent:
                await asyncio.sleep(0.1)
                continue

            # Get next request
            request = self._get_next_request()
            if not request:
                await asyncio.sleep(0.1)
                continue

            # Process the request
            self._processing[request.request_id] = request
            request.started_at = datetime.now(timezone.utc)

            try:
                # Execute with timeout
                result = await asyncio.wait_for(
                    request.func(*request.args, **request.kwargs),
                    timeout=self._request_timeout,
                )
                request.future.set_result(result)
                logger.debug(
                    f"Request {request.request_id} completed in "
                    f"{(request.completed_at - request.started_at).total_seconds():.2f}s"
                )
            except asyncio.TimeoutError:
                request.future.set_exception(TimeoutError("Request timed out"))
                logger.warning(f"Request {request.request_id} timed out")
            except Exception as e:
                request.future.set_exception(e)
                logger.error(f"Request {request.request_id} failed: {e}")
            finally:
                request.completed_at = datetime.now(timezone.utc)
                del self._processing[request.request_id]

    async def enqueue(
        self,
        func: Callable[..., Awaitable[Any]],
        args: tuple = (),
        kwargs: dict | None = None,
        priority: int = 0,
    ) -> Any:
        """
        Enqueue a request to be processed.

        Args:
            func: Async function to execute
            args: Positional arguments for the function
            kwargs: Keyword arguments for the function
            priority: Request priority (higher = processed first)

        Returns:
            Result of the function call

        Raises:
            QueueFullError: If the queue is at capacity
        """
        if kwargs is None:
            kwargs = {}

        # Check queue size
        if len(self._queue) >= self._max_queue_size:
            raise QueueFullError(f"Request queue is full ({self._max_queue_size} requests)")

        request_id = str(uuid.uuid4())
        request = QueuedRequest(request_id, func, args, kwargs, priority)
        self._queue.append(request)

        logger.debug(
            f"Enqueued request {request_id} "
            f"(queue size: {len(self._queue)}, processing: {len(self._processing)})"
        )

        # Wait for result
        return await request.future

    def start(self) -> None:
        """Start the request queue workers."""
        if self._running:
            return

        self._running = True
        for i in range(self._max_concurrent):
            task = asyncio.create_task(self._worker(i))
            self._workers.append(task)

        logger.info(f"Request queue started with {self._max_concurrent} workers")

    async def stop(self) -> None:
        """Stop the request queue workers."""
        if not self._running:
            return

        self._running = False

        # Cancel all workers
        for worker in self._workers:
            worker.cancel()

        # Wait for workers to finish
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()

        # Fail remaining queued requests
        for request in self._queue:
            request.future.set_exception(RuntimeError("Queue is shutting down"))

        logger.info("Request queue stopped")

    def get_stats(self) -> dict[str, Any]:
        """Get queue statistics."""
        return {
            "queue_size": len(self._queue),
            "processing": len(self._processing),
            "max_concurrent": self._max_concurrent,
            "max_queue_size": self._max_queue_size,
            "workers": len(self._workers),
            "running": self._running,
        }


class QueueFullError(Exception):
    """Raised when the request queue is at capacity."""

    pass


# Global request queue instance
_request_queue: Optional[RequestQueue] = None


def get_request_queue() -> RequestQueue:
    """Get or create the global request queue instance."""
    global _request_queue
    if _request_queue is None:
        settings = get_settings()
        _request_queue = RequestQueue(
            max_concurrent=settings.max_async_workers,
            max_queue_size=100,
            request_timeout=settings.llm_timeout,
        )
        _request_queue.start()
    return _request_queue
