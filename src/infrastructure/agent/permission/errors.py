"""Permission errors for tool access control."""


class PermissionError(Exception):
    """Base class for permission errors."""

    pass


class PermissionDeniedError(PermissionError):
    """Raised when a permission is denied by rule."""

    def __init__(self, permission: str, pattern: str, message: str | None = None) -> None:
        self.permission = permission
        self.pattern = pattern
        super().__init__(message or f"Permission denied: {permission} for pattern '{pattern}'")


class PermissionRejectedError(PermissionError):
    """Raised when a user rejects a permission request."""

    def __init__(self, permission: str, patterns: list[str], message: str | None = None) -> None:
        self.permission = permission
        self.patterns = patterns
        super().__init__(
            message or f"Permission rejected by user: {permission} for patterns {patterns}"
        )
