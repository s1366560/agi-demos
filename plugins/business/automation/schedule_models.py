"""Schedule command models. This module does not open the relational store."""

from datetime import datetime
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.triggers.cron import CronTrigger
from pydantic import BaseModel, ConfigDict, Field, field_validator

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
