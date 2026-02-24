"""Retry Policy - Reference: OpenCode session/retry.ts

Intelligent retry strategy with exponential backoff and
provider-specific retry-after header support.
"""

import re
from dataclasses import dataclass
from typing import ClassVar


@dataclass
class RetryableError:
    """Wrapper for retryable errors with optional retry timing."""

    message: str
    retry_after_ms: int | None = None
    attempt: int = 0


class RetryPolicy:
    """
    Intelligent retry strategy - Reference: OpenCode session/retry.ts

    Features:
    - Exponential backoff with configurable parameters
    - Provider retry-after header parsing (ms and seconds)
    - Smart error classification for retryability
    - Configurable max delay caps

    Example:
        policy = RetryPolicy()

        try:
            await call_llm()
        except Exception as e:
            if policy.is_retryable(e):
                delay = policy.calculate_delay(attempt=1, error=e)
                await asyncio.sleep(delay / 1000)
                # retry...
    """

    # Default configuration
    INITIAL_DELAY_MS = 2000
    BACKOFF_FACTOR = 2
    MAX_DELAY_NO_HEADERS_MS = 30000
    MAX_DELAY_MS = 2147483647  # 32-bit max
    MAX_ATTEMPTS = 5

    # Patterns indicating retryable errors
    RETRYABLE_PATTERNS: ClassVar[list] = [
        r"overloaded",
        r"too_many_requests",
        r"rate.?limit",
        r"exhausted",
        r"unavailable",
        r"no_kv_space",
        r"server.?error",
        r"timeout",
        r"connection.?reset",
        r"connection.?refused",
        r"temporary.?failure",
        r"service.?unavailable",
        r"bad.?gateway",
        r"gateway.?timeout",
    ]

    # HTTP status codes that indicate retryable errors
    RETRYABLE_STATUS_CODES: ClassVar[set] = {429, 500, 502, 503, 504}

    def __init__(
        self,
        initial_delay_ms: int = INITIAL_DELAY_MS,
        backoff_factor: int = BACKOFF_FACTOR,
        max_delay_ms: int = MAX_DELAY_NO_HEADERS_MS,
        max_attempts: int = MAX_ATTEMPTS,
    ) -> None:
        """
        Initialize retry policy.

        Args:
            initial_delay_ms: Initial delay before first retry (default: 2000ms)
            backoff_factor: Multiplier for each subsequent retry (default: 2)
            max_delay_ms: Maximum delay without headers (default: 30000ms)
            max_attempts: Maximum number of retry attempts (default: 5)
        """
        self.initial_delay_ms = initial_delay_ms
        self.backoff_factor = backoff_factor
        self.max_delay_ms = max_delay_ms
        self.max_attempts = max_attempts

    def is_retryable(self, error: Exception) -> bool:
        """
        Determine if an error is retryable.

        Checks:
        1. HTTP status codes (429, 5xx)
        2. Error message patterns
        3. Provider-specific indicators

        Args:
            error: The exception to check

        Returns:
            True if the error is retryable, False otherwise
        """
        error_str = str(error).lower()

        # Check for retryable patterns in error message
        for pattern in self.RETRYABLE_PATTERNS:
            if re.search(pattern, error_str, re.IGNORECASE):
                return True

        # Check HTTP status code if available
        status_code = self._get_status_code(error)
        if status_code and status_code in self.RETRYABLE_STATUS_CODES:
            return True

        # Check for specific error types
        error_type = type(error).__name__.lower()
        return bool(any(t in error_type for t in ["timeout", "connection", "temporary"]))

    def calculate_delay(self, attempt: int, error: Exception | None = None) -> int:
        """
        Calculate retry delay in milliseconds.

        Priority:
        1. Provider retry-after-ms header
        2. Provider retry-after header (seconds)
        3. Exponential backoff

        Args:
            attempt: Current attempt number (1-based)
            error: The error that triggered the retry (optional)

        Returns:
            Delay in milliseconds before next retry
        """
        # 1. Check retry-after headers from provider
        if error:
            header_delay = self._parse_retry_after_headers(error)
            if header_delay is not None:
                return header_delay

        # 2. Fall back to exponential backoff
        delay = self.initial_delay_ms * (self.backoff_factor ** (attempt - 1))
        return min(delay, self.max_delay_ms)

    def should_retry(self, attempt: int, error: Exception) -> bool:
        """
        Determine if we should retry based on attempt count and error.

        Args:
            attempt: Current attempt number (1-based)
            error: The error that occurred

        Returns:
            True if we should retry, False otherwise
        """
        if attempt >= self.max_attempts:
            return False
        return self.is_retryable(error)

    def _parse_retry_after_headers(self, error: Exception) -> int | None:
        """
        Parse retry-after headers from error response.

        Supports:
        - retry-after-ms (milliseconds)
        - retry-after (seconds or HTTP date)

        Args:
            error: The exception with response headers

        Returns:
            Delay in milliseconds, or None if no valid header found
        """
        headers = self._get_headers(error)
        if not headers:
            return None

        # Try retry-after-ms first (milliseconds)
        retry_after_ms = headers.get("retry-after-ms")
        if retry_after_ms:
            try:
                return int(retry_after_ms)
            except (ValueError, TypeError):
                pass

        # Try retry-after (seconds or HTTP date)
        retry_after = headers.get("retry-after")
        if retry_after:
            # Try parsing as seconds
            try:
                return int(float(retry_after) * 1000)
            except (ValueError, TypeError):
                pass

            # Try parsing as HTTP date
            try:
                import time
                from email.utils import parsedate_to_datetime

                dt = parsedate_to_datetime(retry_after)
                delay_seconds = dt.timestamp() - time.time()
                if delay_seconds > 0:
                    return int(delay_seconds * 1000)
            except (ValueError, TypeError, ImportError):
                pass

        return None

    def _get_headers(self, error: Exception) -> dict | None:
        """
        Extract response headers from an exception.

        Args:
            error: The exception to inspect

        Returns:
            Headers dict or None
        """
        # Try common response attributes
        for attr in ["response", "http_response", "_response"]:
            response = getattr(error, attr, None)
            if response:
                headers = getattr(response, "headers", None)
                if headers:
                    # Convert to dict if needed
                    if hasattr(headers, "items"):
                        return dict(headers.items())
                    return dict(headers)

        # Try direct headers attribute
        headers = getattr(error, "headers", None)
        if headers:
            if hasattr(headers, "items"):
                return dict(headers.items())
            return dict(headers)

        return None

    def _get_status_code(self, error: Exception) -> int | None:
        """
        Extract HTTP status code from an exception.

        Args:
            error: The exception to inspect

        Returns:
            Status code or None
        """
        # Direct status code attribute
        for attr in ["status_code", "status", "code", "http_status"]:
            code = getattr(error, attr, None)
            if code is not None:
                try:
                    return int(code)
                except (ValueError, TypeError):
                    pass

        # Try response attribute
        for attr in ["response", "http_response", "_response"]:
            response = getattr(error, attr, None)
            if response:
                for code_attr in ["status_code", "status", "code"]:
                    code = getattr(response, code_attr, None)
                    if code is not None:
                        try:
                            return int(code)
                        except (ValueError, TypeError):
                            pass

        return None

    def get_retry_message(self, attempt: int, delay_ms: int, error: Exception) -> str:
        """
        Generate a human-readable retry message.

        Args:
            attempt: Current attempt number
            delay_ms: Delay before next retry in milliseconds
            error: The error that triggered the retry

        Returns:
            Formatted retry message
        """
        error_str = str(error)
        if len(error_str) > 100:
            error_str = error_str[:100] + "..."

        return (
            f"Retry attempt {attempt}/{self.max_attempts} "
            f"after {delay_ms}ms delay. "
            f"Error: {error_str}"
        )
