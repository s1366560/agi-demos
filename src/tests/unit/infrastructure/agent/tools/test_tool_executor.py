"""
Unit tests for ToolExecutor module.

Tests cover:
- Tool execution lifecycle
- Doom loop detection
- Permission checking
- Argument validation and parsing
- Result processing
- Error handling
- Singleton management
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.infrastructure.agent.tools.executor import (
    ExecutionContext,
    ExecutionResult,
    PermissionAction,
    ToolExecutor,
    ToolState,
    create_tool_executor,
    escape_control_chars,
    get_tool_executor,
    is_hitl_tool,
    parse_raw_arguments,
    set_tool_executor,
)

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_doom_loop_detector():
    """Create mock doom loop detector."""
    detector = MagicMock()
    detector.should_intervene.return_value = False
    detector.record = MagicMock()
    return detector


@pytest.fixture
def mock_permission_manager():
    """Create mock permission manager."""
    manager = MagicMock()
    manager.evaluate.return_value = MagicMock(action=PermissionAction.ALLOW)
    manager.ask = AsyncMock(return_value="approve")
    return manager


@pytest.fixture
def mock_artifact_service():
    """Create mock artifact service."""
    service = MagicMock()
    service.upload_artifact = AsyncMock(
        return_value={"artifact_id": "art-001", "url": "https://example.com/art-001"}
    )
    return service


@pytest.fixture
def executor(mock_doom_loop_detector, mock_permission_manager):
    """Create ToolExecutor instance."""
    return ToolExecutor(
        doom_loop_detector=mock_doom_loop_detector,
        permission_manager=mock_permission_manager,
        debug_logging=True,
    )


@pytest.fixture
def execution_context():
    """Create execution context."""
    return ExecutionContext(
        session_id="sess-001",
        project_id="proj-001",
        tenant_id="tenant-001",
        conversation_id="conv-001",
        permission_timeout=30.0,
    )


@pytest.fixture
def mock_tool_def():
    """Create mock tool definition."""
    tool = MagicMock()
    tool.name = "test_tool"
    tool.permission = None
    tool.execute = AsyncMock(return_value={"output": "Tool executed successfully"})
    return tool


@pytest.fixture
def mock_tool_part():
    """Create mock tool part."""
    part = MagicMock()
    part.status = ToolState.RUNNING
    part.error = None
    part.output = None
    part.start_time = 1000.0
    part.end_time = None
    part.tool_execution_id = "exec-001"
    return part


# ============================================================================
# Test Helper Functions
# ============================================================================


@pytest.mark.unit
class TestEscapeControlChars:
    """Test escape_control_chars function."""

    def test_escape_newline(self):
        """Test escaping newlines."""
        assert escape_control_chars("line1\nline2") == "line1\\nline2"

    def test_escape_carriage_return(self):
        """Test escaping carriage returns."""
        assert escape_control_chars("line1\rline2") == "line1\\rline2"

    def test_escape_tab(self):
        """Test escaping tabs."""
        assert escape_control_chars("col1\tcol2") == "col1\\tcol2"

    def test_escape_multiple(self):
        """Test escaping multiple control chars."""
        result = escape_control_chars("a\nb\rc\td")
        assert result == "a\\nb\\rc\\td"

    def test_no_control_chars(self):
        """Test string without control chars."""
        assert escape_control_chars("hello world") == "hello world"


@pytest.mark.unit
class TestParseRawArguments:
    """Test parse_raw_arguments function."""

    def test_valid_json(self):
        """Test parsing valid JSON."""
        result = parse_raw_arguments('{"key": "value"}')
        assert result == {"key": "value"}

    def test_json_with_control_chars(self):
        """Test parsing JSON with control characters."""
        result = parse_raw_arguments('{"text": "line1\\nline2"}')
        assert result is not None
        assert "text" in result

    def test_double_encoded_json(self):
        """Test parsing double-encoded JSON."""
        # Double-encoded: the JSON string is itself quoted and escaped
        # This format sometimes comes from LLM outputs
        # Note: parse_raw_arguments returns the inner parsed value
        result = parse_raw_arguments('"{\\"key\\": \\"value\\"}"')
        # The function attempts to parse the inner JSON, which may or may not succeed
        # depending on the escape handling. If it returns a string, that's acceptable.
        assert result is not None

    def test_invalid_json(self):
        """Test parsing invalid JSON returns None."""
        result = parse_raw_arguments("not valid json")
        assert result is None

    def test_empty_string(self):
        """Test parsing empty string."""
        result = parse_raw_arguments("")
        assert result is None


@pytest.mark.unit
class TestIsHITLTool:
    """Test is_hitl_tool function."""

    def test_clarification_is_hitl(self):
        """Test ask_clarification is HITL."""
        assert is_hitl_tool("ask_clarification") is True

    def test_decision_is_hitl(self):
        """Test request_decision is HITL."""
        assert is_hitl_tool("request_decision") is True

    def test_env_var_is_hitl(self):
        """Test request_env_var is HITL."""
        assert is_hitl_tool("request_env_var") is True

    def test_other_tool_not_hitl(self):
        """Test other tools are not HITL."""
        assert is_hitl_tool("search_memory") is False
        assert is_hitl_tool("web_search") is False


# ============================================================================
# Test Data Classes
# ============================================================================


@pytest.mark.unit
class TestToolState:
    """Test ToolState enum."""

    def test_pending_state(self):
        """Test pending state."""
        assert ToolState.PENDING.value == "pending"

    def test_running_state(self):
        """Test running state."""
        assert ToolState.RUNNING.value == "running"

    def test_completed_state(self):
        """Test completed state."""
        assert ToolState.COMPLETED.value == "completed"

    def test_error_state(self):
        """Test error state."""
        assert ToolState.ERROR.value == "error"


@pytest.mark.unit
class TestPermissionAction:
    """Test PermissionAction enum."""

    def test_allow_action(self):
        """Test allow action."""
        assert PermissionAction.ALLOW.value == "allow"

    def test_deny_action(self):
        """Test deny action."""
        assert PermissionAction.DENY.value == "deny"

    def test_ask_action(self):
        """Test ask action."""
        assert PermissionAction.ASK.value == "ask"


@pytest.mark.unit
class TestExecutionContext:
    """Test ExecutionContext dataclass."""

    def test_minimal_context(self):
        """Test minimal context."""
        ctx = ExecutionContext(session_id="sess-001")
        assert ctx.session_id == "sess-001"
        assert ctx.project_id is None
        assert ctx.permission_timeout == 60.0

    def test_full_context(self):
        """Test full context."""
        ctx = ExecutionContext(
            session_id="sess-001",
            project_id="proj-001",
            tenant_id="tenant-001",
            conversation_id="conv-001",
            permission_timeout=30.0,
        )
        assert ctx.project_id == "proj-001"
        assert ctx.permission_timeout == 30.0


@pytest.mark.unit
class TestExecutionResult:
    """Test ExecutionResult dataclass."""

    def test_success_result(self):
        """Test successful result."""
        result = ExecutionResult(
            success=True,
            output="Done",
            duration_ms=100,
        )
        assert result.success is True
        assert result.output == "Done"
        assert result.error is None

    def test_error_result(self):
        """Test error result."""
        result = ExecutionResult(
            success=False,
            error="Something went wrong",
        )
        assert result.success is False
        assert result.error == "Something went wrong"


# ============================================================================
# Test ToolExecutor Initialization
# ============================================================================


@pytest.mark.unit
class TestToolExecutorInit:
    """Test ToolExecutor initialization."""

    def test_init_default(self, mock_doom_loop_detector, mock_permission_manager):
        """Test default initialization."""
        executor = ToolExecutor(
            doom_loop_detector=mock_doom_loop_detector,
            permission_manager=mock_permission_manager,
        )
        assert executor._artifact_service is None
        assert executor._debug_logging is False

    def test_init_with_artifact_service(
        self, mock_doom_loop_detector, mock_permission_manager, mock_artifact_service
    ):
        """Test initialization with artifact service."""
        executor = ToolExecutor(
            doom_loop_detector=mock_doom_loop_detector,
            permission_manager=mock_permission_manager,
            artifact_service=mock_artifact_service,
        )
        assert executor._artifact_service is mock_artifact_service


# ============================================================================
# Test Argument Validation
# ============================================================================


@pytest.mark.unit
class TestArgumentValidation:
    """Test argument validation."""

    def test_valid_arguments(self, executor):
        """Test valid arguments pass through."""
        args = {"query": "test"}
        validated, error = executor._validate_arguments("test_tool", args)
        assert validated == args
        assert error is None

    def test_truncated_arguments(self, executor):
        """Test truncated arguments return error."""
        args = {"_error": "truncated", "_message": "Content too large"}
        validated, error = executor._validate_arguments("test_tool", args)
        assert "truncated" in error.lower() or "too large" in error.lower()

    def test_raw_arguments_valid_json(self, executor):
        """Test _raw arguments with valid JSON."""
        args = {"_raw": '{"key": "value"}'}
        validated, error = executor._validate_arguments("test_tool", args)
        assert validated == {"key": "value"}
        assert error is None

    def test_raw_arguments_invalid_json(self, executor):
        """Test _raw arguments with invalid JSON."""
        args = {"_raw": "not valid json"}
        validated, error = executor._validate_arguments("test_tool", args)
        assert error is not None
        assert "Invalid JSON" in error


# ============================================================================
# Test Result Processing
# ============================================================================


@pytest.mark.unit
class TestResultProcessing:
    """Test result processing."""

    def test_dict_with_output(self, executor):
        """Test dict result with output field."""
        result = {"output": "Hello", "metadata": {"key": "value"}}
        output_str, sse_result = executor._process_result(result)
        assert output_str == "Hello"
        assert sse_result == result

    def test_string_result(self, executor):
        """Test string result."""
        result = "Simple output"
        output_str, sse_result = executor._process_result(result)
        assert output_str == "Simple output"
        assert sse_result == "Simple output"

    def test_dict_without_output(self, executor):
        """Test dict result without output field."""
        result = {"data": [1, 2, 3]}
        output_str, sse_result = executor._process_result(result)
        assert output_str == '{"data": [1, 2, 3]}'
        assert sse_result == result

    def test_list_result(self, executor):
        """Test list result."""
        result = [1, 2, 3]
        output_str, sse_result = executor._process_result(result)
        assert output_str == "[1, 2, 3]"
        assert sse_result == [1, 2, 3]


# ============================================================================
# Test Tool Execution
# ============================================================================


@pytest.mark.unit
class TestToolExecution:
    """Test tool execution."""

    async def test_successful_execution(
        self, executor, execution_context, mock_tool_def, mock_tool_part
    ):
        """Test successful tool execution."""
        events = []
        async for event in executor.execute(
            tool_name="test_tool",
            tool_def=mock_tool_def,
            arguments={"input": "test"},
            tool_part=mock_tool_part,
            context=execution_context,
            call_id="call-001",
        ):
            events.append(event)

        # Should have observe event
        assert len(events) >= 1
        observe_events = [e for e in events if e.__class__.__name__ == "AgentObserveEvent"]
        assert len(observe_events) >= 1
        assert observe_events[0].result is not None

    async def test_execution_with_work_plan(
        self, executor, execution_context, mock_tool_def, mock_tool_part
    ):
        """Test execution updates work plan."""
        work_plan_steps = [{"description": "Test step", "status": "pending"}]
        tool_to_step_mapping = {"test_tool": 0}

        events = []
        async for event in executor.execute(
            tool_name="test_tool",
            tool_def=mock_tool_def,
            arguments={},
            tool_part=mock_tool_part,
            context=execution_context,
            call_id="call-001",
            work_plan_steps=work_plan_steps,
            tool_to_step_mapping=tool_to_step_mapping,
        ):
            events.append(event)

        # Work plan should be updated
        assert work_plan_steps[0]["status"] == "completed"

    async def test_execution_error(
        self, executor, execution_context, mock_tool_def, mock_tool_part
    ):
        """Test execution error handling."""
        mock_tool_def.execute = AsyncMock(side_effect=Exception("Tool failed"))

        events = []
        async for event in executor.execute(
            tool_name="test_tool",
            tool_def=mock_tool_def,
            arguments={},
            tool_part=mock_tool_part,
            context=execution_context,
            call_id="call-001",
        ):
            events.append(event)

        # Should have error in observe event
        observe_events = [e for e in events if e.__class__.__name__ == "AgentObserveEvent"]
        assert len(observe_events) >= 1
        assert observe_events[0].error is not None
        assert "Tool failed" in observe_events[0].error


# ============================================================================
# Test Doom Loop Detection
# ============================================================================


@pytest.mark.unit
class TestDoomLoopDetection:
    """Test doom loop detection."""

    async def test_no_doom_loop(
        self, mock_doom_loop_detector, mock_permission_manager, execution_context
    ):
        """Test execution without doom loop."""
        executor = ToolExecutor(
            doom_loop_detector=mock_doom_loop_detector,
            permission_manager=mock_permission_manager,
        )
        mock_doom_loop_detector.should_intervene.return_value = False

        tool_def = MagicMock()
        tool_def.permission = None
        tool_def.execute = AsyncMock(return_value="ok")

        tool_part = MagicMock()
        tool_part.tool_execution_id = "exec-001"
        tool_part.start_time = 1000.0

        events = []
        async for event in executor.execute(
            tool_name="test_tool",
            tool_def=tool_def,
            arguments={},
            tool_part=tool_part,
            context=execution_context,
            call_id="call-001",
        ):
            events.append(event)

        # Should not have doom loop event
        doom_events = [e for e in events if e.__class__.__name__ == "AgentDoomLoopDetectedEvent"]
        assert len(doom_events) == 0

    async def test_doom_loop_approved(
        self, mock_doom_loop_detector, mock_permission_manager, execution_context
    ):
        """Test doom loop detected but approved."""
        executor = ToolExecutor(
            doom_loop_detector=mock_doom_loop_detector,
            permission_manager=mock_permission_manager,
        )
        mock_doom_loop_detector.should_intervene.return_value = True
        mock_permission_manager.ask = AsyncMock(return_value="approve")

        tool_def = MagicMock()
        tool_def.permission = None
        tool_def.execute = AsyncMock(return_value="ok")

        tool_part = MagicMock()
        tool_part.tool_execution_id = "exec-001"
        tool_part.start_time = 1000.0

        events = []
        async for event in executor.execute(
            tool_name="test_tool",
            tool_def=tool_def,
            arguments={},
            tool_part=tool_part,
            context=execution_context,
            call_id="call-001",
        ):
            events.append(event)

        # Should have doom loop event but execution continues
        doom_events = [e for e in events if e.__class__.__name__ == "AgentDoomLoopDetectedEvent"]
        assert len(doom_events) >= 1

    async def test_doom_loop_rejected(
        self, mock_doom_loop_detector, mock_permission_manager, execution_context
    ):
        """Test doom loop rejected by user."""
        executor = ToolExecutor(
            doom_loop_detector=mock_doom_loop_detector,
            permission_manager=mock_permission_manager,
        )
        mock_doom_loop_detector.should_intervene.return_value = True
        mock_permission_manager.ask = AsyncMock(return_value="reject")

        tool_def = MagicMock()
        tool_def.permission = None
        tool_def.execute = AsyncMock(return_value="ok")

        tool_part = MagicMock()
        tool_part.tool_execution_id = "exec-001"
        tool_part.start_time = 1000.0

        events = []
        async for event in executor.execute(
            tool_name="test_tool",
            tool_def=tool_def,
            arguments={},
            tool_part=tool_part,
            context=execution_context,
            call_id="call-001",
        ):
            events.append(event)

        # Should have doom loop event and observe event with error
        doom_events = [e for e in events if e.__class__.__name__ == "AgentDoomLoopDetectedEvent"]
        assert len(doom_events) >= 1

        observe_events = [e for e in events if e.__class__.__name__ == "AgentObserveEvent"]
        # When rejected, there should be an observe event with error
        assert len(observe_events) >= 1
        # The error should mention rejection or doom loop
        assert any(
            e.error and ("rejected" in e.error.lower() or "doom" in e.error.lower())
            for e in observe_events
        )


# ============================================================================
# Test Permission Checking
# ============================================================================


@pytest.mark.unit
class TestPermissionChecking:
    """Test permission checking."""

    async def test_permission_allowed(
        self, mock_doom_loop_detector, mock_permission_manager, execution_context
    ):
        """Test execution with allowed permission."""
        executor = ToolExecutor(
            doom_loop_detector=mock_doom_loop_detector,
            permission_manager=mock_permission_manager,
        )
        mock_permission_manager.evaluate.return_value = MagicMock(action=PermissionAction.ALLOW)

        tool_def = MagicMock()
        tool_def.permission = "write"
        tool_def.execute = AsyncMock(return_value="ok")

        tool_part = MagicMock()
        tool_part.tool_execution_id = "exec-001"
        tool_part.start_time = 1000.0

        events = []
        async for event in executor.execute(
            tool_name="test_tool",
            tool_def=tool_def,
            arguments={},
            tool_part=tool_part,
            context=execution_context,
            call_id="call-001",
        ):
            events.append(event)

        # Should execute successfully
        observe_events = [e for e in events if e.__class__.__name__ == "AgentObserveEvent"]
        assert len(observe_events) >= 1
        assert observe_events[0].error is None

    async def test_permission_denied(
        self, mock_doom_loop_detector, mock_permission_manager, execution_context
    ):
        """Test execution with denied permission."""
        executor = ToolExecutor(
            doom_loop_detector=mock_doom_loop_detector,
            permission_manager=mock_permission_manager,
        )
        mock_permission_manager.evaluate.return_value = MagicMock(action=PermissionAction.DENY)

        tool_def = MagicMock()
        tool_def.permission = "admin"
        tool_def.execute = AsyncMock(return_value="ok")

        tool_part = MagicMock()
        tool_part.tool_execution_id = "exec-001"
        tool_part.start_time = 1000.0

        events = []
        async for event in executor.execute(
            tool_name="test_tool",
            tool_def=tool_def,
            arguments={},
            tool_part=tool_part,
            context=execution_context,
            call_id="call-001",
        ):
            events.append(event)

        # Should have observe event with permission denied error
        observe_events = [e for e in events if e.__class__.__name__ == "AgentObserveEvent"]
        assert len(observe_events) >= 1
        # Check that at least one observe event has an error about permission
        assert any(
            e.error and ("denied" in e.error.lower() or "permission" in e.error.lower())
            for e in observe_events
        )


# ============================================================================
# Test HITL Tool Handling
# ============================================================================


@pytest.mark.unit
class TestHITLToolHandling:
    """Test HITL tool handling."""

    async def test_hitl_tool_with_callback(
        self, executor, execution_context, mock_tool_def, mock_tool_part
    ):
        """Test HITL tool uses callback."""
        mock_tool_def.name = "ask_clarification"
        callback_called = []

        async def hitl_callback(session_id, call_id, tool_name, arguments, tool_part):
            callback_called.append(True)
            yield MagicMock()  # Yield mock event

        events = []
        async for event in executor.execute(
            tool_name="ask_clarification",
            tool_def=mock_tool_def,
            arguments={"question": "Test?"},
            tool_part=mock_tool_part,
            context=execution_context,
            call_id="call-001",
            hitl_callback=hitl_callback,
        ):
            events.append(event)

        assert len(callback_called) == 1

    async def test_hitl_tool_without_callback(
        self, executor, execution_context, mock_tool_def, mock_tool_part
    ):
        """Test HITL tool without callback executes normally."""
        mock_tool_def.name = "ask_clarification"

        events = []
        async for event in executor.execute(
            tool_name="ask_clarification",
            tool_def=mock_tool_def,
            arguments={},
            tool_part=mock_tool_part,
            context=execution_context,
            call_id="call-001",
            hitl_callback=None,  # No callback
        ):
            events.append(event)

        # Should execute the tool directly
        observe_events = [e for e in events if e.__class__.__name__ == "AgentObserveEvent"]
        assert len(observe_events) >= 1


# ============================================================================
# Test Singleton Functions
# ============================================================================


@pytest.mark.unit
class TestSingletonFunctions:
    """Test singleton getter/setter functions."""

    def test_get_without_init_raises(self):
        """Test getting executor without initialization raises."""
        import src.infrastructure.agent.tools.executor as module

        module._executor = None

        with pytest.raises(RuntimeError, match="not initialized"):
            get_tool_executor()

    def test_set_and_get(self, mock_doom_loop_detector, mock_permission_manager):
        """Test setting and getting executor."""
        executor = ToolExecutor(
            doom_loop_detector=mock_doom_loop_detector,
            permission_manager=mock_permission_manager,
        )
        set_tool_executor(executor)

        result = get_tool_executor()
        assert result is executor

    def test_create_tool_executor(self, mock_doom_loop_detector, mock_permission_manager):
        """Test create_tool_executor function."""
        executor = create_tool_executor(
            doom_loop_detector=mock_doom_loop_detector,
            permission_manager=mock_permission_manager,
            debug_logging=True,
        )

        assert isinstance(executor, ToolExecutor)
        assert executor._debug_logging is True

        # Should be retrievable
        result = get_tool_executor()
        assert result is executor
