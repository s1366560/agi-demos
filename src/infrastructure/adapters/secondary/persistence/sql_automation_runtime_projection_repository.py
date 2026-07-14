"""SQLAlchemy CAS projector for Agent-backed automation runs."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.automation_runtime_projection_service import (
    AutomationRuntimeIdentity,
    AutomationRuntimeProjection,
    AutomationRuntimeProjectionConflictError,
    AutomationRuntimeTerminal,
)
from src.domain.model.cron.value_objects import CronRunStatus
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.models import (
    CronJobModel,
    CronJobRunModel,
    CronOperationModel,
)

_NON_TERMINAL_RUN_STATUSES = frozenset(
    {
        CronRunStatus.QUEUED.value,
        CronRunStatus.RUNNING.value,
        CronRunStatus.WAITING_HUMAN.value,
    }
)
_TERMINAL_RUN_STATUSES = frozenset(
    {
        CronRunStatus.SUCCESS.value,
        CronRunStatus.FAILED.value,
        CronRunStatus.TIMEOUT.value,
        CronRunStatus.CANCELLED.value,
        CronRunStatus.SKIPPED.value,
    }
)


class SqlAutomationRuntimeProjectionRepository:
    """Project runtime facts inside the caller-owned transaction."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__()
        self._session = session

    async def mark_running(
        self,
        *,
        identity: AutomationRuntimeIdentity,
        observed_at: datetime,
    ) -> AutomationRuntimeProjection:
        run = await self._locked_run(identity)
        if run is None:
            return AutomationRuntimeProjection(matched=False)
        if run.status in _TERMINAL_RUN_STATUSES:
            return AutomationRuntimeProjection(
                matched=True,
                run_status=run.status,
                duplicate=True,
            )
        if run.status not in _NON_TERMINAL_RUN_STATUSES:
            raise AutomationRuntimeProjectionConflictError(
                f"unsupported automation run status: {run.status}"
            )

        duplicate = run.status == CronRunStatus.RUNNING.value
        if run.status == CronRunStatus.QUEUED.value:
            run.started_at = observed_at
        run.status = CronRunStatus.RUNNING.value
        run.conversation_id = identity.conversation_id
        await self._session.flush()
        return AutomationRuntimeProjection(
            matched=True,
            run_status=run.status,
            duplicate=duplicate,
        )

    async def project_terminal(
        self,
        *,
        identity: AutomationRuntimeIdentity,
        terminal: AutomationRuntimeTerminal,
    ) -> AutomationRuntimeProjection:
        run = await self._locked_run(identity)
        if run is None:
            return AutomationRuntimeProjection(matched=False)

        desired_status = terminal.outcome.value
        duplicate = run.status == desired_status
        if run.status in _TERMINAL_RUN_STATUSES and not duplicate:
            raise AutomationRuntimeProjectionConflictError(
                f"automation run is already terminal with status: {run.status}"
            )
        if run.status not in _NON_TERMINAL_RUN_STATUSES and not duplicate:
            raise AutomationRuntimeProjectionConflictError(
                f"unsupported automation run status: {run.status}"
            )

        if not duplicate:
            run.status = desired_status
            run.finished_at = terminal.observed_at
            run.duration_ms = round(terminal.execution_time_ms)
            run.error_message = terminal.outcome.error_code
            run.conversation_id = identity.conversation_id
            run.result_summary = {
                "conversation_id": identity.conversation_id,
                "runtime_execution_id": identity.runtime_execution_id,
                "runtime_status": desired_status,
                "event_count": terminal.event_count,
                "execution_time_ms": terminal.execution_time_ms,
                **(
                    {"error_code": terminal.outcome.error_code}
                    if terminal.outcome.error_code
                    else {}
                ),
            }

        operation = await self._locked_operation(identity)
        delivery_ack_pending = operation is None
        operation_status = operation.status if operation is not None else None
        if operation is not None and operation.status == "waiting_runtime":
            operation.status = "completed"
            operation.result_json = {
                **dict(operation.result_json or {}),
                "runtime_execution_id": identity.runtime_execution_id,
                "runtime_status": desired_status,
                "event_count": terminal.event_count,
                **(
                    {"error_code": terminal.outcome.error_code}
                    if terminal.outcome.error_code
                    else {}
                ),
            }
            operation.last_error_code = None
            operation.last_error_redacted = None
            operation.next_attempt_at = None
            operation.lease_owner = None
            operation.lease_token = None
            operation.lease_expires_at = None
            operation.completed_at = terminal.observed_at
            operation.updated_at = terminal.observed_at
            operation_status = operation.status
            delivery_ack_pending = False
        elif operation is not None and operation.status == "completed":
            delivery_ack_pending = False
        elif operation is not None:
            delivery_ack_pending = True

        await self._session.flush()
        return AutomationRuntimeProjection(
            matched=True,
            run_status=run.status,
            operation_status=operation_status,
            duplicate=duplicate,
            delivery_ack_pending=delivery_ack_pending,
        )

    async def mark_waiting_human(
        self,
        *,
        identity: AutomationRuntimeIdentity,
        observed_at: datetime,
    ) -> AutomationRuntimeProjection:
        run = await self._locked_run(identity)
        if run is None:
            return AutomationRuntimeProjection(matched=False)
        if run.status in _TERMINAL_RUN_STATUSES:
            return AutomationRuntimeProjection(
                matched=True,
                run_status=run.status,
                duplicate=True,
            )
        if run.status not in _NON_TERMINAL_RUN_STATUSES:
            raise AutomationRuntimeProjectionConflictError(
                f"unsupported automation run status: {run.status}"
            )

        duplicate = run.status == CronRunStatus.WAITING_HUMAN.value
        if run.status == CronRunStatus.QUEUED.value:
            run.started_at = observed_at
        run.status = CronRunStatus.WAITING_HUMAN.value
        run.conversation_id = identity.conversation_id
        await self._session.flush()
        return AutomationRuntimeProjection(
            matched=True,
            run_status=run.status,
            duplicate=duplicate,
        )

    async def _locked_run(
        self,
        identity: AutomationRuntimeIdentity,
    ) -> CronJobRunModel | None:
        statement = (
            select(CronJobRunModel)
            .join(CronJobModel, CronJobModel.id == CronJobRunModel.job_id)
            .where(
                CronJobRunModel.runtime_execution_id == identity.runtime_execution_id,
                CronJobRunModel.project_id == identity.project_id,
                CronJobModel.project_id == identity.project_id,
                CronJobModel.tenant_id == identity.tenant_id,
            )
            .with_for_update()
        )
        result = await self._session.execute(refresh_select_statement(statement))
        return result.scalar_one_or_none()

    async def _locked_operation(
        self,
        identity: AutomationRuntimeIdentity,
    ) -> CronOperationModel | None:
        statement = (
            select(CronOperationModel)
            .where(
                CronOperationModel.tenant_id == identity.tenant_id,
                CronOperationModel.project_id == identity.project_id,
                CronOperationModel.run_id == identity.runtime_execution_id,
                CronOperationModel.operation_kind == "execute_run",
            )
            .with_for_update()
        )
        result = await self._session.execute(refresh_select_statement(statement))
        return result.scalar_one_or_none()
