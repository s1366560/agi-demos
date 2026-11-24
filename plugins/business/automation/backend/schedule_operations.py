"""Revision-bound project schedule editing and durable manual dispatch for signed pages."""

from datetime import datetime
from typing import TYPE_CHECKING, Annotated, Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.triggers.cron import CronTrigger
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

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
    job_id: Identifier | None = None


class Revision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    job_id: Identifier
    expected_revision: int = Field(ge=1)
    idempotency_key: str = Field(min_length=1, max_length=255, pattern=r"^[!-~]+$")


class Every(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["every"]
    interval_seconds: int = Field(ge=1, le=31536000)


class At(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["at"]
    run_at: str = Field(min_length=1, max_length=64)

    @field_validator("run_at")
    @classmethod
    def validate_instant(cls, value: str) -> str:
        if datetime.fromisoformat(value).tzinfo is None:
            raise ValueError("An explicit time zone is required")
        return value


class Cron(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["cron"]
    expr: str = Field(min_length=1, max_length=256)
    timezone: str = Field(min_length=1, max_length=128)

    @field_validator("expr")
    @classmethod
    def validate_expression(cls, value: str) -> str:
        CronTrigger.from_crontab(value, timezone="UTC")
        return value

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("Unknown time zone") from exc
        return value


class ScheduleEdit(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    job_id: Identifier | None = None
    expected_revision: int | None = Field(None, ge=1)
    idempotency_key: str = Field(min_length=1, max_length=255, pattern=r"^[!-~]+$")
    name: Identifier
    enabled: bool
    interval_seconds: int | None = Field(None, ge=1, le=31536000)
    trigger: Annotated[At | Every | Cron, Field(discriminator="kind")] | None = None
    description: str | None = Field(None, max_length=1000)


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
        "description": job.description,
        "schedule": job.schedule.model_dump(mode="json"),
        "timezone": job.timezone,
        "payload_kind": job.payload.kind.value,
        "interval_seconds": interval,
    }


async def schedules(
    ctx: "PackageOperationContext", payload: dict[str, Any], _progress: "Progress | None"
) -> dict[str, Any]:
    query = PageQuery.model_validate(payload)
    project = ctx.scope.project_id
    async with cron_authority(ctx.request, ctx.user, ctx.db, project, _scope(ctx)) as authority:
        if query.job_id:
            runs = await cron.list_cron_job_runs(project, query.job_id, 32, query.offset, authority)
            return {
                "items": [
                    run.model_dump(
                        mode="json",
                        include={
                            "id",
                            "status",
                            "trigger_type",
                            "started_at",
                            "finished_at",
                            "duration_ms",
                        },
                    )
                    for run in runs.items
                ],
                "total": runs.total,
            }
        result = await cron.list_cron_jobs(project, True, 32, query.offset, authority)
    return {"items": [_row(job) for job in result.items], "total": result.total}


async def save_schedule(
    ctx: "PackageOperationContext", payload: dict[str, Any], _progress: "Progress | None"
) -> dict[str, Any]:
    edit = ScheduleEdit.model_validate(payload)
    project = ctx.scope.project_id
    if (edit.job_id is None) != (edit.expected_revision is None):
        raise HTTPException(422, _("A schedule edit requires its current revision"))
    values: dict[str, Any] = {
        "name": edit.name,
        "enabled": edit.enabled,
        "idempotency_key": edit.idempotency_key,
    }
    if edit.description is not None:
        values["description"] = edit.description
    if edit.trigger and edit.interval_seconds is not None:
        raise HTTPException(422, _("Specify only one schedule"))
    trigger = edit.trigger
    if edit.interval_seconds is not None:
        trigger = Every(kind="every", interval_seconds=edit.interval_seconds)
    if trigger:
        values["schedule"] = {"kind": trigger.kind, "config": trigger.model_dump(exclude={"kind"})}
    if edit.job_id is None and not trigger:
        raise HTTPException(422, _("A schedule is required"))
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
