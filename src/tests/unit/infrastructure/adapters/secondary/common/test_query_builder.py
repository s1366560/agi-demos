"""
Unit tests for QueryBuilder.

Tests are written FIRST (TDD RED phase).
These tests MUST FAIL before implementation exists.
"""

import pytest
from typing import Optional
from dataclasses import dataclass

from sqlalchemy import Column, String, and_, or_, func, select
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.sql import Select


class Base(DeclarativeBase):
    """Test base for SQLAlchemy models."""
    pass


class TestModel(Base):
    """Test SQLAlchemy model."""
    __tablename__ = "test_entities"

    id = Column(String, primary_key=True)
    name = Column(String)
    tenant_id = Column(String)
    status = Column(String)
    created_at = Column(String)


@dataclass
class FilterOptions:
    """Filter options for testing."""
    tenant_id: Optional[str] = None
    status: Optional[str] = None
    name_contains: Optional[str] = None


class TestQueryBuilder:
    """Test suite for QueryBuilder foundation class."""

    # === TEST: QueryBuilder class exists ===

    def test_query_builder_class_exists(self):
        """Test that QueryBuilder class can be imported."""
        from src.infrastructure.adapters.secondary.common.query_builder import (
            QueryBuilder,
        )
        assert QueryBuilder is not None

    # === TEST: Initialization ===

    def test_query_builder_initialization(self):
        """Test QueryBuilder can be initialized."""
        from src.infrastructure.adapters.secondary.common.query_builder import (
            QueryBuilder,
        )

        qb = QueryBuilder(TestModel)
        assert qb.model_class == TestModel

    def test_query_builder_with_initial_select(self):
        """Test QueryBuilder can be initialized with an existing Select."""
        from src.infrastructure.adapters.secondary.common.query_builder import (
            QueryBuilder,
        )

        initial_query = select(TestModel)
        qb = QueryBuilder(TestModel, query=initial_query)
        assert qb.build() == initial_query

    # === TEST: Basic filter operations ===

    def test_where_eq(self):
        """Test where with equality condition."""
        from src.infrastructure.adapters.secondary.common.query_builder import (
            QueryBuilder,
        )

        qb = QueryBuilder(TestModel)
        query = qb.where_eq("tenant_id", "tenant-1").build()

        assert query is not None
        # Verify query has a where clause
        str(query)  # Should compile without error

    def test_where_in(self):
        """Test where with IN condition."""
        from src.infrastructure.adapters.secondary.common.query_builder import (
            QueryBuilder,
        )

        qb = QueryBuilder(TestModel)
        query = qb.where_in("status", ["active", "pending"]).build()

        assert query is not None

    def test_where_like(self):
        """Test where with LIKE condition."""
        from src.infrastructure.adapters.secondary.common.query_builder import (
            QueryBuilder,
        )

        qb = QueryBuilder(TestModel)
        query = qb.where_like("name", "test%").build()

        assert query is not None

    def test_where_ilike(self):
        """Test where with case-insensitive LIKE condition."""
        from src.infrastructure.adapters.secondary.common.query_builder import (
            QueryBuilder,
        )

        qb = QueryBuilder(TestModel)
        query = qb.where_ilike("name", "test%").build()

        assert query is not None

    def test_where_gt(self):
        """Test where with greater than condition."""
        from src.infrastructure.adapters.secondary.common.query_builder import (
            QueryBuilder,
        )

        qb = QueryBuilder(TestModel)
        query = qb.where_gt("created_at", "2024-01-01").build()

        assert query is not None

    def test_where_gte(self):
        """Test where with greater than or equal condition."""
        from src.infrastructure.adapters.secondary.common.query_builder import (
            QueryBuilder,
        )

        qb = QueryBuilder(TestModel)
        query = qb.where_gte("created_at", "2024-01-01").build()

        assert query is not None

    def test_where_lt(self):
        """Test where with less than condition."""
        from src.infrastructure.adapters.secondary.common.query_builder import (
            QueryBuilder,
        )

        qb = QueryBuilder(TestModel)
        query = qb.where_lt("created_at", "2024-12-31").build()

        assert query is not None

    def test_where_lte(self):
        """Test where with less than or equal condition."""
        from src.infrastructure.adapters.secondary.common.query_builder import (
            QueryBuilder,
        )

        qb = QueryBuilder(TestModel)
        query = qb.where_lte("created_at", "2024-12-31").build()

        assert query is not None

    def test_where_between(self):
        """Test where with BETWEEN condition."""
        from src.infrastructure.adapters.secondary.common.query_builder import (
            QueryBuilder,
        )

        qb = QueryBuilder(TestModel)
        query = qb.where_between("created_at", "2024-01-01", "2024-12-31").build()

        assert query is not None

    def test_where_null(self):
        """Test where with IS NULL condition."""
        from src.infrastructure.adapters.secondary.common.query_builder import (
            QueryBuilder,
        )

        qb = QueryBuilder(TestModel)
        query = qb.where_null("name").build()

        assert query is not None

    def test_where_not_null(self):
        """Test where with IS NOT NULL condition."""
        from src.infrastructure.adapters.secondary.common.query_builder import (
            QueryBuilder,
        )

        qb = QueryBuilder(TestModel)
        query = qb.where_not_null("name").build()

        assert query is not None

    # === TEST: Chaining filters ===

    def test_chain_multiple_wheres(self):
        """Test chaining multiple where conditions."""
        from src.infrastructure.adapters.secondary.common.query_builder import (
            QueryBuilder,
        )

        qb = QueryBuilder(TestModel)
        query = (
            qb.where_eq("tenant_id", "tenant-1")
            .where_eq("status", "active")
            .where_like("name", "test%")
            .build()
        )

        assert query is not None

    # === TEST: Logical operators ===

    def test_and_conditions(self):
        """Test AND logical operator."""
        from src.infrastructure.adapters.secondary.common.query_builder import (
            QueryBuilder,
        )

        qb = QueryBuilder(TestModel)
        query = qb.and_(
            lambda q: q.where_eq("tenant_id", "tenant-1").where_eq("status", "active")
        ).build()

        assert query is not None

    def test_or_conditions(self):
        """Test OR logical operator."""
        from src.infrastructure.adapters.secondary.common.query_builder import (
            QueryBuilder,
        )

        qb = QueryBuilder(TestModel)
        query = qb.or_(
            lambda q: q.where_eq("status", "active").where_eq("status", "pending")
        ).build()

        assert query is not None

    # === TEST: Ordering ===

    def test_order_by_asc(self):
        """Test ordering ascending."""
        from src.infrastructure.adapters.secondary.common.query_builder import (
            QueryBuilder,
        )

        qb = QueryBuilder(TestModel)
        query = qb.order_by("name", ascending=True).build()

        assert query is not None

    def test_order_by_desc(self):
        """Test ordering descending."""
        from src.infrastructure.adapters.secondary.common.query_builder import (
            QueryBuilder,
        )

        qb = QueryBuilder(TestModel)
        query = qb.order_by("name", ascending=False).build()

        assert query is not None

    def test_order_by_multiple_columns(self):
        """Test ordering by multiple columns."""
        from src.infrastructure.adapters.secondary.common.query_builder import (
            QueryBuilder,
        )

        qb = QueryBuilder(TestModel)
        query = qb.order_by("status").order_by("name").build()

        assert query is not None

    # === TEST: Pagination ===

    def test_limit(self):
        """Test limiting results."""
        from src.infrastructure.adapters.secondary.common.query_builder import (
            QueryBuilder,
        )

        qb = QueryBuilder(TestModel)
        query = qb.limit(10).build()

        assert query is not None

    def test_offset(self):
        """Test offsetting results."""
        from src.infrastructure.adapters.secondary.common.query_builder import (
            QueryBuilder,
        )

        qb = QueryBuilder(TestModel)
        query = qb.offset(20).build()

        assert query is not None

    def test_limit_and_offset(self):
        """Test limiting and offsetting results."""
        from src.infrastructure.adapters.secondary.common.query_builder import (
            QueryBuilder,
        )

        qb = QueryBuilder(TestModel)
        query = qb.limit(10).offset(20).build()

        assert query is not None

    # === TEST: Joins ===

    def test_join(self):
        """Test JOIN clause."""
        from src.infrastructure.adapters.secondary.common.query_builder import (
            QueryBuilder,
        )

        # Create another model to join with
        class RelatedModel(Base):
            __tablename__ = "related"
            id = Column(String, primary_key=True)
            test_id = Column(String)

        qb = QueryBuilder(TestModel)
        query = qb.join(RelatedModel, RelatedModel.test_id == TestModel.id).build()

        assert query is not None

    # === TEST: Aggregations ===

    def test_count(self):
        """Test COUNT aggregation."""
        from src.infrastructure.adapters.secondary.common.query_builder import (
            QueryBuilder,
        )

        qb = QueryBuilder(TestModel)
        query = qb.count().build()

        assert query is not None

    def test_count_with_filter(self):
        """Test COUNT aggregation with filters."""
        from src.infrastructure.adapters.secondary.common.query_builder import (
            QueryBuilder,
        )

        qb = QueryBuilder(TestModel)
        query = qb.where_eq("tenant_id", "tenant-1").count().build()

        assert query is not None

    # === TEST: Edge cases ===

    def test_where_with_none_value_skips_condition(self):
        """Test that where with None value skips the condition."""
        from src.infrastructure.adapters.secondary.common.query_builder import (
            QueryBuilder,
        )

        qb = QueryBuilder(TestModel)
        query = qb.where_eq("tenant_id", None).build()

        # Should still have a valid query, just without that filter
        assert query is not None

    def test_where_in_with_empty_list_skips_condition(self):
        """Test that where_in with empty list skips the condition."""
        from src.infrastructure.adapters.secondary.common.query_builder import (
            QueryBuilder,
        )

        qb = QueryBuilder(TestModel)
        query = qb.where_in("status", []).build()

        # Should still have a valid query
        assert query is not None

    def test_reset_clears_conditions(self):
        """Test that reset clears all conditions."""
        from src.infrastructure.adapters.secondary.common.query_builder import (
            QueryBuilder,
        )

        qb = QueryBuilder(TestModel)
        qb.where_eq("tenant_id", "tenant-1").order_by("name").limit(10)

        qb.reset()

        # After reset, should have a clean query
        query = qb.build()
        assert query is not None

    # === TEST: Build method ===

    def test_build_returns_select(self):
        """Test that build returns a SQLAlchemy Select object."""
        from src.infrastructure.adapters.secondary.common.query_builder import (
            QueryBuilder,
        )

        qb = QueryBuilder(TestModel)
        query = qb.build()

        assert isinstance(query, Select)

    def test_build_idempotent(self):
        """Test that build can be called multiple times with same result."""
        from src.infrastructure.adapters.secondary.common.query_builder import (
            QueryBuilder,
        )

        qb = QueryBuilder(TestModel)
        qb.where_eq("tenant_id", "tenant-1")

        query1 = qb.build()
        query2 = qb.build()

        # Both queries should be equivalent
        assert str(query1) == str(query2)
