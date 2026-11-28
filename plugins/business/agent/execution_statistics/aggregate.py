"""Summarize compact, anonymized execution history rows for a project conversation."""

from collections import Counter, defaultdict
from typing import Any

BUCKET_MINUTES = 60


def summarize(
    rows: list[list[int | None]], *, legacy_terminal_counts: bool = False
) -> dict[str, Any]:
    completed_slots = (0,) if legacy_terminal_counts else (0, 2)
    failed_slots = (1,) if legacy_terminal_counts else (1, 3)
    statuses: Counter[int] = Counter()
    tools: Counter[int] = Counter()
    buckets: dict[int, list[int]] = defaultdict(lambda: [0, 0, 0])
    elapsed = 0
    timed = 0
    for status, tool, minute, microseconds in rows:
        if status is None:
            raise ValueError("missing execution status slot")
        statuses[status] += 1
        if tool is not None:
            tools[tool] += 1
        if minute is not None:
            counts = buckets[minute - minute % BUCKET_MINUTES]
            counts[0] += 1
            counts[1] += int(status in completed_slots)
            counts[2] += int(status in failed_slots)
        if microseconds is not None:
            elapsed += microseconds
            timed += 1
    return {
        "completed_count": sum(statuses[slot] for slot in completed_slots),
        "failed_count": sum(statuses[slot] for slot in failed_slots),
        "status_counts": [[key, count] for key, count in statuses.items()],
        "tool_counts": [[key, count] for key, count in tools.items()],
        "time_buckets": [[key, *counts] for key, counts in sorted(buckets.items())],
        "average_duration_ms": (elapsed / timed / 1000) if timed else 0.0,
    }
