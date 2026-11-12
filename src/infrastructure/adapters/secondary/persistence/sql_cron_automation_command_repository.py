"""Atomic SQL implementation of the durable automation command boundary."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.automation_command_service import (
    AutomationActor,
    AutomationCommandIdempotencyConflictError,
    AutomationCommandRevisionConflictError,
    AutomationCommandTargetNotFoundError,
    AutomationJobReceipt,
    AutomationRunReceipt,
    CreateAutomationJobCommand,
    QueueManualRunCommand,
)
from src.domain.model.cron.value_objects import CronDelivery, CronRunStatus, TriggerType
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.models import (
    CronJobModel,
    CronJobRunModel,
    CronOperationModel,
    CronRequestReceiptModel,
)

_RECEIPT_TTL = timedelta(hours=24)


class SqlCronAutomationCommandRepository:
    """Persist receipt, run, and operation rows in one caller-owned transaction."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__()
        self._session = session

    async def queue_manual_run(
        self,
        *,
        actor: AutomationActor,
        command: QueueManualRunCommand,
        request_hash: str,
    ) -> AutomationRunReceipt:
        now = datetime.now(UTC)
        await self._delete_expired_receipt(actor=actor, command=command, now=now)

        existing = await self._find_receipt(actor=actor, command=command)
        if existing is not None:
            return self._replay_receipt(existing, request_hash=request_hash)

        job = await self._find_locked_job(actor=actor, job_id=command.job_id)
        if job is None:
            raise AutomationCommandTargetNotFoundError("Automation job not found in project scope")
        if int(job.revision) != command.expected_revision:
            raise AutomationCommandRevisionConflictError(
                expected_revision=command.expected_revision,
                current_revision=int(job.revision),
            )

        # Recheck after taking the job lock so same-job requests serialize before
        # reserving the unique idempotency receipt.
        existing = await self._find_receipt(actor=actor, command=command)
        if existing is not None:
            return self._replay_receipt(existing, request_hash=request_hash)

        run_id = str(uuid.uuid4())
        operation_id = str(uuid.uuid4())
        receipt_id = str(uuid.uuid4())
        # The Agent runtime uses message_id as its authoritative execution ID.
        # Reusing run_id makes dispatch retries deterministic and directly
        # correlates terminal events without a second lookup key.
        runtime_execution_id = run_id
        timeout_seconds = max(1, int(job.timeout_seconds or 300))
        delete_after_run = bool(job.delete_after_run)
        one_shot = job.schedule_type == "at"
        max_retries = max(1, int(job.max_retries))
        response: dict[str, object] = {
            "receipt_id": receipt_id,
            "operation_id": operation_id,
            "run_id": run_id,
            "runtime_execution_id": runtime_execution_id,
            "job_id": job.id,
            "job_revision": int(job.revision),
            "status": CronRunStatus.QUEUED.value,
        }
        receipt = CronRequestReceiptModel(
            id=receipt_id,
            tenant_id=actor.tenant_id,
            project_id=actor.project_id,
            actor_user_id=actor.user_id,
            actor_api_key_id=actor.api_key_id,
            operation="run_now",
            idempotency_key=command.idempotency_key,
            request_hash=request_hash,
            resource_kind="cron_run",
            resource_id=run_id,
            operation_id=operation_id,
            http_status=202,
            response_json_redacted=response,
            created_at=now,
            expires_at=now + _RECEIPT_TTL,
        )

        try:
            async with self._session.begin_nested():
                self._session.add(receipt)
                await self._session.flush()
        except IntegrityError:
            existing = await self._find_receipt(actor=actor, command=command)
            if existing is None:
                raise
            return self._replay_receipt(existing, request_hash=request_hash)

        self._session.add_all(
            [
                CronJobRunModel(
                    id=run_id,
                    job_id=job.id,
                    project_id=actor.project_id,
                    status=CronRunStatus.QUEUED.value,
                    trigger_type=TriggerType.MANUAL.value,
                    accepted_at=now,
                    started_at=now,
                    job_revision=int(job.revision),
                    schedule_revision=int(job.schedule_revision),
                    runtime_execution_id=runtime_execution_id,
                    idempotency_key=command.idempotency_key,
                    request_receipt_id=receipt_id,
                    conversation_id=command.conversation_id,
                    result_summary={},
                ),
                CronOperationModel(
                    id=operation_id,
                    tenant_id=actor.tenant_id,
                    project_id=actor.project_id,
                    job_id=job.id,
                    job_revision=int(job.revision),
                    schedule_revision=None,
                    operation_kind="execute_run",
                    run_id=run_id,
                    trigger_type=TriggerType.MANUAL.value,
                    input_json={
                        "conversation_id": command.conversation_id,
                        "runtime_execution_id": runtime_execution_id,
                        "timeout_seconds": timeout_seconds,
                        "delete_after_run": delete_after_run,
                        "one_shot": one_shot,
                        "max_retries": max_retries,
                    },
                    status="pending",
                    attempt_count=0,
                    max_attempts=max(1, int(job.max_retries) + 1),
                    next_attempt_at=now,
                    actor_user_id=actor.user_id,
                    actor_api_key_id=actor.api_key_id,
                    request_receipt_id=receipt_id,
                    result_json={},
                    created_at=now,
                    updated_at=now,
                ),
            ]
        )
        await self._session.flush()
        return self._receipt_from_response(response, duplicate=False)

    async def create_job(
        self,
        *,
        actor: AutomationActor,
        command: CreateAutomationJobCommand,
        request_hash: str,
    ) -> AutomationJobReceipt:
        now = datetime.now(UTC)
        await self._delete_expired_receipt(
            actor=actor, command=command, now=now, operation="create_job"
        )
        existing = await self._find_receipt(actor=actor, command=command, operation="create_job")
        if existing is not None:
            return self._replay_job_receipt(existing, request_hash=request_hash)

        job_id = str(uuid.uuid4())
        operation_id = str(uuid.uuid4())
        receipt_id = str(uuid.uuid4())
        delivery = command.delivery or CronDelivery.none()
        response: dict[str, object] = {
            "receipt_id": receipt_id,
            "operation_id": operation_id,
            "job_id": job_id,
            "job_revision": 1,
            "status": "persisted",
        }
        receipt = CronRequestReceiptModel(
            id=receipt_id,
            tenant_id=actor.tenant_id,
            project_id=actor.project_id,
            actor_user_id=actor.user_id,
            actor_api_key_id=actor.api_key_id,
            operation="create_job",
            idempotency_key=command.idempotency_key,
            request_hash=request_hash,
            resource_kind="cron_job",
            resource_id=job_id,
            operation_id=operation_id,
            http_status=201,
            response_json_redacted=response,
            created_at=now,
            expires_at=now + _RECEIPT_TTL,
        )
        try:
            async with self._session.begin_nested():
                self._session.add(receipt)
                await self._session.flush()
        except IntegrityError:
            existing = await self._find_receipt(
                actor=actor, command=command, operation="create_job"
            )
            if existing is None:
                raise
            return self._replay_job_receipt(existing, request_hash=request_hash)

        self._session.add_all(
            [
                CronJobModel(
                    id=job_id,
                    project_id=actor.project_id,
                    tenant_id=actor.tenant_id,
                    name=command.name.strip(),
                    description=command.description,
                    enabled=command.enabled,
                    delete_after_run=command.delete_after_run,
                    revision=1,
                    schedule_revision=1,
                    schedule_type=command.schedule.kind.value,
                    schedule_config=command.schedule.config,
                    payload_type=command.payload.kind.value,
                    payload_config=command.payload.config,
                    delivery_type=delivery.kind.value,
                    delivery_config=delivery.config,
                    conversation_mode=command.conversation_mode.value,
                    conversation_id=command.conversation_id,
                    timezone=command.timezone,
                    stagger_seconds=command.stagger_seconds,
                    timeout_seconds=command.timeout_seconds,
                    max_retries=command.max_retries,
                    state={},
                    created_by=actor.user_id,
                    created_at=now,
                ),
                CronOperationModel(
                    id=operation_id,
                    tenant_id=actor.tenant_id,
                    project_id=actor.project_id,
                    job_id=job_id,
                    job_revision=1,
                    schedule_revision=1,
                    operation_kind="record_create",
                    run_id=None,
                    trigger_type=None,
                    input_json={"idempotency_key": command.idempotency_key},
                    status="succeeded",
                    attempt_count=1,
                    max_attempts=1,
                    next_attempt_at=None,
                    actor_user_id=actor.user_id,
                    actor_api_key_id=actor.api_key_id,
                    request_receipt_id=receipt_id,
                    result_json=response,
                    created_at=now,
                    updated_at=now,
                ),
            ]
        )
        await self._session.flush()
        return AutomationJobReceipt(
            receipt_id=receipt_id,
            operation_id=operation_id,
            job_id=job_id,
            job_revision=1,
            duplicate=False,
        )

    async def _delete_expired_receipt(
        self,
        *,
        actor: AutomationActor,
        command: QueueManualRunCommand | CreateAutomationJobCommand,
        now: datetime,
        operation: str = "run_now",
    ) -> None:
        _ = await self._session.execute(
            delete(CronRequestReceiptModel).where(
                CronRequestReceiptModel.project_id == actor.project_id,
                CronRequestReceiptModel.actor_user_id == actor.user_id,
                CronRequestReceiptModel.operation == operation,
                CronRequestReceiptModel.idempotency_key == command.idempotency_key,
                CronRequestReceiptModel.expires_at <= now,
            )
        )

    async def _find_receipt(
        self,
        *,
        actor: AutomationActor,
        command: QueueManualRunCommand | CreateAutomationJobCommand,
        operation: str = "run_now",
    ) -> CronRequestReceiptModel | None:
        result = await self._session.execute(
            refresh_select_statement(
                select(CronRequestReceiptModel).where(
                    CronRequestReceiptModel.tenant_id == actor.tenant_id,
                    CronRequestReceiptModel.project_id == actor.project_id,
                    CronRequestReceiptModel.actor_user_id == actor.user_id,
                    CronRequestReceiptModel.operation == operation,
                    CronRequestReceiptModel.idempotency_key == command.idempotency_key,
                )
            )
        )
        return result.scalar_one_or_none()

    async def _find_locked_job(
        self,
        *,
        actor: AutomationActor,
        job_id: str,
    ) -> CronJobModel | None:
        result = await self._session.execute(
            refresh_select_statement(
                select(CronJobModel)
                .where(
                    CronJobModel.id == job_id,
                    CronJobModel.tenant_id == actor.tenant_id,
                    CronJobModel.project_id == actor.project_id,
                )
                .with_for_update()
            )
        )
        return result.scalar_one_or_none()

    @classmethod
    def _replay_job_receipt(
        cls,
        receipt: CronRequestReceiptModel,
        *,
        request_hash: str,
    ) -> AutomationJobReceipt:
        if receipt.request_hash != request_hash:
            raise AutomationCommandIdempotencyConflictError(
                "Idempotency key already belongs to a different automation intent"
            )
        if receipt.http_status != 201:
            raise AutomationCommandIdempotencyConflictError(
                "Idempotency receipt is incomplete and cannot be replayed"
            )
        response = receipt.response_json_redacted
        required = ("receipt_id", "operation_id", "job_id", "job_revision")
        if any(key not in response for key in required):
            raise AutomationCommandIdempotencyConflictError(
                "Idempotency receipt response is incomplete and cannot be replayed"
            )
        job_revision = response["job_revision"]
        if isinstance(job_revision, bool) or not isinstance(job_revision, int):
            raise AutomationCommandIdempotencyConflictError(
                "Idempotency receipt job revision is invalid and cannot be replayed"
            )
        return AutomationJobReceipt(
            receipt_id=str(response["receipt_id"]),
            operation_id=str(response["operation_id"]),
            job_id=str(response["job_id"]),
            job_revision=job_revision,
            duplicate=True,
        )

    @classmethod
    def _replay_receipt(
        cls,
        receipt: CronRequestReceiptModel,
        *,
        request_hash: str,
    ) -> AutomationRunReceipt:
        if receipt.request_hash != request_hash:
            raise AutomationCommandIdempotencyConflictError(
                "Idempotency key already belongs to a different automation intent"
            )
        if receipt.http_status != 202:
            raise AutomationCommandIdempotencyConflictError(
                "Idempotency receipt is incomplete and cannot be replayed"
            )
        return cls._receipt_from_response(receipt.response_json_redacted, duplicate=True)

    @staticmethod
    def _receipt_from_response(
        response: Mapping[str, object],
        *,
        duplicate: bool,
    ) -> AutomationRunReceipt:
        required = (
            "receipt_id",
            "operation_id",
            "run_id",
            "runtime_execution_id",
            "job_id",
            "job_revision",
            "status",
        )
        if any(key not in response for key in required):
            raise AutomationCommandIdempotencyConflictError(
                "Idempotency receipt response is incomplete and cannot be replayed"
            )
        job_revision = response["job_revision"]
        if isinstance(job_revision, bool) or not isinstance(job_revision, int):
            raise AutomationCommandIdempotencyConflictError(
                "Idempotency receipt job revision is invalid and cannot be replayed"
            )
        return AutomationRunReceipt(
            receipt_id=str(response["receipt_id"]),
            operation_id=str(response["operation_id"]),
            run_id=str(response["run_id"]),
            runtime_execution_id=str(response["runtime_execution_id"]),
            job_id=str(response["job_id"]),
            job_revision=job_revision,
            status=str(response["status"]),
            duplicate=duplicate,
        )
