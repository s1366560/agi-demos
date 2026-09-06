"""APScheduler 4.x integration for MemStack cron jobs.

Provides a thin wrapper around ``AsyncScheduler`` that:
- Uses the existing PostgreSQL engine (from ``database.py``) as the data store.
- Uses Redis (from settings) as the event broker for multi-worker coordination.
- Exposes ``register_job`` / ``unregister_job`` to keep APScheduler schedules
  in sync with the ``cron_jobs`` table.
- Integrates with FastAPI lifespan (start / stop).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from src.configuration.config import get_settings
from src.infrastructure.scheduler.scheduler_owner import SchedulerOwner

if TYPE_CHECKING:
    from apscheduler import AsyncScheduler

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_scheduler: AsyncScheduler | None = None
_scheduler_owner: SchedulerOwner | None = None
_scheduler_lock = asyncio.Lock()


def get_scheduler() -> AsyncScheduler:
    """Return the running scheduler or raise."""
    if _scheduler is None:
        raise RuntimeError("Scheduler not initialised -- call start_scheduler() first")
    return _scheduler


# ---------------------------------------------------------------------------
# Lifecycle helpers (called from FastAPI lifespan)
# ---------------------------------------------------------------------------


async def start_scheduler() -> AsyncScheduler:
    """Create, configure and start the APScheduler ``AsyncScheduler``.

    The scheduler is stored as a module-level singleton so that routers and
    the job executor can access it via ``get_scheduler()``.
    """
    global _scheduler, _scheduler_owner

    async with _scheduler_lock:
        if _scheduler is not None:
            return _scheduler
        if _scheduler_owner is not None:
            previous_owner = _scheduler_owner
            try:
                await previous_owner.close()
            finally:
                if previous_owner.finished and _scheduler_owner is previous_owner:
                    _scheduler_owner = None
        # Lazy imports so the module can be loaded without APScheduler installed.
        from apscheduler import AsyncScheduler
        from apscheduler.datastores.sqlalchemy import SQLAlchemyDataStore
        from apscheduler.eventbrokers.redis import RedisEventBroker

        from src.infrastructure.adapters.secondary.persistence.database import (
            engine,
        )

        settings = get_settings()

        # --- Data store (reuses the existing async engine) ---------------------
        data_store = SQLAlchemyDataStore(engine)

        # --- Event broker (Redis) ---------------------------------------------
        event_broker = RedisEventBroker(settings.redis_url)

        # --- Build scheduler ---------------------------------------------------
        scheduler = AsyncScheduler(
            data_store=data_store,
            event_broker=event_broker,
        )

        owner = SchedulerOwner(scheduler)
        _scheduler_owner = owner
        try:
            _scheduler = await owner.start()
        except BaseException:
            # Startup cancellation still drains resources in the task that entered them.
            try:
                await owner.close()
            finally:
                if owner.finished and _scheduler_owner is owner:
                    _scheduler_owner = None
            raise
        logger.info("APScheduler started (PostgreSQL + Redis)")
        return _scheduler


async def stop_scheduler() -> None:
    """Gracefully shut down the scheduler."""
    global _scheduler, _scheduler_owner

    async with _scheduler_lock:
        owner = _scheduler_owner
        if owner is None:
            return
        # Revoke use immediately; a cancelled waiter must not expose a draining scheduler.
        _scheduler = None
        try:
            await owner.close()
        finally:
            if owner.finished and _scheduler_owner is owner:
                _scheduler_owner = None
        logger.info("APScheduler stopped")


# ---------------------------------------------------------------------------
# Job synchronisation helpers
# ---------------------------------------------------------------------------


async def register_job(
    *,
    job_id: str,
    schedule_type: str,
    schedule_config: dict[str, Any],
    timezone: str = "UTC",
) -> None:
    """Add or replace an APScheduler schedule for a cron job.

    Translates the domain ``CronSchedule`` representation into the matching
    APScheduler trigger and registers (or replaces) it under the given
    *job_id*.
    """
    from apscheduler import ConflictPolicy
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.date import DateTrigger
    from apscheduler.triggers.interval import IntervalTrigger

    from src.domain.model.cron.value_objects import CronSchedule, ScheduleType
    from src.infrastructure.scheduler.job_executor import execute_cron_job

    scheduler = get_scheduler()

    try:
        schedule = CronSchedule(
            kind=ScheduleType(schedule_type),
            config=schedule_config,
        )
    except ValueError as exc:
        logger.error(
            "Invalid schedule config for job %s (%s): %s",
            job_id,
            schedule_type,
            exc,
        )
        return

    schedule_type = schedule.kind.value
    schedule_config = schedule.config

    trigger: CronTrigger | IntervalTrigger | DateTrigger
    tz = schedule_config.get("timezone") or timezone

    if schedule_type == "cron":
        trigger = CronTrigger.from_crontab(
            schedule_config["expr"],
            timezone=tz,
        )
    elif schedule_type == "every":
        trigger = IntervalTrigger(
            seconds=int(schedule_config["interval_seconds"]),
        )
    elif schedule_type == "at":
        trigger = DateTrigger(
            run_time=schedule_config["run_at"],
        )
    else:
        logger.error("Unknown schedule type %s for job %s", schedule_type, job_id)
        return

    _ = await scheduler.add_schedule(
        execute_cron_job,
        trigger,
        id=job_id,
        kwargs={"job_id": job_id},
        conflict_policy=ConflictPolicy.replace,
    )
    logger.info("Registered APScheduler schedule for job %s (%s)", job_id, schedule_type)


async def unregister_job(job_id: str) -> None:
    """Remove an APScheduler schedule for a cron job (idempotent)."""
    scheduler = get_scheduler()
    try:
        await scheduler.remove_schedule(job_id)
        logger.info("Unregistered APScheduler schedule for job %s", job_id)
    except Exception:
        # Schedule may not exist (already removed, never registered, etc.)
        logger.debug("Schedule %s not found in APScheduler -- nothing to remove", job_id)


async def sync_all_jobs() -> None:
    """Load all enabled cron jobs from the DB and register them in APScheduler.

    Called once at startup to hydrate the scheduler with existing schedules.
    """
    from src.infrastructure.adapters.secondary.persistence.database import (
        async_session_factory,
    )
    from src.infrastructure.adapters.secondary.persistence.sql_cron_job_repository import (
        SqlCronJobRepository,
    )

    async with async_session_factory() as session:
        repo = SqlCronJobRepository(session)
        # find_due_jobs returns enabled jobs not in backoff
        jobs = await repo.find_due_jobs(now=datetime.now(UTC))

    registered = 0
    for job in jobs:
        try:
            await register_job(
                job_id=job.id,
                schedule_type=job.schedule.kind.value,
                schedule_config=job.schedule.config,
                timezone=job.timezone,
            )
            registered += 1
        except Exception:
            logger.exception("Failed to register schedule for job %s", job.id)

    logger.info("Synced %d / %d cron jobs to APScheduler", registered, len(jobs))
