"""Tests for Unified Event Bus System.

Tests the unified event bus port, routing key, and event router.
"""

import asyncio

import pytest

from src.domain.events.envelope import EventEnvelope
from src.domain.events.types import AgentEventType
from src.domain.ports.services.unified_event_bus_port import (
    EventWithMetadata,
    PublishResult,
    RoutingKey,
    SubscriptionOptions,
)
from src.infrastructure.adapters.secondary.messaging.event_router import (
    EventRouter,
    HandlerRegistration,
)


class TestRoutingKey:
    """Tests for RoutingKey class."""

    def test_create_routing_key(self):
        """Test basic routing key creation."""
        key = RoutingKey("agent", "conv-123", "msg-456")
        assert key.namespace == "agent"
        assert key.entity_id == "conv-123"
        assert key.sub_id == "msg-456"

    def test_routing_key_str_with_sub_id(self):
        """Test string representation with sub_id."""
        key = RoutingKey("agent", "conv-123", "msg-456")
        assert str(key) == "agent.conv-123.msg-456"

    def test_routing_key_str_without_sub_id(self):
        """Test string representation without sub_id."""
        key = RoutingKey("hitl", "req-789")
        assert str(key) == "hitl.req-789"

    def test_from_string_two_parts(self):
        """Test parsing from string with two parts."""
        key = RoutingKey.from_string("hitl.req-123")
        assert key.namespace == "hitl"
        assert key.entity_id == "req-123"
        assert key.sub_id is None

    def test_from_string_three_parts(self):
        """Test parsing from string with three parts."""
        key = RoutingKey.from_string("agent.conv-123.msg-456")
        assert key.namespace == "agent"
        assert key.entity_id == "conv-123"
        assert key.sub_id == "msg-456"

    def test_from_string_multiple_dots_in_sub_id(self):
        """Test parsing string with dots in sub_id."""
        key = RoutingKey.from_string("system.health.check.detailed")
        assert key.namespace == "system"
        assert key.entity_id == "health"
        assert key.sub_id == "check.detailed"

    def test_from_string_invalid(self):
        """Test parsing invalid routing key."""
        with pytest.raises(ValueError):
            RoutingKey.from_string("invalid")

    def test_agent_factory(self):
        """Test agent routing key factory."""
        key = RoutingKey.agent("conv-123", "msg-456")
        assert key.namespace == "agent"
        assert str(key) == "agent.conv-123.msg-456"

    def test_hitl_factory(self):
        """Test HITL routing key factory."""
        key = RoutingKey.hitl("req-789")
        assert key.namespace == "hitl"
        assert str(key) == "hitl.req-789"

    def test_sandbox_factory(self):
        """Test sandbox routing key factory."""
        key = RoutingKey.sandbox("sbx-abc")
        assert key.namespace == "sandbox"
        assert str(key) == "sandbox.sbx-abc"

    def test_system_factory(self):
        """Test system routing key factory."""
        key = RoutingKey.system("health")
        assert key.namespace == "system"
        assert str(key) == "system.health"


class TestSubscriptionOptions:
    """Tests for SubscriptionOptions."""

    def test_default_options(self):
        """Test default subscription options."""
        opts = SubscriptionOptions()
        assert opts.consumer_group is None
        assert opts.batch_size == 100
        assert opts.block_ms == 5000
        assert opts.ack_immediately is True

    def test_custom_options(self):
        """Test custom subscription options."""
        opts = SubscriptionOptions(
            consumer_group="workers",
            consumer_name="worker-1",
            batch_size=50,
            block_ms=10000,
        )
        assert opts.consumer_group == "workers"
        assert opts.consumer_name == "worker-1"
        assert opts.batch_size == 50


