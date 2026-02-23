"""
AuthorizationService: Backward-compatible re-export.

The implementation has moved to src.infrastructure.security.authorization_service
since it depends on SQLAlchemy ORM models (infrastructure concern).

Import from here is preserved for backward compatibility.
"""

from src.infrastructure.security.authorization_service import (
    AuthorizationService,
)

__all__ = ["AuthorizationService"]
