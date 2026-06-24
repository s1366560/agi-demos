"""Tests for Unified Event Bus System.

Tests the unified event bus port, routing key, and event router.
"""

import asyncio
import logging
from unittest.mock import AsyncMock, Mock

import pytest
import redis.asyncio as redis

from src.domain.events.envelope import EventEnvelope
from src.domain.events.serialization import EventSerializer
from src.domain.events.types import AgentEventType
from src.domain.ports.services.unified_event_bus_port import (
    EventPublishError,
    EventWithMetadata,
    PublishResult,
    RoutingKey,
    SubscriptionOptions,
)
from src.infrastructure.adapters.secondary.messaging.event_router import (
    EventRouter,
    HandlerRegistration,
)
from src.infrastructure.adapters.secondary.messaging.redis_unified_event_bus import (
    RedisUnifiedEventBusAdapter,
)

LOGGER_NAME = "src.infrastructure.adapters.secondary.messaging.redis_unified_event_bus"


class _RedisStreamSubscribeFake:
    def __init__(self, stream_key: str, fields: dict[bytes, bytes]) -> None:
        self._stream_key = stream_key
        self._fields = fields
        self.scan_calls = 0
        self.xread_calls = 0

    async def scan(self, *, cursor: int, match: str, count: int):
        self.scan_calls += 1
        if self.scan_calls == 1:
            return 0, []
        return 0, [self._stream_key]

    async def xread(self, streams, *, count: int, block: int):
        self.xread_calls += 1
        return [(self._stream_key, [("1-0", self._fields)])]


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

    def test_workspace_factory(self):
        """Test workspace routing key factory."""
        key = RoutingKey.workspace("ws-123", "topology_updated")
        assert key.namespace == "workspace"
        assert key.entity_id == "ws-123"
        assert key.sub_id == "topology_updated"
        assert str(key) == "workspace.ws-123.topology_updated"


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


class TestRedisUnifiedEventBusSubscription:
    @pytest.mark.asyncio
    async def test_direct_subscription_waits_for_stream_created_after_subscribe(self) -> None:
        envelope = EventEnvelope.wrap(
            event_type=AgentEventType.WORKSPACE_UPDATED,
            payload={"workspace_id": "ws-1"},
        )
        serializer = EventSerializer(auto_migrate=True)
        fields = {
            b"event_id": envelope.event_id.encode(),
            b"event_type": envelope.event_type.encode(),
            b"schema_version": envelope.schema_version.encode(),
            b"data": serializer.serialize(envelope).encode(),
            b"timestamp": envelope.timestamp.encode(),
            b"routing_key": b"workspace:ws-1:workspace_updated",
        }
        redis = _RedisStreamSubscribeFake("events:workspace:ws-1:workspace_updated", fields)
        adapter = RedisUnifiedEventBusAdapter(redis_client=redis)  # type: ignore[arg-type]

        subscription = adapter.subscribe(
            "workspace:ws-1:*",
            SubscriptionOptions(batch_size=1, block_ms=1),
        )
        try:
            event = await asyncio.wait_for(anext(subscription), timeout=1)
        finally:
            await subscription.aclose()

        assert redis.scan_calls >= 2
        assert event.envelope.event_type == AgentEventType.WORKSPACE_UPDATED.value
        assert event.routing_key == "workspace:ws-1:workspace_updated"


