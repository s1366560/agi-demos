"""
Unit tests for ReActLoop module.

Tests cover:
- Loop initialization
- Step processing
- Abort handling
- Max steps limit
- Work plan integration
- Doom loop detection
- Event emission
- Singleton management
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Any, AsyncIterator, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.domain.events.agent_events import (
    AgentActEvent,
    AgentCompleteEvent,
    AgentDomainEvent,
    AgentErrorEvent,
    AgentEventType,
    AgentObserveEvent,
    AgentStartEvent,
    AgentStepFinishEvent,
    AgentStepStartEvent,
    AgentTextDeltaEvent,
    AgentWorkPlanEvent,
)
from src.infrastructure.agent.core.react_loop import (
    LoopConfig,
    LoopContext,
    LoopResult,
    LoopState,
    ReActLoop,
    StepResult,
    create_react_loop,
    get_react_loop,
    set_react_loop,
)


# Helper to create step finish events with required fields
def make_step_finish(step_index: int, finish_reason: str) -> AgentStepFinishEvent:
    return AgentStepFinishEvent(
        step_index=step_index,
        finish_reason=finish_reason,
        tokens={"input": 100, "output": 50},
        cost=0.001,
    )


# ============================================================================
# Mock Components
# ============================================================================


class MockLLMInvoker:
    """Mock LLM invoker."""

    def __init__(self):
        self._events_to_yield = []
        self._call_count = 0

    def set_events(self, events: List[AgentDomainEvent]):
        self._events_to_yield = events

    async def invoke(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        context: Optional[Dict[str, Any]] = None,
    ) -> AsyncIterator[AgentDomainEvent]:
        self._call_count += 1
        for event in self._events_to_yield:
            yield event


class MockToolExecutor:
    """Mock tool executor."""

    def __init__(self):
        self._events_to_yield = []
        self._executed_tools = []

    def set_events(self, events: List[AgentDomainEvent]):
        self._events_to_yield = events

    async def execute(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        call_id: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> AsyncIterator[AgentDomainEvent]:
        self._executed_tools.append({
            "name": tool_name,
            "args": tool_args,
            "call_id": call_id,
        })
        for event in self._events_to_yield:
            yield event


class MockWorkPlanGenerator:
    """Mock work plan generator."""

    def __init__(self):
        self._plan_to_return = None

    def set_plan(self, plan: Optional[Dict[str, Any]]):
        self._plan_to_return = plan

    def generate(
        self,
        query: str,
        available_tools: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        return self._plan_to_return


class MockDoomLoopDetector:
    """Mock doom loop detector."""

    def __init__(self):
        self._should_detect_loop = False
        self._call_count = 0

    def set_detect_loop(self, detect: bool):
        self._should_detect_loop = detect

    def record_call(self, tool_name: str, tool_args: Dict[str, Any]) -> bool:
        self._call_count += 1
        return self._should_detect_loop

    def reset(self) -> None:
        self._call_count = 0


class MockCostTracker:
    """Mock cost tracker."""

    def __init__(self):
        self._total_cost = 0.0

    def add_usage(self, input_tokens: int, output_tokens: int, model: str) -> float:
        cost = (input_tokens + output_tokens) * 0.00001
        self._total_cost += cost
        return cost

    def get_total_cost(self) -> float:
        return self._total_cost


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_llm_invoker():
    """Create mock LLM invoker."""
    return MockLLMInvoker()


@pytest.fixture
def mock_tool_executor():
    """Create mock tool executor."""
    return MockToolExecutor()


@pytest.fixture
def mock_work_plan_generator():
    """Create mock work plan generator."""
    return MockWorkPlanGenerator()


@pytest.fixture
def mock_doom_loop_detector():
    """Create mock doom loop detector."""
    return MockDoomLoopDetector()


@pytest.fixture
def mock_cost_tracker():
    """Create mock cost tracker."""
    return MockCostTracker()


@pytest.fixture
def config():
    """Create loop config."""
    return LoopConfig(
        max_steps=10,
        max_tool_calls_per_step=5,
        enable_work_plan=True,
        enable_doom_loop_detection=True,
    )


@pytest.fixture
def context():
    """Create loop context."""
    return LoopContext(
        session_id="session-001",
        project_id="proj-001",
        user_id="user-001",
        tenant_id="tenant-001",
    )


@pytest.fixture
def loop(
    mock_llm_invoker,
    mock_tool_executor,
    mock_work_plan_generator,
    mock_doom_loop_detector,
    mock_cost_tracker,
    config,
):
    """Create ReActLoop instance."""
    return ReActLoop(
        llm_invoker=mock_llm_invoker,
        tool_executor=mock_tool_executor,
        work_plan_generator=mock_work_plan_generator,
        doom_loop_detector=mock_doom_loop_detector,
        cost_tracker=mock_cost_tracker,
        config=config,
        debug_logging=True,
    )


@pytest.fixture
def sample_messages():
    """Create sample messages."""
    return [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Hello, what can you do?"},
    ]


@pytest.fixture
def sample_tools():
    """Create sample tools."""
    return {
        "search": {
            "name": "search",
            "description": "Search the web",
            "parameters": {"type": "object", "properties": {}},
        },
        "calculate": {
            "name": "calculate",
            "description": "Perform calculations",
            "parameters": {"type": "object", "properties": {}},
        },
    }


# ============================================================================
# Test Data Classes
# ============================================================================


@pytest.mark.unit
class TestLoopState:
    """Test LoopState enum."""

    def test_states(self):
        """Test all loop states."""
        assert LoopState.IDLE.value == "idle"
        assert LoopState.THINKING.value == "thinking"
        assert LoopState.ACTING.value == "acting"
        assert LoopState.OBSERVING.value == "observing"
        assert LoopState.COMPLETED.value == "completed"
        assert LoopState.ERROR.value == "error"


@pytest.mark.unit
class TestLoopResult:
    """Test LoopResult enum."""

    def test_results(self):
        """Test all loop results."""
        assert LoopResult.CONTINUE.value == "continue"
        assert LoopResult.STOP.value == "stop"
        assert LoopResult.COMPLETE.value == "complete"
        assert LoopResult.COMPACT.value == "compact"


@pytest.mark.unit
class TestLoopConfig:
    """Test LoopConfig dataclass."""

    def test_default_config(self):
        """Test default configuration."""
        config = LoopConfig()
        assert config.max_steps == 50
        assert config.max_tool_calls_per_step == 10
        assert config.step_timeout == 300.0
        assert config.enable_work_plan is True
        assert config.enable_doom_loop_detection is True

    def test_custom_config(self):
        """Test custom configuration."""
        config = LoopConfig(
            max_steps=20,
            max_tool_calls_per_step=3,
            enable_work_plan=False,
        )
        assert config.max_steps == 20
        assert config.max_tool_calls_per_step == 3
        assert config.enable_work_plan is False


@pytest.mark.unit
class TestLoopContext:
    """Test LoopContext dataclass."""

    def test_required_fields(self):
        """Test required fields."""
        ctx = LoopContext(session_id="sess-1")
        assert ctx.session_id == "sess-1"
        assert ctx.project_id is None

    def test_all_fields(self):
        """Test all fields."""
        ctx = LoopContext(
            session_id="sess-1",
            project_id="proj-1",
            user_id="user-1",
            tenant_id="tenant-1",
            sandbox_id="sandbox-1",
            extra={"key": "value"},
        )
        assert ctx.sandbox_id == "sandbox-1"
        assert ctx.extra == {"key": "value"}


@pytest.mark.unit
class TestStepResult:
    """Test StepResult dataclass."""

    def test_default_result(self):
        """Test default step result."""
        result = StepResult(result=LoopResult.CONTINUE)
        assert result.result == LoopResult.CONTINUE
        assert result.tool_calls == []
        assert result.text_output == ""
        assert result.error is None


# ============================================================================
# Test Initialization
# ============================================================================


@pytest.mark.unit
class TestReActLoopInit:
    """Test ReActLoop initialization."""

    def test_init_with_components(self, loop):
        """Test initialization with all components."""
        assert loop.state == LoopState.IDLE
        assert loop.step_count == 0

    def test_init_minimal(self):
        """Test minimal initialization."""
        loop = ReActLoop()
        assert loop.state == LoopState.IDLE


# ============================================================================
# Test Loop Execution
# ============================================================================


@pytest.mark.unit
class TestLoopExecution:
    """Test loop execution."""

    async def test_run_emits_start_event(self, loop, sample_messages, sample_tools, context):
        """Test that run emits start event."""
        # Set up LLM to return completion
        loop._llm_invoker.set_events([
            make_step_finish(1, "stop")
        ])

        events = []
        async for event in loop.run(sample_messages, sample_tools, context):
            events.append(event)

        assert any(e.event_type == AgentEventType.START for e in events)

    async def test_run_emits_complete_event(self, loop, sample_messages, sample_tools, context):
        """Test that run emits complete event on success."""
        loop._llm_invoker.set_events([
            make_step_finish(1, "stop")
        ])

        events = []
        async for event in loop.run(sample_messages, sample_tools, context):
            events.append(event)

        assert any(e.event_type == AgentEventType.COMPLETE for e in events)
        assert loop.state == LoopState.COMPLETED

    async def test_run_respects_max_steps(self, config, sample_messages, sample_tools, context):
        """Test that run stops at max steps."""
        config.max_steps = 3

        invoker = MockLLMInvoker()
        invoker.set_events([
            AgentActEvent(tool_name="search", tool_input={}, call_id="1"),
            make_step_finish(1, "tool_calls"),
        ])

        executor = MockToolExecutor()
        executor.set_events([
            AgentObserveEvent(tool_name="search", result="done", call_id="1")
        ])

        loop = ReActLoop(
            llm_invoker=invoker,
            tool_executor=executor,
            config=config,
        )

        events = []
        async for event in loop.run(sample_messages, sample_tools, context):
            events.append(event)

        assert any(
            e.event_type == AgentEventType.ERROR and "Maximum steps" in e.message
            for e in events
        )

    async def test_run_handles_abort(self, loop, sample_messages, sample_tools, context):
        """Test that run handles abort signal."""
        abort_event = asyncio.Event()
        abort_event.set()  # Already aborted

        loop.set_abort_event(abort_event)
        loop._llm_invoker.set_events([
            make_step_finish(1, "tool_calls")
        ])

        events = []
        async for event in loop.run(sample_messages, sample_tools, context):
            events.append(event)

        assert any(
            e.event_type == AgentEventType.ERROR and "aborted" in e.message.lower()
            for e in events
        )


# ============================================================================
# Test Work Plan Integration
# ============================================================================


@pytest.mark.unit
class TestWorkPlanIntegration:
    """Test work plan integration."""

    async def test_emits_work_plan_event(
        self, loop, mock_work_plan_generator, sample_messages, sample_tools, context
    ):
        """Test that work plan event is emitted."""
        mock_work_plan_generator.set_plan({
            "id": "plan-1",
            "steps": [{"description": "Step 1"}],
        })
        loop._llm_invoker.set_events([
            make_step_finish(1, "stop")
        ])

        events = []
        async for event in loop.run(sample_messages, sample_tools, context):
            events.append(event)

        assert any(e.event_type == AgentEventType.WORK_PLAN for e in events)

    async def test_no_work_plan_when_disabled(
        self, mock_llm_invoker, sample_messages, sample_tools, context
    ):
        """Test no work plan event when disabled."""
        config = LoopConfig(enable_work_plan=False)
        mock_llm_invoker.set_events([
            make_step_finish(1, "stop")
        ])

        loop = ReActLoop(llm_invoker=mock_llm_invoker, config=config)

        events = []
        async for event in loop.run(sample_messages, sample_tools, context):
            events.append(event)

        assert not any(e.event_type == AgentEventType.WORK_PLAN for e in events)


# ============================================================================
# Test Tool Execution
# ============================================================================


@pytest.mark.unit
class TestToolExecution:
    """Test tool execution."""

    async def test_executes_tool_calls(
        self, loop, mock_tool_executor, sample_messages, sample_tools, context
    ):
        """Test that tool calls are executed."""
        loop._llm_invoker.set_events([
            AgentActEvent(tool_name="search", tool_input={"query": "test"}, call_id="call-1"),
            make_step_finish(1, "tool_calls"),
        ])
        mock_tool_executor.set_events([
            AgentObserveEvent(tool_name="search", result="found", call_id="call-1"),
        ])

        # Make loop complete after one tool execution
        loop._llm_invoker._events_to_yield = [
            AgentActEvent(tool_name="search", tool_input={"query": "test"}, call_id="call-1"),
            make_step_finish(1, "stop"),
        ]

        events = []
        async for event in loop.run(sample_messages, sample_tools, context):
            events.append(event)

        assert len(mock_tool_executor._executed_tools) >= 1
        assert mock_tool_executor._executed_tools[0]["name"] == "search"


# ============================================================================
# Test Doom Loop Detection
# ============================================================================


@pytest.mark.unit
class TestDoomLoopDetection:
    """Test doom loop detection."""

    async def test_detects_doom_loop(
        self, mock_doom_loop_detector, sample_messages, sample_tools, context
    ):
        """Test that doom loop is detected."""
        mock_doom_loop_detector.set_detect_loop(True)

        invoker = MockLLMInvoker()
        invoker.set_events([
            AgentActEvent(tool_name="search", tool_input={}, call_id="1"),
            make_step_finish(1, "tool_calls"),
        ])

        executor = MockToolExecutor()
        executor.set_events([])

        config = LoopConfig(enable_doom_loop_detection=True)
        loop = ReActLoop(
            llm_invoker=invoker,
            tool_executor=executor,
            doom_loop_detector=mock_doom_loop_detector,
            config=config,
        )

        events = []
        async for event in loop.run(sample_messages, sample_tools, context):
            events.append(event)

        assert any(
            e.event_type == AgentEventType.ERROR and "doom loop" in e.message.lower()
            for e in events
        )


# ============================================================================
# Test User Query Extraction
# ============================================================================


@pytest.mark.unit
class TestUserQueryExtraction:
    """Test user query extraction."""

    def test_extract_from_string_content(self, loop):
        """Test extraction from string content."""
        messages = [
            {"role": "user", "content": "Hello world"},
        ]
        query = loop._extract_user_query(messages)
        assert query == "Hello world"

    def test_extract_from_list_content(self, loop):
        """Test extraction from list content."""
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "What is this?"},
                ],
            },
        ]
        query = loop._extract_user_query(messages)
        assert query == "What is this?"

    def test_extract_latest_user_message(self, loop):
        """Test extraction gets latest user message."""
        messages = [
            {"role": "user", "content": "First message"},
            {"role": "assistant", "content": "Response"},
            {"role": "user", "content": "Second message"},
        ]
        query = loop._extract_user_query(messages)
        assert query == "Second message"

    def test_extract_no_user_message(self, loop):
        """Test extraction returns None when no user message."""
        messages = [
            {"role": "assistant", "content": "Hello"},
        ]
        query = loop._extract_user_query(messages)
        assert query is None


# ============================================================================
# Test Singleton Functions
# ============================================================================


@pytest.mark.unit
class TestSingletonFunctions:
    """Test singleton getter/setter functions."""

    def test_get_without_init_raises(self):
        """Test getting loop without initialization raises."""
        import src.infrastructure.agent.core.react_loop as module

        module._loop = None

        with pytest.raises(RuntimeError, match="not initialized"):
            get_react_loop()

    def test_set_and_get(self, loop):
        """Test setting and getting loop."""
        set_react_loop(loop)

        result = get_react_loop()
        assert result is loop

    def test_create_react_loop(self, mock_llm_invoker, config):
        """Test create_react_loop function."""
        loop = create_react_loop(
            llm_invoker=mock_llm_invoker,
            config=config,
            debug_logging=True,
        )

        assert isinstance(loop, ReActLoop)
        assert loop._debug_logging is True

        result = get_react_loop()
        assert result is loop
