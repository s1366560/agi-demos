"""
Base repository providing common CRUD operations for all repositories.

This foundation class implements the Repository pattern with:
- Generic CRUD operations (create, read, update, delete)
- Transaction management
- Query building with filters and pagination
- Bulk operations for performance
- Context manager support for automatic commit/rollback
- Exception mapping from SQLAlchemy to domain exceptions

All concrete repositories should inherit from BaseRepository and implement:
- _model_class: The SQLAlchemy model class
- _to_domain(): Convert database model to domain entity
- _to_db(): Convert domain entity to database model (optional)
- _update_fields(): Update database model fields from domain entity (optional)
"""

import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager, suppress
from functools import wraps
from typing import Any, TypeVar

from sqlalchemy import delete, func, select
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql import Select

from src.domain.exceptions import (
    ConnectionError as DomainConnectionError,
    DuplicateEntityError,
    RepositoryError,
    TransactionError,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")  # Domain entity type
M = TypeVar("M")  # Database model type


def handle_db_errors(entity_type: str = "Entity") -> Callable[..., Any]:
    """
    Decorator to handle database errors and convert to domain exceptions.

    Args:
        entity_type: Name of the entity type for error messages

    Returns:
        Decorated function that maps SQLAlchemy errors to domain exceptions
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> None:
            try:
                return await func(*args, **kwargs)
            except IntegrityError as e:
                error_str = str(e.orig) if e.orig else str(e)
                # Check for unique constraint violation
                if "unique" in error_str.lower() or "duplicate" in error_str.lower():
                    # Try to extract field name from error message
                    field_name = "id"  # default
                    if "Key" in error_str and "=" in error_str:
                        # PostgreSQL format: Key (field)=(value) already exists
                        with suppress(IndexError, AttributeError):
                            field_name = error_str.split("Key (")[1].split(")")[0]
                    raise DuplicateEntityError(
                        entity_type=entity_type,
                        field_name=field_name,
                        field_value="<unknown>",
                        message=f"Duplicate {entity_type} detected",
                    ) from e
                raise RepositoryError(
                    f"Integrity error while operating on {entity_type}",
                    original_error=e,
                ) from e
            except DBAPIError as e:
                error_str = str(e).lower()
                if "connection" in error_str or "timeout" in error_str:
                    raise DomainConnectionError(
                        database="PostgreSQL",
                        message=f"Database connection error while operating on {entity_type}",
                        original_error=e,
                    ) from e
                raise RepositoryError(
                    f"Database error while operating on {entity_type}",
                    original_error=e,
                ) from e

        return wrapper

    return decorator


def transactional(func: Callable[..., Any]) -> Callable[..., Any]:
    """
    Decorator to wrap a repository method in a transaction.

    Automatically commits on success, rolls back on error.
    Works with methods that have 'self' as the first argument
    where self has a '_session' attribute.

    Example:
        class MyRepository(BaseRepository):
            @transactional
            async def complex_operation(self, entity):
                await self.save(entity)
                await self._do_related_work(entity)
                # Auto-commits if no exception
    """

    @wraps(func)
    async def wrapper(self: Any, *args: Any, **kwargs: Any) -> None:
        session = getattr(self, "_session", None)
        if session is None:
            raise RepositoryError("No session available for transaction")

        try:
            if not session.in_transaction():
                await session.begin()

            result = await func(self, *args, **kwargs)
            await session.commit()
            return result
        except Exception as e:
            await session.rollback()
            if isinstance(e, (RepositoryError, DuplicateEntityError, DomainConnectionError)):
                raise
            raise TransactionError(
                operation="execute",
                message=f"Transaction failed: {e!s}",
                original_error=e,
            ) from e

    return wrapper


class BaseRepository[T, M](ABC):
    """
    Base repository class providing common database operations.

    Implements Template Method pattern where subclasses provide
    the specific model class and conversion logic.

    Attributes:
        _model_class: SQLAlchemy model class (must be set by subclasses)
        _entity_name: Human-readable entity name for error messages
    """

    # Subclasses must define their SQLAlchemy model class
    _model_class: type[M] = None
    # Optional: override for custom entity name in error messages
    _entity_name: str | None = None

    def __init__(self, session: AsyncSession) -> None:
        """
        Initialize the repository with a database session.

        Args:
            session: SQLAlchemy async session for database operations
        """
        if session is None:
            raise ValueError("Session cannot be None")
        self._session = session

    @property
    def session(self) -> AsyncSession:
        """Get the database session."""
        return self._session

    @property
    def entity_name(self) -> str:
        """Get the entity name for error messages."""
        if self._entity_name:
            return self._entity_name
        if self._model_class:
            return self._model_class.__name__
        return "Entity"

    def _eager_load_options(self) -> list[Any]:
        """
        Return eager loading options for queries.

        Override this method to specify relationships to load eagerly.
        Use joinedload for single-object relationships (many-to-one, one-to-one).
        Use selectinload for collection relationships (one-to-many, many-to-many).

        Returns:
            List of SQLAlchemy loader options

        Example:
            def _eager_load_options(self) -> list:
                return [
                    joinedload(DBUser.tenant),
                    selectinload(DBUser.projects),
                ]
        """
        return []

    # === Abstract methods (must be implemented by subclasses) ===

    @abstractmethod
    def _to_domain(self, db_model: M | None) -> T | None:
        """
        Convert database model to domain entity.

        Args:
            db_model: Database model instance or None

        Returns:
            Domain entity instance or None
        """

    def _to_db(self, domain_entity: T) -> M:
        """
        Convert domain entity to database model.

        Default implementation creates a new model instance.
        Override if you need custom conversion logic.

        Args:
            domain_entity: Domain entity instance

        Returns:
            Database model instance
        """
        return self._model_class(**domain_entity.__dict__)

    def _update_fields(self, db_model: M, domain_entity: T) -> None:
        """
        Update database model fields from domain entity.

        Default implementation updates all attributes.
        Override for selective field updates.

        Args:
            db_model: Database model to update
            domain_entity: Domain entity with new values
        """
        for key, value in domain_entity.__dict__.items():
            if hasattr(db_model, key) and not key.startswith("_"):
                setattr(db_model, key, value)

    def _apply_filters(self, query: Select[Any], **filters: Any) -> Select[Any]:
        """
        Apply filters to a query.

        Override this method to implement custom filtering logic.
        Default implementation applies exact match filters for all
        columns that exist on the model.

        Args:
            query: SQLAlchemy Select query
            **filters: Filter key-value pairs

        Returns:
            Filtered query
        """
        for key, value in filters.items():
            if value is not None and hasattr(self._model_class, key):
                query = query.where(getattr(self._model_class, key) == value)
        return query

    # === CRUD operations ===

    async def find_by_id(self, entity_id: str) -> T | None:
        """
        Find an entity by its ID.

        Args:
            entity_id: The entity's unique identifier

        Returns:
            Domain entity or None if not found

        Raises:
            ValueError: If entity_id is empty
            RepositoryError: If database operation fails
        """
        if not entity_id:
            raise ValueError("ID cannot be empty")

        query = select(self._model_class).where(self._model_class.id == entity_id)
        # Apply eager loading options
        for option in self._eager_load_options():
            query = query.options(option)
        result = await self._session.execute(query)
        db_model = result.scalar_one_or_none()
        return self._to_domain(db_model)

    async def find_by_ids(self, entity_ids: list[str]) -> list[T]:
        """
        Find multiple entities by their IDs.

        Args:
            entity_ids: List of entity IDs to find

        Returns:
            List of domain entities (may be shorter than input if some not found)

        Raises:
            RepositoryError: If database operation fails
        """
        if not entity_ids:
            return []

        query = select(self._model_class).where(self._model_class.id.in_(entity_ids))
        # Apply eager loading options
        for option in self._eager_load_options():
            query = query.options(option)
        result = await self._session.execute(query)
        db_models = result.scalars().all()
        return [self._to_domain(m) for m in db_models if m is not None]

    async def find_one(self, **filters: Any) -> T | None:
        """
        Find a single entity matching the given filters.

        Args:
            **filters: Filter criteria

        Returns:
            Domain entity or None if not found

        Raises:
            RepositoryError: If database operation fails
        """
        query = select(self._model_class)
        query = self._apply_filters(query, **filters)
        # Apply eager loading options
        for option in self._eager_load_options():
            query = query.options(option)
        query = query.limit(1)
        result = await self._session.execute(query)
        db_model = result.scalar_one_or_none()
        return self._to_domain(db_model)

    async def exists(self, entity_id: str) -> bool:
        """
        Check if an entity exists by its ID.

        Args:
            entity_id: The entity's unique identifier

        Returns:
            True if entity exists, False otherwise
        """
        if not entity_id:
            return False

        query = (
            select(func.count())
            .select_from(self._model_class)
            .where(self._model_class.id == entity_id)
        )
        result = await self._session.execute(query)
        count = result.scalar()
        return count is not None and count > 0

    async def save(self, domain_entity: T) -> T:
        """
        Save a domain entity (create or update).

        Args:
            domain_entity: Domain entity to save

        Returns:
            Saved domain entity

        Raises:
            ValueError: If domain_entity is None
        """
        if domain_entity is None:
            raise ValueError("Entity cannot be None")

        entity_id = getattr(domain_entity, "id", None)

        if entity_id:
            # Check if entity exists (update)
            existing = await self._find_db_model_by_id(entity_id)
            if existing:
                return await self._update(existing, domain_entity)

        # Create new entity
        return await self._create(domain_entity)

    async def _find_db_model_by_id(self, entity_id: str) -> M | None:
        """Find database model by ID (internal helper)."""
        query = select(self._model_class).where(self._model_class.id == entity_id)
        result = await self._session.execute(query)
        return result.scalar_one_or_none()

    async def _create(self, domain_entity: T) -> T:
        """Create a new entity in the database."""
        db_model = self._to_db(domain_entity)
        self._session.add(db_model)
        await self._session.flush()
        return domain_entity

    async def _update(self, db_model: M, domain_entity: T) -> T:
        """Update an existing entity in the database."""
        self._update_fields(db_model, domain_entity)
        await self._session.flush()
        return domain_entity

    async def delete(self, entity_id: str) -> bool:
        """
        Delete an entity by its ID.

        Args:
            entity_id: The entity's unique identifier

        Returns:
            True if deleted, False if not found
        """
        db_model = await self._find_db_model_by_id(entity_id)
        if db_model:
            await self._session.delete(db_model)
            await self._session.flush()
            return True
        return False

    async def list_all(
        self,
        limit: int = 50,
        offset: int = 0,
        **filters: Any,
    ) -> list[T]:
        """
        List all entities with optional filtering and pagination.

        Args:
            limit: Maximum number of entities to return
            offset: Number of entities to skip
            **filters: Optional filter criteria

        Returns:
            List of domain entities

        Raises:
            ValueError: If limit is negative
            RepositoryError: If database operation fails
        """
        if limit < 0:
            raise ValueError("Limit must be non-negative")

        if limit == 0:
            return []

        query = self._build_query(filters=filters)
        # Apply eager loading options
        for option in self._eager_load_options():
            query = query.options(option)
        query = query.offset(offset).limit(limit)

        result = await self._session.execute(query)
        db_models = result.scalars().all()
        return [self._to_domain(m) for m in db_models if m is not None]

    async def count(self, **filters: Any) -> int:
        """
        Count entities matching the given filters.

        Args:
            **filters: Optional filter criteria

        Returns:
            Number of matching entities
        """
        query = select(func.count()).select_from(self._model_class)
        query = self._apply_filters(query, **filters)
        result = await self._session.execute(query)
        return result.scalar() or 0

    # === Bulk operations ===

    async def bulk_save(self, domain_entities: list[T]) -> None:
        """
        Save multiple entities efficiently using bulk operations.

        Args:
            domain_entities: List of domain entities to save

        Note:
            This is more efficient than calling save() multiple times
            but doesn't do upsert logic. Assumes all entities are new.
        """
        for entity in domain_entities:
            db_model = self._to_db(entity)
            self._session.add(db_model)
        await self._session.flush()

    async def bulk_delete(self, entity_ids: list[str]) -> int:
        """
        Delete multiple entities efficiently.

        Args:
            entity_ids: List of entity IDs to delete

        Returns:
            Number of entities deleted
        """
        if not entity_ids:
            return 0

        query = delete(self._model_class).where(self._model_class.id.in_(entity_ids))
        result = await self._session.execute(query)
        await self._session.flush()
        return result.rowcount

    # === Query building ===

    def _build_query(
        self,
        filters: dict[str, Any] | None = None,
        order_by: str | None = None,
        order_desc: bool = False,
    ) -> Select[Any]:
        """
        Build a SQLAlchemy query with optional filters and ordering.

        Args:
            filters: Optional filter dictionary
            order_by: Optional column name to order by
            order_desc: If True, order descending; otherwise ascending

        Returns:
            SQLAlchemy Select query
        """
        query = select(self._model_class)

        if filters:
            query = self._apply_filters(query, **filters)

        if order_by and hasattr(self._model_class, order_by):
            order_column = getattr(self._model_class, order_by)
            query = query.order_by(order_column.desc() if order_desc else order_column)

        return query

    # === Transaction management ===

    async def begin_transaction(self) -> None:
        """Begin a new transaction if not already in one."""
        if not self._session.in_transaction():
            await self._session.begin()

    async def commit(self) -> None:
        """Commit the current transaction."""
        await self._session.commit()

    async def rollback(self) -> None:
        """Rollback the current transaction."""
        await self._session.rollback()

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[Any, None]:
        """
        Context manager for transactional operations.

        Automatically commits on success, rolls back on error.

        Example:
            async with repo.transaction():
                await repo.save(entity1)
                await repo.save(entity2)
        """
        try:
            await self.begin_transaction()
            yield self
            await self.commit()
        except Exception:
            await self.rollback()
            raise
