"""Permission management module for tool access control."""

from .errors import PermissionDeniedError, PermissionError, PermissionRejectedError
from .manager import (
    ApprovalScope,
    InMemoryPermissionStore,
    PermissionManager,
    PermissionRequest,
    PermissionStore,
)
from .rules import PermissionAction, PermissionRule, RuleScope

__all__ = [
    "ApprovalScope",
    "InMemoryPermissionStore",
    "PermissionAction",
    "PermissionDeniedError",
    "PermissionError",
    "PermissionManager",
    "PermissionRejectedError",
    "PermissionRequest",
    "PermissionRule",
    "PermissionStore",
    "RuleScope",
]
