from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from src.application.services.automation_command_service import (
    AutomationActor,
    AutomationCommandService,
    QueueManualRunCommand,
)
from src.application.services.automation_runtime_projection_service import (
    AutomationRuntimeIdentity,
    AutomationRuntimeOutcome,
    AutomationRuntimeProjectionConflictError,
    AutomationRuntimeProjectionService,
    AutomationRuntimeTerminal,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    CronJobModel,
    CronJobRunModel,
    CronOperationModel,
)
from src.infrastructure.adapters.secondary.persistence.sql_automation_runtime_projection_repository import (
    SqlAutomationRuntimeProjectionRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_cron_automation_command_repository import (
    SqlCronAutomationCommandRepository,
)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)


async def _create_run(db_session, test_project_db, test_user):
    db_session.add(
        CronJobModel(
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
    )
    await db_session.flush()
    return await AutomationCommandService(
        SqlCronAutomationCommandRepository(db_session)
    ).queue_manual_run(
        actor=AutomationActor(
            tenant_id=test_project_db.tenant_id,
            project_id=test_project_db.id,
            user_id=test_user.id,
        ),
        command=QueueManualRunCommand(
            job_id="job-1",
            expected_revision=7,
            idempotency_key="manual-intent-1",
            conversation_id="conversation-1",
        ),
    )


def _identity(test_project_db, runtime_execution_id: str) -> AutomationRuntimeIdentity:
    return AutomationRuntimeIdentity(
        tenant_id=test_project_db.tenant_id,
        project_id=test_project_db.id,
        runtime_execution_id=runtime_execution_id,
        conversation_id="conversation-1",
    )


def _terminal(outcome: AutomationRuntimeOutcome) -> AutomationRuntimeTerminal:
    return AutomationRuntimeTerminal(
        outcome=outcome,
        observed_at=NOW,
        execution_time_ms=125.4,
        event_count=3,
    )


async def test_runtime_success_projects_run_and_waiting_operation_idempotently(
    db_session,
    test_project_db,
    test_user,
) -> None:
    receipt = await _create_run(db_session, test_project_db, test_user)
    operation = (
        await db_session.execute(
            select(CronOperationModel).where(CronOperationModel.id == receipt.operation_id)
        )
    ).scalar_one()
    operation.status = "waiting_runtime"
    await db_session.flush()
    service = AutomationRuntimeProjectionService(
        SqlAutomationRuntimeProjectionRepository(db_session)
    )
    identity = _identity(test_project_db, receipt.runtime_execution_id)

    running = await service.mark_running(identity=identity, observed_at=NOW)
    waiting = await service.mark_waiting_human(identity=identity, observed_at=NOW)
    resumed = await service.mark_running(identity=identity, observed_at=NOW)
    first = await service.project_terminal(
        identity=identity,
        terminal=_terminal(AutomationRuntimeOutcome.SUCCESS),
    )
    replay = await service.project_terminal(
        identity=identity,
        terminal=_terminal(AutomationRuntimeOutcome.SUCCESS),
    )

    run = (
        await db_session.execute(
            select(CronJobRunModel).where(CronJobRunModel.id == receipt.run_id)
        )
    ).scalar_one()
    assert running.run_status == "running"
    assert waiting.run_status == "waiting_human"
    assert resumed.run_status == "running"
    assert first.run_status == "success"
    assert first.operation_status == "completed"
    assert first.delivery_ack_pending is False
    assert replay.duplicate is True
    assert run.status == "success"
    assert run.duration_ms == 125
    assert run.error_message is None
    assert run.result_summary["runtime_execution_id"] == receipt.runtime_execution_id
    assert operation.status == "completed"
    assert operation.result_json["runtime_status"] == "success"
    assert operation.completed_at is not None
    assert operation.completed_at.replace(tzinfo=UTC) == NOW


async def test_terminal_run_can_be_replayed_after_dispatch_ack_race(
    db_session,
    test_project_db,
    test_user,
) -> None:
    receipt = await _create_run(db_session, test_project_db, test_user)
    service = AutomationRuntimeProjectionService(
        SqlAutomationRuntimeProjectionRepository(db_session)
    )
    identity = _identity(test_project_db, receipt.runtime_execution_id)

    first = await service.project_terminal(
        identity=identity,
        terminal=_terminal(AutomationRuntimeOutcome.FAILED),
    )
    operation = (
        await db_session.execute(
            select(CronOperationModel).where(CronOperationModel.id == receipt.operation_id)
        )
    ).scalar_one()
    assert first.delivery_ack_pending is True
    assert first.operation_status == "pending"
    assert operation.status == "pending"

    operation.status = "waiting_runtime"
    await db_session.flush()
    replay = await service.project_terminal(
        identity=identity,
        terminal=_terminal(AutomationRuntimeOutcome.FAILED),
    )
    run = (
        await db_session.execute(
            select(CronJobRunModel).where(CronJobRunModel.id == receipt.run_id)
        )
    ).scalar_one()

    assert replay.duplicate is True
    assert replay.delivery_ack_pending is False
    assert replay.operation_status == "completed"
    assert run.error_message == "agent_execution_failed"
    assert "boom" not in str(run.result_summary)
    assert operation.result_json["error_code"] == "agent_execution_failed"


async def test_terminal_projection_is_scope_bound_and_never_rewrites_a_terminal_verdict(
    db_session,
    test_project_db,
    test_user,
) -> None:
    receipt = await _create_run(db_session, test_project_db, test_user)
    service = AutomationRuntimeProjectionService(
        SqlAutomationRuntimeProjectionRepository(db_session)
    )

    unmatched = await service.project_terminal(
        identity=AutomationRuntimeIdentity(
            tenant_id="another-tenant",
            project_id=test_project_db.id,
            runtime_execution_id=receipt.runtime_execution_id,
            conversation_id="conversation-1",
        ),
        terminal=_terminal(AutomationRuntimeOutcome.SUCCESS),
    )
    assert unmatched.matched is False

    identity = _identity(test_project_db, receipt.runtime_execution_id)
    await service.project_terminal(
        identity=identity,
        terminal=_terminal(AutomationRuntimeOutcome.SUCCESS),
    )
    with pytest.raises(AutomationRuntimeProjectionConflictError):
        await service.project_terminal(
            identity=identity,
            terminal=_terminal(AutomationRuntimeOutcome.FAILED),
        )
