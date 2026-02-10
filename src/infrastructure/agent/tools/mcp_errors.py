"""MCP Tool error handling and classification.

Defines error types for MCP tool execution with proper classification
for retry logic and user-friendly error messages.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional


class MCPToolErrorType(str, Enum):
    """Classification of MCP tool errors for handling strategy."""

    # Connection errors - should retry
    CONNECTION_ERROR = "connection_error"
    TIMEOUT_ERROR = "timeout_error"

    # Parameter errors - should not retry
    PARAMETER_ERROR = "parameter_error"
    VALIDATION_ERROR = "validation_error"

    # Execution errors - context dependent
    EXECUTION_ERROR = "execution_error"
    PERMISSION_ERROR = "permission_error"

    # System errors
    SANDBOX_NOT_FOUND = "sandbox_not_found"
    SANDBOX_TERMINATED = "sandbox_terminated"

    # Unknown
    UNKNOWN_ERROR = "unknown_error"


@dataclass
class MCPToolError:
    """
    Structured error information from MCP tool execution.

    Provides rich context for error handling, retry logic, and user feedback.
    """

    error_type: MCPToolErrorType
    message: str
    tool_name: str
    sandbox_id: str
    timestamp: datetime = field(default_factory=datetime.now)
    is_retryable: bool = False
    retry_count: int = 0
    max_retries: int = 0
    context: Dict[str, Any] = field(default_factory=dict)
    original_error: Optional[Exception] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "error_type": self.error_type.value,
            "message": self.message,
            "tool_name": self.tool_name,
            "sandbox_id": self.sandbox_id,
            "timestamp": self.timestamp.isoformat(),
            "is_retryable": self.is_retryable,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "context": self.context,
        }

    def get_user_message(self) -> str:
        """Get user-friendly error message."""
        if self.error_type == MCPToolErrorType.CONNECTION_ERROR:
            return "无法连接到 sandbox 容器，请稍后重试"
        if self.error_type == MCPToolErrorType.TIMEOUT_ERROR:
            return f"工具执行超时: {self.tool_name}"
        if self.error_type == MCPToolErrorType.PARAMETER_ERROR:
            return f"参数错误: {self.message}"
        if self.error_type == MCPToolErrorType.PERMISSION_ERROR:
            return f"权限被拒绝: {self.message}"
        if self.error_type == MCPToolErrorType.SANDBOX_NOT_FOUND:
            return "Sandbox 不存在或已终止"
        if self.error_type == MCPToolErrorType.SANDBOX_TERMINATED:
            return "Sandbox 已终止"
        return self.message


class MCPToolErrorClassifier:
    """
    Classify errors from MCP tool execution.

    Determines error type and retry strategy based on exception
    characteristics and context.
    """

    # Error patterns for classification
    CONNECTION_PATTERNS = [
        "connection refused",
        "connection reset",
        "connection lost",
        "websocket",
        "cannot connect",
        "failed to connect",
    ]

    TIMEOUT_PATTERNS = [
        "timeout",
        "timed out",
        "deadline exceeded",
    ]

    PARAMETER_PATTERNS = [
        "invalid parameter",
        "missing parameter",
        "required parameter",
        "validation failed",
        "invalid argument",
        "missing argument",
    ]

    PERMISSION_PATTERNS = [
        "permission denied",
        "unauthorized",
        "access denied",
        "forbidden",
        "operation not permitted",
        "eperm",
        "eacces",
    ]

    # File not found patterns - separate from parameter errors
    FILE_NOT_FOUND_PATTERNS = [
        "file not found",
        "no such file",
        "enoent",
        "does not exist",
        "not found:",
        "path not found",
        "directory not found",
    ]

    SANDBOX_NOT_FOUND_PATTERNS = [
        "sandbox not found",
        "container not found",
        "no such container",
    ]

    # Resource errors - may be retryable
    RESOURCE_PATTERNS = [
        "too large",
        "out of memory",
        "no space left",
        "disk quota",
        "file too large",
    ]

    @classmethod
    def classify(
        cls,
        error: Exception,
        tool_name: str,
        sandbox_id: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> MCPToolError:
        """
        Classify an error into an MCPToolError.

        Args:
            error: The exception that occurred
            tool_name: Name of the tool being executed
            sandbox_id: ID of the sandbox
            context: Additional context information

        Returns:
            MCPToolError with classification and retry strategy
        """
        error_message = str(error).lower()
        error_type = MCPToolErrorType.UNKNOWN_ERROR
        is_retryable = False
        max_retries = 0

        # Check timeout errors (MUST be before connection errors since
        # "timeout or connection lost" contains both patterns)
        if any(pattern in error_message for pattern in cls.TIMEOUT_PATTERNS):
            error_type = MCPToolErrorType.TIMEOUT_ERROR
            is_retryable = False
            max_retries = 0

        # Check connection errors
        elif any(pattern in error_message for pattern in cls.CONNECTION_PATTERNS):
            error_type = MCPToolErrorType.CONNECTION_ERROR
            is_retryable = True
            max_retries = 3

        # Check parameter errors
        elif any(pattern in error_message for pattern in cls.PARAMETER_PATTERNS):
            error_type = MCPToolErrorType.PARAMETER_ERROR
            is_retryable = False
            max_retries = 0

        # Check permission errors
        elif any(pattern in error_message for pattern in cls.PERMISSION_PATTERNS):
            error_type = MCPToolErrorType.PERMISSION_ERROR
            is_retryable = False
            max_retries = 0

        # Check sandbox not found (MUST be before file_not_found since "not found" overlaps)
        elif any(pattern in error_message for pattern in cls.SANDBOX_NOT_FOUND_PATTERNS):
            error_type = MCPToolErrorType.SANDBOX_NOT_FOUND
            is_retryable = False
            max_retries = 0

        # Check file not found errors (classify as parameter error - user provided wrong path)
        elif any(pattern in error_message for pattern in cls.FILE_NOT_FOUND_PATTERNS):
            error_type = MCPToolErrorType.PARAMETER_ERROR
            is_retryable = False
            max_retries = 0

        # Check resource errors (file too large, out of space)
        elif any(pattern in error_message for pattern in cls.RESOURCE_PATTERNS):
            error_type = MCPToolErrorType.EXECUTION_ERROR
            is_retryable = False
            max_retries = 0

        # Check by exception type
        elif isinstance(error, (ConnectionError, TimeoutError)):
            if "timeout" in error_message or "timed out" in error_message:
                error_type = MCPToolErrorType.TIMEOUT_ERROR
            else:
                error_type = MCPToolErrorType.CONNECTION_ERROR
            is_retryable = True
            max_retries = 2

        return MCPToolError(
            error_type=error_type,
            message=str(error),
            tool_name=tool_name,
            sandbox_id=sandbox_id,
            is_retryable=is_retryable,
            max_retries=max_retries,
            context=context or {},
            original_error=error,
        )


class RetryConfig:
    """Configuration for retry behavior."""

    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
        exponential_base: float = 2.0,
        jitter: bool = True,
    ):
        """
        Initialize retry configuration.

        Args:
            max_retries: Maximum number of retry attempts
            base_delay: Initial delay between retries in seconds
            max_delay: Maximum delay between retries
            exponential_base: Base for exponential backoff
            jitter: Whether to add random jitter to delays
        """
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.jitter = jitter

    def get_delay(self, attempt: int) -> float:
        """
        Calculate delay for a given retry attempt.

        Uses exponential backoff with optional jitter.

        Args:
            attempt: Retry attempt number (0-based)

        Returns:
            Delay in seconds
        """
        import random

        delay = min(
            self.base_delay * (self.exponential_base**attempt),
            self.max_delay,
        )

        if self.jitter:
            # Add +/- 25% jitter
            delay = delay * random.uniform(0.75, 1.25)

        return delay
