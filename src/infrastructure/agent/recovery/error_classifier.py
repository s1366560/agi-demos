"""Error Classifier for agent session recovery.

Classifies exceptions into recovery-actionable error types by inspecting
error messages, HTTP status codes, and exception class hierarchies.

Reference: OpenCode session recovery patterns.
"""

from __future__ import annotations

import logging
import re
from enum import Enum
from typing import ClassVar

from src.infrastructure.agent.errors import (
    AgentCommunicationError,
    AgentError,
    AgentExecutionError,
    AgentResourceError,
    AgentTimeoutError,
    ErrorCategory,
)

logger = logging.getLogger(__name__)


class ErrorType(str, Enum):
    """Recovery-actionable error types."""

    LLM_RATE_LIMIT = "llm_rate_limit"
    LLM_CONTEXT_OVERFLOW = "llm_context_overflow"
    LLM_PROVIDER_DOWN = "llm_provider_down"
    LLM_AUTH_ERROR = "llm_auth_error"
    TOOL_EXECUTION_ERROR = "tool_execution_error"
    TOOL_TIMEOUT = "tool_timeout"
    DOOM_LOOP = "doom_loop"
    SANDBOX_ERROR = "sandbox_error"
    UNKNOWN = "unknown"


class ErrorClassifier:
    """Classifies exceptions into recovery-actionable error types.

    Inspects error messages, HTTP status codes, exception hierarchies,
    and error codes to determine the appropriate ErrorType for recovery
    strategy selection.

    Example:
        classifier = ErrorClassifier()
        error_type = classifier.classify(some_exception)
        # error_type == ErrorType.LLM_RATE_LIMIT
    """

    # Patterns for rate limit detection
    RATE_LIMIT_PATTERNS: ClassVar[list[str]] = [
        r"rate.?limit",
        r"too.?many.?requests",
        r"quota.?exceeded",
        r"throttl",
        r"exhausted",
        r"insufficient balance",
        r"no resource package",
        r"vendor_rate_limit",
    ]

    # Patterns for context overflow detection
    CONTEXT_OVERFLOW_PATTERNS: ClassVar[list[str]] = [
        r"context.?(?:length|window|limit|too\s+long)",
        r"token.?limit",
        r"maximum.?(?:context|token)",
        r"exceed.{0,20}(?:token|context|length)",
        r"too.?(?:many|long).?token",
        r"input.?too.?long",
        r"prompt.?too.?long",
    ]

    # Patterns for provider down detection
    PROVIDER_DOWN_PATTERNS: ClassVar[list[str]] = [
        r"server.?error",
        r"service.?unavailable",
        r"bad.?gateway",
        r"gateway.?timeout",
        r"connection.?(?:refused|reset|error|timeout)",
        r"network.?error",
        r"internal.?server.?error",
        r"temporarily.?unavailable",
        r"overloaded",
    ]

    # Patterns for auth error detection
    AUTH_ERROR_PATTERNS: ClassVar[list[str]] = [
        r"(?:invalid|expired|missing).?(?:api.?key|token|credential)",
        r"unauthorized",
        r"forbidden",
        r"authentication.?(?:failed|error|required)",
        r"permission.?denied",
        r"access.?denied",
    ]

    # Patterns for doom loop detection
    DOOM_LOOP_PATTERNS: ClassVar[list[str]] = [
        r"doom.?loop",
        r"stuck.?(?:in\s+)?(?:a\s+)?loop",
        r"repetitive.?(?:loop|pattern|action)",
        r"infinite.?loop",
    ]

    # Patterns for sandbox error detection
    SANDBOX_PATTERNS: ClassVar[list[str]] = [
        r"sandbox",
        r"container.?(?:error|failed|unavailable|timeout)",
        r"docker.?(?:error|failed)",
    ]

    # HTTP status code mappings
    RATE_LIMIT_STATUS_CODES: ClassVar[set[int]] = {429}
    PROVIDER_DOWN_STATUS_CODES: ClassVar[set[int]] = {500, 502, 503, 504}
    AUTH_ERROR_STATUS_CODES: ClassVar[set[int]] = {401, 403}

    def classify(self, error: Exception) -> ErrorType:
        """Classify an exception into a recovery-actionable error type.

        Classification priority:
        1. Error code checks (e.g., DOOM_LOOP_DETECTED)
        2. AgentError subclass checks (type-based)
        3. HTTP status code checks
        4. Error message pattern matching

        Args:
            error: The exception to classify.

        Returns:
            The classified ErrorType.
        """
        # 1. Check error codes first (most specific)
        code_result = self._classify_by_error_code(error)
        if code_result is not None:
            return code_result

        # 2. Check AgentError subclasses
        subclass_result = self._classify_by_agent_error_type(error)
        if subclass_result is not None:
            return subclass_result

        # 3. Check HTTP status codes
        status_result = self._classify_by_status_code(error)
        if status_result is not None:
            return status_result

        # 4. Check error message patterns
        pattern_result = self._classify_by_message_pattern(error)
        if pattern_result is not None:
            return pattern_result

        logger.debug(
            "Could not classify error: %s (%s)",
            error,
            type(error).__name__,
        )
        return ErrorType.UNKNOWN

    def _classify_by_error_code(self, error: Exception) -> ErrorType | None:
        """Classify by known error codes from the agent system."""
        code = self._get_error_code(error)
        if code is None:
            return None

        code_upper = code.upper()
        if code_upper == "DOOM_LOOP_DETECTED":
            return ErrorType.DOOM_LOOP
        if code_upper in {"TOOL_TIMEOUT", "TIMEOUT"}:
            return ErrorType.TOOL_TIMEOUT
        if code_upper == "TOOL_EXECUTION_ERROR":
            return ErrorType.TOOL_EXECUTION_ERROR
        return None

    def _classify_by_agent_error_type(
        self,
        error: Exception,
    ) -> ErrorType | None:
        """Classify based on AgentError subclass hierarchy."""
        if not isinstance(error, AgentError):
            return None

        # Dispatch to subclass-specific handlers (order matters)
        for error_type, handler in (
            (AgentTimeoutError, self._classify_timeout),
            (AgentExecutionError, self._classify_execution),
            (AgentCommunicationError, self._classify_communication),
            (AgentResourceError, self._classify_resource),
        ):
            if isinstance(error, error_type):
                return handler(error)

        # Check category for remaining AgentError types
        if error.category == ErrorCategory.PERMISSION:
            return ErrorType.LLM_AUTH_ERROR

        return None

    @staticmethod
    def _classify_timeout(error: AgentError) -> ErrorType:
        """Classify an AgentTimeoutError."""
        operation = getattr(error, "operation", "") or ""
        if "tool" in operation.lower():
            return ErrorType.TOOL_TIMEOUT
        return ErrorType.LLM_PROVIDER_DOWN

    @staticmethod
    def _classify_execution(
        error: AgentError,
    ) -> ErrorType:
        """Classify an AgentExecutionError."""
        return ErrorType.TOOL_EXECUTION_ERROR

    def _classify_communication(
        self,
        error: AgentError,
    ) -> ErrorType:
        """Classify an AgentCommunicationError."""
        status_code = getattr(error, "status_code", None)
        if status_code is not None:
            status_result = self._map_status_code(status_code)
            if status_result is not None:
                return status_result
        return ErrorType.LLM_PROVIDER_DOWN

    @staticmethod
    def _classify_resource(
        error: AgentError,
    ) -> ErrorType:
        """Classify an AgentResourceError."""
        resource_type = (
            getattr(error, "resource_type", "") or ""
        )
        resource_lower = resource_type.lower()
        if "context" in resource_lower or "token" in resource_lower:
            return ErrorType.LLM_CONTEXT_OVERFLOW
        return ErrorType.LLM_RATE_LIMIT

    def _classify_by_status_code(self, error: Exception) -> ErrorType | None:
        """Classify based on HTTP status codes from the error."""
        status_code = self._get_status_code(error)
        if status_code is None:
            return None
        return self._map_status_code(status_code)

    # Pattern-to-ErrorType mapping, checked in priority order.
    _MESSAGE_PATTERN_MAP: ClassVar[
        list[tuple[list[str], ErrorType]]
    ] = [
        (DOOM_LOOP_PATTERNS, ErrorType.DOOM_LOOP),
        (RATE_LIMIT_PATTERNS, ErrorType.LLM_RATE_LIMIT),
        (AUTH_ERROR_PATTERNS, ErrorType.LLM_AUTH_ERROR),
        (CONTEXT_OVERFLOW_PATTERNS, ErrorType.LLM_CONTEXT_OVERFLOW),
        (SANDBOX_PATTERNS, ErrorType.SANDBOX_ERROR),
        (PROVIDER_DOWN_PATTERNS, ErrorType.LLM_PROVIDER_DOWN),
    ]

    def _classify_by_message_pattern(
        self,
        error: Exception,
    ) -> ErrorType | None:
        """Classify based on error message pattern matching."""
        error_msg = str(error).lower()

        # Check message content against ordered pattern groups
        for patterns, error_type in self._MESSAGE_PATTERN_MAP:
            if self._matches_any(error_msg, patterns):
                return error_type

        # Check for timeout in exception type name
        error_type_name = type(error).__name__.lower()
        if "timeout" in error_type_name:
            return ErrorType.TOOL_TIMEOUT

        return None

    def _map_status_code(self, status_code: int) -> ErrorType | None:
        """Map an HTTP status code to an ErrorType."""
        if status_code in self.RATE_LIMIT_STATUS_CODES:
            return ErrorType.LLM_RATE_LIMIT
        if status_code in self.AUTH_ERROR_STATUS_CODES:
            return ErrorType.LLM_AUTH_ERROR
        if status_code in self.PROVIDER_DOWN_STATUS_CODES:
            return ErrorType.LLM_PROVIDER_DOWN
        return None

    @staticmethod
    def _matches_any(text: str, patterns: list[str]) -> bool:
        """Check if text matches any of the given regex patterns."""
        return any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns)

    @staticmethod
    def _get_status_code(error: Exception) -> int | None:
        """Extract HTTP status code from an exception."""
        for attr in (
            "status_code",
            "status",
            "code",
            "http_status",
        ):
            code = getattr(error, attr, None)
            if code is not None:
                try:
                    return int(code)
                except (ValueError, TypeError):
                    pass

        # Check nested response attribute
        for attr in ("response", "http_response", "_response"):
            response = getattr(error, attr, None)
            if response is not None:
                for code_attr in ("status_code", "status", "code"):
                    code = getattr(response, code_attr, None)
                    if code is not None:
                        try:
                            return int(code)
                        except (ValueError, TypeError):
                            pass
        return None

    @staticmethod
    def _get_error_code(error: Exception) -> str | None:
        """Extract error code string from an exception."""
        code = getattr(error, "code", None)
        if isinstance(code, str):
            return code
        return None
