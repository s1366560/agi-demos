"""Application service for CronJob operations."""

from __future__ import annotations

from src.domain.model.cron.cron_job import CronJob
from src.domain.model.cron.cron_job_run import CronJobRun
from src.domain.model.cron.value_objects import (
    ConversationMode,
    CronDelivery,
    CronPayload,
    CronSchedule,
)
from src.domain.ports.repositories.cron_job_repository import (
    CronJobRepository,
    CronJobRunRepository,
)


class CronMutationUnavailableError(RuntimeError):
    """Raised when a mutation cannot be processed by the durable command path."""


class CronExecutionUnavailableError(CronMutationUnavailableError):
    """Raised when a requested run cannot be durably queued for execution."""


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
        """Reject creation until the durable command path is production-ready."""
        raise CronMutationUnavailableError(
            "Create requires durable automation command processing; no job was created"
        )

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
        """Reject updates until revision-guarded durable commands are available."""
        raise CronMutationUnavailableError(
            "Update requires durable automation command processing; no job was changed"
        )

    async def delete_job(self, job_id: str) -> bool:
        """Reject deletion until revision-guarded durable commands are available."""
        raise CronMutationUnavailableError(
            "Delete requires durable automation command processing; no job was deleted"
        )

    async def toggle_job(self, job_id: str, enabled: bool) -> CronJob:
        """Reject toggles until revision-guarded durable commands are available."""
        raise CronMutationUnavailableError(
            "Toggle requires durable automation command processing; no job was changed"
        )

    # -- Manual trigger -----------------------------------------------------

    async def trigger_manual_run(
        self,
        job_id: str,
        *,
        conversation_id: str | None = None,
    ) -> CronJobRun:
        """Reject manual execution until a durable execution queue is available.

        Raises:
            ValueError: If the job is not found.
            CronExecutionUnavailableError: If no durable execution queue is available.
        """
        job = await self._cron_job_repo.find_by_id(job_id)
        if job is None:
            raise ValueError(f"CronJob {job_id} not found")

        raise CronExecutionUnavailableError(
            "Manual run requires durable automation execution; no run was queued"
        )

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
