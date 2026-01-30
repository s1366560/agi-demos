"""ExecutePlanUseCase for unified plan execution.

This use case executes a PlanExecution with support for reflection,
adjustments, and snapshot-based rollback.
"""

import asyncio
from typing import Any, Callable, Optional

from src.domain.model.agent.plan_execution import ExecutionStatus, PlanExecution
from src.domain.model.agent.plan_snapshot import PlanSnapshot
from src.domain.ports.repositories.plan_execution_repository import (
    PlanExecutionRepository,
)
from src.domain.ports.repositories.plan_snapshot_repository import (
    PlanSnapshotRepository,
)
from src.infrastructure.agent.planning.plan_mode_orchestrator import (
    PlanModeOrchestrator,
)


class ExecutePlanUseCase:
    """Use case for executing a plan.

    This use case coordinates the execution of a plan with support for:
    - Step-by-step execution
    - Reflection and adjustment cycles
    - Snapshot-based rollback
    - Pause/resume functionality
    """

    def __init__(
        self,
        plan_execution_repository: PlanExecutionRepository,
        plan_snapshot_repository: PlanSnapshotRepository,
        plan_mode_orchestrator: PlanModeOrchestrator,
    ):
        """Initialize the use case.

        Args:
            plan_execution_repository: Repository for plan execution persistence
            plan_snapshot_repository: Repository for plan snapshots
            plan_mode_orchestrator: Orchestrator for plan execution workflow
        """
        self._execution_repo = plan_execution_repository
        self._snapshot_repo = plan_snapshot_repository
        self._orchestrator = plan_mode_orchestrator

    async def execute(
        self,
        execution_id: str,
        event_emitter: Optional[Callable[[dict], None]] = None,
        abort_signal: Optional[asyncio.Event] = None,
    ) -> PlanExecution:
        """Execute a plan.

        Args:
            execution_id: The execution ID
            event_emitter: Optional callback for emitting events
            abort_signal: Optional signal for aborting execution

        Returns:
            The completed plan execution
        """
        # Load the plan execution
        execution = await self._execution_repo.find_by_id(execution_id)
        if not execution:
            raise ValueError(f"Plan execution not found: {execution_id}")

        # Mark as running
        execution = execution.mark_running()
        execution = await self._execution_repo.save(execution)

        # Create initial snapshot
        await self._create_snapshot(execution, "Initial state", "pre_execution")

        try:
            # Execute using orchestrator
            final_execution = await self._orchestrator.execute_plan(
                plan=self._convert_to_execution_plan(execution),
                abort_signal=abort_signal or asyncio.Event(),
            )

            # Update execution with results
            execution = await self._execution_repo.find_by_id(execution_id)
            if final_execution.status.value == "completed":
                execution = execution.mark_completed()
            elif final_execution.status.value == "failed":
                execution = execution.mark_failed(
                    final_execution.error or "Execution failed"
                )
            elif final_execution.status.value == "cancelled":
                execution = execution.mark_cancelled()

            execution = await self._execution_repo.save(execution)

            # Create final snapshot
            await self._create_snapshot(execution, "Final state", "post_execution")

            return execution

        except Exception as e:
            # Mark as failed on error
            execution = execution.mark_failed(str(e))
            execution = await self._execution_repo.save(execution)
            raise

    async def pause(self, execution_id: str) -> PlanExecution:
        """Pause a running execution.

        Args:
            execution_id: The execution ID

        Returns:
            The paused plan execution
        """
        execution = await self._execution_repo.find_by_id(execution_id)
        if not execution:
            raise ValueError(f"Plan execution not found: {execution_id}")

        if execution.status != ExecutionStatus.RUNNING:
            raise ValueError(f"Cannot pause execution with status: {execution.status}")

        execution = execution.mark_paused()
        execution = await self._execution_repo.save(execution)

        # Create snapshot before pausing
        await self._create_snapshot(execution, "Paused state", "paused")

        return execution

    async def resume(
        self,
        execution_id: str,
        event_emitter: Optional[Callable[[dict], None]] = None,
    ) -> PlanExecution:
        """Resume a paused execution.

        Args:
            execution_id: The execution ID
            event_emitter: Optional callback for emitting events

        Returns:
            The resumed plan execution
        """
        execution = await self._execution_repo.find_by_id(execution_id)
        if not execution:
            raise ValueError(f"Plan execution not found: {execution_id}")

        if execution.status != ExecutionStatus.PAUSED:
            raise ValueError(f"Cannot resume execution with status: {execution.status}")

        execution = execution.mark_running()
        execution = await self._execution_repo.save(execution)

        # Continue execution
        return await self.execute(execution_id, event_emitter)

    async def rollback(
        self,
        execution_id: str,
        snapshot_id: Optional[str] = None,
    ) -> PlanExecution:
        """Rollback execution to a snapshot.

        Args:
            execution_id: The execution ID
            snapshot_id: Optional specific snapshot to rollback to.
                        If not provided, uses the latest snapshot.

        Returns:
            The rolled back plan execution
        """
        execution = await self._execution_repo.find_by_id(execution_id)
        if not execution:
            raise ValueError(f"Plan execution not found: {execution_id}")

        # Get snapshot
        if snapshot_id:
            snapshot = await self._snapshot_repo.find_by_id(snapshot_id)
        else:
            snapshot = await self._snapshot_repo.find_latest_by_execution(execution_id)

        if not snapshot:
            raise ValueError(f"No snapshot found for execution: {execution_id}")

        # Apply snapshot state to execution
        # This would restore step states from the snapshot
        # Implementation depends on how step states are stored in the snapshot

        # Reset to running state
        execution = execution.mark_running()
        execution = await self._execution_repo.save(execution)

        return execution

    async def _create_snapshot(
        self,
        execution: PlanExecution,
        name: str,
        snapshot_type: str,
    ) -> PlanSnapshot:
        """Create a snapshot of the current execution state.

        Args:
            execution: The plan execution
            name: Snapshot name
            snapshot_type: Type of snapshot

        Returns:
            The created snapshot
        """
        from src.domain.model.agent.plan_snapshot import StepState

        step_states = {}
        for step in execution.steps:
            step_states[step.step_id] = StepState(
                status=step.status.value,
                result=step.result,
                error=step.error,
                started_at=step.started_at,
                completed_at=step.completed_at,
            )

        snapshot = PlanSnapshot(
            plan_id=execution.id,  # Use execution_id as plan_id for snapshots
            name=name,
            step_states=step_states,
            description=f"Snapshot at {execution.status.value}",
            auto_created=True,
            snapshot_type=snapshot_type,
        )

        return await self._snapshot_repo.save(snapshot)

    def _convert_to_execution_plan(
        self,
        plan_execution: PlanExecution,
    ) -> Any:
        """Convert PlanExecution to ExecutionPlan for orchestrator.

        Args:
            plan_execution: The plan execution

        Returns:
            ExecutionPlan compatible with orchestrator
        """
        from src.domain.model.agent.execution_plan import (
            ExecutionPlan,
            ExecutionStep as OldExecutionStep,
            ExecutionStepStatus,
        )

        # Convert steps to old format for compatibility
        old_steps = []
        for step in plan_execution.steps:
            old_step = OldExecutionStep(
                step_id=step.step_id,
                description=step.description,
                tool_name=step.tool_name,
                tool_input=step.tool_input,
                dependencies=step.dependencies,
                status=ExecutionStepStatus(step.status.value),
                result=step.result,
                error=step.error,
                started_at=step.started_at,
                completed_at=step.completed_at,
            )
            old_steps.append(old_step)

        return ExecutionPlan(
            id=plan_execution.id,
            conversation_id=plan_execution.conversation_id,
            user_query="",  # Would be stored in metadata
            steps=old_steps,
            status=ExecutionPlan.ExecutionPlanStatus(plan_execution.status.value),
            reflection_enabled=plan_execution.reflection_enabled,
            max_reflection_cycles=plan_execution.max_reflection_cycles,
        )
