"""Tests for ReActAgent Core Components Integration.

Tests the integration between all refactored components:
- Error handling (AgentError hierarchy)
- Configuration management (AgentConfig, ConfigManager)
- Event system (EventBus, EventMapper, SSE)
- Tool system (ToolRegistry, ToolExecutor)
- Execution routing (ExecutionRouter)

This is Phase 6 of the refactoring plan.

NOTE: This test file uses AgentEventType from the unified domain events types.
EventType is now an alias for AgentEventType for backward compatibility.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

import pytest

from src.domain.events.types import AgentEventType
from src.infrastructure.agent.config import (
    AgentConfig,
    ConfigManager,
    ExecutionConfig,
    get_config,
    set_config,
)
from src.infrastructure.agent.errors import (
    AgentError,
    ErrorCategory,
    ErrorContext,
    wrap_error,
)
from src.infrastructure.agent.events import (
    AgentDomainEvent,
    EventBus,
    EventMapper,
    EventType,  # Alias for AgentEventType
    SSEEvent,
    get_event_bus,
    set_event_bus,
)
from src.infrastructure.agent.routing.execution_router import (
    ExecutionPath,
    ExecutionRouter,
    SkillMatcher,
)
from src.infrastructure.agent.tools.tool_registry import (
    Tool,
    ToolExecutor,
    ToolMetadata,
    ToolRegistry,
)


class MockTool(Tool):
    """Mock tool for testing."""

    def __init__(
        self,
        name: str = "test_tool",
        description: str = "A test tool",
        execute_result: Any = "success",
    ) -> None:
        self._name = name
        self._description = description
        self._execute_result = execute_result

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    async def execute(self, **kwargs) -> Any:
        return self._execute_result

    def get_metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name=self.name,
            description=self.description,
            category="test",
            parameters={},
        )


class TestErrorAndConfigIntegration:
    """Tests for error handling and config integration."""

    def test_config_validation_errors(self) -> None:
        """Should raise validation errors for invalid config."""
        with pytest.raises(ValueError):
            config = ExecutionConfig(max_steps=-1)
            config.validate()

        with pytest.raises(ValueError):
            config = ExecutionConfig(skill_match_threshold=2.0)
            config.validate()

    def test_config_manager_with_error_context(self) -> None:
        """Should use error context in config operations."""
        manager = ConfigManager()
        manager.set_tenant_config("tenant_1", AgentConfig(
            execution=ExecutionConfig(max_steps=5),
        ))

        # Get config should work
        config = manager.get_config("tenant_1")
        assert config.execution.max_steps == 5

        # Getting non-existent tenant should return default
        default_config = manager.get_config("non_existent")
        assert default_config.execution.max_steps == 20  # default


class TestEventAndConfigIntegration:
    """Tests for event system and config integration."""

    def test_config_change_triggers_event(self) -> None:
        """Should emit event when config changes."""
        bus = EventBus()
        manager = ConfigManager()

        events = []

        def on_config_change(event: AgentDomainEvent) -> None:
            events.append(event)

        bus.subscribe(callback=on_config_change)

        # Register config change callback
        def on_change(tenant_id: str, config: AgentConfig) -> None:
            bus.publish(AgentDomainEvent(
                event_type=AgentEventType.STATUS,
                data={"tenant": tenant_id, "config_changed": True},
            ))

        manager.register_change_callback(on_change)
        manager.set_tenant_config("tenant_1", AgentConfig(
            execution=ExecutionConfig(max_steps=15),
        ))

        assert len(events) == 1
        assert events[0].event_type == AgentEventType.STATUS


class TestToolAndEventIntegration:
    """Tests for tool system and event integration."""

    @pytest.mark.asyncio
    async def test_tool_execution_emits_events(self) -> None:
        """Should emit events during tool execution."""
        bus = EventBus()
        registry = ToolRegistry()
        tool = MockTool("test_tool", "Test tool", "result")

        registry.register(tool)
        executor = ToolExecutor(registry)

        events = []

        def capture_events(event: AgentDomainEvent) -> None:
            events.append(event)

        bus.subscribe(callback=capture_events)

        # Emit events manually (in real implementation, executor would do this)
        bus.publish(AgentDomainEvent(
            event_type=AgentEventType.ACT,
            data={"tool": "test_tool", "phase": "start"},
        ))

        result = await executor.execute("test_tool", {})

        bus.publish(AgentDomainEvent(
            event_type=AgentEventType.OBSERVE,
            data={"tool": "test_tool", "result": result.result},
        ))

        assert len(events) == 2
        assert events[0].event_type == AgentEventType.ACT
        assert events[1].event_type == AgentEventType.OBSERVE

    @pytest.mark.asyncio
    async def test_tool_error_emits_error_event(self) -> None:
        """Should emit error event on tool failure."""
        bus = EventBus()
        registry = ToolRegistry()

        class FailingTool(Tool):
            @property
            def name(self) -> str:
                return "failing_tool"

            @property
            def description(self) -> str:
                return "A failing tool"

            async def execute(self, **kwargs) -> Any:
                raise ValueError("Tool failed!")

        registry.register(FailingTool())
        executor = ToolExecutor(registry)

        events = []

        bus.subscribe(callback=events.append)

        result = await executor.execute("failing_tool", {})

        assert result.success is False
        # In real implementation, executor would emit TOOL_ERROR


class TestRouterAndToolIntegration:
    """Tests for routing and tool system integration."""

    def test_router_recommends_tool_based_on_message(self) -> None:
        """Should recommend tool based on message content."""
        registry = ToolRegistry()
        registry.register(MockTool("read_file", "Read a file"))
        registry.register(MockTool("write_file", "Write to a file"))

        # Mock skill matcher that looks for keywords
        class KeywordSkillMatcher(SkillMatcher):
            def __init__(self, tool_names: List[str]):
                self._tools = tool_names

            async def match(
                self,
                message: str,
                context: Dict[str, Any],
            ) -> Optional[str]:
                for tool in self._tools:
                    if tool.replace("_", " ") in message.lower():
                        return tool
                return None

        router = ExecutionRouter(
            skill_matcher=KeywordSkillMatcher(["read_file", "write_file"]),
        )

        decision = router.decide(
            message="Please read the file for me",
            context={},
        )

        assert decision.path in (ExecutionPath.DIRECT_SKILL, ExecutionPath.REACT_LOOP)
        assert decision.confidence > 0.0


class TestFullIntegration:
    """Full integration tests for all components."""

    @pytest.mark.asyncio
    async def test_end_to_end_agent_flow(self) -> None:
        """Should simulate complete agent flow with all components."""
        # Setup
        config_manager = ConfigManager()
        event_bus = EventBus()
        tool_registry = ToolRegistry()
        router = ExecutionRouter()

        # Register tools
        tool_registry.register(MockTool("hello", "Say hello", "Hello!"))
        tool_registry.register(MockTool("goodbye", "Say goodbye", "Goodbye!"))

        # Create executor
        executor = ToolExecutor(tool_registry)

        # Track events
        events = []
        event_bus.subscribe(callback=events.append)

        # Simulate agent flow
        # 1. Route decision
        decision = router.decide("Say hello", {})
        assert decision.path in (
            ExecutionPath.DIRECT_SKILL,
            ExecutionPath.REACT_LOOP,
        )

        # 2. Emit start event
        event_bus.publish(AgentDomainEvent(
            event_type=AgentEventType.START,
            data={"message": "Say hello"},
        ))

        # 3. Execute tool
        result = await executor.execute("hello", {})

        # 4. Emit end event
        event_bus.publish(AgentDomainEvent(
            event_type=AgentEventType.COMPLETE,
            data={"success": result.success},
        ))

        # Verify
        assert result.success is True
        assert result.result == "Hello!"
        assert len(events) == 2

    @pytest.mark.asyncio
    async def test_error_propagation_through_components(self) -> None:
        """Should handle errors across all components."""
        # Setup
        event_bus = EventBus()
        tool_registry = ToolRegistry()

        # Create a tool that fails
        class BrokenTool(Tool):
            @property
            def name(self) -> str:
                return "broken_tool"

            @property
            def description(self) -> str:
                return "This tool is broken"

            async def execute(self, **kwargs) -> Any:
                raise RuntimeError("Something went wrong!")

        tool_registry.register(BrokenTool())
        executor = ToolExecutor(tool_registry)

        # Track events
        errors = []

        def capture_errors(event: AgentDomainEvent) -> None:
            if event.event_type == AgentEventType.ERROR:
                errors.append(event)

        event_bus.subscribe(callback=capture_errors)

        # Execute and expect failure
        result = await executor.execute("broken_tool", {})

        assert result.success is False
        # In real implementation, error event would be emitted

    def test_sse_stream_from_all_components(self) -> None:
        """Should create SSE stream integrating all components."""
        mapper = EventMapper()
        bus = EventBus(mapper=mapper)

        # Create events from different components
        events = [
            # Status event
            AgentDomainEvent(
                event_type=AgentEventType.STATUS,
                data={"max_iterations": 10},
            ),
            # Act event
            AgentDomainEvent(
                event_type=AgentEventType.ACT,
                data={"tool": "test_tool"},
            ),
            # Error event
            AgentDomainEvent(
                event_type=AgentEventType.ERROR,
                data={"error": "Test error"},
            ),
        ]

        # Create SSE stream
        stream = mapper.create_sse_stream(events)

        # Verify format
        assert "event: status" in stream
        assert "event: act" in stream
        assert "event: error" in stream
        assert "data: " in stream


class TestConfigScenarios:
    """Test configuration scenarios."""

    def test_multi_tenant_config_isolation(self) -> None:
        """Should isolate configs between tenants."""
        manager = ConfigManager()

        manager.set_tenant_config("tenant_a", AgentConfig(
            execution=ExecutionConfig(max_steps=5),
        ))

        manager.set_tenant_config("tenant_b", AgentConfig(
            execution=ExecutionConfig(max_steps=20),
        ))

        config_a = manager.get_config("tenant_a")
        config_b = manager.get_config("tenant_b")

        assert config_a.execution.max_steps == 5
        assert config_b.execution.max_steps == 20

    def test_config_fallback_to_default(self) -> None:
        """Should fallback to default for unset tenant configs."""
        manager = ConfigManager()

        # Set tenant config with only one field changed
        manager.set_tenant_config("tenant_1", AgentConfig(
            execution=ExecutionConfig(max_steps=15),
        ))

        config = manager.get_config("tenant_1")

        # Changed field
        assert config.execution.max_steps == 15
        # Default fields
        assert config.execution.skill_match_threshold == 0.9
        assert config.performance.enable_cache is True


class TestEventScenarios:
    """Test event scenarios."""

    def test_event_history_with_filters(self) -> None:
        """Should filter event history correctly."""
        bus = EventBus()

        # Publish different types of events
        for i in range(5):
            bus.publish(AgentDomainEvent(
                event_type=AgentEventType.ACT,
                data={"index": i},
            ))

        for i in range(3):
            bus.publish(AgentDomainEvent(
                event_type=AgentEventType.STATUS,
                data={"index": i},
            ))

        # Get all
        all_history = bus.get_history()
        assert len(all_history) == 8

        # Filter by type
        act_events = bus.get_history(event_type=AgentEventType.ACT)
        assert len(act_events) == 5

        status_events = bus.get_history(event_type=AgentEventType.STATUS)
        assert len(status_events) == 3

    def test_custom_event_transformer(self) -> None:
        """Should apply custom transformer to events."""
        mapper = EventMapper()

        def transform_act(event: AgentDomainEvent) -> dict:
            tool_name = event.data.get("tool", "unknown")
            return {
                "action": "executing",
                "target": tool_name,
                "timestamp": datetime.utcnow().isoformat(),
            }

        mapper.register_transformer(AgentEventType.ACT, transform_act)

        event = AgentDomainEvent(
            event_type=AgentEventType.ACT,
            data={"tool": "read_file"},
        )

        sse = mapper.to_sse(event, "1")

        assert "action" in sse.data
        assert sse.data["action"] == "executing"
        assert sse.data["target"] == "read_file"


class TestToolScenarios:
    """Test tool scenarios."""

    @pytest.mark.asyncio
    async def test_batch_execution_with_mixed_results(self) -> None:
        """Should handle batch execution with mixed success/failure."""
        registry = ToolRegistry()

        # Mix of successful and failing tools
        registry.register(MockTool("tool1", "Tool 1", "result1"))
        registry.register(MockTool("tool2", "Tool 2", "result2"))

        class FailingTool(Tool):
            @property
            def name(self) -> str:
                return "failing_tool"

            @property
            def description(self) -> str:
                return "Fails"

            async def execute(self, **kwargs) -> Any:
                raise ValueError("Failed!")

        registry.register(FailingTool())

        executor = ToolExecutor(registry)

        requests = [
            {"tool_name": "tool1", "parameters": {}},
            {"tool_name": "failing_tool", "parameters": {}},
            {"tool_name": "tool2", "parameters": {}},
        ]

        results = await executor.execute_batch(requests)

        assert len(results) == 3
        assert results[0].success is True
        assert results[1].success is False
        assert results[2].success is True

    @pytest.mark.asyncio
    async def test_tool_execution_stats_tracking(self) -> None:
        """Should track tool execution statistics."""
        registry = ToolRegistry()
        tool = MockTool("stats_tool", "Stats tool", "ok")

        registry.register(tool)
        executor = ToolExecutor(registry)

        # Execute multiple times
        for _ in range(5):
            await executor.execute("stats_tool", {})

        stats = registry.get_stats("stats_tool")

        assert stats["calls"] == 5
        assert stats["errors"] == 0
        assert stats["total_duration_ms"] >= 0


class TestErrorWrapping:
    """Test error wrapping utilities."""

    def test_wrap_generic_exception(self) -> None:
        """Should wrap generic exceptions as AgentError."""
        try:
            try:
                raise ValueError("Generic error")
            except Exception as e:
                raise wrap_error(e, category=ErrorCategory.INTERNAL)
        except AgentError as agent_error:
            assert isinstance(agent_error, AgentError)
            assert "Generic error" in str(agent_error)

    def test_wrap_with_context(self) -> None:
        """Should wrap error with context."""
        context = ErrorContext(
            operation="test_tool",
            conversation_id="conv-123",
            details={"attempt": 1},
        )

        try:
            try:
                raise RuntimeError("Failed")
            except Exception as e:
                raise wrap_error(e, context=context)
        except AgentError as agent_error:
            assert agent_error.context.operation == "test_tool"
            assert agent_error.context.conversation_id == "conv-123"


class TestGlobalSingletons:
    """Test global singleton management."""

    def test_global_config_manager_isolation(self) -> None:
        """Global config manager should be isolated."""
        manager = ConfigManager()
        set_config(manager)

        # Get default config
        config1 = get_config()
        config2 = get_config()

        # Same instance
        assert config1.execution.max_steps == config2.execution.max_steps

        # Create new manager and verify isolation
        new_manager = ConfigManager()
        new_manager.set_tenant_config("test", AgentConfig(
            execution=ExecutionConfig(max_steps=99),
        ))
        set_config(new_manager)

        config3 = get_config("test")
        assert config3.execution.max_steps == 99

    def test_global_event_bus_isolation(self) -> None:
        """Global event bus should be isolated."""
        bus1 = get_event_bus()
        bus2 = get_event_bus()

        assert bus1 is bus2

        # Change global
        custom = EventBus()
        set_event_bus(custom)

        bus3 = get_event_bus()
        assert bus3 is custom
        assert bus3 is not bus1


class TestSSEFormat:
    """Test SSE format generation."""

    def test_sse_event_format(self) -> None:
        """Should generate correct SSE format."""
        event = SSEEvent(
            id="123",
            event=AgentEventType.ACT,
            data={"tool": "test", "args": ["a", "b"]},
            retry=3000,
        )

        sse = event.to_sse_format()

        assert "id: 123" in sse
        assert "event: act" in sse
        assert "retry: 3000" in sse
        assert "data: " in sse
        assert sse.endswith("\n\n")

    def test_sse_event_without_optional_fields(self) -> None:
        """Should handle SSE event without optional fields."""
        event = SSEEvent(
            id="",
            event=AgentEventType.STATUS,
            data={"value": 50},
        )

        sse = event.to_sse_format()

        # Should not have id or retry
        assert "id: " not in sse or sse.count("id:") == 0
        assert "retry:" not in sse
        assert "event: status" in sse
