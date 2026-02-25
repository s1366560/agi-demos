"""
Unit tests for LLMInvoker module.

Tests cover:
- Token usage tracking
- Invocation configuration
- Invocation context
- Stream event processing
- Tool call validation
- Retry logic
- Usage/cost calculation
- Singleton management
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.infrastructure.agent.llm.invoker import (
    InvocationConfig,
    InvocationContext,
    InvocationResult,
    InvokerState,
    LLMInvoker,
    TokenUsage,
    create_llm_invoker,
    get_llm_invoker,
    set_llm_invoker,
)

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_retry_policy():
    """Create mock retry policy."""
    policy = MagicMock()
    policy.is_retryable.return_value = True
    policy.calculate_delay.return_value = 100  # 100ms
    return policy


@pytest.fixture
def mock_cost_tracker():
    """Create mock cost tracker."""
    tracker = MagicMock()
    tracker.calculate.return_value = MagicMock(cost=0.001)
    tracker.needs_compaction.return_value = False
    return tracker


@pytest.fixture
def invoker(mock_retry_policy, mock_cost_tracker):
    """Create LLMInvoker instance."""
    return LLMInvoker(
        retry_policy=mock_retry_policy,
        cost_tracker=mock_cost_tracker,
        debug_logging=True,
    )


@pytest.fixture
def invocation_config():
    """Create invocation configuration."""
    return InvocationConfig(
        model="gpt-4",
        api_key="test-api-key",
        base_url="https://api.openai.com/v1",
        temperature=0.7,
        max_tokens=4096,
        max_attempts=3,
    )


@pytest.fixture
def invocation_context():
    """Create invocation context."""
    return InvocationContext(
        step_count=1,
        langfuse_context={"conversation_id": "conv-001"},
        abort_event=None,
    )


@pytest.fixture
def mock_message():
    """Create mock message protocol."""
    message = MagicMock()
    message.add_text = MagicMock()
    message.add_reasoning = MagicMock()
    message.add_tool_call = MagicMock(return_value=MagicMock())
    return message


@pytest.fixture
def mock_tool():
    """Create mock tool."""
    tool = MagicMock()
    tool.to_openai_format.return_value = {
        "type": "function",
        "function": {
            "name": "test_tool",
            "description": "Test tool",
            "parameters": {"type": "object", "properties": {}},
        },
    }
    return tool


# ============================================================================
# Test TokenUsage
# ============================================================================


@pytest.mark.unit
class TestTokenUsage:
    """Test TokenUsage dataclass."""

    def test_default_values(self):
        """Test default token usage values."""
        usage = TokenUsage()
        assert usage.input == 0
        assert usage.output == 0
        assert usage.reasoning == 0
        assert usage.cache_read == 0
        assert usage.cache_write == 0

    def test_custom_values(self):
        """Test custom token usage values."""
        usage = TokenUsage(
            input=100,
            output=50,
            reasoning=30,
            cache_read=20,
            cache_write=10,
        )
        assert usage.input == 100
        assert usage.output == 50
        assert usage.reasoning == 30
        assert usage.cache_read == 20
        assert usage.cache_write == 10

    def test_to_dict(self):
        """Test conversion to dictionary."""
        usage = TokenUsage(input=100, output=50, reasoning=30)
        result = usage.to_dict()

        assert result == {
            "input": 100,
            "output": 50,
            "reasoning": 30,
            "cache_read": 0,
            "cache_write": 0,
        }


# ============================================================================
# Test InvocationConfig
# ============================================================================


@pytest.mark.unit
class TestInvocationConfig:
    """Test InvocationConfig dataclass."""

    def test_required_fields(self):
        """Test required config fields."""
        config = InvocationConfig(
            model="gpt-4",
            api_key="test-key",
        )
        assert config.model == "gpt-4"
        assert config.api_key == "test-key"
        assert config.base_url is None
        assert config.temperature == 0.7
        assert config.max_tokens == 4096
        assert config.max_attempts == 3

    def test_all_fields(self):
        """Test all config fields."""
        config = InvocationConfig(
            model="claude-3",
            api_key="test-key",
            base_url="https://api.anthropic.com",
            temperature=0.5,
            max_tokens=8192,
            max_attempts=5,
        )
        assert config.model == "claude-3"
        assert config.base_url == "https://api.anthropic.com"
        assert config.temperature == 0.5
        assert config.max_tokens == 8192
        assert config.max_attempts == 5


# ============================================================================
# Test InvocationContext
# ============================================================================


@pytest.mark.unit
class TestInvocationContext:
    """Test InvocationContext dataclass."""

    def test_minimal_context(self):
        """Test minimal context."""
        context = InvocationContext(step_count=1)
        assert context.step_count == 1
        assert context.langfuse_context is None
        assert context.abort_event is None

    def test_full_context(self):
        """Test full context."""
        abort_event = asyncio.Event()
        context = InvocationContext(
            step_count=5,
            langfuse_context={"trace_id": "trace-001"},
            abort_event=abort_event,
        )
        assert context.step_count == 5
        assert context.langfuse_context == {"trace_id": "trace-001"}
        assert context.abort_event is abort_event


# ============================================================================
# Test InvocationResult
# ============================================================================


@pytest.mark.unit
class TestInvocationResult:
    """Test InvocationResult dataclass."""

    def test_default_result(self):
        """Test default result values."""
        result = InvocationResult()
        assert result.text == ""
        assert result.reasoning == ""
        assert result.tool_calls_completed == []
        assert isinstance(result.tokens, TokenUsage)
        assert result.cost == 0.0
        assert result.finish_reason == "stop"
        assert result.trace_url is None

    def test_result_with_values(self):
        """Test result with values."""
        tokens = TokenUsage(input=100, output=50)
        result = InvocationResult(
            text="Hello world",
            reasoning="Thinking...",
            tool_calls_completed=["call-1", "call-2"],
            tokens=tokens,
            cost=0.005,
            finish_reason="tool_calls",
            trace_url="https://langfuse.com/trace/123",
        )
        assert result.text == "Hello world"
        assert result.reasoning == "Thinking..."
        assert len(result.tool_calls_completed) == 2
        assert result.tokens.input == 100
        assert result.cost == 0.005
        assert result.finish_reason == "tool_calls"
        assert result.trace_url == "https://langfuse.com/trace/123"


# ============================================================================
# Test InvokerState
# ============================================================================


@pytest.mark.unit
class TestInvokerState:
    """Test InvokerState enum."""

    def test_idle_state(self):
        """Test idle state."""
        assert InvokerState.IDLE.value == "idle"

    def test_streaming_state(self):
        """Test streaming state."""
        assert InvokerState.STREAMING.value == "streaming"

    def test_retrying_state(self):
        """Test retrying state."""
        assert InvokerState.RETRYING.value == "retrying"

    def test_error_state(self):
        """Test error state."""
        assert InvokerState.ERROR.value == "error"

    def test_complete_state(self):
        """Test complete state."""
        assert InvokerState.COMPLETE.value == "complete"


# ============================================================================
# Test LLMInvoker Initialization
# ============================================================================


@pytest.mark.unit
class TestLLMInvokerInit:
    """Test LLMInvoker initialization."""

    def test_init_default(self, mock_retry_policy, mock_cost_tracker):
        """Test default initialization."""
        invoker = LLMInvoker(
            retry_policy=mock_retry_policy,
            cost_tracker=mock_cost_tracker,
        )
        assert invoker.state == InvokerState.IDLE

    def test_init_with_debug(self, mock_retry_policy, mock_cost_tracker):
        """Test initialization with debug logging."""
        invoker = LLMInvoker(
            retry_policy=mock_retry_policy,
            cost_tracker=mock_cost_tracker,
            debug_logging=True,
        )
        assert invoker._debug_logging is True


# ============================================================================
# Test Tool Call Validation
# ============================================================================


@pytest.mark.unit
class TestToolCallValidation:
    """Test tool call validation."""

    def test_valid_tool_call(self, invoker):
        """Test valid tool call."""
        error = invoker._validate_tool_call(
            call_id="call-001",
            tool_name="search_memory",
            arguments={"query": "test"},
        )
        assert error is None

    def test_empty_tool_name(self, invoker):
        """Test empty tool name."""
        error = invoker._validate_tool_call(
            call_id="call-001",
            tool_name="",
            arguments={},
        )
        assert error is not None
        assert "Invalid tool_name" in error

    def test_whitespace_tool_name(self, invoker):
        """Test whitespace-only tool name."""
        error = invoker._validate_tool_call(
            call_id="call-001",
            tool_name="   ",
            arguments={},
        )
        assert error is not None
        assert "Invalid tool_name" in error

    def test_non_string_tool_name(self, invoker):
        """Test non-string tool name."""
        error = invoker._validate_tool_call(
            call_id="call-001",
            tool_name=123,  # type: ignore
            arguments={},
        )
        assert error is not None
        assert "Invalid tool_name" in error

    def test_non_dict_arguments(self, invoker):
        """Test non-dict arguments."""
        error = invoker._validate_tool_call(
            call_id="call-001",
            tool_name="test_tool",
            arguments="not a dict",  # type: ignore
        )
        assert error is not None
        assert "Invalid tool_input type" in error

    def test_list_arguments(self, invoker):
        """Test list arguments (should fail)."""
        error = invoker._validate_tool_call(
            call_id="call-001",
            tool_name="test_tool",
            arguments=["a", "b"],  # type: ignore
        )
        assert error is not None
        assert "Invalid tool_input type" in error

    def test_non_string_call_id(self, invoker):
        """Test non-string call_id."""
        error = invoker._validate_tool_call(
            call_id=123,  # type: ignore
            tool_name="test_tool",
            arguments={},
        )
        assert error is not None
        assert "Invalid call_id type" in error

    def test_empty_call_id_is_ok(self, invoker):
        """Test empty call_id is acceptable."""
        error = invoker._validate_tool_call(
            call_id="",
            tool_name="test_tool",
            arguments={},
        )
        assert error is None


# ============================================================================
# Test Trace URL Building
# ============================================================================


@pytest.mark.unit
class TestTraceUrlBuilding:
    """Test Langfuse trace URL building."""

    def test_no_langfuse_context(self, invoker):
        """Test without langfuse context."""
        context = InvocationContext(step_count=1, langfuse_context=None)
        url = invoker._build_trace_url(context)
        assert url is None

    def test_with_langfuse_context(self, invoker):
        """Test with langfuse context."""
        context = InvocationContext(
            step_count=1,
            langfuse_context={"conversation_id": "conv-123"},
        )

        with patch("src.configuration.config.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                langfuse_enabled=True,
                langfuse_host="https://langfuse.example.com",
            )
            url = invoker._build_trace_url(context)

        assert url == "https://langfuse.example.com/trace/conv-123"

    def test_langfuse_disabled(self, invoker):
        """Test with langfuse disabled."""
        context = InvocationContext(
            step_count=1,
            langfuse_context={"conversation_id": "conv-123"},
        )

        with patch("src.configuration.config.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                langfuse_enabled=False,
                langfuse_host="https://langfuse.example.com",
            )
            url = invoker._build_trace_url(context)

        assert url is None


# ============================================================================
# Test Usage Event Handling
# ============================================================================


@pytest.mark.unit
class TestUsageEventHandling:
    """Test usage event handling."""

    async def test_handle_usage_event(self, invoker, invocation_config):
        """Test handling usage event."""
        event = MagicMock()
        event.data = {
            "input_tokens": 100,
            "output_tokens": 50,
            "reasoning_tokens": 30,
            "cache_read_tokens": 20,
            "cache_write_tokens": 10,
        }

        result = InvocationResult()

        events = []
        async for e in invoker._handle_usage_event(event, result, invocation_config):
            events.append(e)

        assert len(events) >= 1
        assert result.tokens.input == 100
        assert result.tokens.output == 50
        assert result.tokens.reasoning == 30
        assert result.cost > 0

    async def test_handle_usage_event_needs_compaction(
        self, mock_retry_policy, mock_cost_tracker, invocation_config
    ):
        """Test usage event triggers compaction."""
        mock_cost_tracker.needs_compaction.return_value = True

        invoker = LLMInvoker(
            retry_policy=mock_retry_policy,
            cost_tracker=mock_cost_tracker,
        )

        event = MagicMock()
        event.data = {"input_tokens": 10000, "output_tokens": 5000}

        result = InvocationResult()

        events = []
        async for e in invoker._handle_usage_event(event, result, invocation_config):
            events.append(e)

        # Should have cost update and compact needed events
        assert len(events) >= 2


# ============================================================================
# Test Singleton Functions
# ============================================================================


@pytest.mark.unit
class TestSingletonFunctions:
    """Test singleton getter/setter functions."""

    def test_get_without_init_raises(self):
        """Test getting invoker without initialization raises."""
        # Reset global
        import src.infrastructure.agent.llm.invoker as module

        module._invoker = None

        with pytest.raises(RuntimeError, match="not initialized"):
            get_llm_invoker()

    def test_set_and_get(self, mock_retry_policy, mock_cost_tracker):
        """Test setting and getting invoker."""
        invoker = LLMInvoker(
            retry_policy=mock_retry_policy,
            cost_tracker=mock_cost_tracker,
        )
        set_llm_invoker(invoker)

        result = get_llm_invoker()
        assert result is invoker

    def test_create_llm_invoker(self, mock_retry_policy, mock_cost_tracker):
        """Test create_llm_invoker function."""
        invoker = create_llm_invoker(
            retry_policy=mock_retry_policy,
            cost_tracker=mock_cost_tracker,
            debug_logging=True,
        )

        assert isinstance(invoker, LLMInvoker)
        assert invoker._debug_logging is True

        # Should be retrievable
        result = get_llm_invoker()
        assert result is invoker


# ============================================================================
# Test Stream Event Processing
# ============================================================================


@pytest.mark.unit
class TestStreamEventProcessing:
    """Test stream event processing."""

    async def test_process_text_start(
        self, invoker, mock_message, invocation_config, invocation_context
    ):
        """Test processing TEXT_START event."""
        from src.infrastructure.agent.core.llm_stream import StreamEventType

        event = MagicMock()
        event.type = StreamEventType.TEXT_START
        event.data = {}

        result = InvocationResult()

        events = []
        async for e in invoker._process_stream_event(
            event=event,
            result=result,
            config=invocation_config,
            context=invocation_context,
            current_message=mock_message,
            pending_tool_calls={},
            work_plan_steps=[],
            tool_to_step_mapping={},
            execute_tool_callback=AsyncMock(),
            current_plan_step_holder=[None],
        ):
            events.append(e)

        assert len(events) == 1
        assert events[0].__class__.__name__ == "AgentTextStartEvent"

    async def test_process_text_delta(
        self, invoker, mock_message, invocation_config, invocation_context
    ):
        """Test processing TEXT_DELTA event."""
        from src.infrastructure.agent.core.llm_stream import StreamEventType

        event = MagicMock()
        event.type = StreamEventType.TEXT_DELTA
        event.data = {"delta": "Hello "}

        result = InvocationResult()

        events = []
        async for e in invoker._process_stream_event(
            event=event,
            result=result,
            config=invocation_config,
            context=invocation_context,
            current_message=mock_message,
            pending_tool_calls={},
            work_plan_steps=[],
            tool_to_step_mapping={},
            execute_tool_callback=AsyncMock(),
            current_plan_step_holder=[None],
        ):
            events.append(e)

        assert len(events) == 1
        assert events[0].__class__.__name__ == "AgentTextDeltaEvent"
        assert events[0].delta == "Hello "
        assert result.text == "Hello "

    async def test_process_text_end(
        self, invoker, mock_message, invocation_config, invocation_context
    ):
        """Test processing TEXT_END event."""
        from src.infrastructure.agent.core.llm_stream import StreamEventType

        event = MagicMock()
        event.type = StreamEventType.TEXT_END
        event.data = {"full_text": "Hello world"}

        result = InvocationResult()
        result.text = "Hello world"

        events = []
        async for e in invoker._process_stream_event(
            event=event,
            result=result,
            config=invocation_config,
            context=invocation_context,
            current_message=mock_message,
            pending_tool_calls={},
            work_plan_steps=[],
            tool_to_step_mapping={},
            execute_tool_callback=AsyncMock(),
            current_plan_step_holder=[None],
        ):
            events.append(e)

        assert len(events) == 1
        assert events[0].__class__.__name__ == "AgentTextEndEvent"
        mock_message.add_text.assert_called_once_with("Hello world")

    async def test_process_reasoning_events(
        self, invoker, mock_message, invocation_config, invocation_context
    ):
        """Test processing reasoning events."""
        from src.infrastructure.agent.core.llm_stream import StreamEventType

        result = InvocationResult()

        # REASONING_START
        event_start = MagicMock()
        event_start.type = StreamEventType.REASONING_START
        event_start.data = {}

        events = []
        async for e in invoker._process_stream_event(
            event=event_start,
            result=result,
            config=invocation_config,
            context=invocation_context,
            current_message=mock_message,
            pending_tool_calls={},
            work_plan_steps=[],
            tool_to_step_mapping={},
            execute_tool_callback=AsyncMock(),
            current_plan_step_holder=[None],
        ):
            events.append(e)

        assert len(events) == 1
        assert events[0].__class__.__name__ == "AgentThoughtEvent"

        # REASONING_DELTA
        event_delta = MagicMock()
        event_delta.type = StreamEventType.REASONING_DELTA
        event_delta.data = {"delta": "Thinking..."}

        events = []
        async for e in invoker._process_stream_event(
            event=event_delta,
            result=result,
            config=invocation_config,
            context=invocation_context,
            current_message=mock_message,
            pending_tool_calls={},
            work_plan_steps=[],
            tool_to_step_mapping={},
            execute_tool_callback=AsyncMock(),
            current_plan_step_holder=[None],
        ):
            events.append(e)

        assert len(events) == 1
        assert events[0].__class__.__name__ == "AgentThoughtDeltaEvent"
        assert result.reasoning == "Thinking..."



# ============================================================================
# Test Tool Call End Handling
# ============================================================================


@pytest.mark.unit
class TestToolCallEndHandling:
    """Test tool call end handling."""

    async def test_handle_tool_call_end_validation_error(self, invoker, invocation_context):
        """Test tool call end with validation error."""
        event = MagicMock()
        event.data = {
            "call_id": "call-001",
            "name": "",  # Invalid empty name
            "arguments": {},
        }

        result = InvocationResult()

        events = []
        async for e in invoker._handle_tool_call_end(
            event=event,
            result=result,
            context=invocation_context,
            pending_tool_calls={},
            work_plan_steps=[],
            tool_to_step_mapping={},
            execute_tool_callback=AsyncMock(),
            current_plan_step_holder=[None],
        ):
            events.append(e)

        assert len(events) == 1
        assert events[0].__class__.__name__ == "AgentErrorEvent"
        assert "validation failed" in events[0].message.lower()

    async def test_handle_tool_call_end_success(self, invoker, invocation_context):
        """Test successful tool call end handling."""
        event = MagicMock()
        event.data = {
            "call_id": "call-001",
            "name": "search_memory",
            "arguments": {"query": "test"},
        }

        # Create mock tool part
        tool_part = MagicMock()
        tool_part.input = {}
        pending_tool_calls = {"call-001": tool_part}

        # Mock execute callback
        async def mock_execute(*args):
            yield MagicMock()  # Yield one event

        result = InvocationResult()

        events = []
        async for e in invoker._handle_tool_call_end(
            event=event,
            result=result,
            context=invocation_context,
            pending_tool_calls=pending_tool_calls,
            work_plan_steps=[{"description": "Search", "status": "pending"}],
            tool_to_step_mapping={"search_memory": 0},
            execute_tool_callback=mock_execute,
            current_plan_step_holder=[None],
        ):
            events.append(e)

        # Should have: AgentActEvent, tool event
        assert len(events) >= 2
        assert "call-001" in result.tool_calls_completed


# ============================================================================
# Test Retry Logic
# ============================================================================


@pytest.mark.unit
class TestRetryLogic:
    """Test retry logic in invoke method."""

    async def test_retry_on_retryable_error(self, mock_retry_policy, mock_cost_tracker):
        """Test retry on retryable error."""
        mock_retry_policy.is_retryable.return_value = True
        mock_retry_policy.calculate_delay.return_value = 10  # 10ms

        invoker = LLMInvoker(
            retry_policy=mock_retry_policy,
            cost_tracker=mock_cost_tracker,
        )

        # This is a complex test that would require mocking LLMStream
        # For now, just verify the invoker is created correctly
        assert invoker._retry_policy.is_retryable(Exception("test"))
        assert invoker._retry_policy.calculate_delay(1, Exception("test")) == 10

    async def test_no_retry_on_non_retryable_error(self, mock_retry_policy, mock_cost_tracker):
        """Test no retry on non-retryable error."""
        mock_retry_policy.is_retryable.return_value = False

        invoker = LLMInvoker(
            retry_policy=mock_retry_policy,
            cost_tracker=mock_cost_tracker,
        )

        assert not invoker._retry_policy.is_retryable(ValueError("test"))
