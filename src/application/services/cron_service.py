"""Application service for CronJob operations."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from src.domain.model.cron.cron_job import CronJob
from src.domain.model.cron.cron_job_run import CronJobRun
from src.domain.model.cron.value_objects import (
    ConversationMode,
    CronDelivery,
    CronPayload,
    CronRunStatus,
    CronSchedule,
    TriggerType,
)
from src.domain.ports.repositories.cron_job_repository import (
    CronJobRepository,
    CronJobRunRepository,
)

logger = logging.getLogger(__name__)


class CronJobService:
    """Service for managing cron job lifecycle."""

    def __init__(
        self,
        cron_job_repo: CronJobRepository,
        cron_job_run_repo: CronJobRunRepository,
    ) -> None:
        self._cron_job_repo = cron_job_repo
        self._cron_job_run_repo = cron_job_run_repo

    # -- Job CRUD -----------------------------------------------------------

    async def create_job(  # noqa: PLR0913
        self,
        *,
        project_id: str,
        tenant_id: str,
        name: str,
        schedule: CronSchedule,
        payload: CronPayload,
        description: str | None = None,
        enabled: bool = True,
        delete_after_run: bool = False,
        delivery: CronDelivery | None = None,
        conversation_mode: ConversationMode = ConversationMode.REUSE,
        conversation_id: str | None = None,
        timezone: str = "UTC",
        stagger_seconds: int = 0,
        timeout_seconds: int = 300,
        max_retries: int = 3,
        created_by: str | None = None,
    ) -> CronJob:
        """Create a new cron job."""
        job = CronJob(
            project_id=project_id,
            tenant_id=tenant_id,
            name=name,
            description=description,
            enabled=enabled,
            delete_after_run=delete_after_run,
            schedule=schedule,
            payload=payload,
            delivery=delivery or CronDelivery.none(),
            conversation_mode=conversation_mode,
            conversation_id=conversation_id,
            timezone=timezone,
            stagger_seconds=stagger_seconds,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            created_by=created_by,
        )
        saved = await self._cron_job_repo.save(job)
        logger.info("Created cron job %s in project %s", saved.id, project_id)
        return saved

    async def get_job(self, job_id: str) -> CronJob | None:
        """Get a cron job by ID."""
        return await self._cron_job_repo.find_by_id(job_id)

    async def list_jobs(
        self,
        project_id: str,
        *,
        include_disabled: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> list[CronJob]:
        """List cron jobs for a project."""
        return await self._cron_job_repo.find_by_project(
            project_id,
            include_disabled=include_disabled,
            limit=limit,
            offset=offset,
        )

    async def count_jobs(
        self,
        project_id: str,
        *,
        include_disabled: bool = False,
    ) -> int:
        """Count cron jobs for a project."""
        return await self._cron_job_repo.count_by_project(
            project_id, include_disabled=include_disabled
        )

    async def update_job(
        self,
        job_id: str,
        **updates: object,
    ) -> CronJob:
        """Update a cron job with the given fields.

        Raises:
            ValueError: If the job is not found.
        """
        job = await self._cron_job_repo.find_by_id(job_id)
        if job is None:
            raise ValueError(f"CronJob {job_id} not found")

        for key, value in updates.items():
            if value is not None and hasattr(job, key):
                setattr(job, key, value)

        job.touch()
        saved = await self._cron_job_repo.save(job)
        logger.info("Updated cron job %s", saved.id)
        return saved

    async def delete_job(self, job_id: str) -> bool:
        """Delete a cron job.

        Returns:
            True if the job was deleted, False if not found.
        """
        deleted = await self._cron_job_repo.delete(job_id)
        if deleted:
            logger.info("Deleted cron job %s", job_id)
        return deleted

    async def toggle_job(self, job_id: str, enabled: bool) -> CronJob:
        """Enable or disable a cron job.

        Raises:
            ValueError: If the job is not found.
        """
        job = await self._cron_job_repo.find_by_id(job_id)
        if job is None:
            raise ValueError(f"CronJob {job_id} not found")

        if enabled:
            job.enable()
        else:
            job.disable()

        saved = await self._cron_job_repo.save(job)
        logger.info("Toggled cron job %s to %s", saved.id, "enabled" if enabled else "disabled")
        return saved

    # -- Manual trigger -----------------------------------------------------

    async def trigger_manual_run(
        self,
        job_id: str,
        *,
        conversation_id: str | None = None,
    ) -> CronJobRun:
        """Record a manual trigger for a cron job.

        This only creates the run record. The actual execution is handled
        by the scheduler engine (separate task).

        Raises:
            ValueError: If the job is not found.
        """
        job = await self._cron_job_repo.find_by_id(job_id)
        if job is None:
            raise ValueError(f"CronJob {job_id} not found")

        run = CronJobRun(
            job_id=job.id,
            project_id=job.project_id,
            status=CronRunStatus.SUCCESS,
            trigger_type=TriggerType.MANUAL,
            started_at=datetime.now(UTC),
            conversation_id=conversation_id or job.conversation_id,
        )
        saved = await self._cron_job_run_repo.save(run)
        logger.info("Created manual run %s for job %s", saved.id, job_id)
        return saved

    # -- Run queries --------------------------------------------------------

    async def list_runs(
        self,
        job_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[CronJobRun]:
        """List runs for a specific cron job."""
        return await self._cron_job_run_repo.find_by_job(job_id, limit=limit, offset=offset)

    async def count_runs(self, job_id: str) -> int:
        """Count runs for a specific cron job."""
        return await self._cron_job_run_repo.count_by_job(job_id)

    async def list_project_runs(
        self,
        project_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[CronJobRun]:
        """List all runs for a project."""
        return await self._cron_job_run_repo.find_by_project(project_id, limit=limit, offset=offset)
