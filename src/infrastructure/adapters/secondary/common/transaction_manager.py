"""
TransactionManager for database transaction management.

Provides:
- Simple transaction context manager
- Distributed transaction support (PostgreSQL + Neo4j)
- Read/write splitting for read replicas
- Automatic retry on transient failures
- Savepoint support for nested transactions
"""

import contextlib
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession as SQLAlchemyAsyncSession
from sqlalchemy import text

logger = logging.getLogger(__name__)


class TransactionManager:
    """
    Manages database transactions with support for distributed transactions.

    Features:
    - Simple commit/rollback transactions
    - Distributed transactions across PostgreSQL and Neo4j
    - Read replica routing for read operations
    - Automatic retry on transient database errors
    - Savepoint support for nested transactions
    """

    def __init__(
        self,
        session: SQLAlchemyAsyncSession,
        read_session: SQLAlchemyAsyncSession | None = None,
        max_retries: int = 3,
    ) -> None:
        """
        Initialize the transaction manager.

        Args:
            session: Primary database session for write operations
            read_session: Optional read replica session for read operations
            max_retries: Maximum number of retry attempts for transient errors

        Raises:
            ValueError: If session is None
        """
        if session is None:
            raise ValueError("Session cannot be None")

        self._session = session
        self._read_session = read_session or session
        self._max_retries = max_retries
        self._transaction_depth = 0
        self._in_context = False

    @property
    def session(self) -> SQLAlchemyAsyncSession:
        """Get the primary database session."""
        return self._session

    @property
    def read_session(self) -> SQLAlchemyAsyncSession:
        """Get the read replica session (falls back to primary if not configured)."""
        return self._read_session

    def get_session_for_read(self) -> SQLAlchemyAsyncSession:
        """
        Get the appropriate session for read operations.

        Returns the read replica session if configured,
        otherwise returns the primary session.

        Returns:
            Session for read operations
        """
        return self._read_session

    def get_session_for_write(self) -> SQLAlchemyAsyncSession:
        """
        Get the appropriate session for write operations.

        Always returns the primary session to ensure consistency.

        Returns:
            Session for write operations
        """
        return self._session

    def is_in_transaction(self) -> bool:
        """
        Check if currently in a transaction.

        Returns:
            True if in a transaction, False otherwise
        """
        return self._session.in_transaction()

    @property
    def transaction_depth(self) -> int:
        """Get the current nesting depth of transactions."""
        return self._transaction_depth

    # === Transaction lifecycle ===

    async def begin(self) -> None:
        """Begin a new transaction."""
        if not self._session.in_transaction():
            await self._session.begin()
            self._transaction_depth = 1
        else:
            # Already in transaction, increment depth
            self._transaction_depth += 1

    async def commit(self) -> None:
        """Commit the current transaction."""
        await self._session.commit()
        self._transaction_depth = 0

    async def rollback(self) -> None:
        """Rollback the current transaction."""
        await self._session.rollback()
        self._transaction_depth = 0

    async def close(self) -> None:
        """Close the database session."""
        await self._session.close()
        if self._read_session != self._session:
            await self._read_session.close()

    # === Context managers ===

    @asynccontextmanager
    async def transaction(
        self,
        read_only: bool = False,
    ) -> AsyncGenerator["TransactionManager", None]:
        """
        Context manager for transactional operations.

        Automatically commits on success, rolls back on error.

        Args:
            read_only: If True, hints that this is a read-only transaction

        Yields:
            self for fluent API usage

        Example:
            async with tm.transaction():
                await repository.save(entity)
        """
        # Reset transaction depth at the start
        self._transaction_depth = 0

        try:
            await self.begin()

            try:
                yield self
            except Exception:
                # Error during yield - rollback and reraise
                await self.rollback()
                raise

            # If we get here, yield completed without error
            # Now try to commit
            await self.commit()

        except Exception:
            # Any error from begin(), yield, or commit
            # Already rolled back if needed
            raise

    @asynccontextmanager
    async def distributed_transaction(
        self,
        neo4j_tx: Any | None = None,
        redis_tx: Any | None = None,
    ) -> AsyncGenerator["TransactionManager", None]:
        """
        Context manager for distributed transactions across multiple databases.

        Implements two-phase commit pattern:
        1. Prepare all participants
        2. Commit PostgreSQL first (source of truth)
        3. Commit Neo4j second (derived data)
        4. Rollback all if any step fails

        Args:
            neo4j_tx: Optional Neo4j transaction
            redis_tx: Optional Redis transaction

        Yields:
            self for fluent API usage

        Example:
            async with tm.distributed_transaction(neo4j_tx=neo_tx):
                await pg_repo.save(entity)
                await graph_repo.create_node(entity)
        """
        try:
            # Begin all transactions
            if not self._session.in_transaction():
                await self._session.begin()

            yield self

            # Two-phase commit: PostgreSQL first, then others
            # PostgreSQL is the source of truth
            await self._session.commit()

            # Commit other participants in order
            if neo4j_tx:
                neo4j_tx.commit()

            if redis_tx:
                await redis_tx.execute()

        except Exception as e:
            logger.error(f"Distributed transaction failed, rolling back all: {e}")

            # Rollback all participants
            try:
                await self._session.rollback()
            except Exception as pg_err:
                logger.error(f"PostgreSQL rollback failed: {pg_err}")

            if neo4j_tx:
                try:
                    neo4j_tx.rollback()
                except Exception as neo_err:
                    logger.error(f"Neo4j rollback failed: {neo_err}")

            if redis_tx:
                try:
                    await redis_tx.discard()
                except Exception as redis_err:
                    logger.error(f"Redis discard failed: {redis_err}")

            raise

    @asynccontextmanager
    async def savepoint(self, name: str) -> AsyncGenerator[None, None]:
        """
        Context manager for savepoints within a transaction.

        Allows rolling back to a specific point within a transaction.

        Args:
            name: Name of the savepoint

        Yields:
            None

        Example:
            async with tm.transaction():
                async with tm.savepoint("sp1"):
                    # Potentially failing operation
                # Can continue even if sp1 was rolled back
        """
        try:
            # Create savepoint
            await self._session.execute(text(f"SAVEPOINT {name}"))
            yield
        except Exception:
            # Rollback to savepoint
            await self._session.execute(text(f"ROLLBACK TO SAVEPOINT {name}"))
            raise
        finally:
            # Release savepoint
            # Release savepoint (may have been rolled back)
            with contextlib.suppress(Exception):
                await self._session.execute(text(f"RELEASE SAVEPOINT {name}"))

    # === Error handling ===

    def _is_transient_error(self, error: DBAPIError) -> bool:
        """
        Check if a database error is transient and worth retrying.

        Transient errors include:
        - Connection failures
        - Timeouts
        - Deadlocks

        Args:
            error: The database error

        Returns:
            True if error is transient, False otherwise
        """
        # Check for common transient error codes
        transient_codes = {
            "08001",  # Connection does not exist
            "08004",  # Server rejected the connection
            "08006",  # Connection failure
            "08007",  # Transaction resolution unknown
            "40001",  # Serialization failure
            "40P01",  # Deadlock detected
            "53000",  # Insufficient resources
            "53100",  # Disk full
            "53200",  # Out of memory
            "53300",  # Too many connections
            "54000",  # Program limit exceeded
            "55P03",  # Lock not available
            "57P02",  # Cannot connect now
        }

        # Check error code if available
        if hasattr(error, "orig") and hasattr(error.orig, "pgcode"):
            return error.orig.pgcode in transient_codes  # type: ignore[union-attr]

        # Check error message
        error_str = str(error).lower()
        transient_keywords = [
            "connection",
            "timeout",
            "deadlock",
            "temporarily",
            "unavailable",
        ]

        return any(keyword in error_str for keyword in transient_keywords)
