"""Event Router - Routes events to registered handlers.

The EventRouter provides pattern-based event routing to multiple handlers.
It supports:
- Exact pattern matching
- Wildcard patterns (*, ?)
- Multiple handlers per pattern
- Async handler execution

Usage:
    router = EventRouter()

    # Register handlers
    @router.handler("agent.*")
    async def handle_agent_events(event):
        print(f"Agent event: {event.envelope.event_type}")

    @router.handler("hitl.decision.*")
    async def handle_decisions(event):
        print(f"Decision: {event}")

    # Route events
    await router.route(event)
"""

import asyncio
import fnmatch
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from src.domain.ports.services.unified_event_bus_port import EventWithMetadata

logger = logging.getLogger(__name__)


# Type for event handlers
EventHandler = Callable[[EventWithMetadata], Awaitable[None]]


@dataclass
class HandlerRegistration:
    """Registration info for an event handler.

    Attributes:
        pattern: Pattern to match routing keys
        handler: Async handler function
        name: Optional handler name for logging
        priority: Higher priority handlers execute first
        filter_fn: Optional filter function
    """

    pattern: str
    handler: EventHandler
    name: str | None = None
    priority: int = 0
    filter_fn: Callable[[EventWithMetadata], bool] | None = None

    def matches(self, routing_key: str) -> bool:
        """Check if the pattern matches a routing key."""
        return fnmatch.fnmatch(routing_key, self.pattern)

    def should_handle(self, event: EventWithMetadata) -> bool:
        """Check if this handler should handle the event."""
        if not self.matches(event.routing_key):
            return False
        return not (self.filter_fn and not self.filter_fn(event))


@dataclass
class RoutingResult:
    """Result of routing an event.

    Attributes:
        event: The routed event
        handlers_invoked: Number of handlers that processed the event
        errors: List of (handler_name, error) for failed handlers
        handled: Whether at least one handler succeeded
    """

    event: EventWithMetadata
    handlers_invoked: int = 0
    errors: list[tuple[str, Exception]] = field(default_factory=list)

    @property
    def handled(self) -> bool:
        return self.handlers_invoked > 0

    @property
    def success(self) -> bool:
        return self.handled and len(self.errors) == 0


