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

# Global singleton instance
_permission_manager_instance: PermissionManager | None = None


def get_permission_manager() -> PermissionManager:
    """
    Get the global PermissionManager singleton instance.

    Returns:
        The global PermissionManager instance
    """
    global _permission_manager_instance
    if _permission_manager_instance is None:
        _permission_manager_instance = PermissionManager()
    return _permission_manager_instance


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
    "get_permission_manager",
]
