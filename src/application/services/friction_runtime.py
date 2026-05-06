"""Friction runtime — process-level singleton wiring for ``FrictionLedger``.

Mirrors :func:`configure_reflection_tool`: production code calls
``configure_friction_ingest()`` once at startup with a ledger instance, and
domain services (``WorkspaceTaskService``, lane state machines, ...) call
:func:`record_lane_change` on every observed status change. The helper is a
no-op when no ledger has been configured, so unit tests never need to set
this up.

Per Agent-First: this module only ingests *structural* lane transitions
(positional comparison in ``lane_order``). Subjective verdicts stay with
``ReflectorPort`` consumers downstream.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from src.domain.model.flow.friction_signal import FrictionKind, FrictionSignal
from src.domain.ports.repositories.friction_ledger import FrictionLedger

logger = logging.getLogger(__name__)


_ledger: FrictionLedger | None = None
_lane_order: tuple[str, ...] = ()


def configure_friction_ingest(
    ledger: FrictionLedger,
    *,
    lane_order: tuple[str, ...],
) -> None:
    """Install the process-level friction ledger + lane ordering.

    ``lane_order`` is the canonical forward sequence (e.g. workspace task
    status enum values in happy-path order). Backward moves derive a
    ``BOUNCE`` signal; forward moves are silently ignored.
    """
    global _ledger, _lane_order
    _ledger = ledger
    _lane_order = tuple(lane_order)


def reset_friction_ingest() -> None:
    """Clear the configured ledger. Test helper."""
    global _ledger, _lane_order
    _ledger = None
    _lane_order = ()


def get_friction_ledger() -> FrictionLedger | None:
    """Return the process-level friction ledger if configured.

    Used by read paths (e.g. ``LaneExperienceService``) that share the
    same ledger as the ingest path. Returns ``None`` when
    ``configure_friction_ingest`` has not been called (typical in unit
    tests and minimal runtimes).
    """
    return _ledger


async def record_lane_change(
    *,
    project_id: str,
    task_id: str,
    from_lane: str,
    to_lane: str,
    metadata: Mapping[str, Any] | None = None,
) -> FrictionSignal | None:
    """Append a ``BOUNCE`` signal when ``to_lane`` precedes ``from_lane``.

    Returns the appended signal (or ``None`` if no ledger configured /
    move is forward / lanes unknown). Errors are logged and swallowed —
    friction ingestion must never break the calling transition.
    """
    if (
        _ledger is None
        or not _lane_order
        or not project_id
        or not task_id
        or from_lane == to_lane
    ):
        return None
    try:
        src_idx = _lane_order.index(from_lane)
        dst_idx = _lane_order.index(to_lane)
    except ValueError:
        return None
    if dst_idx >= src_idx:
        return None

    signal = FrictionSignal(
        project_id=project_id,
        task_id=task_id,
        kind=FrictionKind.BOUNCE,
        source_lane=from_lane,
        target_lane=to_lane,
        metadata=dict(metadata or {}),
    )
    try:
        await _ledger.append(signal)
    except Exception:
        logger.exception(
            "FrictionLedger.append failed for project=%s task=%s",
            project_id,
            task_id,
        )
        return None
    return signal


__all__ = [
    "configure_friction_ingest",
    "get_friction_ledger",
    "record_lane_change",
    "reset_friction_ingest",
]
