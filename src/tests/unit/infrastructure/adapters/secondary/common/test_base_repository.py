"""
Unit tests for BaseRepository.

Tests are written FIRST (TDD RED phase).
These tests MUST FAIL before implementation exists.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, Mock
from typing import Optional
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import Column, String, select
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Test base for SQLAlchemy models."""
    pass


class TestModel(Base):
    """Test SQLAlchemy model."""
    __tablename__ = "test_entities"

    id = Column(String, primary_key=True)
    name = Column(String)
    tenant_id = Column(String)


@dataclass
class TestDomainEntity:
    """Test domain entity."""
    id: str
    name: str
    tenant_id: Optional[str] = None


class TestBaseRepository:
    """Test suite for BaseRepository foundation class."""

    @pytest.fixture
    def mock_session(self):
        """Create a mock AsyncSession."""
        session = AsyncMock(spec=AsyncSession)
        session.execute = AsyncMock()
        session.flush = AsyncMock()
        session.add = MagicMock()
        session.commit = AsyncMock()
        session.rollback = AsyncMock()
        session.in_transaction = MagicMock(return_value=False)
        session.begin = AsyncMock()
        return session

    # === TEST: BaseRepository class exists ===

    def test_base_repository_class_exists(self):
        """Test that BaseRepository class can be imported."""
        from src.infrastructure.adapters.secondary.common.base_repository import (
            BaseRepository,
        )
        assert BaseRepository is not None

    # === TEST: Initialization ===

    @pytest.mark.asyncio
    async def test_base_repository_initialization(self, mock_session):
        """Test BaseRepository can be initialized with a session."""
        from src.infrastructure.adapters.secondary.common.base_repository import (
            BaseRepository,
        )

        class ConcreteRepository(BaseRepository):
            """Concrete implementation for testing."""

            def _to_domain(self, db_model):
                return db_model

            def _to_db(self, domain_entity):
                return domain_entity

        repo = ConcreteRepository(mock_session)
        assert repo._session == mock_session
        assert repo.session == mock_session

    @pytest.mark.asyncio
    async def test_base_repository_requires_session(self):
        """Test BaseRepository raises error when session is None."""
        from src.infrastructure.adapters.secondary.common.base_repository import (
            BaseRepository,
        )

        class ConcreteRepository(BaseRepository):
            def _to_domain(self, db_model):
                return db_model

        with pytest.raises(ValueError, match="Session cannot be None"):
            ConcreteRepository(None)

    # === TEST: Generic CRUD operations ===

    @pytest.mark.asyncio
    async def test_find_by_id_returns_entity(self, mock_session):
        """Test find_by_id returns domain entity when found."""
        from src.infrastructure.adapters.secondary.common.base_repository import (
            BaseRepository,
        )

        # Arrange
        mock_db_entity = TestModel(id="test-id", name="Test Entity")

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_db_entity
        mock_session.execute.return_value = mock_result

        class TestRepository(BaseRepository[TestModel, TestDomainEntity]):
            _model_class = TestModel

            def _to_domain(self, db_model):
                if db_model is None:
                    return None
                return TestDomainEntity(
                    id=db_model.id,
                    name=db_model.name,
                    tenant_id=getattr(db_model, "tenant_id", None)
                )

        repo = TestRepository(mock_session)

        # Act
        result = await repo.find_by_id("test-id")

        # Assert
        assert result is not None
        assert result.id == "test-id"
        assert result.name == "Test Entity"
        mock_session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_find_by_id_returns_none_when_not_found(self, mock_session):
        """Test find_by_id returns None when entity doesn't exist."""
        from src.infrastructure.adapters.secondary.common.base_repository import (
            BaseRepository,
        )

        # Arrange
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        class TestRepository(BaseRepository[TestModel, TestDomainEntity]):
            _model_class = TestModel

            def _to_domain(self, db_model):
                return db_model

        repo = TestRepository(mock_session)

        # Act
        result = await repo.find_by_id("non-existent-id")

        # Assert
        assert result is None

    @pytest.mark.asyncio
    async def test_save_creates_new_entity(self, mock_session):
        """Test save creates a new entity when it doesn't exist."""
        from src.infrastructure.adapters.secondary.common.base_repository import (
            BaseRepository,
        )

        # Arrange
        domain_entity = TestDomainEntity(id="new-id", name="New Entity")

        # First call to _find_db_model_by_id returns None (not exists)
        # Second call to execute returns None for flush
        mock_session.execute = AsyncMock()
        mock_session.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=None))

        class TestRepository(BaseRepository[TestModel, TestDomainEntity]):
            _model_class = TestModel

            def _to_domain(self, db_model):
                return db_model

            def _to_db(self, domain):
                return TestModel(id=domain.id, name=domain.name)

        repo = TestRepository(mock_session)

        # Act
        result = await repo.save(domain_entity)

        # Assert
        mock_session.add.assert_called_once()
        mock_session.flush.assert_called_once()
        assert result.id == "new-id"

    @pytest.mark.asyncio
    async def test_save_updates_existing_entity(self, mock_session):
        """Test save updates an existing entity."""
        from src.infrastructure.adapters.secondary.common.base_repository import (
            BaseRepository,
        )

        # Arrange
        domain_entity = TestDomainEntity(id="existing-id", name="Updated Name")
        mock_db_entity = TestModel(id="existing-id", name="Old Name")

        # First call finds the entity, subsequent calls return it
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_db_entity
        mock_session.execute = AsyncMock(return_value=mock_result)

        class TestRepository(BaseRepository[TestModel, TestDomainEntity]):
            _model_class = TestModel

            def _to_domain(self, db_model):
                return db_model

            def _update_fields(self, db_model, domain):
                db_model.name = domain.name

        repo = TestRepository(mock_session)

        # Act
        result = await repo.save(domain_entity)

        # Assert
        assert mock_db_entity.name == "Updated Name"
        mock_session.flush.assert_called_once()
        mock_session.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_removes_entity(self, mock_session):
        """Test delete removes entity from database."""
        from src.infrastructure.adapters.secondary.common.base_repository import (
            BaseRepository,
        )

        # Arrange
        mock_db_entity = TestModel(id="delete-id", name="Delete Me")

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_db_entity
        mock_session.execute.return_value = mock_result

        class TestRepository(BaseRepository[TestModel, TestDomainEntity]):
            _model_class = TestModel

            def _to_domain(self, db_model):
                return db_model

        repo = TestRepository(mock_session)

        # Act
        result = await repo.delete("delete-id")

        # Assert
        mock_session.delete.assert_called_once_with(mock_db_entity)
        mock_session.flush.assert_called_once()
        assert result is True

    @pytest.mark.asyncio
    async def test_delete_returns_false_when_not_found(self, mock_session):
        """Test delete returns False when entity doesn't exist."""
        from src.infrastructure.adapters.secondary.common.base_repository import (
            BaseRepository,
        )

        # Arrange
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        class TestRepository(BaseRepository[TestModel, TestDomainEntity]):
            _model_class = TestModel

            def _to_domain(self, db_model):
                return db_model

        repo = TestRepository(mock_session)

        # Act
        result = await repo.delete("non-existent-id")

        # Assert
        assert result is False
        mock_session.delete.assert_not_called()

    # === TEST: List operations ===

    @pytest.mark.asyncio
    async def test_list_all_returns_entities(self, mock_session):
        """Test list_all returns all entities with pagination."""
        from src.infrastructure.adapters.secondary.common.base_repository import (
            BaseRepository,
        )

        # Arrange
        mock_db_entities = [
            TestModel(id="id1", name="Entity 1"),
            TestModel(id="id2", name="Entity 2"),
        ]

        mock_scalars = MagicMock()
        mock_scalars.all.return_value = mock_db_entities

        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        mock_session.execute.return_value = mock_result

        class TestRepository(BaseRepository[TestModel, TestDomainEntity]):
            _model_class = TestModel

            def _to_domain(self, db_model):
                if db_model is None:
                    return None
                return TestDomainEntity(
                    id=db_model.id,
                    name=db_model.name,
                    tenant_id=getattr(db_model, "tenant_id", None)
                )

        repo = TestRepository(mock_session)

        # Act
        results = await repo.list_all(limit=10, offset=0)

        # Assert
        assert len(results) == 2
        assert results[0].id == "id1"
        assert results[1].id == "id2"

    @pytest.mark.asyncio
    async def test_list_all_with_filters(self, mock_session):
        """Test list_all applies filters correctly."""
        from src.infrastructure.adapters.secondary.common.base_repository import (
            BaseRepository,
        )

        # Arrange
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result.scalars.return_value = mock_scalars
        mock_session.execute.return_value = mock_result

        class TestRepository(BaseRepository[TestModel, TestDomainEntity]):
            _model_class = TestModel

            def _to_domain(self, db_model):
                return db_model

        repo = TestRepository(mock_session)

        # Act
        results = await repo.list_all(tenant_id="tenant-1", limit=10)

        # Assert
        assert isinstance(results, list)
        mock_session.execute.assert_called_once()

    # === TEST: Count operations ===

    @pytest.mark.asyncio
    async def test_count_returns_total(self, mock_session):
        """Test count returns the total number of entities."""
        from src.infrastructure.adapters.secondary.common.base_repository import (
            BaseRepository,
        )

        # Arrange
        mock_result = MagicMock()
        mock_result.scalar.return_value = 42
        mock_session.execute.return_value = mock_result

        class TestRepository(BaseRepository[TestModel, TestDomainEntity]):
            _model_class = TestModel

            def _to_domain(self, db_model):
                return db_model

        repo = TestRepository(mock_session)

        # Act
        count = await repo.count()

        # Assert
        assert count == 42

    @pytest.mark.asyncio
    async def test_count_with_filters(self, mock_session):
        """Test count applies filters correctly."""
        from src.infrastructure.adapters.secondary.common.base_repository import (
            BaseRepository,
        )

        # Arrange
        mock_result = MagicMock()
        mock_result.scalar.return_value = 5
        mock_session.execute.return_value = mock_result

        class TestRepository(BaseRepository[TestModel, TestDomainEntity]):
            _model_class = TestModel

            def _to_domain(self, db_model):
                return db_model

        repo = TestRepository(mock_session)

        # Act
        count = await repo.count(tenant_id="tenant-1")

        # Assert
        assert count == 5

    # === TEST: Transaction management ===

    @pytest.mark.asyncio
    async def test_begin_transaction_starts_transaction(self, mock_session):
        """Test begin_transaction starts a new transaction."""
        from src.infrastructure.adapters.secondary.common.base_repository import (
            BaseRepository,
        )

        # Arrange
        mock_session.in_transaction.return_value = False

        class TestRepository(BaseRepository[TestModel, TestDomainEntity]):
            _model_class = TestModel

            def _to_domain(self, db_model):
                return db_model

        repo = TestRepository(mock_session)

        # Act
        await repo.begin_transaction()

        # Assert
        mock_session.begin.assert_called_once()

    @pytest.mark.asyncio
    async def test_commit_commits_transaction(self, mock_session):
        """Test commit commits the current transaction."""
        from src.infrastructure.adapters.secondary.common.base_repository import (
            BaseRepository,
        )

        class TestRepository(BaseRepository[TestModel, TestDomainEntity]):
            _model_class = TestModel

            def _to_domain(self, db_model):
                return db_model

        repo = TestRepository(mock_session)

        # Act
        await repo.commit()

        # Assert
        mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_rollback_rolls_back_transaction(self, mock_session):
        """Test rollback rolls back the current transaction."""
        from src.infrastructure.adapters.secondary.common.base_repository import (
            BaseRepository,
        )

        class TestRepository(BaseRepository[TestModel, TestDomainEntity]):
            _model_class = TestModel

            def _to_domain(self, db_model):
                return db_model

        repo = TestRepository(mock_session)

        # Act
        await repo.rollback()

        # Assert
        mock_session.rollback.assert_called_once()

    # === TEST: Context manager for transactions ===

    @pytest.mark.asyncio
    async def test_transaction_context_manager_commits_on_success(self, mock_session):
        """Test transaction context manager commits on success."""
        from src.infrastructure.adapters.secondary.common.base_repository import (
            BaseRepository,
        )

        class TestRepository(BaseRepository[TestModel, TestDomainEntity]):
            _model_class = TestModel

            def _to_domain(self, db_model):
                return db_model

        repo = TestRepository(mock_session)

        # Act
        async with repo.transaction():
            pass

        # Assert
        mock_session.commit.assert_called_once()
        mock_session.rollback.assert_not_called()

    @pytest.mark.asyncio
    async def test_transaction_context_manager_rolls_back_on_error(self, mock_session):
        """Test transaction context manager rolls back on error."""
        from src.infrastructure.adapters.secondary.common.base_repository import (
            BaseRepository,
        )

        class TestRepository(BaseRepository[TestModel, TestDomainEntity]):
            _model_class = TestModel

            def _to_domain(self, db_model):
                return db_model

        repo = TestRepository(mock_session)

        # Act & Assert
        with pytest.raises(ValueError, match="Test error"):
            async with repo.transaction():
                raise ValueError("Test error")

        mock_session.rollback.assert_called_once()
        mock_session.commit.assert_not_called()

    # === TEST: Bulk operations ===

    @pytest.mark.asyncio
    async def test_bulk_save_creates_multiple_entities(self, mock_session):
        """Test bulk_save saves multiple entities efficiently."""
        from src.infrastructure.adapters.secondary.common.base_repository import (
            BaseRepository,
        )

        # Arrange
        entities = [
            TestDomainEntity(id=f"id-{i}", name=f"Entity {i}")
            for i in range(3)
        ]

        class TestRepository(BaseRepository[TestModel, TestDomainEntity]):
            _model_class = TestModel

            def _to_domain(self, db_model):
                return db_model

            def _to_db(self, domain):
                return TestModel(id=domain.id, name=domain.name)

        repo = TestRepository(mock_session)

        # Act
        await repo.bulk_save(entities)

        # Assert
        assert mock_session.add.call_count == 3
        mock_session.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_bulk_delete_removes_multiple_entities(self, mock_session):
        """Test bulk_delete removes multiple entities efficiently."""
        from src.infrastructure.adapters.secondary.common.base_repository import (
            BaseRepository,
        )

        # Arrange
        entity_ids = ["id-1", "id-2", "id-3"]

        mock_result = MagicMock()
        mock_result.rowcount = 3
        mock_session.execute.return_value = mock_result

        class TestRepository(BaseRepository[TestModel, TestDomainEntity]):
            _model_class = TestModel

            def _to_domain(self, db_model):
                return db_model

        repo = TestRepository(mock_session)

        # Act
        deleted_count = await repo.bulk_delete(entity_ids)

        # Assert
        assert deleted_count == 3

    # === TEST: Query building ===

    @pytest.mark.asyncio
    async def test_build_query_creates_basic_select(self, mock_session):
        """Test _build_query creates a basic SELECT query."""
        from src.infrastructure.adapters.secondary.common.base_repository import (
            BaseRepository,
        )

        class TestRepository(BaseRepository[TestModel, TestDomainEntity]):
            _model_class = TestModel

            def _to_domain(self, db_model):
                return db_model

        repo = TestRepository(mock_session)

        # Act
        query = repo._build_query()

        # Assert
        assert query is not None
        # Verify query is a Select object
        from sqlalchemy.sql import Select
        assert isinstance(query, Select)

    @pytest.mark.asyncio
    async def test_build_query_with_filters(self, mock_session):
        """Test _build_query applies filters."""
        from src.infrastructure.adapters.secondary.common.base_repository import (
            BaseRepository,
        )

        class TestRepository(BaseRepository[TestModel, TestDomainEntity]):
            _model_class = TestModel

            def _to_domain(self, db_model):
                return db_model

        repo = TestRepository(mock_session)

        # Act
        query = repo._build_query(filters={"tenant_id": "tenant-1"})

        # Assert
        assert query is not None
        from sqlalchemy.sql import Select
        assert isinstance(query, Select)

    @pytest.mark.asyncio
    async def test_build_query_with_ordering(self, mock_session):
        """Test _build_query applies ordering."""
        from src.infrastructure.adapters.secondary.common.base_repository import (
            BaseRepository,
        )

        class TestRepository(BaseRepository[TestModel, TestDomainEntity]):
            _model_class = TestModel

            def _to_domain(self, db_model):
                return db_model

        repo = TestRepository(mock_session)

        # Act
        query = repo._build_query(order_by="name", order_desc=True)

        # Assert
        assert query is not None
        from sqlalchemy.sql import Select
        assert isinstance(query, Select)

    # === TEST: Edge cases ===

    @pytest.mark.asyncio
    async def test_save_with_none_entity_raises_error(self, mock_session):
        """Test save raises error when entity is None."""
        from src.infrastructure.adapters.secondary.common.base_repository import (
            BaseRepository,
        )

        class TestRepository(BaseRepository[TestModel, TestDomainEntity]):
            _model_class = TestModel

            def _to_domain(self, db_model):
                return db_model

        repo = TestRepository(mock_session)

        # Act & Assert
        with pytest.raises(ValueError, match="Entity cannot be None"):
            await repo.save(None)

    @pytest.mark.asyncio
    async def test_find_by_id_with_empty_id_raises_error(self, mock_session):
        """Test find_by_id raises error when id is empty."""
        from src.infrastructure.adapters.secondary.common.base_repository import (
            BaseRepository,
        )

        class TestRepository(BaseRepository[TestModel, TestDomainEntity]):
            _model_class = TestModel

            def _to_domain(self, db_model):
                return db_model

        repo = TestRepository(mock_session)

        # Act & Assert
        with pytest.raises(ValueError, match="ID cannot be empty"):
            await repo.find_by_id("")

    @pytest.mark.asyncio
    async def test_list_all_with_negative_limit_raises_error(self, mock_session):
        """Test list_all raises error when limit is negative."""
        from src.infrastructure.adapters.secondary.common.base_repository import (
            BaseRepository,
        )

        class TestRepository(BaseRepository[TestModel, TestDomainEntity]):
            _model_class = TestModel

            def _to_domain(self, db_model):
                return db_model

        repo = TestRepository(mock_session)

        # Act & Assert
        with pytest.raises(ValueError, match="Limit must be non-negative"):
            await repo.list_all(limit=-1)

    @pytest.mark.asyncio
    async def test_list_all_with_zero_limit_returns_empty_list(self, mock_session):
        """Test list_all returns empty list when limit is 0."""
        from src.infrastructure.adapters.secondary.common.base_repository import (
            BaseRepository,
        )

        class TestRepository(BaseRepository[TestModel, TestDomainEntity]):
            _model_class = TestModel

            def _to_domain(self, db_model):
                return db_model

        repo = TestRepository(mock_session)

        # Act
        results = await repo.list_all(limit=0)

        # Assert
        assert results == []

    @pytest.mark.asyncio
    async def test_exists_returns_true_when_entity_found(self, mock_session):
        """Test exists returns True when entity exists."""
        from src.infrastructure.adapters.secondary.common.base_repository import (
            BaseRepository,
        )

        # Arrange
        mock_result = MagicMock()
        mock_result.scalar.return_value = 1
        mock_session.execute.return_value = mock_result

        class TestRepository(BaseRepository[TestModel, TestDomainEntity]):
            _model_class = TestModel

            def _to_domain(self, db_model):
                return db_model

        repo = TestRepository(mock_session)

        # Act
        exists = await repo.exists("existing-id")

        # Assert
        assert exists is True

    @pytest.mark.asyncio
    async def test_exists_returns_false_when_entity_not_found(self, mock_session):
        """Test exists returns False when entity doesn't exist."""
        from src.infrastructure.adapters.secondary.common.base_repository import (
            BaseRepository,
        )

        # Arrange
        mock_result = MagicMock()
        mock_result.scalar.return_value = None
        mock_session.execute.return_value = mock_result

        class TestRepository(BaseRepository[TestModel, TestDomainEntity]):
            _model_class = TestModel

            def _to_domain(self, db_model):
                return db_model

        repo = TestRepository(mock_session)

        # Act
        exists = await repo.exists("non-existent-id")

        # Assert
        assert exists is False

    @pytest.mark.asyncio
    async def test_exists_with_empty_id_returns_false(self, mock_session):
        """Test exists returns False when id is empty."""
        from src.infrastructure.adapters.secondary.common.base_repository import (
            BaseRepository,
        )

        class TestRepository(BaseRepository[TestModel, TestDomainEntity]):
            _model_class = TestModel

            def _to_domain(self, db_model):
                return db_model

        repo = TestRepository(mock_session)

        # Act
        exists = await repo.exists("")

        # Assert
        assert exists is False
        # Should not execute any query
        mock_session.execute.assert_not_called()
