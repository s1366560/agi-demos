from __future__ import annotations

import logging
from datetime import datetime
from typing import override

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.cron.cron_job import CronJob
from src.domain.model.cron.cron_job_run import CronJobRun
from src.domain.model.cron.value_objects import (
    ConversationMode,
    CronDelivery,
    CronPayload,
    CronRunStatus,
    CronSchedule,
    DeliveryType,
    PayloadType,
    ScheduleType,
    TriggerType,
)
from src.domain.ports.repositories.cron_job_repository import (
    CronJobRepository,
    CronJobRunRepository,
)
from src.infrastructure.adapters.secondary.common.base_repository import (
    BaseRepository,
    refresh_select_statement,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    CronJobModel,
    CronJobRunModel,
)

logger = logging.getLogger(__name__)


class SqlCronJobRepository(BaseRepository[CronJob, CronJobModel], CronJobRepository):
    _model_class = CronJobModel

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    @override
    async def find_by_project(
        self,
        project_id: str,
        *,
        include_disabled: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> list[CronJob]:
        stmt = select(CronJobModel).where(CronJobModel.project_id == project_id)
        if not include_disabled:
            stmt = stmt.where(CronJobModel.enabled.is_(True))
        stmt = stmt.order_by(CronJobModel.created_at.desc())
        stmt = stmt.offset(offset).limit(limit)

        result = await self._session.execute(
            refresh_select_statement(self._refresh_statement(stmt))
        )
        return [d for row in result.scalars().all() if (d := self._to_domain(row)) is not None]

    @override
    async def count_by_project(
        self,
        project_id: str,
        *,
        include_disabled: bool = False,
    ) -> int:
        from sqlalchemy import func

        stmt = (
            select(func.count())
            .select_from(CronJobModel)
            .where(CronJobModel.project_id == project_id)
        )
        if not include_disabled:
            stmt = stmt.where(CronJobModel.enabled.is_(True))
        result = await self._session.execute(
            refresh_select_statement(self._refresh_statement(stmt))
        )
        return result.scalar_one()

    @override
    async def find_due_jobs(self, now: datetime) -> list[CronJob]:
        stmt = (
            select(CronJobModel)
            .where(CronJobModel.enabled.is_(True))
            .order_by(CronJobModel.created_at.asc())
        )
        result = await self._session.execute(
            refresh_select_statement(self._refresh_statement(stmt))
        )
        jobs: list[CronJob] = []
        for row in result.scalars().all():
            try:
                domain = self._to_domain(row)
            except ValueError as exc:
                logger.warning(
                    "Skipping invalid cron job %s during scheduler sync: %s",
                    getattr(row, "id", "<unknown>"),
                    exc,
                )
                continue
            if domain is None:
                continue
            backoff_until = domain.state.get("backoff_until")
            if backoff_until and datetime.fromisoformat(backoff_until) > now:
                continue
            jobs.append(domain)
        return jobs

    @override
    def _to_domain(self, db_model: CronJobModel | None) -> CronJob | None:
        if db_model is None:
            return None
        return CronJob(
            id=db_model.id,
            project_id=db_model.project_id,
            tenant_id=db_model.tenant_id,
            name=db_model.name,
            description=db_model.description,
            enabled=db_model.enabled,
            delete_after_run=db_model.delete_after_run,
            schedule=CronSchedule(
                kind=ScheduleType(db_model.schedule_type),
                config=db_model.schedule_config or {},
            ),
            payload=CronPayload(
                kind=PayloadType(db_model.payload_type),
                config=db_model.payload_config or {},
            ),
            delivery=CronDelivery(
                kind=DeliveryType(db_model.delivery_type),
                config=db_model.delivery_config or {},
            ),
            conversation_mode=ConversationMode(db_model.conversation_mode),
            conversation_id=db_model.conversation_id,
            timezone=db_model.timezone,
            stagger_seconds=db_model.stagger_seconds,
            timeout_seconds=db_model.timeout_seconds,
            max_retries=db_model.max_retries,
            state=db_model.state or {},
            created_by=db_model.created_by,
            created_at=db_model.created_at,
            updated_at=db_model.updated_at,
        )

    @override
    def _to_db(self, domain_entity: CronJob) -> CronJobModel:
        return CronJobModel(
            id=domain_entity.id,
            project_id=domain_entity.project_id,
            tenant_id=domain_entity.tenant_id,
            name=domain_entity.name,
            description=domain_entity.description,
            enabled=domain_entity.enabled,
            delete_after_run=domain_entity.delete_after_run,
            schedule_type=domain_entity.schedule.kind.value,
            schedule_config=domain_entity.schedule.config,
            payload_type=domain_entity.payload.kind.value,
            payload_config=domain_entity.payload.config,
            delivery_type=domain_entity.delivery.kind.value,
            delivery_config=domain_entity.delivery.config,
            conversation_mode=domain_entity.conversation_mode.value,
            conversation_id=domain_entity.conversation_id,
            timezone=domain_entity.timezone,
            stagger_seconds=domain_entity.stagger_seconds,
            timeout_seconds=domain_entity.timeout_seconds,
            max_retries=domain_entity.max_retries,
            state=domain_entity.state,
            created_by=domain_entity.created_by,
            created_at=domain_entity.created_at,
            updated_at=domain_entity.updated_at,
        )

    @override
    def _update_fields(self, db_model: CronJobModel, domain_entity: CronJob) -> None:
        db_model.name = domain_entity.name
        db_model.description = domain_entity.description
        db_model.enabled = domain_entity.enabled
        db_model.delete_after_run = domain_entity.delete_after_run
        db_model.schedule_type = domain_entity.schedule.kind.value
        db_model.schedule_config = domain_entity.schedule.config
        db_model.payload_type = domain_entity.payload.kind.value
        db_model.payload_config = domain_entity.payload.config
        db_model.delivery_type = domain_entity.delivery.kind.value
        db_model.delivery_config = domain_entity.delivery.config
        db_model.conversation_mode = domain_entity.conversation_mode.value
        db_model.conversation_id = domain_entity.conversation_id
        db_model.timezone = domain_entity.timezone
        db_model.stagger_seconds = domain_entity.stagger_seconds
        db_model.timeout_seconds = domain_entity.timeout_seconds
        db_model.max_retries = domain_entity.max_retries
        db_model.state = domain_entity.state
        db_model.updated_at = domain_entity.updated_at


class SqlCronJobRunRepository(BaseRepository[CronJobRun, CronJobRunModel], CronJobRunRepository):
    _model_class = CronJobRunModel

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    @override
    async def find_by_job(
        self,
        job_id: str,
        *,
        statuses: list[CronRunStatus] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[CronJobRun]:
        stmt = select(CronJobRunModel).where(CronJobRunModel.job_id == job_id)
        if statuses:
            stmt = stmt.where(CronJobRunModel.status.in_([s.value for s in statuses]))
        stmt = stmt.order_by(CronJobRunModel.started_at.desc())
        stmt = stmt.offset(offset).limit(limit)
        result = await self._session.execute(
            refresh_select_statement(self._refresh_statement(stmt))
        )
        return [d for row in result.scalars().all() if (d := self._to_domain(row)) is not None]

    @override
    async def find_by_project(
        self,
        project_id: str,
        *,
        statuses: list[CronRunStatus] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[CronJobRun]:
        stmt = select(CronJobRunModel).where(CronJobRunModel.project_id == project_id)
        if statuses:
            stmt = stmt.where(CronJobRunModel.status.in_([s.value for s in statuses]))
        stmt = stmt.order_by(CronJobRunModel.started_at.desc())
        stmt = stmt.offset(offset).limit(limit)
        result = await self._session.execute(
            refresh_select_statement(self._refresh_statement(stmt))
        )
        return [d for row in result.scalars().all() if (d := self._to_domain(row)) is not None]

    @override
    async def count_by_job(
        self,
        job_id: str,
        *,
        statuses: list[CronRunStatus] | None = None,
    ) -> int:
        from sqlalchemy import func

        stmt = (
            select(func.count())
            .select_from(CronJobRunModel)
            .where(CronJobRunModel.job_id == job_id)
        )
        if statuses:
            stmt = stmt.where(CronJobRunModel.status.in_([s.value for s in statuses]))
        result = await self._session.execute(
            refresh_select_statement(self._refresh_statement(stmt))
        )
        return result.scalar_one()

    @override
    def _to_domain(self, db_model: CronJobRunModel | None) -> CronJobRun | None:
        if db_model is None:
            return None
        return CronJobRun(
            id=db_model.id,
            job_id=db_model.job_id,
            project_id=db_model.project_id,
            status=CronRunStatus(db_model.status),
            trigger_type=TriggerType(db_model.trigger_type),
            started_at=db_model.started_at,
            finished_at=db_model.finished_at,
            duration_ms=db_model.duration_ms,
            error_message=db_model.error_message,
            result_summary=db_model.result_summary or {},
            conversation_id=db_model.conversation_id,
        )

    @override
    def _to_db(self, domain_entity: CronJobRun) -> CronJobRunModel:
        return CronJobRunModel(
            id=domain_entity.id,
            job_id=domain_entity.job_id,
            project_id=domain_entity.project_id,
            status=domain_entity.status.value,
            trigger_type=domain_entity.trigger_type.value,
            started_at=domain_entity.started_at,
            finished_at=domain_entity.finished_at,
            duration_ms=domain_entity.duration_ms,
            error_message=domain_entity.error_message,
            result_summary=domain_entity.result_summary,
            conversation_id=domain_entity.conversation_id,
        )

    @override
    def _update_fields(self, db_model: CronJobRunModel, domain_entity: CronJobRun) -> None:
        db_model.status = domain_entity.status.value
        db_model.finished_at = domain_entity.finished_at
        db_model.duration_ms = domain_entity.duration_ms
        db_model.error_message = domain_entity.error_message
        db_model.result_summary = domain_entity.result_summary
        db_model.conversation_id = domain_entity.conversation_id
