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

    async with async_session_factory() as session:
        job_repo = SqlCronJobRepository(session)

        job = await job_repo.find_by_id(job_id)
        if job is None:
            logger.warning("[CronExecutor] Job %s not found -- skipping", job_id)
            return

        if not job.enabled:
            logger.info("[CronExecutor] Job %s is disabled -- skipping", job_id)
            return

        run = CronJobRun(
            job_id=job.id,
            project_id=job.project_id,
            status=CronRunStatus.QUEUED,
            trigger_type=TriggerType.SCHEDULED,
            started_at=datetime.now(UTC),
        )
        admission_attempted = False
        try:
            conversation_id = await _resolve_conversation(job, session)
            run.conversation_id = conversation_id
            admission_attempted = True
            admission = await _admit_legacy_execution(job, run, conversation_id, session)
            if admission is None:
                return
            await _execute_payload(job, conversation_id, session, admission)
            logger.info("[CronExecutor] Job %s dispatched; awaiting execution terminal", job_id)
        except Exception:
            if admission_attempted:
                # Commit/delivery uncertainty is not proof that execution has stopped.
                logger.warning("[CronExecutor] Job %s delivery unresolved", job_id)
                return
            await session.rollback()
            await _record_preparation_failure(job, run, session)
            await session.commit()
            logger.warning("[CronExecutor] Job %s preparation failed before admission", job_id)


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
    job: CronJob, run: CronJobRun, conversation_id: str, session: AsyncSession
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
        message_id=str(uuid.uuid4()),
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
    """Execute the job payload with timeout."""
    timeout = job.timeout_seconds or 300

    try:
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

    bootstrapper = _get_bootstrapper()
    _ = await bootstrapper.start_chat_actor(
        conversation=conversation,
        message_id=message_id,
        user_message=message,
        conversation_context=[],
        correlation_id=f"cron:{job.id}",
        legacy_cron_admission=admission.to_wire(),
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

    bootstrapper = _get_bootstrapper()
    _ = await bootstrapper.start_chat_actor(
        conversation=conversation,
        message_id=message_id,
        user_message=f"[System Event] {content}",
        conversation_context=[],
        correlation_id=f"cron:{job.id}",
        legacy_cron_admission=admission.to_wire(),
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


def _get_bootstrapper() -> AgentRuntimeBootstrapper:
    """Lazily create and return the ``AgentRuntimeBootstrapper`` singleton."""
    global _bootstrapper_instance

    if _bootstrapper_instance is None:
        from src.application.services.agent.runtime_bootstrapper import (
            AgentRuntimeBootstrapper,
        )

        _bootstrapper_instance = AgentRuntimeBootstrapper()

    return _bootstrapper_instance
