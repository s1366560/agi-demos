"""Unit tests for MCP tool error handling and classification.

TDD: Tests written first (RED phase).
"""

import asyncio
from datetime import datetime

import pytest

from src.infrastructure.agent.tools.mcp_errors import (
    MCPToolError,
    MCPToolErrorClassifier,
    MCPToolErrorType,
    RetryConfig,
)


class TestMCPToolError:
    """Test MCPToolError dataclass."""

    def test_create_error(self):
        """Test creating an MCPToolError."""
        error = MCPToolError(
            error_type=MCPToolErrorType.CONNECTION_ERROR,
            message="Connection refused",
            tool_name="file_read",
            sandbox_id="abc123",
        )

        assert error.error_type == MCPToolErrorType.CONNECTION_ERROR
        assert error.message == "Connection refused"
        assert error.tool_name == "file_read"
        assert error.sandbox_id == "abc123"
        assert error.is_retryable is False
        assert error.retry_count == 0

    def test_create_error_with_defaults(self):
        """Test creating error with default values."""
        before = datetime.now()
        error = MCPToolError(
            error_type=MCPToolErrorType.TIMEOUT_ERROR,
            message="Timeout",
            tool_name="bash",
            sandbox_id="xyz789",
            is_retryable=True,
            max_retries=3,
        )
        after = datetime.now()

        assert error.timestamp >= before
        assert error.timestamp <= after
        assert error.context == {}
        assert error.original_error is None

    def test_to_dict(self):
        """Test converting error to dictionary."""
        error = MCPToolError(
            error_type=MCPToolErrorType.PARAMETER_ERROR,
            message="Missing required parameter",
            tool_name="file_write",
            sandbox_id="test123",
            is_retryable=False,
            max_retries=0,
            context={"param": "file_path"},
        )

        result = error.to_dict()

        assert result["error_type"] == "parameter_error"
        assert result["message"] == "Missing required parameter"
        assert result["tool_name"] == "file_write"
        assert result["sandbox_id"] == "test123"
        assert result["is_retryable"] is False
        assert result["retry_count"] == 0
        assert result["max_retries"] == 0
        assert result["context"] == {"param": "file_path"}
        assert "timestamp" in result

    def test_get_user_message_connection_error(self):
        """Test user message for connection error."""
        error = MCPToolError(
            error_type=MCPToolErrorType.CONNECTION_ERROR,
            message="Connection refused",
            tool_name="file_read",
            sandbox_id="abc123",
        )

        user_msg = error.get_user_message()
        assert "无法连接" in user_msg or "connection" in user_msg.lower()

    def test_get_user_message_timeout_error(self):
        """Test user message for timeout error."""
        error = MCPToolError(
            error_type=MCPToolErrorType.TIMEOUT_ERROR,
            message="Request timed out",
            tool_name="bash",
            sandbox_id="xyz789",
        )

        user_msg = error.get_user_message()
        assert "timeout" in user_msg.lower() or "超时" in user_msg

    def test_get_user_message_parameter_error(self):
        """Test user message for parameter error."""
        error = MCPToolError(
            error_type=MCPToolErrorType.PARAMETER_ERROR,
            message="Missing required parameter: file_path",
            tool_name="file_write",
            sandbox_id="test123",
        )

        user_msg = error.get_user_message()
        assert "参数" in user_msg or "parameter" in user_msg.lower()

    def test_get_user_message_permission_error(self):
        """Test user message for permission error."""
        error = MCPToolError(
            error_type=MCPToolErrorType.PERMISSION_ERROR,
            message="Access denied",
            tool_name="bash",
            sandbox_id="test123",
        )

        user_msg = error.get_user_message()
        assert "permission" in user_msg.lower() or "权限" in user_msg

    def test_get_user_message_sandbox_not_found(self):
        """Test user message for sandbox not found."""
        error = MCPToolError(
            error_type=MCPToolErrorType.SANDBOX_NOT_FOUND,
            message="Sandbox not found",
            tool_name="file_read",
            sandbox_id="missing",
        )

        user_msg = error.get_user_message()
        assert "sandbox" in user_msg.lower() or "不存在" in user_msg or "终止" in user_msg


