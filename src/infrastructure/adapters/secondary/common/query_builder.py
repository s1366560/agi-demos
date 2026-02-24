"""
QueryBuilder for fluent SQLAlchemy query construction.

Provides a fluent interface for building SQLAlchemy queries with:
- Method chaining for filter conditions
- Support for all common comparison operators
- Logical operators (AND, OR)
- Ordering, pagination, and joins
- Type-safe query building
"""

from collections.abc import Callable
from typing import Any, Generic, TypeVar

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.sql import ColumnElement, Select

T = TypeVar("T", bound=DeclarativeBase)


class QueryBuilder(Generic[T]):
    """
    Fluent query builder for SQLAlchemy.

    Provides a chainable API for building database queries with
    type safety and null-safety built in.

    Example:
        query = (QueryBuilder(User)
                 .where_eq("tenant_id", "tenant-1")
                 .where_in("status", ["active", "pending"])
                 .order_by("created_at", ascending=False)
                 .limit(10)
                 .build())
    """

    def __init__(
        self,
        model_class: type[T],
        query: Select[tuple[T]] | None = None,
    ) -> None:
        """
        Initialize the query builder.

        Args:
            model_class: The SQLAlchemy model class
            query: Optional existing Select query to build upon
        """
        self._model_class = model_class
        self._query: Select[tuple[T]] = query if query is not None else select(model_class)
        self._where_conditions: list[ColumnElement[bool]] = []
        self._order_by_clauses: list[Any] = []
        self._limit_value: int | None = None
        self._offset_value: int | None = None

    @property
    def model_class(self) -> type[T]:
        """Get the model class."""
        return self._model_class

    # === Filter methods ===

    def where_eq(
        self,
        column: str,
        value: Any,
    ) -> "QueryBuilder[T]":
        """
        Add equality condition.

        Args:
            column: Column name
            value: Value to compare (None skips the condition)

        Returns:
            Self for chaining
        """
        if value is not None:
            self._where_conditions.append(getattr(self._model_class, column) == value)
        return self

    def where_ne(
        self,
        column: str,
        value: Any,
    ) -> "QueryBuilder[T]":
        """
        Add inequality condition.

        Args:
            column: Column name
            value: Value to compare (None skips the condition)

        Returns:
            Self for chaining
        """
        if value is not None:
            self._where_conditions.append(getattr(self._model_class, column) != value)
        return self

    def where_in(
        self,
        column: str,
        values: list[Any],
    ) -> "QueryBuilder[T]":
        """
        Add IN condition.

        Args:
            column: Column name
            values: List of values (empty list skips the condition)

        Returns:
            Self for chaining
        """
        if values:
            self._where_conditions.append(getattr(self._model_class, column).in_(values))
        return self

    def where_not_in(
        self,
        column: str,
        values: list[Any],
    ) -> "QueryBuilder[T]":
        """
        Add NOT IN condition.

        Args:
            column: Column name
            values: List of values (empty list skips the condition)

        Returns:
            Self for chaining
        """
        if values:
            self._where_conditions.append(getattr(self._model_class, column).notin_(values))
        return self

    def where_like(
        self,
        column: str,
        pattern: str,
    ) -> "QueryBuilder[T]":
        """
        Add LIKE condition (case-sensitive).

        Args:
            column: Column name
            pattern: SQL LIKE pattern (e.g., "test%")

        Returns:
            Self for chaining
        """
        if pattern:
            self._where_conditions.append(getattr(self._model_class, column).like(pattern))
        return self

    def where_ilike(
        self,
        column: str,
        pattern: str,
    ) -> "QueryBuilder[T]":
        """
        Add ILIKE condition (case-insensitive).

        Args:
            column: Column name
            pattern: SQL ILIKE pattern (e.g., "test%")

        Returns:
            Self for chaining
        """
        if pattern:
            self._where_conditions.append(getattr(self._model_class, column).ilike(pattern))
        return self

    def where_gt(
        self,
        column: str,
        value: Any,
    ) -> "QueryBuilder[T]":
        """
        Add greater than condition.

        Args:
            column: Column name
            value: Value to compare

        Returns:
            Self for chaining
        """
        if value is not None:
            self._where_conditions.append(getattr(self._model_class, column) > value)
        return self

    def where_gte(
        self,
        column: str,
        value: Any,
    ) -> "QueryBuilder[T]":
        """
        Add greater than or equal condition.

        Args:
            column: Column name
            value: Value to compare

        Returns:
            Self for chaining
        """
        if value is not None:
            self._where_conditions.append(getattr(self._model_class, column) >= value)
        return self

    def where_lt(
        self,
        column: str,
        value: Any,
    ) -> "QueryBuilder[T]":
        """
        Add less than condition.

        Args:
            column: Column name
            value: Value to compare

        Returns:
            Self for chaining
        """
        if value is not None:
            self._where_conditions.append(getattr(self._model_class, column) < value)
        return self

    def where_lte(
        self,
        column: str,
        value: Any,
    ) -> "QueryBuilder[T]":
        """
        Add less than or equal condition.

        Args:
            column: Column name
            value: Value to compare

        Returns:
            Self for chaining
        """
        if value is not None:
            self._where_conditions.append(getattr(self._model_class, column) <= value)
        return self

    def where_between(
        self,
        column: str,
        lower: Any,
        upper: Any,
    ) -> "QueryBuilder[T]":
        """
        Add BETWEEN condition.

        Args:
            column: Column name
            lower: Lower bound
            upper: Upper bound

        Returns:
            Self for chaining
        """
        if lower is not None and upper is not None:
            self._where_conditions.append(getattr(self._model_class, column).between(lower, upper))
        return self

    def where_null(
        self,
        column: str,
    ) -> "QueryBuilder[T]":
        """
        Add IS NULL condition.

        Args:
            column: Column name

        Returns:
            Self for chaining
        """
        self._where_conditions.append(getattr(self._model_class, column).is_(None))
        return self

    def where_not_null(
        self,
        column: str,
    ) -> "QueryBuilder[T]":
        """
        Add IS NOT NULL condition.

        Args:
            column: Column name

        Returns:
            Self for chaining
        """
        self._where_conditions.append(getattr(self._model_class, column).is_not(None))
        return self

    # === Logical operators ===

    def and_(
        self,
        builder_fn: Callable[["QueryBuilder[T]"], "QueryBuilder[T]"],
    ) -> "QueryBuilder[T]":
        """
        Apply conditions wrapped in AND.

        Args:
            builder_fn: Function that returns a QueryBuilder with conditions

        Returns:
            Self for chaining
        """
        # The conditions are already AND-ed together in where_conditions
        # This method is provided for API completeness and potential future enhancements
        return builder_fn(self)

    def or_(
        self,
        builder_fn: Callable[["QueryBuilder[T]"], "QueryBuilder[T]"],
    ) -> "QueryBuilder[T]":
        """
        Apply conditions wrapped in OR.

        Args:
            builder_fn: Function that returns a QueryBuilder with conditions

        Returns:
            Self for chaining
        """
        # Create a temporary builder to collect OR conditions
        temp_builder = QueryBuilder(self._model_class)
        builder_fn(temp_builder)

        if temp_builder._where_conditions:
            # Wrap the OR conditions in an or_() clause
            self._where_conditions.append(or_(*temp_builder._where_conditions))

        return self

    # === Ordering ===

    def order_by(
        self,
        column: str,
        ascending: bool = True,
    ) -> "QueryBuilder[T]":
        """
        Add ORDER BY clause.

        Args:
            column: Column name
            ascending: Sort order (True for ASC, False for DESC)

        Returns:
            Self for chaining
        """
        col = getattr(self._model_class, column)
        if ascending:
            self._order_by_clauses.append(col.asc())
        else:
            self._order_by_clauses.append(col.desc())
        return self

    # === Pagination ===

    def limit(
        self,
        count: int,
    ) -> "QueryBuilder[T]":
        """
        Add LIMIT clause.

        Args:
            count: Maximum number of results

        Returns:
            Self for chaining
        """
        if count > 0:
            self._limit_value = count
        return self

    def offset(
        self,
        count: int,
    ) -> "QueryBuilder[T]":
        """
        Add OFFSET clause.

        Args:
            count: Number of results to skip

        Returns:
            Self for chaining
        """
        if count > 0:
            self._offset_value = count
        return self

    # === Joins ===

    def join(
        self,
        other_model: type,
        on_clause: Any,
        is_outer: bool = False,
    ) -> "QueryBuilder[T]":
        """
        Add JOIN clause.

        Args:
            other_model: Model to join with
            on_clause: Join condition
            is_outer: If True, use LEFT OUTER JOIN

        Returns:
            Self for chaining
        """
        if is_outer:
            self._query = self._query.outerjoin(other_model, on_clause)
        else:
            self._query = self._query.join(other_model, on_clause)
        return self

    # === Aggregations ===

    def count(self) -> "QueryBuilder[T]":
        """
        Change query to return COUNT.

        Returns:
            Self for chaining
        """
        from sqlalchemy import func

        self._query = select(func.count()).select_from(self._model_class)
        return self

    # === Build ===

    def build(self) -> Select[Any]:
        """
        Build and return the SQLAlchemy Select query.

        Returns:
            Compiled SQLAlchemy Select query
        """
        query = self._query

        # Apply WHERE conditions
        if self._where_conditions:
            query = query.where(and_(*self._where_conditions))

        # Apply ORDER BY
        if self._order_by_clauses:
            query = query.order_by(*self._order_by_clauses)

        # Apply LIMIT
        if self._limit_value is not None:
            query = query.limit(self._limit_value)

        # Apply OFFSET
        if self._offset_value is not None:
            query = query.offset(self._offset_value)

        return query

    # === Reset ===

    def reset(self) -> "QueryBuilder[T]":
        """
        Reset the query builder to initial state.

        Returns:
            Self for chaining
        """
        self._query = select(self._model_class)
        self._where_conditions.clear()
        self._order_by_clauses.clear()
        self._limit_value = None
        self._offset_value = None
        return self
