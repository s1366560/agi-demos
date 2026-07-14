from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.application.services.automation_command_service import (
    AutomationActor,
    AutomationCommandService,
    QueueManualRunCommand,
)
from src.application.services.automation_runtime_projection_service import (
    AutomationRuntimeIdentity,
    AutomationRuntimeOutcome,
    AutomationRuntimeProjectionService,
    AutomationRuntimeTerminal,
)
from src.configuration.config import get_settings
from src.infrastructure.adapters.secondary.persistence.models import (
    CronJobModel,
    CronJobRunModel,
    CronOperationModel,
    CronRequestReceiptModel,
    Project,
    UserProject,
)
from src.infrastructure.adapters.secondary.persistence.sql_automation_runtime_projection_repository import (
    SqlAutomationRuntimeProjectionRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_cron_automation_command_repository import (
    SqlCronAutomationCommandRepository,
)

pytestmark = pytest.mark.integration


async def test_postgres_manual_run_receipt_and_operation_are_atomic() -> None:
    engine = create_async_engine(get_settings().postgres_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            transaction = await session.begin()
            try:
                membership = (
                    await session.execute(
                        select(UserProject, Project)
                        .join(Project, Project.id == UserProject.project_id)
                        .order_by(UserProject.created_at.asc())
                        .limit(1)
                    )
                ).one_or_none()
                if membership is None:
                    pytest.skip("PostgreSQL fixture has no project membership")
                user_project, project = membership
                job_id = f"cron-command-test-{uuid.uuid4()}"
                idempotency_key = f"cron-command-intent-{uuid.uuid4()}"
                session.add(
                    CronJobModel(
                        id=job_id,
                        project_id=project.id,
                        tenant_id=project.tenant_id,
                        name="Command transaction probe",
                        enabled=True,
                        delete_after_run=False,
                        revision=7,
                        schedule_revision=3,
                        schedule_type="every",
                        schedule_config={"interval_seconds": 3600},
                        payload_type="agent_turn",
                        payload_config={"message": "Probe"},
                        delivery_type="none",
                        delivery_config={},
                        conversation_mode="reuse",
                        timezone="UTC",
                        stagger_seconds=0,
                        timeout_seconds=300,
                        max_retries=3,
                        state={},
                        created_by=user_project.user_id,
                    )
                )
                await session.flush()

                service = AutomationCommandService(SqlCronAutomationCommandRepository(session))
                actor = AutomationActor(
                    tenant_id=project.tenant_id,
                    project_id=project.id,
                    user_id=user_project.user_id,
                )
                command = QueueManualRunCommand(
                    job_id=job_id,
                    expected_revision=7,
                    idempotency_key=idempotency_key,
                )

                first = await service.queue_manual_run(actor=actor, command=command)
                replay = await service.queue_manual_run(actor=actor, command=command)

                assert first.duplicate is False
                assert replay.duplicate is True
                assert replay.run_id == first.run_id
                assert first.runtime_execution_id == first.run_id
                for model in (
                    CronRequestReceiptModel,
                    CronJobRunModel,
                    CronOperationModel,
                ):
                    count = await session.scalar(
                        select(func.count())
                        .select_from(model)
                        .where(
                            model.request_receipt_id == first.receipt_id
                            if model is not CronRequestReceiptModel
                            else model.id == first.receipt_id
                        )
                    )
                    assert count == 1

                operation = (
                    await session.execute(
                        select(CronOperationModel).where(
                            CronOperationModel.id == first.operation_id
                        )
                    )
                ).scalar_one()
                operation.status = "waiting_runtime"
                await session.flush()
                projection_service = AutomationRuntimeProjectionService(
                    SqlAutomationRuntimeProjectionRepository(session)
                )
                identity = AutomationRuntimeIdentity(
                    tenant_id=project.tenant_id,
                    project_id=project.id,
                    runtime_execution_id=first.runtime_execution_id,
                    conversation_id="cron-command-conversation",
                )
                observed_at = datetime.now(UTC)
                running = await projection_service.mark_running(
                    identity=identity,
                    observed_at=observed_at,
                )
                terminal = await projection_service.project_terminal(
                    identity=identity,
                    terminal=AutomationRuntimeTerminal(
                        outcome=AutomationRuntimeOutcome.SUCCESS,
                        observed_at=observed_at,
                        execution_time_ms=42,
                        event_count=2,
                    ),
                )
                assert running.run_status == "running"
                assert terminal.run_status == "success"
                assert terminal.operation_status == "completed"
                assert terminal.delivery_ack_pending is False
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()
