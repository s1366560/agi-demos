"""Prepared-bound local cron schedule closure, never deployment verification.

Only scheduler-service writers in this process are serialized here. The shared
scheduler context, queued jobs, admitted executions and HITL state stay alive.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from src.infrastructure.adapters.secondary.persistence.sql_cron_cutover_repository import (
    CronCutoverConflictError,
    SqlCronCutoverRepository,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from apscheduler import Schedule, Task

CRON_TASK_REFERENCE = "src.infrastructure.scheduler.job_executor:execute_cron_job"


@dataclass(frozen=True, kw_only=True)
class CronProducerCloseRequest:
    deployment_id: str
    source_generation: str
    producer_id: str
    expected_revision: int
    schedule_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self.expected_revision) is not int or self.expected_revision < 1:
            raise ValueError("invalid prepared deployment revision")
        if not isinstance(self.schedule_ids, tuple) or len(self.schedule_ids) > 10000:
            raise ValueError("invalid explicit cron schedule identities")
        for value in (
            self.deployment_id,
            self.source_generation,
            self.producer_id,
            *self.schedule_ids,
        ):
            if not isinstance(value, str) or not value.strip() or len(value) > 255:
                raise ValueError("invalid local cron producer identity")
        if len(set(self.schedule_ids)) != len(self.schedule_ids):
            raise ValueError("duplicate cron schedule identities")


@dataclass(frozen=True, kw_only=True)
class CronProducerCloseObservation:
    request: CronProducerCloseRequest
    observation: Literal["closed", "unresolved"]
    reason_code: str
    removed_schedule_ids: tuple[str, ...] = ()
    absent_schedule_ids: tuple[str, ...] = ()

    def to_wire(self) -> dict[str, object]:
        return {
            "protocol": "cron-local-producer-close.v1",
            "boundary": "local_cron_schedule_production",
            "verified": False,
            "deployment_id": self.request.deployment_id,
            "source_generation": self.request.source_generation,
            "producer_id": self.request.producer_id,
            "cutover_revision": self.request.expected_revision,
            "schedule_ids": list(self.request.schedule_ids),
            "removed_schedule_ids": list(self.removed_schedule_ids),
            "absent_schedule_ids": list(self.absent_schedule_ids),
            "observation": self.observation,
            "reason_code": self.reason_code,
        }


async def _require_prepared(request: CronProducerCloseRequest) -> None:
    from src.infrastructure.adapters.secondary.persistence.database import async_session_factory

    async with async_session_factory() as session:
        await SqlCronCutoverRepository(session).require_prepared_deployment(
            deployment_id=request.deployment_id,
            source_generation=request.source_generation,
            expected_revision=request.expected_revision,
            producer_id=request.producer_id,
        )


def _owned(schedule: Schedule, tasks: Mapping[str, Task]) -> bool:
    task = tasks.get(schedule.task_id)
    return (
        schedule.task_id == CRON_TASK_REFERENCE
        and task is not None
        and task.func == CRON_TASK_REFERENCE
        and not schedule.args
        and schedule.kwargs == {"job_id": schedule.id}
    )


def _cron_candidate(schedule: Schedule, tasks: Mapping[str, Task]) -> bool:
    task = tasks.get(schedule.task_id)
    return schedule.task_id == CRON_TASK_REFERENCE or (
        task is not None and task.func == CRON_TASK_REFERENCE
    )


async def _close_locked(
    request: CronProducerCloseRequest,
    removed: list[str],
    absent: list[str],
) -> str:
    from apscheduler import ScheduleLookupError

    from src.infrastructure.scheduler import scheduler_service

    async with scheduler_service._scheduler_lock:
        scheduler = scheduler_service._scheduler
        if scheduler is None:
            return "local_scheduler_unavailable"
        if scheduler.identity != request.producer_id:
            return "local_producer_identity_mismatch"
        await _require_prepared(request)
        # This latch survives cancellation, failures and a local stop/start.
        # Only a later explicit persisted Python/unverified revision can reopen it.
        scheduler_service._cron_registration_seal = (
            request.deployment_id,
            request.expected_revision,
        )
        tasks = {task.id: task for task in await scheduler.get_tasks()}
        schedules = {schedule.id: schedule for schedule in await scheduler.get_schedules()}
        for identity in request.schedule_ids:
            schedule = schedules.get(identity)
            if schedule is not None and not _owned(schedule, tasks):
                return "requested_schedule_not_owned"
        for identity in request.schedule_ids:
            await _require_prepared(request)
            # Re-read identity immediately before the narrow APScheduler API call.
            try:
                schedule = await scheduler.get_schedule(identity)
            except ScheduleLookupError:
                absent.append(identity)
                continue
            tasks = {task.id: task for task in await scheduler.get_tasks()}
            if not _owned(schedule, tasks):
                return "requested_schedule_not_owned"
            await scheduler.remove_schedule(identity)
            removed.append(identity)
        # A changed barrier or any remaining cron schedule cannot report closed.
        await _require_prepared(request)
        tasks = {task.id: task for task in await scheduler.get_tasks()}
        remaining = await scheduler.get_schedules()
        if any(
            _cron_candidate(schedule, tasks) or schedule.id in request.schedule_ids
            for schedule in remaining
        ):
            return "local_cron_schedules_remaining"
        await _require_prepared(request)
        return "local_cron_schedules_closed"


async def close_local_cron_producer(
    request: CronProducerCloseRequest,
) -> CronProducerCloseObservation:
    """Return only a local observation; cancellation is an unresolved operation.

    Callers supply explicit schedule IDs and the current scheduler identity from
    deployment discovery. This never records a deployment receipt or changes the
    barrier. Cancellation stops this operation and never reopens registration.
    """
    removed: list[str] = []
    absent: list[str] = []
    try:
        reason = await _close_locked(request, removed, absent)
    except asyncio.CancelledError:
        reason = "local_close_cancelled"
    except CronCutoverConflictError:
        reason = "prepared_deployment_changed"
    except Exception:
        # No datastore messages or connection details belong in observations.
        reason = "local_close_unavailable"
    return CronProducerCloseObservation(
        request=request,
        observation="closed" if reason == "local_cron_schedules_closed" else "unresolved",
        reason_code=reason,
        removed_schedule_ids=tuple(removed),
        absent_schedule_ids=tuple(absent),
    )
