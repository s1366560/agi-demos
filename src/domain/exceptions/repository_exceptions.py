"""
Repository-related domain exceptions.

These exceptions provide a clean abstraction over infrastructure-level
database errors, allowing the domain and application layers to handle
errors without knowledge of the underlying persistence technology.

Exception Hierarchy:
    RepositoryError (base)
    ├── EntityNotFoundError    - Entity not found by ID/query
    ├── DuplicateEntityError   - Unique constraint violation
    ├── TransactionError       - Transaction commit/rollback failure
    ├── ConnectionError        - Database connection issues
    └── OptimisticLockError    - Concurrent modification detected

Usage:
    from src.domain.exceptions import EntityNotFoundError

    try:
        user = await user_repository.find_by_id(user_id)
        if user is None:
            raise EntityNotFoundError("User", user_id)
    except EntityNotFoundError as e:
        # Handle not found case
        pass
"""

from typing import Any, Optional


class RepositoryError(Exception):
    """
    Base exception for all repository-related errors.

    This is the base class for all persistence-layer exceptions.
    Catch this to handle any repository error generically.

    Attributes:
        message: Human-readable error description
        original_error: The underlying exception (if any)
        details: Additional context about the error
    """

    def __init__(
        self,
        message: str,
        original_error: Optional[Exception] = None,
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.original_error = original_error
        self.details = details or {}

    def __str__(self) -> str:
        if self.original_error:
            return f"{self.message} (caused by: {self.original_error})"
        return self.message


class EntityNotFoundError(RepositoryError):
    """
    Raised when an entity cannot be found by its identifier.

    Attributes:
        entity_type: Name of the entity type (e.g., "User", "Project")
        entity_id: The ID that was searched for
    """

    def __init__(
        self,
        entity_type: str,
        entity_id: str,
        message: Optional[str] = None,
    ) -> None:
        self.entity_type = entity_type
        self.entity_id = entity_id
        msg = message or f"{entity_type} with ID '{entity_id}' not found"
        super().__init__(msg, details={"entity_type": entity_type, "entity_id": entity_id})


class DuplicateEntityError(RepositoryError):
    """
    Raised when attempting to create an entity that violates a unique constraint.

    This typically occurs when:
    - Creating an entity with an ID that already exists
    - Creating an entity with a unique field value that already exists

    Attributes:
        entity_type: Name of the entity type
        field_name: Name of the field that caused the conflict
        field_value: The conflicting value
    """

    def __init__(
        self,
        entity_type: str,
        field_name: str,
        field_value: Any,
        message: Optional[str] = None,
    ) -> None:
        self.entity_type = entity_type
        self.field_name = field_name
        self.field_value = field_value
        msg = message or f"{entity_type} with {field_name}='{field_value}' already exists"
        super().__init__(
            msg,
            details={
                "entity_type": entity_type,
                "field_name": field_name,
                "field_value": str(field_value),
            },
        )


class TransactionError(RepositoryError):
    """
    Raised when a transaction operation fails.

    This can occur during:
    - Transaction commit
    - Transaction rollback
    - Savepoint operations

    Attributes:
        operation: The operation that failed (e.g., "commit", "rollback")
    """

    def __init__(
        self,
        operation: str,
        message: Optional[str] = None,
        original_error: Optional[Exception] = None,
    ) -> None:
        self.operation = operation
        msg = message or f"Transaction {operation} failed"
        super().__init__(msg, original_error=original_error, details={"operation": operation})


class ConnectionError(RepositoryError):
    """
    Raised when unable to connect to the database.

    This can occur due to:
    - Network issues
    - Database server unavailable
    - Authentication failures
    - Connection pool exhausted

    Attributes:
        database: Name or type of the database
        host: Database host (if known)
    """

    def __init__(
        self,
        database: str,
        host: Optional[str] = None,
        message: Optional[str] = None,
        original_error: Optional[Exception] = None,
    ) -> None:
        self.database = database
        self.host = host
        msg = message or f"Failed to connect to {database}"
        if host:
            msg += f" at {host}"
        super().__init__(
            msg,
            original_error=original_error,
            details={"database": database, "host": host},
        )


class OptimisticLockError(RepositoryError):
    """
    Raised when an optimistic lock conflict is detected.

    This occurs when:
    - Two concurrent transactions try to update the same entity
    - The entity version has changed since it was read

    Attributes:
        entity_type: Name of the entity type
        entity_id: ID of the conflicting entity
        expected_version: The version expected by the client
        actual_version: The current version in the database
    """

    def __init__(
        self,
        entity_type: str,
        entity_id: str,
        expected_version: Optional[int] = None,
        actual_version: Optional[int] = None,
        message: Optional[str] = None,
    ) -> None:
        self.entity_type = entity_type
        self.entity_id = entity_id
        self.expected_version = expected_version
        self.actual_version = actual_version
        msg = message or f"Concurrent modification detected for {entity_type} '{entity_id}'"
        if expected_version is not None and actual_version is not None:
            msg += f" (expected version {expected_version}, found {actual_version})"
        super().__init__(
            msg,
            details={
                "entity_type": entity_type,
                "entity_id": entity_id,
                "expected_version": expected_version,
                "actual_version": actual_version,
            },
        )
