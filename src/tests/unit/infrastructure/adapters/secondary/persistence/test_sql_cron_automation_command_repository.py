from __future__ import annotations

import pytest
from sqlalchemy import func, select

from src.application.services.automation_command_service import (
    AutomationActor,
    AutomationCommandIdempotencyConflictError,
    AutomationCommandRevisionConflictError,
    AutomationCommandService,
    AutomationCommandTargetNotFoundError,
    QueueManualRunCommand,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    CronJobModel,
    CronJobRunModel,
    CronOperationModel,
    CronRequestReceiptModel,
)
from src.infrastructure.adapters.secondary.persistence.sql_cron_automation_command_repository import (
    SqlCronAutomationCommandRepository,
)

pytestmark = pytest.mark.unit


async def _create_job(db_session, test_project_db, test_user) -> CronJobModel:
    job = CronJobModel(
        id="job-1",
        project_id=test_project_db.id,
        tenant_id=test_project_db.tenant_id,
        name="Daily briefing",
        enabled=True,
        delete_after_run=False,
        revision=7,
        schedule_revision=3,
        schedule_type="every",
        schedule_config={"interval_seconds": 3600},
        payload_type="agent_turn",
        payload_config={"message": "Prepare the briefing"},
        delivery_type="none",
        delivery_config={},
        conversation_mode="reuse",
        timezone="UTC",
        stagger_seconds=0,
        timeout_seconds=300,
        max_retries=3,
        state={},
        created_by=test_user.id,
    )
    db_session.add(job)
    await db_session.flush()
    return job


def _actor(test_project_db, test_user) -> AutomationActor:
    return AutomationActor(
        tenant_id=test_project_db.tenant_id,
        project_id=test_project_db.id,
        user_id=test_user.id,
    )


def _command(**overrides: object) -> QueueManualRunCommand:
    values: dict[str, object] = {
        "job_id": "job-1",
        "expected_revision": 7,
        "idempotency_key": "manual-intent-1",
        "conversation_id": "conversation-1",
    }
    values.update(overrides)
    return QueueManualRunCommand(**values)  # type: ignore[arg-type]


async def _count(db_session, model: type[object]) -> int:
    result = await db_session.execute(select(func.count()).select_from(model))
    return int(result.scalar_one())


async def test_manual_run_is_one_atomic_receipt_run_and_operation(
    db_session,
    test_project_db,
    test_user,
) -> None:
    await _create_job(db_session, test_project_db, test_user)
    service = AutomationCommandService(SqlCronAutomationCommandRepository(db_session))

    first = await service.queue_manual_run(
        actor=_actor(test_project_db, test_user),
        command=_command(),
    )
    replay = await service.queue_manual_run(
        actor=_actor(test_project_db, test_user),
        command=_command(),
    )

    assert first.duplicate is False
    assert replay.duplicate is True
    assert replay.run_id == first.run_id
    assert replay.operation_id == first.operation_id
    assert replay.runtime_execution_id == first.runtime_execution_id
    assert await _count(db_session, CronRequestReceiptModel) == 1
    assert await _count(db_session, CronJobRunModel) == 1
    assert await _count(db_session, CronOperationModel) == 1

    run = (
        await db_session.execute(select(CronJobRunModel).where(CronJobRunModel.id == first.run_id))
    ).scalar_one()
    operation = (
        await db_session.execute(
            select(CronOperationModel).where(CronOperationModel.id == first.operation_id)
        )
    ).scalar_one()
    assert run.status == "queued"
    assert run.job_revision == 7
    assert run.schedule_revision == 3
    assert run.request_receipt_id == first.receipt_id
    assert operation.run_id == run.id
    assert operation.request_receipt_id == first.receipt_id
    assert operation.input_json == {
        "conversation_id": "conversation-1",
        "runtime_execution_id": first.runtime_execution_id,
        "timeout_seconds": 300,
        "delete_after_run": False,
        "one_shot": False,
        "max_retries": 3,
    }


async def test_same_idempotency_key_with_different_intent_is_rejected(
    db_session,
    test_project_db,
    test_user,
) -> None:
    await _create_job(db_session, test_project_db, test_user)
    service = AutomationCommandService(SqlCronAutomationCommandRepository(db_session))
    actor = _actor(test_project_db, test_user)

    await service.queue_manual_run(actor=actor, command=_command())

    with pytest.raises(AutomationCommandIdempotencyConflictError):
        await service.queue_manual_run(
            actor=actor,
            command=_command(conversation_id="conversation-2"),
        )

    assert await _count(db_session, CronRequestReceiptModel) == 1
    assert await _count(db_session, CronJobRunModel) == 1
    assert await _count(db_session, CronOperationModel) == 1


async def test_revision_and_scope_mismatches_write_nothing(
    db_session,
    test_project_db,
    test_user,
) -> None:
    await _create_job(db_session, test_project_db, test_user)
    service = AutomationCommandService(SqlCronAutomationCommandRepository(db_session))

    with pytest.raises(AutomationCommandRevisionConflictError) as revision_error:
        await service.queue_manual_run(
            actor=_actor(test_project_db, test_user),
            command=_command(expected_revision=6),
        )
    assert revision_error.value.current_revision == 7

    with pytest.raises(AutomationCommandTargetNotFoundError):
        await service.queue_manual_run(
            actor=AutomationActor(
                tenant_id=test_project_db.tenant_id,
                project_id="another-project",
                user_id=test_user.id,
            ),
            command=_command(idempotency_key="manual-intent-2"),
        )

    assert await _count(db_session, CronRequestReceiptModel) == 0
    assert await _count(db_session, CronJobRunModel) == 0
    assert await _count(db_session, CronOperationModel) == 0


async def test_final_operation_flush_failure_rolls_back_the_reserved_receipt(
    db_session,
    test_project_db,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _create_job(db_session, test_project_db, test_user)
    service = AutomationCommandService(SqlCronAutomationCommandRepository(db_session))
    original_flush = db_session.flush
    flush_count = 0

    async def fail_after_receipt_reservation(*args, **kwargs) -> None:
        nonlocal flush_count
        flush_count += 1
        if flush_count == 2:
            raise RuntimeError("injected operation flush failure")
        await original_flush(*args, **kwargs)

    monkeypatch.setattr(db_session, "flush", fail_after_receipt_reservation)

    with pytest.raises(RuntimeError, match="injected operation flush failure"):
        await service.queue_manual_run(
            actor=_actor(test_project_db, test_user),
            command=_command(),
        )

    assert flush_count == 2
    await db_session.rollback()
    assert await _count(db_session, CronRequestReceiptModel) == 0
    assert await _count(db_session, CronJobRunModel) == 0
    assert await _count(db_session, CronOperationModel) == 0