class TestRedisUnifiedEventBusLogging:
    @pytest.mark.asyncio
    async def test_publish_batch_error_log_redacts_routing_key_and_exception(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        exception_detail = "batch publish redis secret 2468"
        secret_routing_key = "agent.secret-conversation.secret-message"

        class _FailingPipeline:
            async def __aenter__(self) -> "_FailingPipeline":
                return self

            async def __aexit__(
                self,
                _exc_type: type[BaseException] | None,
                _exc: BaseException | None,
                _traceback: object | None,
            ) -> None:
                return None

            def xadd(self, *_args: object, **_kwargs: object) -> None:
                return None

            async def execute(self) -> None:
                raise redis.RedisError(exception_detail)

        event = EventEnvelope.wrap(
            event_type=AgentEventType.WORKSPACE_UPDATED,
            payload={"workspace_id": "ws-secret"},
        )
        redis_client = Mock()
        redis_client.pipeline = Mock(return_value=_FailingPipeline())
        adapter = RedisUnifiedEventBusAdapter(redis_client)  # type: ignore[arg-type]

        with (
            caplog.at_level(logging.ERROR, logger=LOGGER_NAME),
            pytest.raises(EventPublishError) as exc_info,
        ):
            await adapter.publish_batch([(event, secret_routing_key)])

        assert exception_detail in str(exc_info.value)
        assert "Batch publish failed" in caplog.text
        assert secret_routing_key not in caplog.text
        assert exception_detail not in caplog.text
        assert "error_type=RedisError" in caplog.text
        assert "event_count=1" in caplog.text

    @pytest.mark.asyncio
    async def test_get_events_error_log_redacts_routing_key_and_exception(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        redis_client = Mock()
        redis_client.xrange = AsyncMock(side_effect=redis.RedisError("redis secret unavailable"))
        adapter = RedisUnifiedEventBusAdapter(redis_client)  # type: ignore[arg-type]
        secret_routing_key = "agent.secret-conversation.secret-message"

        with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
            events = await adapter.get_events(secret_routing_key, max_count=3)

        assert events == []
        assert "Failed to get events" in caplog.text
        assert secret_routing_key not in caplog.text
        assert "redis secret unavailable" not in caplog.text
        assert "error_type=RedisError" in caplog.text
        assert "max_count=3" in caplog.text
        assert "has_routing_key=True" in caplog.text

    @pytest.mark.asyncio
    async def test_get_latest_event_error_log_redacts_routing_key_and_exception(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        redis_client = Mock()
        redis_client.xrevrange = AsyncMock(side_effect=redis.RedisError("redis secret unavailable"))
        adapter = RedisUnifiedEventBusAdapter(redis_client)  # type: ignore[arg-type]
        secret_routing_key = "agent.secret-conversation.secret-message"

        with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
            event = await adapter.get_latest_event(secret_routing_key)

        assert event is None
        assert "Failed to get latest" in caplog.text
        assert secret_routing_key not in caplog.text
        assert "redis secret unavailable" not in caplog.text
        assert "error_type=RedisError" in caplog.text
        assert "has_routing_key=True" in caplog.text

    @pytest.mark.asyncio
    async def test_trim_stream_error_log_redacts_routing_key_and_exception(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        redis_client = Mock()
        redis_client.xtrim = AsyncMock(side_effect=redis.RedisError("redis secret unavailable"))
        adapter = RedisUnifiedEventBusAdapter(redis_client)  # type: ignore[arg-type]
        secret_routing_key = "agent.secret-conversation.secret-message"

        with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
            removed = await adapter.trim_stream(secret_routing_key, max_length=5)

        assert removed == 0
        assert "Failed to trim stream" in caplog.text
        assert secret_routing_key not in caplog.text
        assert "redis secret unavailable" not in caplog.text
        assert "error_type=RedisError" in caplog.text
        assert "max_length=5" in caplog.text
        assert "has_routing_key=True" in caplog.text

    @pytest.mark.asyncio
    async def test_delete_stream_error_log_redacts_routing_key_and_exception(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        redis_client = Mock()
        redis_client.delete = AsyncMock(side_effect=redis.RedisError("redis secret unavailable"))
        adapter = RedisUnifiedEventBusAdapter(redis_client)  # type: ignore[arg-type]
        secret_routing_key = "agent.secret-conversation.secret-message"

        with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
            deleted = await adapter.delete_stream(secret_routing_key)

        assert deleted is False
        assert "Failed to delete stream" in caplog.text
        assert secret_routing_key not in caplog.text
        assert "redis secret unavailable" not in caplog.text
        assert "error_type=RedisError" in caplog.text
        assert "has_routing_key=True" in caplog.text

    @pytest.mark.asyncio
    async def test_acknowledge_error_log_redacts_routing_group_and_exception(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        redis_client = Mock()
        redis_client.xack = AsyncMock(
            side_effect=redis.RedisError("redis secret group unavailable")
        )
        adapter = RedisUnifiedEventBusAdapter(redis_client)  # type: ignore[arg-type]
        secret_routing_key = "agent.secret-conversation.secret-message"
        secret_consumer_group = "secret-consumer-group"

        with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
            acked = await adapter.acknowledge(
                routing_key=secret_routing_key,
                sequence_ids=["1-0", "2-0"],
                consumer_group=secret_consumer_group,
            )

        assert acked == 0
        assert "Failed to ack events" in caplog.text
        assert secret_routing_key not in caplog.text
        assert secret_consumer_group not in caplog.text
        assert "redis secret group unavailable" not in caplog.text
        assert "error_type=RedisError" in caplog.text
        assert "sequence_count=2" in caplog.text
        assert "has_routing_key=True" in caplog.text
        assert "has_consumer_group=True" in caplog.text

    @pytest.mark.asyncio
    async def test_create_consumer_group_error_log_redacts_routing_group_and_exception(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        redis_client = Mock()
        redis_client.xgroup_create = AsyncMock(
            side_effect=redis.ResponseError("ERR secret group unavailable")
        )
        adapter = RedisUnifiedEventBusAdapter(redis_client)  # type: ignore[arg-type]
        secret_routing_key = "agent.secret-conversation.secret-message"
        secret_group_name = "secret-consumer-group"

        with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
            created = await adapter.create_consumer_group(
                routing_key=secret_routing_key,
                group_name=secret_group_name,
                start_id="1-0",
            )

        assert created is False
        assert "Failed to create consumer group" in caplog.text
        assert secret_routing_key not in caplog.text
        assert secret_group_name not in caplog.text
        assert "secret group unavailable" not in caplog.text
        assert "error_type=ResponseError" in caplog.text
        assert "start_id=1-0" in caplog.text
        assert "has_routing_key=True" in caplog.text
        assert "has_group_name=True" in caplog.text


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