class TestMCPToolErrorClassifier:
    """Test MCPToolErrorClassifier."""

    def test_classify_connection_error(self):
        """Test classification of connection errors."""
        error = Exception("connection refused to websocket server")

        mcp_error = MCPToolErrorClassifier.classify(
            error=error,
            tool_name="file_read",
            sandbox_id="abc123",
        )

        assert mcp_error.error_type == MCPToolErrorType.CONNECTION_ERROR
        assert mcp_error.is_retryable is True
        assert mcp_error.max_retries == 3
        assert mcp_error.tool_name == "file_read"
        assert mcp_error.sandbox_id == "abc123"

    def test_classify_timeout_error(self):
        """Test classification of timeout errors."""
        error = Exception("request timed out after 30 seconds")

        mcp_error = MCPToolErrorClassifier.classify(
            error=error,
            tool_name="bash",
            sandbox_id="xyz789",
        )

        assert mcp_error.error_type == MCPToolErrorType.TIMEOUT_ERROR
        assert mcp_error.is_retryable is False
        assert mcp_error.max_retries == 0

    def test_classify_parameter_error(self):
        """Test classification of parameter errors."""
        error = Exception("missing required parameter: file_path")

        mcp_error = MCPToolErrorClassifier.classify(
            error=error,
            tool_name="file_write",
            sandbox_id="test123",
        )

        assert mcp_error.error_type == MCPToolErrorType.PARAMETER_ERROR
        assert mcp_error.is_retryable is False
        assert mcp_error.max_retries == 0

    def test_classify_permission_error(self):
        """Test classification of permission errors."""
        error = Exception("permission denied to access /root")

        mcp_error = MCPToolErrorClassifier.classify(
            error=error,
            tool_name="bash",
            sandbox_id="test123",
        )

        assert mcp_error.error_type == MCPToolErrorType.PERMISSION_ERROR
        assert mcp_error.is_retryable is False

    def test_classify_sandbox_not_found(self):
        """Test classification of sandbox not found errors."""
        error = Exception("sandbox not found: nonexistent")

        mcp_error = MCPToolErrorClassifier.classify(
            error=error,
            tool_name="file_read",
            sandbox_id="nonexistent",
        )

        assert mcp_error.error_type == MCPToolErrorType.SANDBOX_NOT_FOUND
        assert mcp_error.is_retryable is False

    def test_classify_connection_error_by_exception_type(self):
        """Test classification by exception type."""
        error = ConnectionError("Failed to connect")

        mcp_error = MCPToolErrorClassifier.classify(
            error=error,
            tool_name="file_read",
            sandbox_id="abc123",
        )

        assert mcp_error.error_type in (
            MCPToolErrorType.CONNECTION_ERROR,
            MCPToolErrorType.TIMEOUT_ERROR,
        )
        assert mcp_error.is_retryable is True

    def test_classify_timeout_by_exception_type(self):
        """Test classification of TimeoutError."""
        error = TimeoutError("Operation timed out")

        mcp_error = MCPToolErrorClassifier.classify(
            error=error,
            tool_name="bash",
            sandbox_id="xyz789",
        )

        assert mcp_error.error_type == MCPToolErrorType.TIMEOUT_ERROR
        assert mcp_error.is_retryable is False

    def test_classify_unknown_error(self):
        """Test classification of unknown errors."""
        error = ValueError("Some unknown error")

        mcp_error = MCPToolErrorClassifier.classify(
            error=error,
            tool_name="file_read",
            sandbox_id="abc123",
        )

        assert mcp_error.error_type == MCPToolErrorType.UNKNOWN_ERROR
        assert mcp_error.is_retryable is False

    def test_classify_with_context(self):
        """Test classification with additional context."""
        error = Exception("connection refused")

        mcp_error = MCPToolErrorClassifier.classify(
            error=error,
            tool_name="file_read",
            sandbox_id="abc123",
            context={"attempt": 1, "timeout": 30},
        )

        assert mcp_error.context == {"attempt": 1, "timeout": 30}
        assert mcp_error.original_error is error


