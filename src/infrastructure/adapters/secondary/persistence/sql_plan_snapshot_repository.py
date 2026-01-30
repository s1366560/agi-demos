"""SQL implementation of PlanSnapshotRepository.

This module provides the SQLAlchemy-based implementation of the PlanSnapshotRepository
port for persisting plan snapshot entities.
"""

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent.plan_snapshot import PlanSnapshot, StepState
from src.domain.ports.repositories.plan_snapshot_repository import (
    PlanSnapshotRepository,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    PlanSnapshotRecord,
)


class SQLPlanSnapshotRepository(PlanSnapshotRepository):
    """SQLAlchemy implementation of PlanSnapshotRepository."""

    def __init__(self, db: AsyncSession):
        """Initialize with database session.

        Args:
            db: Async SQLAlchemy session
        """
        self._db = db

    def _to_domain(self, record: PlanSnapshotRecord) -> PlanSnapshot:
        """Convert database record to domain entity.

        Args:
            record: Database record

        Returns:
            Domain entity
        """
        step_states = {
            k: StepState(**v) for k, v in record.step_states.items()
        }
        return PlanSnapshot(
            id=record.id,
            plan_id=record.execution_id,  # Map execution_id to plan_id
            name=record.name,
            step_states=step_states,
            description=record.description,
            auto_created=record.auto_created,
            snapshot_type=record.snapshot_type,
            created_at=record.created_at,
        )

    def _to_record(self, snapshot: PlanSnapshot, execution_id: str) -> PlanSnapshotRecord:
        """Convert domain entity to database record.

        Args:
            snapshot: Domain entity
            execution_id: The execution ID (since snapshot uses plan_id)

        Returns:
            Database record
        """
        step_states = {
            k: {
                "status": v.status,
                "result": v.result,
                "error": v.error,
                "started_at": v.started_at.isoformat() if v.started_at else None,
                "completed_at": v.completed_at.isoformat() if v.completed_at else None,
            }
            for k, v in snapshot.step_states.items()
        }
        return PlanSnapshotRecord(
            id=snapshot.id,
            execution_id=execution_id,
            name=snapshot.name,
            description=snapshot.description,
            step_states=step_states,
            auto_created=snapshot.auto_created,
            snapshot_type=snapshot.snapshot_type,
            metadata_json={},  # Additional metadata if needed
            created_at=snapshot.created_at,
        )

    async def save(self, snapshot: PlanSnapshot) -> PlanSnapshot:
        """Save a snapshot.

        Args:
            snapshot: The snapshot to save

        Returns:
            The saved snapshot
        """
        # For PlanExecution, plan_id is actually the execution_id
        record = self._to_record(snapshot, snapshot.plan_id)
        self._db.add(record)
        await self._db.commit()
        await self._db.refresh(record)
        return self._to_domain(record)

    async def find_by_id(self, snapshot_id: str) -> Optional[PlanSnapshot]:
        """Find a snapshot by its ID.

        Args:
            snapshot_id: The snapshot ID

        Returns:
            The snapshot if found, None otherwise
        """
        record = await self._db.get(PlanSnapshotRecord, snapshot_id)
        return self._to_domain(record) if record else None

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
        result = await self._db.execute(
            select(PlanSnapshotRecord)
            .where(PlanSnapshotRecord.execution_id == execution_id)
            .order_by(PlanSnapshotRecord.created_at.desc())
        )
        records = result.scalars().all()
        return [self._to_domain(r) for r in records]

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
        result = await self._db.execute(
            select(PlanSnapshotRecord)
            .where(PlanSnapshotRecord.execution_id == execution_id)
            .order_by(PlanSnapshotRecord.created_at.desc())
            .limit(1)
        )
        record = result.scalar_one_or_none()
        return self._to_domain(record) if record else None

    async def delete_by_execution(self, execution_id: str) -> int:
        """Delete all snapshots for an execution.

        Args:
            execution_id: The execution ID

        Returns:
            Number of snapshots deleted
        """
        result = await self._db.execute(
            select(PlanSnapshotRecord).where(
                PlanSnapshotRecord.execution_id == execution_id
            )
        )
        records = result.scalars().all()
        count = len(records)

        for record in records:
            await self._db.delete(record)

        await self._db.commit()
        return count

    async def delete(self, snapshot_id: str) -> bool:
        """Delete a snapshot by ID.

        Args:
            snapshot_id: The snapshot ID to delete

        Returns:
            True if deleted, False if not found
        """
        record = await self._db.get(PlanSnapshotRecord, snapshot_id)
        if not record:
            return False

        await self._db.delete(record)
        await self._db.commit()
        return True
