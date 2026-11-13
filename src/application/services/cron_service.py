"""Application service for CronJob operations."""

from __future__ import annotations

from src.application.services.automation_command_service import (
    AutomationActor,
    AutomationCommandService,
    CreateAutomationJobCommand,
    DeleteAutomationJobCommand,
    QueueManualRunCommand,
    UpdateAutomationJobCommand,
)
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
        commands: AutomationCommandService | None = None,
    ) -> None:
        self._cron_job_repo = cron_job_repo
        self._cron_job_run_repo = cron_job_run_repo
        self._commands = commands

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
        idempotency_key: str | None = None,
    ) -> CronJob:
        """Persist a job through the durable command path."""
        if self._commands is None:
            raise CronMutationUnavailableError(
                "Create requires durable automation command processing; no job was created"
            )
        if not created_by or not created_by.strip():
            raise CronMutationUnavailableError(
                "Create requires an authenticated user; no job was created"
            )
        if not idempotency_key:
            raise CronMutationUnavailableError("idempotency_key is required; no job was created")
        receipt = await self._commands.create_job(
            actor=AutomationActor(
                tenant_id=tenant_id,
                project_id=project_id,
                user_id=created_by,
            ),
            command=CreateAutomationJobCommand(
                idempotency_key=idempotency_key,
                name=name,
                schedule=schedule,
                payload=payload,
                description=description,
                enabled=enabled,
                delete_after_run=delete_after_run,
                delivery=delivery,
                conversation_mode=conversation_mode,
                conversation_id=conversation_id,
                timezone=timezone,
                stagger_seconds=stagger_seconds,
                timeout_seconds=timeout_seconds,
                max_retries=max_retries,
            ),
        )
        job = await self._cron_job_repo.find_by_id(receipt.job_id)
        if job is None or job.project_id != project_id or job.tenant_id != tenant_id:
            raise CronMutationUnavailableError(
                "Created job is outside the requested project scope; no job was returned"
            )
        return job

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
        """Apply a revision-guarded update inside the caller's project."""
        if self._commands is None:
            raise CronMutationUnavailableError(
                "Update requires durable automation command processing; no job was changed"
            )
        project_id, actor_user_id, expected_revision, idempotency_key = self._mutation_scope(
            updates,
            unavailable="Update requires expected_revision, idempotency_key, and project scope; no job was changed",
        )
        existing = await self._require_project_job(job_id, project_id)
        name = updates.get("name")
        description = updates.get("description")
        enabled = updates.get("enabled")
        schedule = updates.get("schedule")
        payload = updates.get("payload")
        receipt = await self._commands.update_job(
            actor=AutomationActor(
                tenant_id=existing.tenant_id,
                project_id=project_id,
                user_id=actor_user_id,
            ),
            command=UpdateAutomationJobCommand(
                job_id=job_id,
                expected_revision=expected_revision,
                idempotency_key=idempotency_key,
                name=name if isinstance(name, str) else None,
                description=description if isinstance(description, str) else None,
                enabled=enabled if isinstance(enabled, bool) else None,
                schedule=schedule if isinstance(schedule, CronSchedule) else None,
                payload=payload if isinstance(payload, CronPayload) else None,
            ),
        )
        updated = await self._cron_job_repo.find_by_id(receipt.job_id)
        if updated is None or updated.project_id != project_id:
            raise CronMutationUnavailableError(
                "Updated job is outside the requested project scope; no job was returned"
            )
        return updated

    async def delete_job(self, job_id: str, **scope: object) -> bool:
        """Delete one job inside the caller's project."""
        if self._commands is None:
            raise CronMutationUnavailableError(
                "Delete requires durable automation command processing; no job was deleted"
            )
        project_id, actor_user_id, expected_revision, idempotency_key = self._mutation_scope(
            scope,
            unavailable="Delete requires expected_revision, idempotency_key, and project scope; no job was deleted",
        )
        existing = await self._require_project_job(job_id, project_id)
        await self._commands.delete_job(
            actor=AutomationActor(
                tenant_id=existing.tenant_id,
                project_id=project_id,
                user_id=actor_user_id,
            ),
            command=DeleteAutomationJobCommand(
                job_id=job_id,
                expected_revision=expected_revision,
                idempotency_key=idempotency_key,
            ),
        )
        return await self._cron_job_repo.find_by_id(job_id) is None

    async def toggle_job(self, job_id: str, enabled: bool, **scope: object) -> CronJob:
        """Enable or disable a job through the same revision guard as update."""
        if self._commands is None:
            raise CronMutationUnavailableError(
                "Toggle requires durable automation command processing; no job was changed"
            )
        return await self.update_job(job_id, enabled=enabled, **scope)

    def _mutation_scope(
        self,
        values: dict[str, object],
        *,
        unavailable: str,
    ) -> tuple[str, str, int, str]:
        project_id = values.pop("project_id", None)
        actor_user_id = values.pop("actor_user_id", None)
        expected_revision = values.pop("expected_revision", None)
        idempotency_key = values.pop("idempotency_key", None)
        if (
            not isinstance(project_id, str)
            or not project_id.strip()
            or not isinstance(actor_user_id, str)
            or not actor_user_id.strip()
            or not isinstance(expected_revision, int)
            or isinstance(expected_revision, bool)
            or expected_revision < 1
            or not isinstance(idempotency_key, str)
            or not idempotency_key.strip()
        ):
            raise CronMutationUnavailableError(unavailable)
        return project_id, actor_user_id, expected_revision, idempotency_key

    async def _require_project_job(self, job_id: str, project_id: str) -> CronJob:
        existing = await self._cron_job_repo.find_by_id(job_id)
        if existing is None or existing.project_id != project_id:
            raise ValueError(f"CronJob {job_id} not found")
        return existing

    # -- Manual trigger -----------------------------------------------------

    async def trigger_manual_run(
        self,
        job_id: str,
        *,
        conversation_id: str | None = None,
        project_id: str | None = None,
        actor_user_id: str | None = None,
        expected_revision: int | None = None,
        idempotency_key: str | None = None,
    ) -> CronJobRun:
        """Queue one manual run through the durable command path.

        Raises:
            ValueError: If the job is not found in the requested project.
            CronExecutionUnavailableError: If the command path or revision key is missing.
        """
        job = await self._cron_job_repo.find_by_id(job_id)
        if job is None or (project_id is not None and job.project_id != project_id):
            raise ValueError(f"CronJob {job_id} not found")
        if self._commands is None:
            raise CronExecutionUnavailableError(
                "Manual run requires durable automation execution; no run was queued"
            )
        if (
            not actor_user_id
            or not isinstance(expected_revision, int)
            or isinstance(expected_revision, bool)
            or expected_revision < 1
            or not idempotency_key
        ):
            raise CronExecutionUnavailableError(
                "expected_revision and idempotency_key are required; no run was queued"
            )
        receipt = await self._commands.queue_manual_run(
            actor=AutomationActor(
                tenant_id=job.tenant_id,
                project_id=job.project_id,
                user_id=actor_user_id,
            ),
            command=QueueManualRunCommand(
                job_id=job_id,
                expected_revision=expected_revision,
                idempotency_key=idempotency_key,
                conversation_id=conversation_id,
            ),
        )
        return CronJobRun(
            id=receipt.run_id,
            job_id=job.id,
            project_id=job.project_id,
            status=CronRunStatus.QUEUED,
            trigger_type=TriggerType.MANUAL,
            conversation_id=conversation_id,
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
