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

from .schedule_conversations import require_schedule_conversation, schedule_conversations

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
    limit: int = Field(32, ge=1, le=100)
    include_disabled: bool = True
    view: Literal["workbench", "capabilities", "job"] | None = None
    job_id: Identifier | None = None


class Revision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    job_id: Identifier
    expected_revision: int = Field(ge=1)
    idempotency_key: str = Field(min_length=1, max_length=255, pattern=r"^[!-~]+$")


class RunRevision(Revision):
    conversation_id: Identifier | None = None


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


class JobAction(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["system_event", "agent_turn"]
    text: str = Field(min_length=1, max_length=32768)


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
    action: JobAction | None = None
    delete_after_run: bool | None = None
    timezone: str | None = Field(None, min_length=1, max_length=128)
    conversation_id: Identifier | None = None
    conversation_mode: Literal["fresh", "reuse"] | None = None
    delivery_kind: Literal["none", "announce", "webhook"] | None = None
    stagger_seconds: int | None = Field(None, ge=0)
    timeout_seconds: int | None = Field(None, ge=1)
    max_retries: int | None = Field(None, ge=0)


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
        "action_text": job.payload.config.get(
            "message" if job.payload.kind.value == "agent_turn" else "content"
        ),
        "delivery_kind": job.delivery.kind.value,
        "delete_after_run": job.delete_after_run,
        "conversation_mode": job.conversation_mode.value,
        "timeout_seconds": job.timeout_seconds,
        "max_retries": job.max_retries,
        "interval_seconds": interval,
    }


def _workbench_job(job: CronJobResponse) -> dict[str, Any]:
    # Retain the original editor fields and keep provider and delivery credentials in the authority.
    public = job.model_dump(mode="json", exclude={"payload", "delivery", "state"})
    key = "message" if job.payload.kind.value == "agent_turn" else "content"
    public.update(
        payload={"kind": job.payload.kind.value, "config": {key: job.payload.config.get(key)}},
        delivery={"kind": job.delivery.kind.value, "config": {}},
        state={},
    )
    return public


async def schedules(
    ctx: "PackageOperationContext", payload: dict[str, Any], _progress: "Progress | None"
) -> dict[str, Any]:
    query = PageQuery.model_validate(payload)
    project = ctx.scope.project_id
    async with cron_authority(ctx.request, ctx.user, ctx.db, project, _scope(ctx)) as authority:
        if query.view == "capabilities":
            return (await cron.get_cron_job_capabilities(project, authority)).model_dump()
        if query.view == "job":
            if not query.job_id:
                raise HTTPException(422, _("A schedule ID is required"))
            return _workbench_job(await cron.get_cron_job(project, query.job_id, authority))
        if query.job_id:
            runs = await cron.list_cron_job_runs(
                project, query.job_id, query.limit, query.offset, authority
            )
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
                            *(
                                ("error_message", "conversation_id", "job_id", "project_id")
                                if query.view == "workbench"
                                else ()
                            ),
                        },
                    )
                    for run in runs.items
                ],
                "total": runs.total,
            }
        result = await cron.list_cron_jobs(
            project, query.include_disabled, query.limit, query.offset, authority
        )
    project_row = _workbench_job if query.view == "workbench" else _row
    return {"items": [project_row(job) for job in result.items], "total": result.total}


def _edit_fields(edit: ScheduleEdit) -> dict[str, Any]:
    values: dict[str, Any] = {
        "name": edit.name,
        "enabled": edit.enabled,
        "idempotency_key": edit.idempotency_key,
    }
    values.update(
        edit.model_dump(
            include={
                "description",
                "delete_after_run",
                "conversation_mode",
                "timezone",
                "conversation_id",
                "stagger_seconds",
                "timeout_seconds",
                "max_retries",
            },
            exclude_none=True,
        )
    )
    if edit.timezone:
        Cron.validate_timezone(edit.timezone)
    if edit.action:
        field = "message" if edit.action.kind == "agent_turn" else "content"
        values["payload"] = {"kind": edit.action.kind, "config": {field: edit.action.text}}
    if edit.delivery_kind:
        values["delivery"] = {"kind": edit.delivery_kind, "config": {}}
    if edit.trigger and edit.interval_seconds is not None:
        raise HTTPException(422, _("Specify only one schedule"))
    trigger = edit.trigger
    if edit.interval_seconds is not None:
        trigger = Every(kind="every", interval_seconds=edit.interval_seconds)
    if trigger:
        values["schedule"] = {"kind": trigger.kind, "config": trigger.model_dump(exclude={"kind"})}
    if edit.job_id is None and not trigger:
        raise HTTPException(422, _("A schedule is required"))
    return values


