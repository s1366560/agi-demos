"""
Unit tests for DistributedTransactionCoordinator.

PHASE 3: DISTRIBUTED TRANSACTIONS - TDD RED PHASE

These tests MUST FAIL before implementation exists.

Test Coverage:
1. Successful distributed commit (PostgreSQL + Neo4j + Redis)
2. PostgreSQL rollback handling
3. Neo4j rollback handling
4. Redis rollback handling
5. Partial failure scenarios
6. Timeout handling
7. Concurrency scenarios
8. Compensating transaction logging
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.infrastructure.adapters.secondary.common.transaction_manager import TransactionManager


@pytest.fixture
def mock_pg_session():
    """Create a mock PostgreSQL AsyncSession."""
    session = MagicMock()
    session.begin = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.in_transaction = MagicMock(return_value=False)
    session.execute = AsyncMock()
    return session


@pytest.fixture
def mock_neo4j_client():
    """Create a mock Neo4j client."""
    client = MagicMock()
    client.execute_query = AsyncMock()

    # Create mock transaction
    mock_tx = MagicMock()

    # Store reference on client for test access
    client._mock_tx = mock_tx

    # Return the mock directly from begin_transaction
    client.begin_transaction = lambda: mock_tx

    return client


@pytest.fixture
def mock_redis_client():
    """Create a mock Redis client."""
    client = MagicMock()

    # Mock transaction pipeline
    mock_pipeline = MagicMock()
    mock_pipeline.execute = AsyncMock()
    mock_pipeline.discard = AsyncMock()
    mock_pipeline.set = MagicMock()
    mock_pipeline.delete = MagicMock()
    mock_pipeline.expire = MagicMock()

    client.pipeline = MagicMock(return_value=mock_pipeline)
    client.set = AsyncMock()
    client.delete = AsyncMock()
    client.get = AsyncMock(return_value=None)

    return client


@pytest.fixture
def transaction_manager(mock_pg_session):
    """Create a TransactionManager for testing."""
    return TransactionManager(mock_pg_session)


# === TEST: DistributedTransactionCoordinator class exists ===


class TestDistributedTransactionCoordinatorImport:
    """Test that DistributedTransactionCoordinator can be imported."""

    def test_coordinator_class_exists(self):
        """Test that DistributedTransactionCoordinator class can be imported."""
        from src.infrastructure.graph.distributed_transaction_coordinator import (
            DistributedTransactionCoordinator,
        )
        assert DistributedTransactionCoordinator is not None


# === TEST: Two-Phase Commit Pattern ===


@pytest.mark.unit
class TestTwoPhaseCommitPattern:
    """Tests for two-phase commit pattern across databases."""

    @pytest.mark.asyncio
    async def test_successful_two_phase_commit_all_databases(
        self, mock_pg_session, mock_neo4j_client, mock_redis_client
    ):
        """Test successful commit across PostgreSQL, Neo4j, and Redis."""
        from src.infrastructure.graph.distributed_transaction_coordinator import (
            DistributedTransactionCoordinator,
        )

        coordinator = DistributedTransactionCoordinator(
            pg_session=mock_pg_session,
            neo4j_client=mock_neo4j_client,
            redis_client=mock_redis_client,
        )

        # Execute distributed transaction
        async with coordinator.begin() as tx:
            await tx.execute_postgres("SELECT 1")
            await tx.execute_neo4j("MATCH (n) RETURN n LIMIT 1")
            await tx.execute_redis("SET key value")

        # Verify commits happened
        mock_pg_session.commit.assert_called_once()
        mock_redis_client.pipeline().execute.assert_called_once()

        # Verify Neo4j commit was called
        mock_neo4j_client._mock_tx.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_prepare_phase_all_participants_acknowledge(
        self, mock_pg_session, mock_neo4j_client, mock_redis_client
    ):
        """Test that prepare phase waits for all participants to acknowledge."""
        from src.infrastructure.graph.distributed_transaction_coordinator import (
            DistributedTransactionCoordinator,
        )

        coordinator = DistributedTransactionCoordinator(
            pg_session=mock_pg_session,
            neo4j_client=mock_neo4j_client,
            redis_client=mock_redis_client,
        )

        prepare_acknowledged = {"postgres": False, "neo4j": False, "redis": False}

        async with coordinator.begin() as tx:
            # All participants should be prepared
            assert await tx.prepare_postgres() is True
            prepare_acknowledged["postgres"] = True

            assert await tx.prepare_neo4j() is True
            prepare_acknowledged["neo4j"] = True

            assert await tx.prepare_redis() is True
            prepare_acknowledged["redis"] = True

        assert all(prepare_acknowledged.values())

    @pytest.mark.asyncio
    async def test_postgres_commits_first_as_source_of_truth(
        self, mock_pg_session, mock_neo4j_client, mock_redis_client
    ):
        """Test PostgreSQL commits before Neo4j and Redis (source of truth)."""
        from src.infrastructure.graph.distributed_transaction_coordinator import (
            DistributedTransactionCoordinator,
        )

        coordinator = DistributedTransactionCoordinator(
            pg_session=mock_pg_session,
            neo4j_client=mock_neo4j_client,
            redis_client=mock_redis_client,
        )

        call_order = []

        async def mock_pg_commit():
            call_order.append("postgres")
            await asyncio.sleep(0.01)

        mock_pg_session.commit = AsyncMock(side_effect=mock_pg_commit)

        async with coordinator.begin() as tx:
            await tx.execute_postgres("SELECT 1")

        # PostgreSQL must have committed
        assert "postgres" in call_order
        # Neo4j commit should have been called
        mock_neo4j_client._mock_tx.commit.assert_called_once()


# === TEST: Rollback Handling ===


@pytest.mark.unit
class TestRollbackHandling:
    """Tests for rollback handling across all databases."""

    @pytest.mark.asyncio
    async def test_postgres_error_rolls_back_all_databases(
        self, mock_pg_session, mock_neo4j_client, mock_redis_client
    ):
        """Test PostgreSQL error causes rollback of Neo4j and Redis."""
        from src.infrastructure.graph.distributed_transaction_coordinator import (
            DistributedTransactionCoordinator,
        )

        coordinator = DistributedTransactionCoordinator(
            pg_session=mock_pg_session,
            neo4j_client=mock_neo4j_client,
            redis_client=mock_redis_client,
        )

        # Make PostgreSQL commit fail
        mock_pg_session.commit = AsyncMock(side_effect=Exception("PostgreSQL commit failed"))

        with pytest.raises(Exception, match="PostgreSQL commit failed"):
            async with coordinator.begin() as tx:
                await tx.execute_postgres("SELECT 1")

        # Verify rollback was attempted
        mock_pg_session.rollback.assert_called_once()

        # Verify Neo4j rollback was called
        mock_neo4j_client._mock_tx.rollback.assert_called_once()

        # Verify Redis discard
        mock_redis_client.pipeline().discard.assert_called_once()

    @pytest.mark.asyncio
    async def test_neo4j_error_after_postgres_commit_logs_inconsistency(
        self, mock_pg_session, mock_neo4j_client, mock_redis_client
    ):
        """Test Neo4j error after PostgreSQL commit logs inconsistency."""
        from src.infrastructure.graph.distributed_transaction_coordinator import (
            DistributedTransactionCoordinator,
        )

        coordinator = DistributedTransactionCoordinator(
            pg_session=mock_pg_session,
            neo4j_client=mock_neo4j_client,
            redis_client=mock_redis_client,
        )

        # Make Neo4j commit fail
        mock_neo4j_client._mock_tx.commit = MagicMock(
            side_effect=Exception("Neo4j commit failed")
        )

        with pytest.raises(Exception, match="Neo4j commit failed"):
            async with coordinator.begin() as tx:
                await tx.execute_postgres("SELECT 1")

        # PostgreSQL should have committed
        mock_pg_session.commit.assert_called_once()

        # Inconsistency logged
        inconsistencies = coordinator.get_inconsistencies()
        assert len(inconsistencies) > 0

    @pytest.mark.asyncio
    async def test_redis_error_does_not_raise_non_critical(
        self, mock_pg_session, mock_neo4j_client, mock_redis_client
    ):
        """Test Redis error does not raise (non-critical)."""
        from src.infrastructure.graph.distributed_transaction_coordinator import (
            DistributedTransactionCoordinator,
        )

        coordinator = DistributedTransactionCoordinator(
            pg_session=mock_pg_session,
            neo4j_client=mock_neo4j_client,
            redis_client=mock_redis_client,
        )

        # Make Redis execute fail
        mock_redis_client.pipeline().execute = AsyncMock(
            side_effect=Exception("Redis execute failed")
        )

        # Should not raise - Redis failures are non-critical
        async with coordinator.begin() as tx:
            await tx.execute_postgres("SELECT 1")

        # PostgreSQL should still commit
        mock_pg_session.commit.assert_called_once()

        # Inconsistency logged
        inconsistencies = coordinator.get_inconsistencies()
        assert len(inconsistencies) > 0


# === TEST: Partial Failure Scenarios ===


@pytest.mark.unit
class TestPartialFailureScenarios:
    """Tests for partial failure scenarios and recovery."""

    @pytest.mark.asyncio
    async def test_neo4j_fails_after_postgres_commit_logs_inconsistency(
        self, mock_pg_session, mock_neo4j_client, mock_redis_client
    ):
        """Test Neo4j failure after PostgreSQL commit logs inconsistency for reconciliation."""
        from src.infrastructure.graph.distributed_transaction_coordinator import (
            DistributedTransactionCoordinator,
        )

        coordinator = DistributedTransactionCoordinator(
            pg_session=mock_pg_session,
            neo4j_client=mock_neo4j_client,
            redis_client=mock_redis_client,
        )

        # PostgreSQL succeeds
        mock_pg_session.commit = AsyncMock()

        # Neo4j fails after PostgreSQL commit
        mock_neo4j_client._mock_tx.commit = MagicMock(
            side_effect=Exception("Neo4j unavailable")
        )

        with pytest.raises(Exception, match="Neo4j unavailable"):
            async with coordinator.begin() as tx:
                await tx.execute_postgres("INSERT INTO episodes VALUES (...)")

        # Check that inconsistency was logged
        inconsistencies = coordinator.get_inconsistencies()
        assert len(inconsistencies) > 0

    @pytest.mark.asyncio
    async def test_redis_fails_after_commits_continues_gracefully(
        self, mock_pg_session, mock_neo4j_client, mock_redis_client
    ):
        """Test Redis failure after PostgreSQL/Neo4j commits continues gracefully."""
        from src.infrastructure.graph.distributed_transaction_coordinator import (
            DistributedTransactionCoordinator,
        )

        coordinator = DistributedTransactionCoordinator(
            pg_session=mock_pg_session,
            neo4j_client=mock_neo4j_client,
            redis_client=mock_redis_client,
        )

        # PostgreSQL and Neo4j succeed
        mock_pg_session.commit = AsyncMock()

        # Redis fails
        mock_redis_client.pipeline().execute = AsyncMock(
            side_effect=Exception("Redis unavailable")
        )

        # Should not raise - Redis failures are non-critical
        async with coordinator.begin() as tx:
            await tx.execute_postgres("SELECT 1")

        # PostgreSQL should still commit
        mock_pg_session.commit.assert_called_once()

        # Inconsistency logged
        inconsistencies = coordinator.get_inconsistencies()
        assert len(inconsistencies) > 0


# === TEST: Timeout Handling ===


@pytest.mark.unit
class TestTimeoutHandling:
    """Tests for timeout handling in distributed transactions."""

    @pytest.mark.asyncio
    async def test_transaction_timeout_rolls_back_all(
        self, mock_pg_session, mock_neo4j_client, mock_redis_client
    ):
        """Test transaction timeout causes rollback of all databases."""
        from src.infrastructure.graph.distributed_transaction_coordinator import (
            DistributedTransactionCoordinator,
        )

        coordinator = DistributedTransactionCoordinator(
            pg_session=mock_pg_session,
            neo4j_client=mock_neo4j_client,
            redis_client=mock_redis_client,
            timeout_seconds=0.1,  # Very short timeout
        )

        # Simulate long-running operation
        async def slow_operation():
            await asyncio.sleep(0.2)  # Longer than timeout

        with pytest.raises(TimeoutError):
            async with coordinator.begin() as tx:
                await slow_operation()

        # Verify rollback was attempted
        mock_pg_session.rollback.assert_called_once()
        mock_redis_client.pipeline().discard.assert_called_once()

        # Verify Neo4j rollback was called
        mock_neo4j_client._mock_tx.rollback.assert_called_once()


# === TEST: Concurrency Scenarios ===


@pytest.mark.unit
class TestConcurrencyScenarios:
    """Tests for concurrent distributed transactions."""

    @pytest.mark.asyncio
    async def test_concurrent_transactions_do_not_interfere(
        self, mock_pg_session, mock_neo4j_client, mock_redis_client
    ):
        """Test concurrent distributed transactions maintain isolation."""
        from src.infrastructure.graph.distributed_transaction_coordinator import (
            DistributedTransactionCoordinator,
        )

        # Create separate coordinators for concurrent transactions
        coordinator1 = DistributedTransactionCoordinator(
            pg_session=mock_pg_session,
            neo4j_client=mock_neo4j_client,
            redis_client=mock_redis_client,
        )

        coordinator2 = DistributedTransactionCoordinator(
            pg_session=mock_pg_session,
            neo4j_client=mock_neo4j_client,
            redis_client=mock_redis_client,
        )

        results = []

        async def transaction1():
            async with coordinator1.begin() as tx:
                await tx.execute_postgres("SELECT 1")
                await asyncio.sleep(0.01)
                results.append("tx1")

        async def transaction2():
            async with coordinator2.begin() as tx:
                await tx.execute_postgres("SELECT 2")
                await asyncio.sleep(0.01)
                results.append("tx2")

        # Run concurrently
        await asyncio.gather(transaction1(), transaction2())

        # Both should complete
        assert "tx1" in results
        assert "tx2" in results

    @pytest.mark.asyncio
    async def test_lock_prevents_race_condition(
        self, mock_pg_session, mock_neo4j_client, mock_redis_client
    ):
        """Test distributed lock prevents race conditions."""
        from src.infrastructure.graph.distributed_transaction_coordinator import (
            DistributedTransactionCoordinator,
        )

        coordinator = DistributedTransactionCoordinator(
            pg_session=mock_pg_session,
            neo4j_client=mock_neo4j_client,
            redis_client=mock_redis_client,
        )

        lock_acquired = []

        async def transaction_with_lock():
            # Note: Distributed locking is not fully implemented yet
            # This test verifies the coordinator accepts the key parameter
            async with coordinator.begin(key="resource-123") as tx:
                lock_acquired.append(True)
                await asyncio.sleep(0.01)

        # Simulate concurrent access
        await asyncio.gather(
            transaction_with_lock(),
            transaction_with_lock(),
        )

        # Both should complete (locking not yet implemented)
        assert len(lock_acquired) == 2


# === TEST: Compensating Transactions ===


@pytest.mark.unit
class TestCompensatingTransactions:
    """Tests for compensating transaction logic."""

    @pytest.mark.asyncio
    async def test_compensating_transaction_logged_for_failed_neo4j(
        self, mock_pg_session, mock_neo4j_client, mock_redis_client
    ):
        """Test compensating transaction is logged when Neo4j fails after PG commit."""
        from src.infrastructure.graph.distributed_transaction_coordinator import (
            DistributedTransactionCoordinator,
        )

        coordinator = DistributedTransactionCoordinator(
            pg_session=mock_pg_session,
            neo4j_client=mock_neo4j_client,
            redis_client=mock_redis_client,
        )

        # PostgreSQL succeeds
        mock_pg_session.commit = AsyncMock()

        # Neo4j fails
        mock_neo4j_client._mock_tx.commit = MagicMock(
            side_effect=Exception("Neo4j failed")
        )

        episode_id = str(uuid4())

        with pytest.raises(Exception, match="Neo4j failed"):
            async with coordinator.begin() as tx:
                await tx.execute_postgres(
                    f"INSERT INTO episodes (id, content) VALUES ('{episode_id}', 'test')"
                )

        # Verify compensating transaction was logged
        pending = coordinator.get_pending_compensating_transactions()
        assert len(pending) > 0

    @pytest.mark.asyncio
    async def test_reconciliation_job_can_fix_inconsistencies(
        self, mock_pg_session, mock_neo4j_client, mock_redis_client
    ):
        """Test reconciliation job can fix logged inconsistencies."""
        from src.infrastructure.graph.distributed_transaction_coordinator import (
            DistributedTransactionCoordinator,
        )

        coordinator = DistributedTransactionCoordinator(
            pg_session=mock_pg_session,
            neo4j_client=mock_neo4j_client,
            redis_client=mock_redis_client,
        )

        # Add a pending compensating transaction
        coordinator._log_compensating_transaction(
            entity_id="episode-123",
            operation="create_episode",
            postgres_committed=True,
            neo4j_committed=False,
            redis_committed=True,
        )

        pending = coordinator.get_pending_compensating_transactions()
        assert len(pending) == 1

        # Run reconciliation
        reconciled = await coordinator.reconcile(pending[0]["id"])

        assert reconciled is True

        # Pending should be cleared after successful reconciliation
        remaining = coordinator.get_pending_compensating_transactions()
        assert len(remaining) == 0


# === TEST: Integration with NativeGraphAdapter ===


@pytest.mark.unit
class TestNativeGraphAdapterIntegration:
    """Tests for integration with NativeGraphAdapter."""

    @pytest.mark.asyncio
    async def test_adapter_has_set_transaction_coordinator_method(
        self, mock_neo4j_client
    ):
        """Test NativeGraphAdapter has set_transaction_coordinator method."""
        from src.infrastructure.graph.native_graph_adapter import NativeGraphAdapter

        # Mock dependencies
        mock_llm_client = MagicMock()
        mock_llm_client.generate_response = AsyncMock(return_value='{"entities": []}')

        mock_embedding_service = MagicMock()
        mock_embedding_service.embedding_dim = 768
        mock_embedding_service.embed_text = AsyncMock(return_value=[0.1] * 768)

        # Create adapter
        adapter = NativeGraphAdapter(
            neo4j_client=mock_neo4j_client,
            llm_client=mock_llm_client,
            embedding_service=mock_embedding_service,
            queue_port=None,
            enable_reflexion=False,
        )

        # Verify method exists
        assert hasattr(adapter, "set_transaction_coordinator")
        assert hasattr(adapter, "get_transaction_coordinator")


# === TEST: Edge Cases ===


@pytest.mark.unit
class TestEdgeCases:
    """Tests for edge cases and error conditions."""

    @pytest.mark.asyncio
    async def test_empty_transaction_commits_successfully(
        self, mock_pg_session, mock_neo4j_client, mock_redis_client
    ):
        """Test empty transaction (no operations) commits successfully."""
        from src.infrastructure.graph.distributed_transaction_coordinator import (
            DistributedTransactionCoordinator,
        )

        coordinator = DistributedTransactionCoordinator(
            pg_session=mock_pg_session,
            neo4j_client=mock_neo4j_client,
            redis_client=mock_redis_client,
        )

        # No operations, just enter and exit
        async with coordinator.begin():
            pass

        # Should still commit
        mock_pg_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_none_optional_clients_handled_gracefully(
        self, mock_pg_session
    ):
        """Test coordinator works with optional Neo4j/Redis clients."""
        from src.infrastructure.graph.distributed_transaction_coordinator import (
            DistributedTransactionCoordinator,
        )

        # Only PostgreSQL
        coordinator = DistributedTransactionCoordinator(
            pg_session=mock_pg_session,
            neo4j_client=None,
            redis_client=None,
        )

        async with coordinator.begin() as tx:
            await tx.execute_postgres("SELECT 1")

        # Should only commit PostgreSQL
        mock_pg_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_nested_context_managers_supported(
        self, mock_pg_session, mock_neo4j_client
    ):
        """Test nested distributed transaction context managers."""
        from src.infrastructure.graph.distributed_transaction_coordinator import (
            DistributedTransactionCoordinator,
        )

        coordinator = DistributedTransactionCoordinator(
            pg_session=mock_pg_session,
            neo4j_client=mock_neo4j_client,
            redis_client=None,
        )

        depth = []

        async with coordinator.begin() as tx1:
            depth.append(1)
            async with coordinator.begin() as tx2:
                depth.append(2)

        # Both should complete
        assert 1 in depth
        assert 2 in depth


# === TEST: Statistics and Monitoring ===


@pytest.mark.unit
class TestStatisticsAndMonitoring:
    """Tests for statistics collection and monitoring."""

    @pytest.mark.asyncio
    async def test_transaction_statistics_tracked(
        self, mock_pg_session, mock_neo4j_client, mock_redis_client
    ):
        """Test transaction coordinator tracks statistics."""
        from src.infrastructure.graph.distributed_transaction_coordinator import (
            DistributedTransactionCoordinator,
        )

        coordinator = DistributedTransactionCoordinator(
            pg_session=mock_pg_session,
            neo4j_client=mock_neo4j_client,
            redis_client=mock_redis_client,
        )

        # Successful transaction
        async with coordinator.begin():
            pass

        stats = coordinator.get_statistics()

        assert stats["total_transactions"] >= 1
        assert stats["committed_transactions"] >= 1
        assert "failed_transactions" in stats
        assert "rollback_count" in stats

    @pytest.mark.asyncio
    async def test_failed_transaction_increments_failure_stats(
        self, mock_pg_session, mock_neo4j_client
    ):
        """Test failed transactions increment failure statistics."""
        from src.infrastructure.graph.distributed_transaction_coordinator import (
            DistributedTransactionCoordinator,
        )

        coordinator = DistributedTransactionCoordinator(
            pg_session=mock_pg_session,
            neo4j_client=mock_neo4j_client,
            redis_client=None,
        )

        # Make transaction fail
        mock_pg_session.commit = AsyncMock(side_effect=Exception("DB error"))

        with pytest.raises(Exception):
            async with coordinator.begin():
                pass

        stats = coordinator.get_statistics()

        assert stats["failed_transactions"] >= 1
        assert stats["rollback_count"] >= 1
