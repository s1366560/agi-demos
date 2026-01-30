"""Repository port for PlanSnapshot entities.

This module defines the repository interface for plan snapshot persistence.
"""

from abc import ABC, abstractmethod
from typing import Optional

from src.domain.model.agent.plan_snapshot import PlanSnapshot


class PlanSnapshotRepository(ABC):
    """Repository for PlanSnapshot entities.

    Provides CRUD operations for plan snapshots used for rollback functionality.
    """

    @abstractmethod
    async def save(self, snapshot: PlanSnapshot) -> PlanSnapshot:
        """Save a snapshot.

        Args:
            snapshot: The snapshot to save

        Returns:
            The saved snapshot
        """
        ...

    @abstractmethod
    async def find_by_id(self, snapshot_id: str) -> Optional[PlanSnapshot]:
        """Find a snapshot by its ID.

        Args:
            snapshot_id: The snapshot ID

        Returns:
            The snapshot if found, None otherwise
        """
        ...

    @abstractmethod
    async def find_by_execution(
        self,
        execution_id: str,
    ) -> list[PlanSnapshot]:
        """Find snapshots for an execution.

        Args:
            execution_id: The execution ID

        Returns:
            List of snapshots
        """
        ...

    @abstractmethod
    async def find_latest_by_execution(
        self,
        execution_id: str,
    ) -> Optional[PlanSnapshot]:
        """Find latest snapshot for an execution.

        Args:
            execution_id: The execution ID

        Returns:
            The latest snapshot if found, None otherwise
        """
        ...

    @abstractmethod
    async def delete_by_execution(self, execution_id: str) -> int:
        """Delete all snapshots for an execution.

        Args:
            execution_id: The execution ID

        Returns:
            Number of snapshots deleted
        """
        ...

    @abstractmethod
    async def delete(self, snapshot_id: str) -> bool:
        """Delete a snapshot by ID.

        Args:
            snapshot_id: The snapshot ID to delete

        Returns:
            True if deleted, False if not found
        """
        ...