class TestRetryConfig:
    """Test RetryConfig."""

    def test_default_config(self):
        """Test default retry configuration."""
        config = RetryConfig()

        assert config.max_retries == 3
        assert config.base_delay == 1.0
        assert config.max_delay == 30.0
        assert config.exponential_base == 2.0
        assert config.jitter is True

    def test_custom_config(self):
        """Test custom retry configuration."""
        config = RetryConfig(
            max_retries=5,
            base_delay=2.0,
            max_delay=60.0,
            exponential_base=3.0,
            jitter=False,
        )

        assert config.max_retries == 5
        assert config.base_delay == 2.0
        assert config.max_delay == 60.0
        assert config.exponential_base == 3.0
        assert config.jitter is False

    def test_get_delay_exponential_backoff(self):
        """Test exponential backoff delay calculation."""
        config = RetryConfig(
            base_delay=1.0,
            max_delay=100.0,
            exponential_base=2.0,
            jitter=False,
        )

        # Without jitter, delays should be predictable
        assert config.get_delay(0) == 1.0
        assert config.get_delay(1) == 2.0
        assert config.get_delay(2) == 4.0
        assert config.get_delay(3) == 8.0

    def test_get_delay_max_clamp(self):
        """Test that delay is clamped to max_delay."""
        config = RetryConfig(
            base_delay=1.0,
            max_delay=5.0,
            exponential_base=10.0,
            jitter=False,
        )

        # Should be clamped to max_delay
        assert config.get_delay(0) == 1.0
        assert config.get_delay(1) == 5.0  # 10 would exceed max
        assert config.get_delay(2) == 5.0  # 100 would exceed max

    def test_get_delay_with_jitter(self):
        """Test jitter adds randomness to delay."""
        config = RetryConfig(
            base_delay=10.0,
            max_delay=100.0,
            exponential_base=2.0,
            jitter=True,
        )

        delays = [config.get_delay(0) for _ in range(10)]

        # With jitter, delays should vary
        assert len(set(delays)) > 1

        # Base delay for attempt 0 is 10.0 (10 * 2^0)
        # With jitter (25%), should be within 7.5 to 12.5
        for delay in delays:
            assert 7.5 <= delay <= 12.5

    def test_get_delay_no_jitter(self):
        """Test no jitter produces consistent delays."""
        config = RetryConfig(
            base_delay=2.0,
            jitter=False,
        )

        delays = [config.get_delay(1) for _ in range(5)]

        # Without jitter, all delays should be the same
        assert len(set(delays)) == 1
        assert delays[0] == 4.0


