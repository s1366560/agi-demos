"""Run and job projections inside the already locked legacy admission transaction."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.cron.cron_job import CronJob
from src.domain.model.cron.legacy_admission import LegacyCronAdmissionIdentity
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.models import CronJobModel, CronJobRunModel


class SqlLegacyCronRunProjection:
    """Lock order is admission, job, run; never touch a Rust runtime projection."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__()
        self._session = session

    async def lock_run(
        self, identity: LegacyCronAdmissionIdentity
    ) -> tuple[CronJobModel, CronJobRunModel] | None:
        job = await self._session.scalar(
            select(CronJobModel)
            .where(
                CronJobModel.id == identity.job_id,
                CronJobModel.tenant_id == identity.tenant_id,
                CronJobModel.project_id == identity.project_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if job is None:
            return None
        run = await self._session.scalar(
            select(CronJobRunModel)
            .where(
                CronJobRunModel.id == identity.run_id,
                CronJobRunModel.job_id == identity.job_id,
                CronJobRunModel.project_id == identity.project_id,
                CronJobRunModel.conversation_id == identity.conversation_id,
                CronJobRunModel.runtime_execution_id.is_(None),
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return (job, run) if run is not None else None

    async def progress(
        self, identity: LegacyCronAdmissionIdentity, *, waiting: bool, initial: bool = False
    ) -> bool:
        locked = await self.lock_run(identity)
        if locked is None:
            return False
        _, run = locked
        if initial:
            run.started_at = await self._now()
        if not waiting:
            summary = dict(run.result_summary or {})
            summary.pop("legacy_hitl_request_ids", None)
            run.result_summary = summary
        self._set_progress(run, waiting=waiting)
        return True

    @staticmethod
    def _set_progress(run: CronJobRunModel, *, waiting: bool) -> None:
        run.status = "waiting_human" if waiting else "running"
        run.finished_at = None
        run.duration_ms = None
        run.error_message = None

    async def hitl(
        self, identity: LegacyCronAdmissionIdentity, request_id: str, *, waiting: bool
    ) -> bool:
        locked = await self.lock_run(identity)
        if locked is None:
            return False
        _, run = locked
        summary = dict(run.result_summary or {})
        pending = list(summary.get("legacy_hitl_request_ids", []))
        if waiting:
            if request_id not in pending:
                pending.append(request_id)
        elif request_id in pending:
            pending.remove(request_id)
        else:
            return False
        summary["legacy_hitl_request_ids"] = pending
        run.result_summary = summary
        self._set_progress(run, waiting=bool(pending))
        return True

    async def terminal(
        self, identity: LegacyCronAdmissionIdentity, outcome: str
    ) -> datetime | None:
        locked = await self.lock_run(identity)
        if locked is None:
            return None
        job, run = locked
        now = await self._now()
        run.status = outcome
        run.finished_at = now
        run.duration_ms = max(0, int((now - run.started_at).total_seconds() * 1000))
        run.error_message = "legacy_execution_failed" if outcome == "failed" else None
        run.result_summary = {"conversation_id": identity.conversation_id}
        policy = CronJob(
            id=job.id,
            tenant_id=job.tenant_id,
            project_id=job.project_id,
            name=job.name,
            enabled=job.enabled,
            max_retries=job.max_retries,
            state=dict(job.state or {}),
        )
        if outcome == "success":
            policy.record_success(now)
            policy.state.pop("last_error", None)
            if job.schedule_type == "at" or job.delete_after_run:
                policy.enabled = False
                policy.state["retired_at"] = now.isoformat()
                policy.state["retired_reason"] = (
                    "one_shot" if job.schedule_type == "at" else "delete_after_run"
                )
        else:
            policy.record_failure("legacy_execution_failed", now)
        job.state = policy.state
        job.enabled = policy.enabled
        job.updated_at = now
        return now

    async def _now(self) -> datetime:
        value: datetime = (
            await self._session.execute(refresh_select_statement(select(func.clock_timestamp())))
        ).scalar_one()
        return value
