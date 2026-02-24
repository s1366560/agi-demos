"""Permission management module for tool access control."""

from .errors import PermissionDeniedError, PermissionError, PermissionRejectedError
from .manager import PermissionManager, PermissionRequest
from .rules import PermissionAction, PermissionRule

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
    "PermissionAction",
    "PermissionDeniedError",
    "PermissionError",
    "PermissionManager",
    "PermissionRejectedError",
    "PermissionRequest",
    "PermissionRule",
    "get_permission_manager",
]
