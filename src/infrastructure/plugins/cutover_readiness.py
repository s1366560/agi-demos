"""Fail-closed cutover gate combining shadow parity and rollback-drill evidence."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .rollout_readiness import ShadowRolloutReadiness


@dataclass(frozen=True)
class RollbackDrillDataPlaneReadiness:
    """Whether one data plane has an auditable ACK/NACK/restore sequence."""

    data_plane_id: str
    ready: bool
    last_recorded_at: datetime | None
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class RollbackDrillReadiness:
    """Whether enough data planes recorded a valid rollback drill."""

    ready: bool
    checked_at: datetime
    minimum_distinct_data_planes: int
    maximum_evidence_age_seconds: int
    data_planes: tuple[RollbackDrillDataPlaneReadiness, ...]
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class PlatformPluginCutoverReadiness:
    """The combined promotion gate for enabling V2 by default."""

    ready: bool
    checked_at: datetime
    shadow: ShadowRolloutReadiness
    rollback_drill: RollbackDrillReadiness
    reasons: tuple[str, ...]


def evaluate_rollback_drill_readiness(
    *,
    events: Sequence[Mapping[str, Any]],
    checked_at: datetime | None = None,
    minimum_distinct_data_planes: int = 1,
    maximum_evidence_age_seconds: int = 86_400,
) -> RollbackDrillReadiness:
    """Find a baseline ACK, invalid-config NACK, and forward restore ACK."""
    normalized_checked_at = (checked_at or datetime.now(UTC)).astimezone(UTC)
    events_by_plane: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for event in events:
        events_by_plane[str(event["data_plane_id"])].append(event)

    data_planes: list[RollbackDrillDataPlaneReadiness] = []
    for data_plane_id, plane_events in sorted(events_by_plane.items()):
        ordered = sorted(
            plane_events,
            key=lambda event: (
                _normalize_datetime(event["recorded_at"]),
                int(event["requested_version"]),
                str(event["id"]),
            ),
        )
        data_planes.append(
            _evaluate_data_plane_drill(
                data_plane_id=data_plane_id,
                ordered_events=ordered,
                checked_at=normalized_checked_at,
                maximum_evidence_age_seconds=maximum_evidence_age_seconds,
            )
        )

    ready_planes = [item for item in data_planes if item.ready]
    ready = len({item.data_plane_id for item in ready_planes}) >= minimum_distinct_data_planes
    global_reasons = (
        ()
        if ready
        else (f"insufficient_rollback_drills:{len(ready_planes)}:{minimum_distinct_data_planes}",)
    )
    return RollbackDrillReadiness(
        ready=ready,
        checked_at=normalized_checked_at,
        minimum_distinct_data_planes=minimum_distinct_data_planes,
        maximum_evidence_age_seconds=maximum_evidence_age_seconds,
        data_planes=tuple(data_planes),
        reasons=global_reasons,
    )


def evaluate_platform_plugin_cutover_readiness(
    *,
    shadow: ShadowRolloutReadiness,
    rollback_drill: RollbackDrillReadiness,
) -> PlatformPluginCutoverReadiness:
    """Require both zero-diff runtime parity and a real rollback drill."""
    reasons = tuple(f"shadow:{reason}" for reason in shadow.reasons) + tuple(
        f"rollback_drill:{reason}" for reason in rollback_drill.reasons
    )
    return PlatformPluginCutoverReadiness(
        ready=shadow.ready and rollback_drill.ready,
        checked_at=max(shadow.checked_at, rollback_drill.checked_at),
        shadow=shadow,
        rollback_drill=rollback_drill,
        reasons=reasons,
    )


def _evaluate_data_plane_drill(
    *,
    data_plane_id: str,
    ordered_events: Sequence[Mapping[str, Any]],
    checked_at: datetime,
    maximum_evidence_age_seconds: int,
) -> RollbackDrillDataPlaneReadiness:
    """Validate one ordered ACK/NACK/restore receipt sequence."""
    baseline: Mapping[str, Any] | None = None
    failure: Mapping[str, Any] | None = None
    restored_event: Mapping[str, Any] | None = None
    for event in ordered_events:
        status = str(event["status"])
        requested = int(event["requested_version"])
        applied = int(event["applied_version"])
        if status == "ack" and baseline is None:
            baseline = event
        elif _is_invalid_config_nack(event, baseline):
            failure = event
        elif _is_restored_ack(event, failure, requested, applied):
            restored_event = event

    reasons: list[str] = []
    if baseline is None:
        reasons.append("missing_baseline_ack")
    if failure is None:
        reasons.append("missing_invalid_config_nack")
    if restored_event is None:
        reasons.append("missing_restored_ack")
    elif not ordered_events or ordered_events[-1] is not restored_event:
        reasons.append("restored_ack_not_latest")

    last_recorded_at = (
        _normalize_datetime(ordered_events[-1]["recorded_at"]) if ordered_events else None
    )
    if last_recorded_at is None:
        reasons.append("stale_evidence")
    else:
        age = (checked_at - last_recorded_at).total_seconds()
        if age < 0 or age > maximum_evidence_age_seconds:
            reasons.append("stale_evidence")
    return RollbackDrillDataPlaneReadiness(
        data_plane_id=data_plane_id,
        ready=not reasons,
        last_recorded_at=last_recorded_at,
        reasons=tuple(reasons),
    )


def _is_invalid_config_nack(
    event: Mapping[str, Any],
    baseline: Mapping[str, Any] | None,
) -> bool:
    return (
        baseline is not None
        and str(event["status"]) == "nack"
        and int(event["requested_version"]) > int(baseline["requested_version"])
        and int(event["applied_version"]) == int(baseline["requested_version"])
        and str(event.get("error_message") or "").strip() != ""
    )


def _is_restored_ack(
    event: Mapping[str, Any],
    failure: Mapping[str, Any] | None,
    requested_version: int,
    applied_version: int,
) -> bool:
    return (
        failure is not None
        and str(event["status"]) == "ack"
        and requested_version > int(failure["requested_version"])
        and applied_version == requested_version
    )


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
