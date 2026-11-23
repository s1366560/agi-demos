"""Construct the same trigger for a persisted schedule and an isolated schedule preview."""

from collections.abc import Mapping
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger


def build_trigger(
    kind: str, config: Mapping[str, Any], *, timezone: str = "UTC", start: datetime | None = None
) -> CronTrigger | DateTrigger | IntervalTrigger:
    """Consume the canonical CronSchedule fields after admission."""
    if kind == "cron":
        zone = config.get("timezone") or timezone
        # APScheduler evaluates the start's clock fields in the trigger timezone.
        local_start = (
            start.astimezone(None if zone == "local" else ZoneInfo(zone)) if start else None
        )
        return CronTrigger.from_crontab(config["expr"], timezone=zone, start_time=local_start)
    if kind == "at":
        return DateTrigger(run_time=config["run_at"])
    if kind == "every":
        seconds = int(config["interval_seconds"])
        if seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        if start is None:
            return IntervalTrigger(seconds=seconds)
        return IntervalTrigger(seconds=seconds, start_time=start)
    raise ValueError("unsupported schedule type")


def next_scheduled_run(arguments: dict[str, Any]) -> dict[str, str | None]:
    start = datetime.fromisoformat(arguments["start"])
    if start.utcoffset() is None:
        raise ValueError("start must include its time zone")
    trigger = build_trigger(
        arguments["kind"],
        arguments["config"],
        timezone=arguments.get("timezone", "UTC"),
        start=start,
    )
    next_time = trigger.next()
    return {"next_run_at": next_time.isoformat() if next_time and next_time >= start else None}
