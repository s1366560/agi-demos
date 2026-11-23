"""Revision-bound project schedule editing and durable manual dispatch for signed pages."""

from typing import TYPE_CHECKING, Annotated, Any

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from src.application.schemas.cron import (
    AutomationRunCommandV2,
    CronJobCreate,
    CronJobResponse,
    CronJobUpdate,
)
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.primary.web.cron_application_authority_v2 import cron_authority
from src.infrastructure.adapters.primary.web.routers import cron
from src.infrastructure.i18n import gettext as _

if TYPE_CHECKING:
    from src.host.operations.application_commands import (
        Operation,
        PackageOperationContext,
        Progress,
    )

type Identifier = Annotated[str, Field(min_length=1, max_length=255)]


class PageQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    offset: int = Field(0, ge=0)


class Revision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    job_id: Identifier
    expected_revision: int = Field(ge=1)
    idempotency_key: str = Field(min_length=1, max_length=255, pattern=r"^[!-~]+$")


class ScheduleEdit(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    job_id: Identifier | None = None
    expected_revision: int | None = Field(None, ge=1)
    idempotency_key: str = Field(min_length=1, max_length=255, pattern=r"^[!-~]+$")
    name: Identifier
    enabled: bool
    interval_seconds: int = Field(ge=1, le=31536000)


def _scope(ctx: "PackageOperationContext") -> ScopeV2:
    return ScopeV2(
        kind=ScopeKindV2.PROJECT, tenant_id=ctx.scope.tenant_id, project_id=ctx.scope.project_id
    )


def _row(job: CronJobResponse) -> dict[str, Any]:
    interval = (
        job.schedule.config.get("interval_seconds") if job.schedule.kind.value == "every" else None
    )
    return {
        "id": job.id,
        "name": job.name,
        "enabled": job.enabled,
        "revision": job.revision,
        "interval_seconds": interval,
    }


async def schedules(
    ctx: "PackageOperationContext", payload: dict[str, Any], _progress: "Progress | None"
) -> dict[str, Any]:
    query = PageQuery.model_validate(payload)
    project = ctx.scope.project_id
    async with cron_authority(ctx.request, ctx.user, ctx.db, project, _scope(ctx)) as authority:
        result = await cron.list_cron_jobs(project, True, 32, query.offset, authority)
    return {"items": [_row(job) for job in result.items], "total": result.total}


async def save_schedule(
    ctx: "PackageOperationContext", payload: dict[str, Any], _progress: "Progress | None"
) -> dict[str, Any]:
    edit = ScheduleEdit.model_validate(payload)
    project = ctx.scope.project_id
    if (edit.job_id is None) != (edit.expected_revision is None):
        raise HTTPException(422, _("A schedule edit requires its current revision"))
    values = {
        "name": edit.name,
        "enabled": edit.enabled,
        "schedule": {"kind": "every", "config": {"interval_seconds": edit.interval_seconds}},
        "idempotency_key": edit.idempotency_key,
    }
    async with cron_authority(ctx.request, ctx.user, ctx.db, project, _scope(ctx)) as authority:
        if edit.job_id is None:
            create = CronJobCreate.model_validate(
                {
                    **values,
                    "payload": {"kind": "system_event", "config": {"content": edit.name}},
                }
            )
            job = await cron.create_cron_job(project, create, authority)
        else:
            update = CronJobUpdate.model_validate(
                {**values, "expected_revision": edit.expected_revision}
            )
            job = await cron.update_cron_job(project, edit.job_id, update, authority)
    return _row(job)


async def run_schedule(
    ctx: "PackageOperationContext", payload: dict[str, Any], _progress: "Progress | None"
) -> dict[str, Any]:
    run = Revision.model_validate(payload)
    project = ctx.scope.project_id
    body = AutomationRunCommandV2(
        contract_version=2,
        expected_revision=run.expected_revision,
        idempotency_key=run.idempotency_key,
    )
    async with cron_authority(ctx.request, ctx.user, ctx.db, project, _scope(ctx)) as authority:
        receipt = await cron.trigger_manual_run(project, run.job_id, body, authority)
    return receipt.model_dump(
        mode="json", include={"run_id", "job_id", "job_revision", "status", "duplicate"}
    )


SCHEDULE_OPERATIONS: dict[str, "Operation"] = {
    "app.automation.schedules.read": schedules,
    "app.automation.schedules.write": save_schedule,
    "app.automation.schedules.run": run_schedule,
}
