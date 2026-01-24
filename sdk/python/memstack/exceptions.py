"""
Custom exceptions for MemStack SDK.
"""


class MemStackError(Exception):
    """Base exception for MemStack SDK."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class AuthenticationError(MemStackError):
    """Raised when authentication fails."""

    pass


class APIError(MemStackError):
    """Raised when API request fails."""

    def __init__(self, message: str, status_code: int = None, response_body: dict = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class RateLimitError(MemStackError):
    """Raised when rate limit is exceeded."""

    def __init__(self, message: str, retry_after: int = None):
        super().__init__(message)
        self.retry_after = retry_after


class ValidationError(MemStackError):
    """Raised when input validation fails."""

    pass


class NetworkError(MemStackError):
    """Raised when network request fails."""

    pass
