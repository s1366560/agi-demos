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
        SqlCronJobRunRepository,
    )

    logger.info("[CronExecutor] Executing job %s", job_id)

    async with async_session_factory() as session:
        job_repo = SqlCronJobRepository(session)
        run_repo = SqlCronJobRunRepository(session)

        job = await job_repo.find_by_id(job_id)
        if job is None:
            logger.warning("[CronExecutor] Job %s not found -- skipping", job_id)
            return

        if not job.enabled:
            logger.info("[CronExecutor] Job %s is disabled -- skipping", job_id)
            return

        # Create run record
        run = CronJobRun(
            job_id=job.id,
            project_id=job.project_id,
            status=CronRunStatus.SUCCESS,
            trigger_type=TriggerType.SCHEDULED,
            started_at=datetime.now(UTC),
        )

        try:
            conversation_id = await _resolve_conversation(job, session)
            run.conversation_id = conversation_id

            await _execute_payload(job, conversation_id, session)

            # Mark success
            run.mark_finished(
                status=CronRunStatus.SUCCESS,
                result_summary={"conversation_id": conversation_id},
            )
            job.record_success()

        except TimeoutError:
            run.mark_finished(
                status=CronRunStatus.TIMEOUT,
                error_message=f"Execution timed out after {job.timeout_seconds}s",
            )
            job.record_failure(
                f"Timeout after {job.timeout_seconds}s",
            )
            logger.warning(
                "[CronExecutor] Job %s timed out after %ds",
                job_id,
                job.timeout_seconds,
            )
        except Exception as exc:
            error_msg = str(exc)[:500]
            run.mark_finished(
                status=CronRunStatus.FAILED,
                error_message=error_msg,
            )
            job.record_failure(error_msg)
            logger.exception("[CronExecutor] Job %s failed", job_id)

        # Persist run + updated job state
        await run_repo.save(run)
        await job_repo.save(job)

        # Delete one-shot / delete_after_run jobs on success
        if run.status == CronRunStatus.SUCCESS and job.should_delete_after_run():
            await job_repo.delete(job.id)
            # Also unregister from APScheduler
            try:
                from src.infrastructure.scheduler.scheduler_service import (
                    unregister_job,
                )

                await unregister_job(job.id)
            except Exception:
                logger.debug(
                    "[CronExecutor] Could not unregister deleted job %s from APScheduler",
                    job.id,
                )
            logger.info("[CronExecutor] Deleted one-shot job %s after success", job.id)

        # If job got disabled by record_failure (max retries), unregister
        if not job.enabled:
            try:
                from src.infrastructure.scheduler.scheduler_service import (
                    unregister_job,
                )

                await unregister_job(job.id)
            except Exception:
                pass
            logger.warning(
                "[CronExecutor] Job %s disabled after %d consecutive failures",
                job.id,
                job.max_retries,
            )

        await session.commit()

    logger.info(
        "[CronExecutor] Job %s completed with status %s",
        job_id,
        run.status.value,
    )


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
) -> None:
    """Execute the job payload with timeout."""
    timeout = job.timeout_seconds or 300

    try:
        await asyncio.wait_for(
            _dispatch_payload(job, conversation_id, session),
            timeout=timeout,
        )
    except TimeoutError as err:
        raise TimeoutError(f"Cron job {job.id} execution timed out after {timeout}s") from err


async def _dispatch_payload(
    job: CronJob,
    conversation_id: str,
    session: AsyncSession,
) -> None:
    """Dispatch the payload to the correct handler."""
    payload_type = job.payload.kind

    if payload_type == PayloadType.AGENT_TURN:
        await _execute_agent_turn(job, conversation_id, session)
    elif payload_type == PayloadType.SYSTEM_EVENT:
        await _execute_system_event(job, conversation_id, session)
    else:
        raise ValueError(f"Unknown payload type: {payload_type}")


async def _execute_agent_turn(
    job: CronJob,
    conversation_id: str,
    session: AsyncSession,
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
    message_id = str(uuid.uuid4())

    bootstrapper = _get_bootstrapper()
    _ = await bootstrapper.start_chat_actor(
        conversation=conversation,
        message_id=message_id,
        user_message=message,
        conversation_context=[],
        correlation_id=f"cron:{job.id}",
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
    message_id = str(uuid.uuid4())

    bootstrapper = _get_bootstrapper()
    _ = await bootstrapper.start_chat_actor(
        conversation=conversation,
        message_id=message_id,
        user_message=f"[System Event] {content}",
        conversation_context=[],
        correlation_id=f"cron:{job.id}",
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