async def save_schedule(
    ctx: "PackageOperationContext", payload: dict[str, Any], _progress: "Progress | None"
) -> dict[str, Any]:
    edit = ScheduleEdit.model_validate(payload)
    project = ctx.scope.project_id
    if (edit.job_id is None) != (edit.expected_revision is None):
        raise HTTPException(422, _("A schedule edit requires its current revision"))
    if edit.conversation_id:
        await require_schedule_conversation(ctx, edit.conversation_id)
    values = _edit_fields(edit)
    async with cron_authority(ctx.request, ctx.user, ctx.db, project, _scope(ctx)) as authority:
        if edit.job_id is None:
            create = CronJobCreate.model_validate(
                {
                    "payload": {"kind": "system_event", "config": {"content": edit.name}},
                    **values,
                }
            )
            job = await cron.create_cron_job(project, create, authority)
        else:
            if edit.action or edit.delivery_kind:
                previous = await authority.services.cron_jobs.get_job(edit.job_id)
                if (
                    edit.action
                    and previous
                    and previous.project_id == project
                    and previous.payload.kind.value == edit.action.kind
                ):
                    values["payload"]["config"] = {
                        **previous.payload.config,
                        **values["payload"]["config"],
                    }
                if (
                    previous
                    and previous.project_id == project
                    and previous.delivery.kind.value == edit.delivery_kind
                ):
                    values["delivery"]["config"] = dict(previous.delivery.config)
            update = CronJobUpdate.model_validate(
                {**values, "expected_revision": edit.expected_revision}
            )
            job = await cron.update_cron_job(project, edit.job_id, update, authority)
    return _row(job)


async def run_schedule(
    ctx: "PackageOperationContext", payload: dict[str, Any], _progress: "Progress | None"
) -> dict[str, Any]:
    run = RunRevision.model_validate(payload)
    if run.conversation_id:
        await require_schedule_conversation(ctx, run.conversation_id)
    project = ctx.scope.project_id
    body = AutomationRunCommandV2(
        contract_version=2,
        conversation_id=run.conversation_id,
        expected_revision=run.expected_revision,
        idempotency_key=run.idempotency_key,
    )
    async with cron_authority(ctx.request, ctx.user, ctx.db, project, _scope(ctx)) as authority:
        receipt = await cron.trigger_manual_run(project, run.job_id, body, authority)
    return receipt.model_dump(
        mode="json",
        include={"receipt_id", "run_id", "job_id", "job_revision", "status", "duplicate"},
    )


async def delete_schedule(
    ctx: "PackageOperationContext", payload: dict[str, Any], _progress: "Progress | None"
) -> dict[str, Any]:
    edit = Revision.model_validate(payload)
    project = ctx.scope.project_id
    async with cron_authority(ctx.request, ctx.user, ctx.db, project, _scope(ctx)) as authority:
        await cron.delete_cron_job(
            project, edit.job_id, edit.expected_revision, edit.idempotency_key, authority
        )
    return {"id": edit.job_id}


SCHEDULE_OPERATIONS: dict[str, "Operation"] = {
    "app.automation.schedules.read": schedules,
    "app.automation.conversations.read": schedule_conversations,
    "app.automation.schedules.write": save_schedule,
    "app.automation.schedules.run": run_schedule,
    "app.automation.schedules.delete": delete_schedule,
}
