"""Machine-readable promotion gate for staged plugin shadow rollouts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

REQUIRED_SHADOW_EVENTS: frozenset[tuple[str, str]] = frozenset(
    {
        ("agent_events", "agent.before_step"),
        ("agent_events", "agent.before_request"),
        ("agent_events", "tools.before_execute"),
        ("agent_events", "tools.after_execute"),
        ("agent_events", "agent.after_turn"),
        ("agent_tools", "agent.tool_generation"),
    }
)


@dataclass(frozen=True)
class ShadowRolloutCapabilityReadiness:
    """Promotion evidence for one cutover capability."""

    capability: str
    ready: bool
    total_count: int
    equal_count: int
    diff_count: int
    distinct_scope_count: int
    observed_event_count: int
    required_event_count: int
    last_occurred_at: datetime | None
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class ShadowRolloutReadiness:
    """Whether both staged capabilities have sufficient zero-diff evidence."""

    ready: bool
    checked_at: datetime
    minimum_samples_per_event: int
    minimum_distinct_scopes: int
    maximum_evidence_age_seconds: int
    capabilities: tuple[ShadowRolloutCapabilityReadiness, ...]
    reasons: tuple[str, ...]


def evaluate_shadow_rollout_readiness(
    *,
    summary: Sequence[Mapping[str, Any]],
    scope_counts: Sequence[Mapping[str, Any]],
    checked_at: datetime | None = None,
    minimum_samples_per_event: int = 100,
    minimum_distinct_scopes: int = 10,
    maximum_evidence_age_seconds: int = 900,
) -> ShadowRolloutReadiness:
    """Evaluate durable evidence without inferring success from silence.

    Every required legacy/typed event must be present at the requested sample
    volume, contain zero durable differences, cover independent scopes, and be
    recent. The result is deliberately advisory to the operator API; process
    feature flags remain the actual cutover switch and can still roll back.
    """
    normalized_checked_at = (checked_at or datetime.now(UTC)).astimezone(UTC)
    summary_by_key = {(str(row["capability"]), str(row["event_name"])): row for row in summary}
    counts_by_capability = {
        str(row["capability"]): max(0, int(row["distinct_scope_count"])) for row in scope_counts
    }
    capabilities: list[ShadowRolloutCapabilityReadiness] = []

    for capability in sorted({key[0] for key in REQUIRED_SHADOW_EVENTS}):
        required_events = sorted(
            event for item, event in REQUIRED_SHADOW_EVENTS if item == capability
        )
        rows = [summary_by_key.get((capability, event)) for event in required_events]
        present_rows = [row for row in rows if row is not None]
        total_count = sum(max(0, int(row["total_count"])) for row in present_rows)
        equal_count = sum(max(0, int(row["equal_count"])) for row in present_rows)
        diff_count = sum(max(0, int(row["diff_count"])) for row in present_rows)
        last_occurred_values = [
            _normalize_datetime(row["last_occurred_at"])
            for row in present_rows
            if row.get("last_occurred_at") is not None
        ]
        last_occurred_at = max(last_occurred_values) if last_occurred_values else None
        last_occurred_by_event = {
            event: _normalize_datetime(row["last_occurred_at"])
            for row, event in zip(rows, required_events, strict=True)
            if row is not None and row.get("last_occurred_at") is not None
        }
        reasons: list[str] = []

        for row, event in zip(rows, required_events, strict=True):
            if row is None:
                reasons.append(f"missing_event:{event}")
            elif int(row["total_count"]) < minimum_samples_per_event:
                reasons.append(f"insufficient_samples:{event}")

        if diff_count != 0 or equal_count != total_count or total_count == 0:
            reasons.append("diffs_present")

        distinct_scope_count = counts_by_capability.get(capability, 0)
        if distinct_scope_count < minimum_distinct_scopes:
            reasons.append("insufficient_scope_coverage")

        if last_occurred_at is None:
            reasons.append("stale_evidence")
        else:
            for event, occurred_at in last_occurred_by_event.items():
                age_seconds = (normalized_checked_at - occurred_at).total_seconds()
                if age_seconds < 0 or age_seconds > maximum_evidence_age_seconds:
                    reasons.append(f"stale_evidence:{event}")

        capabilities.append(
            ShadowRolloutCapabilityReadiness(
                capability=capability,
                ready=not reasons,
                total_count=total_count,
                equal_count=equal_count,
                diff_count=diff_count,
                distinct_scope_count=distinct_scope_count,
                observed_event_count=len(present_rows),
                required_event_count=len(required_events),
                last_occurred_at=last_occurred_at,
                reasons=tuple(reasons),
            )
        )

    global_reasons = tuple(
        f"{item.capability}:{reason}" for item in capabilities for reason in item.reasons
    )
    return ShadowRolloutReadiness(
        ready=not global_reasons,
        checked_at=normalized_checked_at,
        minimum_samples_per_event=minimum_samples_per_event,
        minimum_distinct_scopes=minimum_distinct_scopes,
        maximum_evidence_age_seconds=maximum_evidence_age_seconds,
        capabilities=tuple(capabilities),
        reasons=global_reasons,
    )


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