class EventRouter:
    """Event router for pattern-based event distribution.

    Supports registering multiple handlers for patterns and routing
    events to matching handlers.
    """

    def __init__(
        self,
        *,
        parallel_execution: bool = False,
        continue_on_error: bool = True,
        max_handlers_per_event: int = 100,
    ) -> None:
        """Initialize the event router.

        Args:
            parallel_execution: Execute handlers in parallel (default: sequential)
            continue_on_error: Continue routing on handler errors
            max_handlers_per_event: Maximum handlers to invoke per event
        """
        self._handlers: list[HandlerRegistration] = []
        self._parallel = parallel_execution
        self._continue_on_error = continue_on_error
        self._max_handlers = max_handlers_per_event
        self._metrics = RouterMetrics()

    def register(
        self,
        pattern: str,
        handler: EventHandler,
        *,
        name: str | None = None,
        priority: int = 0,
        filter_fn: Callable[[EventWithMetadata], bool] | None = None,
    ) -> HandlerRegistration:
        """Register an event handler.

        Args:
            pattern: Pattern to match routing keys
            handler: Async handler function
            name: Optional handler name
            priority: Higher priority handlers execute first
            filter_fn: Optional filter function

        Returns:
            HandlerRegistration for the registered handler
        """
        registration = HandlerRegistration(
            pattern=pattern,
            handler=handler,
            name=name or handler.__name__,
            priority=priority,
            filter_fn=filter_fn,
        )

        self._handlers.append(registration)
        # Keep sorted by priority (descending)
        self._handlers.sort(key=lambda h: -h.priority)

        logger.debug(
            f"[EventRouter] Registered handler '{registration.name}' for pattern '{pattern}'"
        )
        return registration

    def handler(
        self,
        pattern: str,
        *,
        name: str | None = None,
        priority: int = 0,
    ) -> Callable[[EventHandler], EventHandler]:
        """Decorator to register an event handler.

        Args:
            pattern: Pattern to match routing keys
            name: Optional handler name
            priority: Higher priority handlers execute first

        Returns:
            Decorator function

        Example:
            @router.handler("agent.*")
            async def handle_agent(event):
                ...
        """

        def decorator(fn: EventHandler) -> EventHandler:
            self.register(pattern, fn, name=name, priority=priority)
            return fn

        return decorator

    def unregister(self, registration: HandlerRegistration) -> bool:
        """Unregister an event handler.

        Args:
            registration: The HandlerRegistration to remove

        Returns:
            True if handler was removed
        """
        try:
            self._handlers.remove(registration)
            logger.debug(f"[EventRouter] Unregistered handler '{registration.name}'")
            return True
        except ValueError:
            return False

    def unregister_pattern(self, pattern: str) -> int:
        """Unregister all handlers for a pattern.

        Args:
            pattern: Pattern to remove handlers for

        Returns:
            Number of handlers removed
        """
        original_count = len(self._handlers)
        self._handlers = [h for h in self._handlers if h.pattern != pattern]
        removed = original_count - len(self._handlers)
        if removed:
            logger.debug(f"[EventRouter] Unregistered {removed} handlers for pattern '{pattern}'")
        return removed

    async def route(self, event: EventWithMetadata) -> RoutingResult:
        """Route an event to matching handlers.

        Args:
            event: Event to route

        Returns:
            RoutingResult with handler execution details
        """
        result = RoutingResult(event=event)
        matching_handlers = self._get_matching_handlers(event)

        if not matching_handlers:
            logger.debug(f"[EventRouter] No handlers for {event.routing_key}")
            self._metrics.no_handler_count += 1
            return result

        # Limit handlers
        if len(matching_handlers) > self._max_handlers:
            logger.warning(
                f"[EventRouter] Truncating handlers for {event.routing_key} "
                f"({len(matching_handlers)} -> {self._max_handlers})"
            )
            matching_handlers = matching_handlers[: self._max_handlers]

        # Execute handlers
        if self._parallel:
            await self._execute_parallel(event, matching_handlers, result)
        else:
            await self._execute_sequential(event, matching_handlers, result)

        # Update metrics
        self._metrics.events_routed += 1
        self._metrics.handlers_invoked += result.handlers_invoked
        if result.errors:
            self._metrics.errors += len(result.errors)

        return result

    async def route_many(
        self,
        events: list[EventWithMetadata],
    ) -> list[RoutingResult]:
        """Route multiple events.

        Args:
            events: Events to route

        Returns:
            List of RoutingResults
        """
        return [await self.route(event) for event in events]

    def _get_matching_handlers(
        self,
        event: EventWithMetadata,
    ) -> list[HandlerRegistration]:
        """Get handlers matching an event."""
        return [h for h in self._handlers if h.should_handle(event)]

    async def _execute_sequential(
        self,
        event: EventWithMetadata,
        handlers: list[HandlerRegistration],
        result: RoutingResult,
    ) -> None:
        """Execute handlers sequentially."""
        for registration in handlers:
            try:
                await registration.handler(event)
                result.handlers_invoked += 1
            except Exception as e:
                logger.error(f"[EventRouter] Handler '{registration.name}' failed: {e}")
                result.errors.append((registration.name, e))
                if not self._continue_on_error:
                    break

    async def _execute_parallel(
        self,
        event: EventWithMetadata,
        handlers: list[HandlerRegistration],
        result: RoutingResult,
    ) -> None:
        """Execute handlers in parallel."""
        tasks = []
        for registration in handlers:
            task = asyncio.create_task(
                self._safe_invoke(registration, event),
                name=f"handler-{registration.name}",
            )
            tasks.append((registration, task))

        # Wait for all tasks
        for registration, task in tasks:
            try:
                await task
                result.handlers_invoked += 1
            except Exception as e:
                logger.error(f"[EventRouter] Handler '{registration.name}' failed: {e}")
                result.errors.append((registration.name, e))

    async def _safe_invoke(
        self,
        registration: HandlerRegistration,
        event: EventWithMetadata,
    ) -> None:
        """Safely invoke a handler."""
        await registration.handler(event)

    def get_handlers_for_pattern(self, pattern: str) -> list[HandlerRegistration]:
        """Get all handlers registered for a specific pattern."""
        return [h for h in self._handlers if h.pattern == pattern]

    def get_matching_patterns(self, routing_key: str) -> list[str]:
        """Get all patterns that match a routing key."""
        return [h.pattern for h in self._handlers if h.matches(routing_key)]

    @property
    def handler_count(self) -> int:
        """Get the number of registered handlers."""
        return len(self._handlers)

    @property
    def patterns(self) -> set[str]:
        """Get all registered patterns."""
        return {h.pattern for h in self._handlers}

    @property
    def metrics(self) -> "RouterMetrics":
        """Get router metrics."""
        return self._metrics

    def clear(self) -> None:
        """Clear all registered handlers."""
        self._handlers.clear()
        logger.debug("[EventRouter] Cleared all handlers")


@dataclass
class RouterMetrics:
    """Metrics for the event router.

    Attributes:
        events_routed: Total events routed
        handlers_invoked: Total handler invocations
        errors: Total handler errors
        no_handler_count: Events with no matching handler
    """

    events_routed: int = 0
    handlers_invoked: int = 0
    errors: int = 0
    no_handler_count: int = 0

    def reset(self) -> None:
        """Reset all metrics."""
        self.events_routed = 0
        self.handlers_invoked = 0
        self.errors = 0
        self.no_handler_count = 0

    def to_dict(self) -> dict[str, int]:
        """Convert metrics to dictionary."""
        return {
            "events_routed": self.events_routed,
            "handlers_invoked": self.handlers_invoked,
            "errors": self.errors,
            "no_handler_count": self.no_handler_count,
        }
