"""
Domain exceptions for MemStack.

This module provides a hierarchy of domain-specific exceptions that
can be raised by repositories and application services.
"""

from src.domain.exceptions.repository_exceptions import (
    ConnectionError,
    DuplicateEntityError,
    EntityNotFoundError,
    OptimisticLockError,
    RepositoryError,
    TransactionError,
)

__all__ = [
    "RepositoryError",
    "EntityNotFoundError",
    "DuplicateEntityError",
    "TransactionError",
    "ConnectionError",
    "OptimisticLockError",
]