class TestEventRouter:
    """Tests for EventRouter."""

    @pytest.fixture
    def router(self):
        """Create a fresh router for each test."""
        return EventRouter()

    @pytest.fixture
    def sample_event(self):
        """Create a sample event for testing."""
        envelope = EventEnvelope.wrap(
            event_type=AgentEventType.THOUGHT,
            payload={"content": "test thought"},
        )
        return EventWithMetadata(
            envelope=envelope,
            routing_key="agent.conv-123.msg-456",
            sequence_id="1234567890-0",
        )

    def test_register_handler(self, router):
        """Test registering a handler."""

        async def handler(event):
            pass

        registration = router.register("agent.*", handler)

        assert registration.pattern == "agent.*"
        assert registration.handler is handler
        assert router.handler_count == 1

    def test_register_with_decorator(self, router):
        """Test registering handler with decorator."""

        @router.handler("agent.*")
        async def handle_agent(event):
            pass

        assert router.handler_count == 1

    def test_unregister_handler(self, router):
        """Test unregistering a handler."""

        async def handler(event):
            pass

        reg = router.register("agent.*", handler)
        assert router.handler_count == 1

        result = router.unregister(reg)
        assert result is True
        assert router.handler_count == 0

    def test_unregister_pattern(self, router):
        """Test unregistering all handlers for a pattern."""

        async def h1(e):
            pass

        async def h2(e):
            pass

        async def h3(e):
            pass

        router.register("agent.*", h1)
        router.register("agent.*", h2)
        router.register("hitl.*", h3)

        removed = router.unregister_pattern("agent.*")
        assert removed == 2
        assert router.handler_count == 1

    @pytest.mark.asyncio
    async def test_route_to_matching_handler(self, router, sample_event):
        """Test routing to a matching handler."""
        events_received: list[EventWithMetadata] = []

        @router.handler("agent.*")
        async def handle_agent(event):
            events_received.append(event)

        result = await router.route(sample_event)

        assert result.handled is True
        assert result.handlers_invoked == 1
        assert len(events_received) == 1
        assert events_received[0] is sample_event

    @pytest.mark.asyncio
    async def test_route_no_matching_handler(self, router, sample_event):
        """Test routing with no matching handler."""

        @router.handler("hitl.*")
        async def handle_hitl(event):
            pass

        result = await router.route(sample_event)

        assert result.handled is False
        assert result.handlers_invoked == 0

    @pytest.mark.asyncio
    async def test_route_multiple_handlers(self, router, sample_event):
        """Test routing to multiple handlers."""
        call_order = []

        @router.handler("agent.*", priority=1)
        async def h1(event):
            call_order.append("h1")

        @router.handler("agent.conv-123.*", priority=2)
        async def h2(event):
            call_order.append("h2")

        result = await router.route(sample_event)

        assert result.handlers_invoked == 2
        # Higher priority first
        assert call_order == ["h2", "h1"]

    @pytest.mark.asyncio
    async def test_route_handler_error(self, router, sample_event):
        """Test routing with handler error."""

        @router.handler("agent.*")
        async def failing_handler(event):
            raise ValueError("Handler failed")

        result = await router.route(sample_event)

        assert result.handled is False  # No successful handlers
        assert len(result.errors) == 1
        assert result.errors[0][0] == "failing_handler"
        assert result.success is False

    @pytest.mark.asyncio
    async def test_route_continue_on_error(self, router, sample_event):
        """Test routing continues after handler error."""
        call_order = []

        @router.handler("agent.*", priority=2)
        async def failing_handler(event):
            call_order.append("failing")
            raise ValueError("fail")

        @router.handler("agent.*", priority=1)
        async def success_handler(event):
            call_order.append("success")

        result = await router.route(sample_event)

        # Both handlers should be called
        assert call_order == ["failing", "success"]
        assert result.handlers_invoked == 1
        assert len(result.errors) == 1

    @pytest.mark.asyncio
    async def test_route_parallel_execution(self, sample_event):
        """Test parallel handler execution."""
        router = EventRouter(parallel_execution=True)
        call_times = []

        @router.handler("agent.*")
        async def slow_handler(event):
            await asyncio.sleep(0.1)
            call_times.append("slow")

        @router.handler("agent.*")
        async def fast_handler(event):
            call_times.append("fast")

        result = await router.route(sample_event)

        assert result.handlers_invoked == 2
        # Fast should complete before slow in parallel
        # (but we can't guarantee order in parallel)
        assert len(call_times) == 2

    def test_handler_registration_matches(self):
        """Test HandlerRegistration pattern matching."""

        async def handler(e):
            pass

        reg = HandlerRegistration(
            pattern="agent.*.msg-*",
            handler=handler,
        )

        assert reg.matches("agent.conv-123.msg-456") is True
        assert reg.matches("agent.conv-123.other-456") is False
        assert reg.matches("hitl.req-123") is False

    def test_get_matching_patterns(self, router):
        """Test getting patterns that match a routing key."""

        async def h(e):
            pass

        router.register("agent.*", h)
        router.register("agent.conv-123.*", h)
        router.register("hitl.*", h)

        patterns = router.get_matching_patterns("agent.conv-123.msg-456")
        assert len(patterns) == 2
        assert "agent.*" in patterns
        assert "agent.conv-123.*" in patterns

    def test_router_metrics(self, router):
        """Test router metrics."""
        metrics = router.metrics

        assert metrics.events_routed == 0
        assert metrics.handlers_invoked == 0
        assert metrics.errors == 0

    @pytest.mark.asyncio
    async def test_router_metrics_updated(self, router, sample_event):
        """Test router metrics are updated after routing."""

        @router.handler("agent.*")
        async def handler(event):
            pass

        await router.route(sample_event)

        assert router.metrics.events_routed == 1
        assert router.metrics.handlers_invoked == 1


class TestEventWithMetadata:
    """Tests for EventWithMetadata."""

    def test_create_event_with_metadata(self):
        """Test creating EventWithMetadata."""
        envelope = EventEnvelope.wrap(
            event_type=AgentEventType.THOUGHT,
            payload={"content": "test"},
        )

        event = EventWithMetadata(
            envelope=envelope,
            routing_key="agent.conv-123.msg-456",
            sequence_id="12345-0",
        )

        assert event.envelope is envelope
        assert event.routing_key == "agent.conv-123.msg-456"
        assert event.sequence_id == "12345-0"


class TestPublishResult:
    """Tests for PublishResult."""

    def test_create_publish_result(self):
        """Test creating PublishResult."""
        result = PublishResult(
            sequence_id="12345-0",
            stream_key="events:agent.conv-123.msg-456",
        )

        assert result.sequence_id == "12345-0"
        assert result.stream_key == "events:agent.conv-123.msg-456"
        assert result.timestamp is not None
