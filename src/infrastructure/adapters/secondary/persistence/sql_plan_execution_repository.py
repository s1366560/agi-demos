"""SQL implementation of PlanExecutionRepository.

This module provides the SQLAlchemy-based implementation of the PlanExecutionRepository
port for persisting unified plan execution entities.
"""

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent.plan_execution import (
    ExecutionMode,
    ExecutionStatus,
    ExecutionStep,
    PlanExecution,
)
from src.domain.ports.repositories.plan_execution_repository import (
    PlanExecutionRepository,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    PlanExecutionRecord,
)


class SQLPlanExecutionRepository(PlanExecutionRepository):
    """SQLAlchemy implementation of PlanExecutionRepository."""

    def __init__(self, db: AsyncSession):
        """Initialize with database session.

        Args:
            db: Async SQLAlchemy session
        """
        self._db = db

    def _to_domain(self, record: PlanExecutionRecord) -> PlanExecution:
        """Convert database record to domain entity.

        Args:
            record: Database record

        Returns:
            Domain entity
        """
        return PlanExecution(
            id=record.id,
            conversation_id=record.conversation_id,
            plan_id=record.plan_id,
            steps=[ExecutionStep.from_dict(s) for s in record.steps],
            current_step_index=record.current_step_index,
            completed_step_indices=record.completed_step_indices,
            failed_step_indices=record.failed_step_indices,
            status=ExecutionStatus(record.status),
            execution_mode=ExecutionMode(record.execution_mode),
            max_parallel_steps=record.max_parallel_steps,
            reflection_enabled=record.reflection_enabled,
            max_reflection_cycles=record.max_reflection_cycles,
            current_reflection_cycle=record.current_reflection_cycle,
            workflow_pattern_id=record.workflow_pattern_id,
            metadata=record.metadata_json,
            created_at=record.created_at,
            updated_at=record.updated_at,
            started_at=record.started_at,
            completed_at=record.completed_at,
        )

    def _to_record(self, execution: PlanExecution) -> PlanExecutionRecord:
        """Convert domain entity to database record.

        Args:
            execution: Domain entity

        Returns:
            Database record
        """
        return PlanExecutionRecord(
            id=execution.id,
            conversation_id=execution.conversation_id,
            plan_id=execution.plan_id,
            steps=[s.to_dict() for s in execution.steps],
            current_step_index=execution.current_step_index,
            completed_step_indices=execution.completed_step_indices,
            failed_step_indices=execution.failed_step_indices,
            status=execution.status.value,
            execution_mode=execution.execution_mode.value,
            max_parallel_steps=execution.max_parallel_steps,
            reflection_enabled=execution.reflection_enabled,
            max_reflection_cycles=execution.max_reflection_cycles,
            current_reflection_cycle=execution.current_reflection_cycle,
            workflow_pattern_id=execution.workflow_pattern_id,
            metadata_json=execution.metadata,
            created_at=execution.created_at,
            updated_at=execution.updated_at,
            started_at=execution.started_at,
            completed_at=execution.completed_at,
        )

    async def save(self, execution: PlanExecution) -> PlanExecution:
        """Save or update a plan execution.

        Args:
            execution: The plan execution to save

        Returns:
            The saved plan execution
        """
        record = await self._db.get(PlanExecutionRecord, execution.id)

        if record:
            # Update existing record
            record.steps = [s.to_dict() for s in execution.steps]
            record.current_step_index = execution.current_step_index
            record.completed_step_indices = execution.completed_step_indices
            record.failed_step_indices = execution.failed_step_indices
            record.status = execution.status.value
            record.execution_mode = execution.execution_mode.value
            record.max_parallel_steps = execution.max_parallel_steps
            record.reflection_enabled = execution.reflection_enabled
            record.max_reflection_cycles = execution.max_reflection_cycles
            record.current_reflection_cycle = execution.current_reflection_cycle
            record.workflow_pattern_id = execution.workflow_pattern_id
            record.metadata_json = execution.metadata
            record.updated_at = execution.updated_at
            record.started_at = execution.started_at
            record.completed_at = execution.completed_at
        else:
            # Create new record
            record = self._to_record(execution)
            self._db.add(record)

        await self._db.commit()
        await self._db.refresh(record)
        return self._to_domain(record)

    async def find_by_id(self, execution_id: str) -> Optional[PlanExecution]:
        """Find a plan execution by its ID.

        Args:
            execution_id: The execution ID

        Returns:
            The plan execution if found, None otherwise
        """
        record = await self._db.get(PlanExecutionRecord, execution_id)
        return self._to_domain(record) if record else None

    async def find_by_plan_id(self, plan_id: str) -> list[PlanExecution]:
        """Find all executions for a plan.

        Args:
            plan_id: The plan ID

        Returns:
            List of plan executions
        """
        result = await self._db.execute(
            select(PlanExecutionRecord)
            .where(PlanExecutionRecord.plan_id == plan_id)
            .order_by(PlanExecutionRecord.created_at.desc())
        )
        records = result.scalars().all()
        return [self._to_domain(r) for r in records]

    async def find_by_conversation(
        self,
        conversation_id: str,
        status: Optional[ExecutionStatus] = None,
    ) -> list[PlanExecution]:
        """Find executions for a conversation.

        Args:
            conversation_id: The conversation ID
            status: Optional status filter

        Returns:
            List of plan executions
        """
        query = select(PlanExecutionRecord).where(
            PlanExecutionRecord.conversation_id == conversation_id
        )

        if status:
            query = query.where(PlanExecutionRecord.status == status.value)

        query = query.order_by(PlanExecutionRecord.created_at.desc())

        result = await self._db.execute(query)
        records = result.scalars().all()
        return [self._to_domain(r) for r in records]

    async def find_active_by_conversation(
        self,
        conversation_id: str,
    ) -> Optional[PlanExecution]:
        """Find active (running/paused) execution for a conversation.

        Args:
            conversation_id: The conversation ID

        Returns:
            The active plan execution if found, None otherwise
        """
        result = await self._db.execute(
            select(PlanExecutionRecord)
            .where(PlanExecutionRecord.conversation_id == conversation_id)
            .where(PlanExecutionRecord.status.in_(["running", "paused"]))
            .order_by(PlanExecutionRecord.created_at.desc())
            .limit(1)
        )
        record = result.scalar_one_or_none()
        return self._to_domain(record) if record else None

    async def update_status(
        self,
        execution_id: str,
        status: ExecutionStatus,
    ) -> Optional[PlanExecution]:
        """Update execution status.

        Args:
            execution_id: The execution ID
            status: New status

        Returns:
            Updated plan execution if found, None otherwise
        """
        record = await self._db.get(PlanExecutionRecord, execution_id)
        if not record:
            return None

        record.status = status.value
        await self._db.commit()
        await self._db.refresh(record)
        return self._to_domain(record)

    async def update_step(
        self,
        execution_id: str,
        step_index: int,
        step_data: dict,
    ) -> Optional[PlanExecution]:
        """Update a step within an execution.

        Args:
            execution_id: The execution ID
            step_index: Index of the step to update
            step_data: Updated step data

        Returns:
            Updated plan execution if found, None otherwise
        """
        record = await self._db.get(PlanExecutionRecord, execution_id)
        if not record:
            return None

        # Update the specific step
        if 0 <= step_index < len(record.steps):
            record.steps[step_index] = step_data
            await self._db.commit()
            await self._db.refresh(record)
            return self._to_domain(record)

        return None

    async def delete(self, execution_id: str) -> bool:
        """Delete an execution.

        Args:
            execution_id: The execution ID to delete

        Returns:
            True if deleted, False if not found
        """
        record = await self._db.get(PlanExecutionRecord, execution_id)
        if not record:
            return False

        await self._db.delete(record)
        await self._db.commit()
        return True