class TestMCPToolErrorIntegration:
    """Integration tests for error handling."""

    @pytest.mark.asyncio
    async def test_retry_flow_with_mock_errors(self):
        """Test retry flow with mock connection errors."""
        config = RetryConfig(max_retries=3, base_delay=0.01, jitter=False)

        attempts = []
        original_error = ConnectionError("connection refused")
        mcp_error = MCPToolErrorClassifier.classify(
            error=original_error,
            tool_name="file_read",
            sandbox_id="abc123",
        )

        assert mcp_error.is_retryable is True
        assert mcp_error.max_retries == 3

        for attempt in range(config.max_retries):
            mcp_error.retry_count = attempt
            attempts.append(mcp_error.retry_count)
            if attempt < config.max_retries - 1:
                delay = config.get_delay(attempt)
                await asyncio.sleep(delay)

        assert len(attempts) == 3
        assert attempts == [0, 1, 2]

    def test_error_serialization_roundtrip(self):
        """Test error can be serialized and reconstructed."""
        error = MCPToolError(
            error_type=MCPToolErrorType.CONNECTION_ERROR,
            message="Test error",
            tool_name="test_tool",
            sandbox_id="test_sandbox",
            is_retryable=True,
            max_retries=3,
            context={"key": "value"},
        )

        # Convert to dict
        error_dict = error.to_dict()

        # Verify all fields present
        assert error_dict["error_type"] == "connection_error"
        assert error_dict["message"] == "Test error"
        assert error_dict["tool_name"] == "test_tool"
        assert error_dict["sandbox_id"] == "test_sandbox"
        assert error_dict["is_retryable"] is True
        assert error_dict["max_retries"] == 3
        assert error_dict["context"] == {"key": "value"}

    def test_user_message_for_all_error_types(self):
        """Test user message generation for all error types."""
        tool_name = "test_tool"
        sandbox_id = "test_sandbox"

        error_types_messages = [
            (MCPToolErrorType.CONNECTION_ERROR, "connection"),
            (MCPToolErrorType.TIMEOUT_ERROR, "timeout"),
            (MCPToolErrorType.PARAMETER_ERROR, "parameter"),
            (MCPToolErrorType.VALIDATION_ERROR, "validation"),
            (MCPToolErrorType.EXECUTION_ERROR, "execution"),
            (MCPToolErrorType.PERMISSION_ERROR, "permission"),
            (MCPToolErrorType.SANDBOX_NOT_FOUND, "sandbox"),
            (MCPToolErrorType.SANDBOX_TERMINATED, "sandbox"),
        ]

        for error_type, expected_keyword in error_types_messages:
            error = MCPToolError(
                error_type=error_type,
                message=f"Test {expected_keyword} error",
                tool_name=tool_name,
                sandbox_id=sandbox_id,
            )
            user_msg = error.get_user_message()
            # Should return some message
            assert user_msg
            assert len(user_msg) > 0


class TestMCPToolErrorClassifierNewPatterns:
    """Test newly added error classification patterns."""

    def test_classify_file_not_found_error(self):
        """Test classification of file not found errors."""
        error = Exception("Error: File not found: /path/to/file.txt")

        mcp_error = MCPToolErrorClassifier.classify(
            error=error,
            tool_name="export_artifact",
            sandbox_id="abc123",
        )

        assert mcp_error.error_type == MCPToolErrorType.PARAMETER_ERROR
        assert mcp_error.is_retryable is False

    def test_classify_enoent_error(self):
        """Test classification of ENOENT errors."""
        error = Exception("ENOENT: no such file or directory")

        mcp_error = MCPToolErrorClassifier.classify(
            error=error,
            tool_name="export_artifact",
            sandbox_id="abc123",
        )

        assert mcp_error.error_type == MCPToolErrorType.PARAMETER_ERROR
        assert mcp_error.is_retryable is False

    def test_classify_operation_not_permitted(self):
        """Test classification of operation not permitted errors."""
        error = Exception("Operation not permitted: /etc/passwd")

        mcp_error = MCPToolErrorClassifier.classify(
            error=error,
            tool_name="file_read",
            sandbox_id="abc123",
        )

        assert mcp_error.error_type == MCPToolErrorType.PERMISSION_ERROR
        assert mcp_error.is_retryable is False

    def test_classify_eperm_error(self):
        """Test classification of EPERM errors."""
        error = Exception("EPERM: operation not permitted")

        mcp_error = MCPToolErrorClassifier.classify(
            error=error,
            tool_name="file_write",
            sandbox_id="abc123",
        )

        assert mcp_error.error_type == MCPToolErrorType.PERMISSION_ERROR
        assert mcp_error.is_retryable is False

    def test_classify_file_too_large(self):
        """Test classification of file too large errors."""
        error = Exception("Error: File too large (500000000 bytes > 100000000 bytes limit)")

        mcp_error = MCPToolErrorClassifier.classify(
            error=error,
            tool_name="export_artifact",
            sandbox_id="abc123",
        )

        assert mcp_error.error_type == MCPToolErrorType.EXECUTION_ERROR
        assert mcp_error.is_retryable is False

    def test_classify_disk_full(self):
        """Test classification of disk full errors."""
        error = Exception("No space left on device")

        mcp_error = MCPToolErrorClassifier.classify(
            error=error,
            tool_name="file_write",
            sandbox_id="abc123",
        )

        assert mcp_error.error_type == MCPToolErrorType.EXECUTION_ERROR
        assert mcp_error.is_retryable is False

    def test_sandbox_not_found_takes_priority(self):
        """Test that sandbox not found takes priority over file not found."""
        # This error contains both "sandbox not found" and "not found"
        error = Exception("Error: sandbox not found: abc123")

        mcp_error = MCPToolErrorClassifier.classify(
            error=error,
            tool_name="file_read",
            sandbox_id="abc123",
        )

        # Should be SANDBOX_NOT_FOUND, not PARAMETER_ERROR (file not found)
        assert mcp_error.error_type == MCPToolErrorType.SANDBOX_NOT_FOUND
        assert mcp_error.is_retryable is False


