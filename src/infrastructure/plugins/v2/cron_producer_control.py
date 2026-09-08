"""Generation-owned access to one responding process and its shared scheduler view."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from src.infrastructure.scheduler.cron_deployment_drain import (
    CronProducerCloseObservation,
    CronProducerCloseRequest,
    _cron_candidate,
    _owned,
    close_local_cron_producer,
)

CRON_PRODUCER_CONTROL_SERVICE_V2 = "service:runtime.cron-producer-control"


@runtime_checkable
class CronProducerControlProtocolV2(Protocol):
    async def inspect_local(self) -> dict[str, object]: ...

    async def close_prepared(
        self, request: CronProducerCloseRequest
    ) -> CronProducerCloseObservation: ...


@dataclass(frozen=True, kw_only=True)
class BuiltinCronProducerControlV2:
    """Never start a scheduler or claim a complete deployment discovery result."""

    async def inspect_local(self) -> dict[str, object]:
        from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
        from src.infrastructure.adapters.secondary.persistence.sql_cron_cutover_repository import (
            SqlCronCutoverRepository,
        )
        from src.infrastructure.scheduler import scheduler_service

        async with scheduler_service._scheduler_lock:
            scheduler = scheduler_service._scheduler
            seal = scheduler_service._cron_registration_seal
            view: dict[str, object] = {
                "scope": "shared_scheduler_datastore",
                "status": "unavailable",
                "canonical_cron_schedule_ids": [],
                "unresolved_cron_schedule_ids": [],
            }
            result: dict[str, object] = {
                "protocol": "cron-local-producer-inspection.v1",
                "scope": "local_process",
                "verified": False,
                "discovery_complete": False,
                "responding_producer_id": scheduler.identity if scheduler is not None else None,
                "local_registration_sealed": seal is not None,
                "local_registration_seal": (
                    {"deployment_id": seal[0], "cutover_revision": seal[1]} if seal else None
                ),
                "datastore_view": view,
                "prepared_barrier": None,
                "reason_code": "local_scheduler_unavailable",
            }
            if scheduler is None:
                return result
            try:
                tasks = {task.id: task for task in await scheduler.get_tasks()}
                schedules = await scheduler.get_schedules()
                view["canonical_cron_schedule_ids"] = sorted(
                    schedule.id for schedule in schedules if _owned(schedule, tasks)
                )
                view["unresolved_cron_schedule_ids"] = sorted(
                    schedule.id
                    for schedule in schedules
                    if _cron_candidate(schedule, tasks) and not _owned(schedule, tasks)
                )
                view["status"] = "available"
                async with async_session_factory() as session:
                    state = await SqlCronCutoverRepository(session).read()
                result["prepared_barrier"] = state.to_wire()
                result["reason_code"] = "local_producer_inspected"
            except Exception:
                # Inspection is recovery state, never a receipt or a private error log.
                result["reason_code"] = "local_inspection_unavailable"
            return result

    async def close_prepared(
        self, request: CronProducerCloseRequest
    ) -> CronProducerCloseObservation:
        return await close_local_cron_producer(request)
