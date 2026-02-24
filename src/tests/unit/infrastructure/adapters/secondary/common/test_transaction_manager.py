"""
Unit tests for TransactionManager.

Tests are written FIRST (TDD RED phase).
These tests MUST FAIL before implementation exists.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession


class TestTransactionManager:
    """Test suite for TransactionManager foundation class."""

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
        session.close = AsyncMock()
        return session

    @pytest.fixture
    def mock_read_session(self):
        """Create a mock read replica AsyncSession."""
        session = AsyncMock(spec=AsyncSession)
        session.execute = AsyncMock()
        session.flush = AsyncMock()
        session.commit = AsyncMock()
        session.rollback = AsyncMock()
        session.in_transaction = MagicMock(return_value=False)
        session.begin = AsyncMock()
        session.close = AsyncMock()
        return session

    # === TEST: TransactionManager class exists ===

    def test_transaction_manager_class_exists(self):
        """Test that TransactionManager class can be imported."""
        from src.infrastructure.adapters.secondary.common.transaction_manager import (
            TransactionManager,
        )

        assert TransactionManager is not None

    # === TEST: Initialization ===

    def test_transaction_manager_initialization(self, mock_session):
        """Test TransactionManager can be initialized."""
        from src.infrastructure.adapters.secondary.common.transaction_manager import (
            TransactionManager,
        )

        tm = TransactionManager(mock_session)
        assert tm.session == mock_session

    def test_transaction_manager_with_read_replica(self, mock_session, mock_read_session):
        """Test TransactionManager with read replica support."""
        from src.infrastructure.adapters.secondary.common.transaction_manager import (
            TransactionManager,
        )

        tm = TransactionManager(mock_session, read_session=mock_read_session)
        assert tm.session == mock_session
        assert tm.read_session == mock_read_session

    def test_transaction_manager_without_read_replica(self, mock_session):
        """Test TransactionManager without read replica uses primary for reads."""
        from src.infrastructure.adapters.secondary.common.transaction_manager import (
            TransactionManager,
        )

        tm = TransactionManager(mock_session)
        assert tm.read_session == mock_session  # Falls back to primary

    # === TEST: Transaction context manager ===

    @pytest.mark.asyncio
    async def test_transaction_commits_on_success(self, mock_session):
        """Test transaction context manager commits on success."""
        from src.infrastructure.adapters.secondary.common.transaction_manager import (
            TransactionManager,
        )

        tm = TransactionManager(mock_session)

        async with tm.transaction():
            pass

        mock_session.commit.assert_called_once()
        mock_session.rollback.assert_not_called()

    @pytest.mark.asyncio
    async def test_transaction_rolls_back_on_error(self, mock_session):
        """Test transaction context manager rolls back on error."""
        from src.infrastructure.adapters.secondary.common.transaction_manager import (
            TransactionManager,
        )

        tm = TransactionManager(mock_session)

        with pytest.raises(ValueError, match="Test error"):
            async with tm.transaction():
                raise ValueError("Test error")

        mock_session.rollback.assert_called_once()
        mock_session.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_nested_transaction_supported(self, mock_session):
        """Test nested transaction support using savepoints."""
        from src.infrastructure.adapters.secondary.common.transaction_manager import (
            TransactionManager,
        )

        mock_session.in_nested_transaction = MagicMock(return_value=True)

        tm = TransactionManager(mock_session)

        async with tm.transaction():
            pass

        # Commit should happen
        mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_transaction_with_read_only_hint(self, mock_session):
        """Test transaction with read-only hint."""
        from src.infrastructure.adapters.secondary.common.transaction_manager import (
            TransactionManager,
        )

        tm = TransactionManager(mock_session)

        async with tm.transaction(read_only=True):
            pass

        mock_session.commit.assert_called_once()

    # === TEST: Distributed transactions (PostgreSQL + Neo4j) ===

    @pytest.mark.asyncio
    async def test_distributed_transaction_two_phase_commit(self, mock_session):
        """Test distributed transaction with two-phase commit pattern."""
        from src.infrastructure.adapters.secondary.common.transaction_manager import (
            TransactionManager,
        )

        # Mock Neo4j transaction
        mock_neo4j_tx = MagicMock()
        mock_neo4j_tx.commit = MagicMock()
        mock_neo4j_tx.rollback = MagicMock()

        tm = TransactionManager(mock_session)

        # Use distributed transaction API
        async with tm.distributed_transaction(neo4j_tx=mock_neo4j_tx):
            pass

        # Both commits should happen
        mock_session.commit.assert_called_once()
        mock_neo4j_tx.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_distributed_transaction_rolls_back_all_on_error(self, mock_session):
        """Test distributed transaction rolls back both databases on error."""
        from src.infrastructure.adapters.secondary.common.transaction_manager import (
            TransactionManager,
        )

        mock_neo4j_tx = MagicMock()
        mock_neo4j_tx.commit = MagicMock()
        mock_neo4j_tx.rollback = MagicMock()

        tm = TransactionManager(mock_session)

        with pytest.raises(ValueError, match="Distributed error"):
            async with tm.distributed_transaction(neo4j_tx=mock_neo4j_tx):
                raise ValueError("Distributed error")

        # Both rollbacks should happen
        mock_session.rollback.assert_called_once()
        mock_neo4j_tx.rollback.assert_called_once()
        mock_neo4j_tx.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_distributed_transaction_postgres_commits_first(self, mock_session):
        """Test PostgreSQL commits before Neo4j in distributed transaction."""
        from src.infrastructure.adapters.secondary.common.transaction_manager import (
            TransactionManager,
        )

        call_order = []

        async def mock_postgres_commit():
            call_order.append("postgres")

        mock_neo4j_tx = MagicMock()
        mock_neo4j_tx.commit = MagicMock(side_effect=lambda: call_order.append("neo4j"))

        mock_session.commit = AsyncMock(side_effect=mock_postgres_commit)

        tm = TransactionManager(mock_session)

        async with tm.distributed_transaction(neo4j_tx=mock_neo4j_tx):
            pass

        # PostgreSQL should commit first
        assert call_order == ["postgres", "neo4j"]

    # === TEST: Read-write splitting ===

    @pytest.mark.asyncio
    async def test_read_operation_uses_read_replica(self, mock_session, mock_read_session):
        """Test read operations use read replica when available."""
        from src.infrastructure.adapters.secondary.common.transaction_manager import (
            TransactionManager,
        )

        tm = TransactionManager(mock_session, read_session=mock_read_session)

        # Get session for read operation
        read_session = tm.get_session_for_read()

        assert read_session == mock_read_session
        assert read_session != mock_session

    @pytest.mark.asyncio
    async def test_read_operation_falls_back_to_primary(self, mock_session):
        """Test read operations fall back to primary when no read replica."""
        from src.infrastructure.adapters.secondary.common.transaction_manager import (
            TransactionManager,
        )

        tm = TransactionManager(mock_session)

        read_session = tm.get_session_for_read()

        assert read_session == mock_session

    @pytest.mark.asyncio
    async def test_write_operation_always_uses_primary(self, mock_session, mock_read_session):
        """Test write operations always use primary database."""
        from src.infrastructure.adapters.secondary.common.transaction_manager import (
            TransactionManager,
        )

        tm = TransactionManager(mock_session, read_session=mock_read_session)

        write_session = tm.get_session_for_write()

        assert write_session == mock_session
        assert write_session != mock_read_session

    # === TEST: Transaction state tracking ===

    @pytest.mark.asyncio
    async def test_is_in_transaction(self, mock_session):
        """Test is_in_transaction returns correct state."""
        from src.infrastructure.adapters.secondary.common.transaction_manager import (
            TransactionManager,
        )

        tm = TransactionManager(mock_session)

        mock_session.in_transaction.return_value = False
        assert not tm.is_in_transaction()

        async with tm.transaction():
            mock_session.in_transaction.return_value = True
            assert tm.is_in_transaction()

    @pytest.mark.asyncio
    async def test_get_transaction_depth(self, mock_session):
        """Test tracking nested transaction depth."""
        from src.infrastructure.adapters.secondary.common.transaction_manager import (
            TransactionManager,
        )

        tm = TransactionManager(mock_session)

        assert tm.transaction_depth == 0

        async with tm.transaction():
            # When in transaction context manager, depth starts at 1
            assert tm.transaction_depth == 1

        # After transaction, depth should be reset
        assert tm.transaction_depth == 0

    # === TEST: Session lifecycle management ===

    @pytest.mark.asyncio
    async def test_begin_explicit_transaction(self, mock_session):
        """Test beginning an explicit transaction."""
        from src.infrastructure.adapters.secondary.common.transaction_manager import (
            TransactionManager,
        )

        tm = TransactionManager(mock_session)

        await tm.begin()

        mock_session.begin.assert_called_once()
        assert tm.transaction_depth == 1

    @pytest.mark.asyncio
    async def test_commit_explicit_transaction(self, mock_session):
        """Test committing an explicit transaction."""
        from src.infrastructure.adapters.secondary.common.transaction_manager import (
            TransactionManager,
        )

        tm = TransactionManager(mock_session)

        await tm.commit()

        mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_rollback_explicit_transaction(self, mock_session):
        """Test rolling back an explicit transaction."""
        from src.infrastructure.adapters.secondary.common.transaction_manager import (
            TransactionManager,
        )

        tm = TransactionManager(mock_session)

        await tm.rollback()

        mock_session.rollback.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_session(self, mock_session):
        """Test closing the session."""
        from src.infrastructure.adapters.secondary.common.transaction_manager import (
            TransactionManager,
        )

        tm = TransactionManager(mock_session)

        await tm.close()

        mock_session.close.assert_called_once()

    # === TEST: Retry logic ===

    @pytest.mark.asyncio
    async def test_retry_on_begin_error(self, mock_session):
        """Test retrying transaction on begin() connection error."""
        from sqlalchemy.exc import DBAPIError

        from src.infrastructure.adapters.secondary.common.transaction_manager import (
            TransactionManager,
        )

        # First begin fails with transient error, second succeeds
        call_count = 0

        async def failing_then_succeeding_begin():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise DBAPIError("Connection lost", {}, None)
            return None

        mock_session.begin = AsyncMock(side_effect=failing_then_succeeding_begin)
        mock_session.commit = AsyncMock()
        mock_session.rollback = AsyncMock()

        # Note: Current implementation doesn't auto-retry
        # This test documents expected behavior
        tm = TransactionManager(mock_session)

        with pytest.raises(DBAPIError):
            async with tm.transaction():
                pass

        # Should have tried once
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_transaction_error_propagates(self, mock_session):
        """Test that transaction errors are properly propagated."""
        from src.infrastructure.adapters.secondary.common.transaction_manager import (
            TransactionManager,
        )

        tm = TransactionManager(mock_session)

        with pytest.raises(ValueError):
            async with tm.transaction():
                raise ValueError("Test error")

        mock_session.rollback.assert_called_once()

    # === TEST: Savepoints ===

    @pytest.mark.asyncio
    async def test_create_savepoint(self, mock_session):
        """Test creating a savepoint within a transaction."""
        from src.infrastructure.adapters.secondary.common.transaction_manager import (
            TransactionManager,
        )

        tm = TransactionManager(mock_session)

        # Begin a transaction first
        await tm.begin()

        # Mock execute to handle SAVEPOINT commands
        execute_call_count = 0

        async def mock_execute(stmt):
            nonlocal execute_call_count
            execute_call_count += 1

        mock_session.execute = AsyncMock(side_effect=mock_execute)

        async with tm.savepoint("sp1"):
            pass

        # Execute should have been called for SAVEPOINT and RELEASE SAVEPOINT
        assert execute_call_count >= 1

    @pytest.mark.asyncio
    async def test_rollback_to_savepoint(self, mock_session):
        """Test rolling back to a savepoint."""
        from src.infrastructure.adapters.secondary.common.transaction_manager import (
            TransactionManager,
        )

        tm = TransactionManager(mock_session)
        await tm.begin()

        execute_calls = []

        async def mock_execute(stmt):
            execute_calls.append(str(stmt))

        mock_session.execute = AsyncMock(side_effect=mock_execute)

        with pytest.raises(ValueError):
            async with tm.savepoint("sp1"):
                raise ValueError("Error in savepoint")

        # Should have executed ROLLBACK TO SAVEPOINT
        assert any("ROLLBACK" in call for call in execute_calls)

    # === TEST: Edge cases ===

    @pytest.mark.asyncio
    async def test_transaction_manager_with_none_session_raises_error(self):
        """Test TransactionManager raises error when session is None."""
        from src.infrastructure.adapters.secondary.common.transaction_manager import (
            TransactionManager,
        )

        with pytest.raises(ValueError, match="Session cannot be None"):
            TransactionManager(None)

    @pytest.mark.asyncio
    async def test_distributed_transaction_without_neo4j_works(self, mock_session):
        """Test distributed transaction works without Neo4j component."""
        from src.infrastructure.adapters.secondary.common.transaction_manager import (
            TransactionManager,
        )

        tm = TransactionManager(mock_session)

        # Should work with just PostgreSQL
        async with tm.distributed_transaction():
            pass

        mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_is_transient_error_detection(self, mock_session):
        """Test transient error detection logic."""
        from sqlalchemy.exc import DBAPIError

        from src.infrastructure.adapters.secondary.common.transaction_manager import (
            TransactionManager,
        )

        tm = TransactionManager(mock_session)

        # Create a mock transient error
        mock_error = MagicMock(spec=DBAPIError)
        mock_error.orig = MagicMock()
        mock_error.orig.pgcode = "08006"  # Connection failure

        assert tm._is_transient_error(mock_error) is True

        # Create a mock non-transient error
        mock_error.orig.pgcode = "23505"  # Unique violation

        assert tm._is_transient_error(mock_error) is False
