"""Cron job execution bridge.

Called by APScheduler when a schedule fires. Loads the ``CronJob`` from the
database, resolves or creates a conversation, executes the payload via
``AgentRuntimeBootstrapper``, and records the outcome as a ``CronJobRun``.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from src.domain.model.cron.cron_job import CronJob
from src.domain.model.cron.cron_job_run import CronJobRun
from src.domain.model.cron.legacy_admission import LegacyCronAdmissionIdentity
from src.domain.model.cron.value_objects import (
    ConversationMode,
    CronRunStatus,
    PayloadType,
    TriggerType,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from src.application.services.agent.runtime_bootstrapper import (
        AgentRuntimeBootstrapper,
    )

logger = logging.getLogger(__name__)
_HOST_READY_TIMEOUT_S = 30.0
_HOST_READY_POLL_S = 0.05


async def _wait_for_process_host() -> bool:
    """Wait until startup publishes the process generation host.

    Cron registration runs inside plugin apply, before
    ``install_process_generation_host_v2``. A due job can fire in that gap.
    Admitting then would leave a queued run with no pinned tenant scope.
    """
    import time

    from src.infrastructure.plugins.v2.boundary import current_process_generation_host_v2
    from src.infrastructure.plugins.v2.runtime import RuntimeV2Error

    deadline = time.monotonic() + _HOST_READY_TIMEOUT_S
    while True:
        try:
            current_process_generation_host_v2()
        except RuntimeV2Error as exc:
            if exc.code != "process_generation_host_not_configured":
                raise
        else:
            return True
        if time.monotonic() >= deadline:
            return False
        await asyncio.sleep(_HOST_READY_POLL_S)


def _delivery_cause(exc: BaseException) -> str:
    code = getattr(exc, "code", None)
    if not isinstance(code, str) or not code.strip():
        code = type(exc).__name__
    return f"failure_class=backend code={code} {exc}"[:500]


async def _fail_unstarted_delivery(identity: object, exc: BaseException) -> None:
    from src.domain.model.cron.legacy_admission import LegacyCronAdmissionIdentity
    from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
    from src.infrastructure.adapters.secondary.persistence.sql_legacy_cron_admission_repository import (
        SqlLegacyCronAdmissionRepository,
    )

    if not isinstance(identity, LegacyCronAdmissionIdentity):
        return
    cause = _delivery_cause(exc)
    try:
        async with async_session_factory() as session:
            failed = await SqlLegacyCronAdmissionRepository(session).fail_unstarted(identity, cause)
            if failed:
                await session.commit()
    except Exception:
        logger.warning(
            "[CronExecutor] Failed to close unstarted admission run=%s",
            identity.run_id,
            exc_info=True,
        )


async def dispatch_queued_manual_run(job_id: str, run_id: str) -> dict[str, object]:
    """Start a durable manual run, or close it if it cannot start.

    A queued row with no worker is not a successful trigger. When the process
    host or payload cannot run, the run and its operation become failed.
    """
    if not await _wait_for_process_host():
        message = "Cron process host is not ready; the run was not left queued"
        await _close_queued_run(
            job_id,
            run_id,
            code="cron_dispatch_unavailable",
            message=message,
        )
        return {
            "dispatched": False,
            "status": "failed",
            "code": "cron_dispatch_unavailable",
            "message": message,
        }
    try:
        await _dispatch_existing_manual_run(job_id, run_id)
    except Exception as exc:
        message = f"Cron run could not be dispatched: {exc}"
        await _close_queued_run(
            job_id,
            run_id,
            code="cron_dispatch_failed",
            message=message,
        )
        return {
            "dispatched": False,
            "status": "failed",
            "code": "cron_dispatch_failed",
            "message": message,
        }
    return {"dispatched": True, "status": "running"}


async def _close_queued_run(job_id: str, run_id: str, *, code: str, message: str) -> None:
    from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
    from src.infrastructure.adapters.secondary.persistence.models import (
        CronJobRunModel,
        CronOperationModel,
    )

    now = datetime.now(UTC)
    async with async_session_factory() as session:
        run = await session.get(CronJobRunModel, run_id)
        if run is None or run.job_id != job_id or run.status != CronRunStatus.QUEUED.value:
            return
        run.status = CronRunStatus.FAILED.value
        run.finished_at = now
        run.error_message = f"failure_class=backend code={code} {message}"[:500]
        if run.started_at is not None:
            run.duration_ms = max(0, int((now - run.started_at).total_seconds() * 1000))
        from sqlalchemy import select

        operation = await session.scalar(
            select(CronOperationModel).where(
                CronOperationModel.run_id == run_id,
                CronOperationModel.operation_kind == "execute_run",
            )
        )
        if operation is not None and operation.status == "pending":
            operation.status = "failed"
            operation.last_error_code = code
            operation.last_error_redacted = message[:500]
            operation.completed_at = now
            operation.updated_at = now
            operation.next_attempt_at = None
        await session.commit()


async def _dispatch_existing_manual_run(job_id: str, run_id: str) -> None:
    from sqlalchemy import select

    from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
    from src.infrastructure.adapters.secondary.persistence.models import (
        CronJobRunModel,
        CronOperationModel,
    )
    from src.infrastructure.adapters.secondary.persistence.sql_cron_job_repository import (
        SqlCronJobRepository,
    )

    async with async_session_factory() as session:
        job = await SqlCronJobRepository(session).find_by_id(job_id)
        run_row = await session.get(CronJobRunModel, run_id)
        if job is None or not job.enabled:
            raise RuntimeError("cron job is missing or disabled")
        if run_row is None or run_row.job_id != job.id:
            raise RuntimeError("queued cron run was not found")
        if run_row.status != CronRunStatus.QUEUED.value:
            return
        operation = await session.scalar(
            select(CronOperationModel).where(
                CronOperationModel.run_id == run_id,
                CronOperationModel.operation_kind == "execute_run",
            )
        )
        if operation is not None and operation.status == "pending":
            operation.status = "waiting_runtime"
            operation.started_at = datetime.now(UTC)
            operation.updated_at = operation.started_at
        conversation_id = run_row.conversation_id or await _resolve_conversation(job, session)
        run = CronJobRun(
            id=run_row.id,
            job_id=job.id,
            project_id=job.project_id,
            status=CronRunStatus.QUEUED,
            trigger_type=TriggerType.MANUAL,
            conversation_id=conversation_id,
            started_at=run_row.started_at,
        )
        admission = await _admit_legacy_execution(
            job,
            run,
            conversation_id,
            session,
            message_id=run_row.runtime_execution_id or run_row.id,
        )
        if admission is None:
            raise RuntimeError("cron scheduler ownership denied the manual run")
        await _execute_payload(job, conversation_id, session, admission)


async def execute_cron_job(job_id: str) -> None:
    """Execute a single cron job.

    This is the entry point invoked by APScheduler.  It runs in a fresh DB
    session (no request context) and is fully self-contained.
    """
    from src.infrastructure.adapters.secondary.persistence.database import (
        async_session_factory,
    )
    from src.infrastructure.adapters.secondary.persistence.sql_cron_job_repository import (
        SqlCronJobRepository,
    )

    logger.info("[CronExecutor] Executing job %s", job_id)
    if not await _wait_for_process_host():
        logger.warning(
            "[CronExecutor] Job %s process host is not ready; not admitting",
            job_id,
        )
        return

    async with async_session_factory() as session:
        job_repo = SqlCronJobRepository(session)

        job = await job_repo.find_by_id(job_id)
        if job is None:
            logger.warning("[CronExecutor] Job %s not found -- skipping", job_id)
            return

        if not job.enabled:
            logger.info("[CronExecutor] Job %s is disabled -- skipping", job_id)
            return
        open_run_id = await _open_scheduled_run_id(session, job.id)
        if open_run_id is not None:
            logger.warning(
                "[CronExecutor] Job %s already has open run %s; not dispatching another",
                job_id,
                open_run_id,
            )
            return

        run = CronJobRun(
            job_id=job.id,
            project_id=job.project_id,
            status=CronRunStatus.QUEUED,
            trigger_type=TriggerType.SCHEDULED,
            started_at=datetime.now(UTC),
        )
        admission = None
        try:
            conversation_id = await _resolve_conversation(job, session)
            run.conversation_id = conversation_id
            admission = await _admit_legacy_execution(job, run, conversation_id, session)
            if admission is None:
                return
            await _execute_payload(job, conversation_id, session, admission)
            logger.info("[CronExecutor] Job %s dispatched; awaiting execution terminal", job_id)
        except Exception as exc:
            if admission is not None:
                await _fail_unstarted_delivery(admission, exc)
                logger.warning(
                    "[CronExecutor] Job %s delivery failed before start code=%s",
                    job_id,
                    getattr(exc, "code", type(exc).__name__),
                    exc_info=True,
                )
                return
            await session.rollback()
            await _record_preparation_failure(job, run, session)
            await session.commit()
            logger.warning("[CronExecutor] Job %s preparation failed before admission", job_id)


async def _open_scheduled_run_id(session: AsyncSession, job_id: str) -> str | None:
    """A queued, running, or parked run is the occurrence already in flight."""
    from sqlalchemy import select

    from src.infrastructure.adapters.secondary.persistence.models import CronJobRunModel

    run_id = await session.scalar(
        select(CronJobRunModel.id)
        .where(
            CronJobRunModel.job_id == job_id,
            CronJobRunModel.status.in_(("queued", "running", "waiting_human")),
        )
        .limit(1)
    )
    return run_id if isinstance(run_id, str) else None


async def _record_preparation_failure(job: CronJob, run: CronJobRun, session: AsyncSession) -> None:
    """No admission was attempted, so a fresh scoped job lock can count this failure."""
    from sqlalchemy import select

    from src.infrastructure.adapters.secondary.persistence.models import CronJobModel
    from src.infrastructure.adapters.secondary.persistence.sql_cron_job_repository import (
        SqlCronJobRunRepository,
    )

    current = await session.scalar(
        select(CronJobModel)
        .where(
            CronJobModel.id == job.id,
            CronJobModel.tenant_id == job.tenant_id,
            CronJobModel.project_id == job.project_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if current is None:
        return
    run.mark_finished(status=CronRunStatus.FAILED, error_message="legacy_preparation_failed")
    policy = CronJob(
        id=current.id,
        tenant_id=current.tenant_id,
        project_id=current.project_id,
        name=current.name,
        enabled=current.enabled,
        max_retries=current.max_retries,
        state=dict(current.state or {}),
    )
    policy.record_failure("legacy_preparation_failed", run.finished_at)
    current.state = policy.state
    current.enabled = policy.enabled
    current.updated_at = run.finished_at
    _ = await SqlCronJobRunRepository(session).save(run)


async def _admit_legacy_execution(
    job: CronJob,
    run: CronJobRun,
    conversation_id: str,
    session: AsyncSession,
    message_id: str | None = None,
) -> LegacyCronAdmissionIdentity | None:
    """Commit the blocker and conversation before asynchronous dispatch can begin."""
    from src.infrastructure.adapters.secondary.persistence.sql_cron_job_repository import (
        SqlCronJobRunRepository,
    )
    from src.infrastructure.adapters.secondary.persistence.sql_legacy_cron_admission_repository import (
        SqlLegacyCronAdmissionRepository,
    )

    admission = await SqlLegacyCronAdmissionRepository(session).admit(
        tenant_id=job.tenant_id,
        project_id=job.project_id,
        job_id=job.id,
        run_id=run.id,
        message_id=message_id or str(uuid.uuid4()),
        conversation_id=conversation_id,
    )
    if admission is None:
        await session.rollback()
        logger.info("[CronExecutor] Scheduler ownership denies job %s", job.id)
        return None
    if job.conversation_mode == ConversationMode.REUSE:
        from sqlalchemy import update

        from src.infrastructure.adapters.secondary.persistence.models import CronJobModel

        _ = await session.execute(
            update(CronJobModel)
            .where(
                CronJobModel.id == job.id,
                CronJobModel.tenant_id == job.tenant_id,
                CronJobModel.project_id == job.project_id,
            )
            .values(conversation_id=conversation_id)
        )
    _ = await SqlCronJobRunRepository(session).save(run)
    await session.commit()
    return admission


# ---------------------------------------------------------------------------
# Conversation resolution
# ---------------------------------------------------------------------------


async def _resolve_conversation(
    job: CronJob,
    session: AsyncSession,
) -> str:
    """Resolve or create the conversation for this job execution.

    Returns the conversation ID to use.
    """
    from src.domain.model.agent import Conversation
    from src.infrastructure.adapters.secondary.persistence.sql_conversation_repository import (
        SqlConversationRepository,
    )

    conv_repo = SqlConversationRepository(session)

    if job.conversation_mode == ConversationMode.REUSE and job.conversation_id:
        existing = await conv_repo.find_by_id(job.conversation_id)
        if existing is not None:
            return existing.id
        logger.warning(
            "[CronExecutor] Reuse conversation %s not found -- creating fresh",
            job.conversation_id,
        )

    # Create a new conversation
    conversation = Conversation(
        project_id=job.project_id,
        tenant_id=job.tenant_id,
        user_id=job.created_by or "system",
        title=f"[Cron] {job.name}",
    )
    saved = await conv_repo.save(conversation)

    # If mode is reuse, persist the new conversation_id back to the job
    if job.conversation_mode == ConversationMode.REUSE:
        job.conversation_id = saved.id

    return saved.id


# ---------------------------------------------------------------------------
# Payload execution
# ---------------------------------------------------------------------------


async def _execute_payload(
    job: CronJob,
    conversation_id: str,
    session: AsyncSession,
    admission: LegacyCronAdmissionIdentity,
) -> None:
    """Execute the job payload with timeout.

    The scheduler has no HTTP operation. Dispatch always leases the published
    process generation for this job's tenant and project. There is no unscoped
    fallback when the host is missing; the caller must not admit in that case.
    """
    timeout = job.timeout_seconds or 300
    from src.infrastructure.plugins.v2.boundary import pin_agent_turn_operation_v2

    try:
        async with pin_agent_turn_operation_v2(
            operation_id=f"cron-payload:{job.id}:{admission.message_id}",
            tenant_id=job.tenant_id,
            project_id=job.project_id,
            session_id=conversation_id,
            force_process_host_lease=True,
        ):
            await asyncio.wait_for(
                _dispatch_payload(job, conversation_id, session, admission),
                timeout=timeout,
            )
    except TimeoutError as err:
        raise TimeoutError(f"Cron job {job.id} execution timed out after {timeout}s") from err


async def _dispatch_payload(
    job: CronJob,
    conversation_id: str,
    session: AsyncSession,
    admission: LegacyCronAdmissionIdentity,
) -> None:
    """Dispatch the payload to the correct handler."""
    payload_type = job.payload.kind

    if payload_type == PayloadType.AGENT_TURN:
        await _execute_agent_turn(job, conversation_id, session, admission)
    elif payload_type == PayloadType.SYSTEM_EVENT:
        await _execute_system_event(job, conversation_id, session, admission)
    else:
        raise ValueError(f"Unknown payload type: {payload_type}")


async def _execute_agent_turn(
    job: CronJob,
    conversation_id: str,
    session: AsyncSession,
    admission: LegacyCronAdmissionIdentity,
) -> None:
    """Execute an agent turn via the runtime bootstrapper."""
    from src.infrastructure.adapters.secondary.persistence.sql_conversation_repository import (
        SqlConversationRepository,
    )

    conv_repo = SqlConversationRepository(session)
    conversation = await conv_repo.find_by_id(conversation_id)
    if conversation is None:
        raise ValueError(f"Conversation {conversation_id} not found for agent turn")

    message = job.payload.config.get("message", "")
    message_id = admission.message_id
    await _ensure_cron_chat_authority(session, conversation, message_id, message)

    bootstrapper = _get_bootstrapper()
    _ = await bootstrapper.start_chat_actor(
        conversation=conversation,
        message_id=message_id,
        user_message=message,
        conversation_context=[],
        correlation_id=f"cron:{job.id}",
        legacy_cron_admission=admission.to_wire(),
        canonical_run_id=message_id,
    )

    logger.info(
        "[CronExecutor] Agent turn dispatched for job %s, conversation %s",
        job.id,
        conversation_id,
    )


async def _execute_system_event(
    job: CronJob,
    conversation_id: str,
    session: AsyncSession,
    admission: LegacyCronAdmissionIdentity,
) -> None:
    """Execute a system event payload by injecting content as an agent message."""
    from src.infrastructure.adapters.secondary.persistence.sql_conversation_repository import (
        SqlConversationRepository,
    )

    conv_repo = SqlConversationRepository(session)
    conversation = await conv_repo.find_by_id(conversation_id)
    if conversation is None:
        raise ValueError(f"Conversation {conversation_id} not found for system event")

    content = job.payload.config.get("content", "")
    message_id = admission.message_id
    user_message = f"[System Event] {content}"
    await _ensure_cron_chat_authority(session, conversation, message_id, user_message)

    bootstrapper = _get_bootstrapper()
    _ = await bootstrapper.start_chat_actor(
        conversation=conversation,
        message_id=message_id,
        user_message=user_message,
        conversation_context=[],
        correlation_id=f"cron:{job.id}",
        legacy_cron_admission=admission.to_wire(),
        canonical_run_id=message_id,
    )

    logger.info(
        "[CronExecutor] System event dispatched for job %s, conversation %s",
        job.id,
        conversation_id,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_bootstrapper_instance: AgentRuntimeBootstrapper | None = None


async def _ensure_cron_chat_authority(
    session: AsyncSession,
    conversation: object,
    message_id: str,
    request_message: str,
) -> None:
    """Admit the cron turn through the same chat authority ordinary turns use."""
    from src.infrastructure.adapters.secondary.persistence.sql_agent_run_authority import (
        ensure_chat_run_authority,
    )

    _ = await ensure_chat_run_authority(
        session,
        conversation=conversation,  # type: ignore[arg-type]
        run_id=message_id,
        request_message=request_message,
        client_message_id=message_id,
        app_model_context=None,
    )


def _get_bootstrapper() -> AgentRuntimeBootstrapper:
    """Lazily create and return the ``AgentRuntimeBootstrapper`` singleton."""
    global _bootstrapper_instance

    if _bootstrapper_instance is None:
        from src.application.services.agent.runtime_bootstrapper import (
            AgentRuntimeBootstrapper,
        )

        _bootstrapper_instance = AgentRuntimeBootstrapper()

    return _bootstrapper_instance
