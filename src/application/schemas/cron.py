"""Pydantic schemas for cron job API requests and responses."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from src.domain.model.cron.cron_job import CronJob
from src.domain.model.cron.cron_job_run import CronJobRun
from src.domain.model.cron.value_objects import (
    ConversationMode,
    CronDelivery,
    CronPayload,
    CronSchedule,
    DeliveryType,
    PayloadType,
    ScheduleType,
)

# ---------------------------------------------------------------------------
# Nested config schemas
# ---------------------------------------------------------------------------


class ScheduleConfig(BaseModel):
    """Schedule configuration for a cron job."""

    kind: ScheduleType = Field(..., description="Schedule type: at | every | cron")
    config: dict[str, Any] = Field(
        default_factory=dict,
        description="Type-specific config (see CronSchedule docs)",
    )


class PayloadConfig(BaseModel):
    """Payload configuration for a cron job."""

    kind: PayloadType = Field(..., description="Payload type: system_event | agent_turn")
    config: dict[str, Any] = Field(
        default_factory=dict,
        description="Type-specific config (see CronPayload docs)",
    )


class DeliveryConfig(BaseModel):
    """Delivery configuration for a cron job."""

    kind: DeliveryType = Field(
        default=DeliveryType.NONE,
        description="Delivery type: none | announce | webhook",
    )
    config: dict[str, Any] = Field(
        default_factory=dict,
        description="Type-specific config (see CronDelivery docs)",
    )


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class CronJobCreate(BaseModel):
    """Request body for creating a cron job."""

    name: str = Field(..., description="Human-readable job name", min_length=1, max_length=255)
    description: str | None = Field(
        default=None, description="Optional longer description", max_length=1000
    )
    enabled: bool = Field(default=True, description="Whether the job is enabled")
    delete_after_run: bool = Field(
        default=False,
        description="Delete the job after its first successful run",
    )
    schedule: ScheduleConfig = Field(..., description="When the job fires")
    payload: PayloadConfig = Field(..., description="What the job does")
    delivery: DeliveryConfig = Field(
        default_factory=lambda: DeliveryConfig(kind=DeliveryType.NONE),
        description="How the result is delivered",
    )
    conversation_mode: ConversationMode = Field(
        default=ConversationMode.REUSE,
        description="Reuse existing conversation or create a fresh one",
    )
    conversation_id: str | None = Field(
        default=None, description="Conversation to reuse (when mode == reuse)"
    )
    timezone: str = Field(default="UTC", description="IANA timezone")
    stagger_seconds: int = Field(default=0, ge=0, description="Deterministic per-job offset")
    timeout_seconds: int = Field(default=300, ge=1, description="Max execution time per run")
    max_retries: int = Field(
        default=3, ge=0, description="Max consecutive failures before disabling"
    )


class CronJobUpdate(BaseModel):
    """Request body for updating a cron job (partial update)."""

    name: str | None = Field(default=None, description="Job name", min_length=1, max_length=255)
    description: str | None = Field(default=None, description="Job description", max_length=1000)
    enabled: bool | None = Field(default=None, description="Enable/disable")
    delete_after_run: bool | None = Field(default=None, description="Delete after run")
    schedule: ScheduleConfig | None = Field(default=None, description="Schedule config")
    payload: PayloadConfig | None = Field(default=None, description="Payload config")
    delivery: DeliveryConfig | None = Field(default=None, description="Delivery config")
    conversation_mode: ConversationMode | None = Field(
        default=None, description="Conversation mode"
    )
    conversation_id: str | None = Field(default=None, description="Conversation ID for reuse mode")
    timezone: str | None = Field(default=None, description="IANA timezone")
    stagger_seconds: int | None = Field(default=None, ge=0, description="Stagger offset")
    timeout_seconds: int | None = Field(default=None, ge=1, description="Timeout per run")
    max_retries: int | None = Field(default=None, ge=0, description="Max retries")


class ManualRunRequest(BaseModel):
    """Request body for manually triggering a cron job."""

    conversation_id: str | None = Field(
        default=None,
        description="Override conversation ID for this run",
    )


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class CronJobResponse(BaseModel):
    """Response schema for a single cron job."""

    id: str = Field(..., description="Job ID")
    project_id: str = Field(..., description="Project ID")
    tenant_id: str = Field(..., description="Tenant ID")
    name: str = Field(..., description="Job name")
    description: str | None = Field(default=None, description="Description")
    enabled: bool = Field(..., description="Whether enabled")
    delete_after_run: bool = Field(..., description="Delete after run flag")
    schedule: ScheduleConfig = Field(..., description="Schedule configuration")
    payload: PayloadConfig = Field(..., description="Payload configuration")
    delivery: DeliveryConfig = Field(..., description="Delivery configuration")
    conversation_mode: ConversationMode = Field(..., description="Conversation mode")
    conversation_id: str | None = Field(default=None, description="Conversation ID")
    timezone: str = Field(..., description="IANA timezone")
    stagger_seconds: int = Field(..., description="Stagger offset")
    timeout_seconds: int = Field(..., description="Timeout per run")
    max_retries: int = Field(..., description="Max retries")
    state: dict[str, Any] = Field(default_factory=dict, description="Runtime state")
    created_by: str | None = Field(default=None, description="Creator user ID")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime | None = Field(default=None, description="Last update timestamp")


class CronJobListResponse(BaseModel):
    """Response schema for listing cron jobs."""

    items: list[CronJobResponse] = Field(..., description="Cron jobs")
    total: int = Field(..., description="Total count")


class CronJobRunResponse(BaseModel):
    """Response schema for a single cron job run."""

    id: str = Field(..., description="Run ID")
    job_id: str = Field(..., description="Parent job ID")
    project_id: str = Field(..., description="Project ID")
    status: str = Field(..., description="Run status")
    trigger_type: str = Field(..., description="Trigger type")
    started_at: datetime = Field(..., description="Start timestamp")
    finished_at: datetime | None = Field(default=None, description="Finish timestamp")
    duration_ms: int | None = Field(default=None, description="Duration in ms")
    error_message: str | None = Field(default=None, description="Error message")
    result_summary: dict[str, Any] = Field(default_factory=dict, description="Result summary")
    conversation_id: str | None = Field(default=None, description="Conversation ID used")


class CronJobRunListResponse(BaseModel):
    """Response schema for listing cron job runs."""

    items: list[CronJobRunResponse] = Field(..., description="Runs")
    total: int = Field(..., description="Total count")


# ---------------------------------------------------------------------------
# Domain <-> Schema conversion helpers
# ---------------------------------------------------------------------------


def schedule_config_to_domain(cfg: ScheduleConfig) -> CronSchedule:
    """Convert a ScheduleConfig schema to a CronSchedule value object."""
    return CronSchedule(kind=cfg.kind, config=cfg.config)


def payload_config_to_domain(cfg: PayloadConfig) -> CronPayload:
    """Convert a PayloadConfig schema to a CronPayload value object."""
    return CronPayload(kind=cfg.kind, config=cfg.config)


def delivery_config_to_domain(cfg: DeliveryConfig) -> CronDelivery:
    """Convert a DeliveryConfig schema to a CronDelivery value object."""
    return CronDelivery(kind=cfg.kind, config=cfg.config)


def cron_job_to_response(job: CronJob) -> CronJobResponse:
    """Convert a CronJob domain entity to a CronJobResponse."""
    return CronJobResponse(
        id=job.id,
        project_id=job.project_id,
        tenant_id=job.tenant_id,
        name=job.name,
        description=job.description,
        enabled=job.enabled,
        delete_after_run=job.delete_after_run,
        schedule=ScheduleConfig(kind=job.schedule.kind, config=job.schedule.config),
        payload=PayloadConfig(kind=job.payload.kind, config=job.payload.config),
        delivery=DeliveryConfig(kind=job.delivery.kind, config=job.delivery.config),
        conversation_mode=job.conversation_mode,
        conversation_id=job.conversation_id,
        timezone=job.timezone,
        stagger_seconds=job.stagger_seconds,
        timeout_seconds=job.timeout_seconds,
        max_retries=job.max_retries,
        state=job.state,
        created_by=job.created_by,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


def cron_job_run_to_response(run: CronJobRun) -> CronJobRunResponse:
    """Convert a CronJobRun domain entity to a CronJobRunResponse."""
    return CronJobRunResponse(
        id=run.id,
        job_id=run.job_id,
        project_id=run.project_id,
        status=run.status.value,
        trigger_type=run.trigger_type.value,
        started_at=run.started_at,
        finished_at=run.finished_at,
        duration_ms=run.duration_ms,
        error_message=run.error_message,
        result_summary=run.result_summary,
        conversation_id=run.conversation_id,
    )