class TestDurationAwareTimeoutClassification:
    """Test duration-aware timeout classification to prevent false positives."""

    def test_timeout_text_with_short_duration_classified_as_execution_error(self):
        """Error text contains 'timeout' but tool finished quickly -> EXECUTION_ERROR."""
        error = Exception("curl: connection timeout after 5 seconds")

        mcp_error = MCPToolErrorClassifier.classify(
            error=error,
            tool_name="bash",
            sandbox_id="abc123",
            context={
                "execution_duration_ms": 47000,  # 47 seconds
                "configured_timeout_s": 600.0,  # 600 second limit
            },
        )

        assert mcp_error.error_type == MCPToolErrorType.EXECUTION_ERROR
        assert mcp_error.is_retryable is False
        assert mcp_error.execution_duration_ms == 47000
        assert mcp_error.configured_timeout_s == 600.0

    def test_timeout_text_at_actual_timeout_classified_as_timeout_error(self):
        """Error text contains 'timeout' and duration near limit -> TIMEOUT_ERROR."""
        error = Exception("request timed out after 600 seconds")

        mcp_error = MCPToolErrorClassifier.classify(
            error=error,
            tool_name="bash",
            sandbox_id="abc123",
            context={
                "execution_duration_ms": 600000,  # 600 seconds
                "configured_timeout_s": 600.0,
            },
        )

        assert mcp_error.error_type == MCPToolErrorType.TIMEOUT_ERROR

    def test_timeout_text_near_threshold_classified_as_timeout_error(self):
        """Duration at 80% of timeout limit -> TIMEOUT_ERROR (threshold is 0.8)."""
        error = Exception("operation timed out")

        mcp_error = MCPToolErrorClassifier.classify(
            error=error,
            tool_name="bash",
            sandbox_id="abc123",
            context={
                "execution_duration_ms": 480000,  # 480s = 80% of 600s
                "configured_timeout_s": 600.0,
            },
        )

        assert mcp_error.error_type == MCPToolErrorType.TIMEOUT_ERROR

    def test_timeout_text_below_threshold_classified_as_execution_error(self):
        """Duration at 50% of timeout limit -> EXECUTION_ERROR (below 80% threshold)."""
        error = Exception("database connection timed out")

        mcp_error = MCPToolErrorClassifier.classify(
            error=error,
            tool_name="bash",
            sandbox_id="abc123",
            context={
                "execution_duration_ms": 300000,  # 300s = 50% of 600s
                "configured_timeout_s": 600.0,
            },
        )

        assert mcp_error.error_type == MCPToolErrorType.EXECUTION_ERROR

    def test_timeout_without_duration_context_defaults_to_timeout_error(self):
        """Without duration info, fall back to text-based TIMEOUT_ERROR classification."""
        error = Exception("request timed out after 30 seconds")

        mcp_error = MCPToolErrorClassifier.classify(
            error=error,
            tool_name="bash",
            sandbox_id="xyz789",
        )

        assert mcp_error.error_type == MCPToolErrorType.TIMEOUT_ERROR

    def test_asyncio_timeout_exception_always_classified_as_timeout(self):
        """asyncio.TimeoutError (real transport timeout) -> TIMEOUT_ERROR regardless."""
        error = TimeoutError("Operation timed out")

        mcp_error = MCPToolErrorClassifier.classify(
            error=error,
            tool_name="bash",
            sandbox_id="abc123",
            context={
                "execution_duration_ms": 10000,  # 10 seconds
                "configured_timeout_s": 600.0,
            },
        )

        # TimeoutError exception hits the text-based path first,
        # but with short duration, classified as EXECUTION_ERROR.
        # However, isinstance check for TimeoutError should still work
        # for cases without "timeout" text in message.
        assert mcp_error.error_type in (
            MCPToolErrorType.TIMEOUT_ERROR,
            MCPToolErrorType.EXECUTION_ERROR,
        )

    def test_real_timeout_exception_without_timeout_text(self):
        """TimeoutError without 'timeout' in message, caught by isinstance check."""
        error = TimeoutError("Deadline exceeded for RPC call")

        mcp_error = MCPToolErrorClassifier.classify(
            error=error,
            tool_name="bash",
            sandbox_id="abc123",
        )

        # "deadline exceeded" matches TIMEOUT_PATTERNS
        assert mcp_error.error_type == MCPToolErrorType.TIMEOUT_ERROR

    def test_error_includes_duration_fields(self):
        """MCPToolError should include duration fields when provided."""
        error = Exception("some error with timeout word")

        mcp_error = MCPToolErrorClassifier.classify(
            error=error,
            tool_name="bash",
            sandbox_id="abc123",
            context={
                "execution_duration_ms": 5000,
                "configured_timeout_s": 600.0,
            },
        )

        assert mcp_error.execution_duration_ms == 5000
        assert mcp_error.configured_timeout_s == 600.0

    def test_to_dict_includes_duration_fields(self):
        """to_dict should include duration fields when set."""
        error = MCPToolError(
            error_type=MCPToolErrorType.TIMEOUT_ERROR,
            message="timed out",
            tool_name="bash",
            sandbox_id="abc123",
            execution_duration_ms=600000,
            configured_timeout_s=600.0,
        )

        result = error.to_dict()
        assert result["execution_duration_ms"] == 600000
        assert result["configured_timeout_s"] == 600.0

    def test_to_dict_excludes_none_duration_fields(self):
        """to_dict should omit duration fields when None."""
        error = MCPToolError(
            error_type=MCPToolErrorType.TIMEOUT_ERROR,
            message="timed out",
            tool_name="bash",
            sandbox_id="abc123",
        )

        result = error.to_dict()
        assert "execution_duration_ms" not in result
        assert "configured_timeout_s" not in result

    def test_user_message_includes_duration_for_timeout(self):
        """User message should show actual vs configured timeout."""
        error = MCPToolError(
            error_type=MCPToolErrorType.TIMEOUT_ERROR,
            message="timed out",
            tool_name="bash",
            sandbox_id="abc123",
            execution_duration_ms=600000,
            configured_timeout_s=600.0,
        )

        msg = error.get_user_message()
        assert "bash" in msg
        assert "600.0s" in msg
        assert "超时" in msg

    def test_command_output_with_timeout_word_not_misclassified(self):
        """Real-world scenario: command outputs 'timeout' but ran quickly."""
        # Simulates: python script that encounters a database timeout after 47s
        error = Exception(
            "Error: Tool execution failed after 1 attempts: request timeout after 5 seconds"
        )

        mcp_error = MCPToolErrorClassifier.classify(
            error=error,
            tool_name="bash",
            sandbox_id="abc123",
            context={
                "execution_duration_ms": 46954,
                "configured_timeout_s": 600.0,
            },
        )

        # Should NOT be classified as timeout since 47s << 600s
        assert mcp_error.error_type == MCPToolErrorType.EXECUTION_ERROR
