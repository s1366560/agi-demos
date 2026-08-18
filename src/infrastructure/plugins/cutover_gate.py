"""Fail-closed startup gate for platform-plugin agent V2 modes."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from src.infrastructure.adapters.secondary.persistence.platform_plugin_repository import (
    PlatformPluginRepository,
)

from .cutover_readiness import (
    PlatformPluginCutoverReadiness,
    evaluate_platform_plugin_cutover_readiness,
    evaluate_rollback_drill_readiness,
)
from .rollout_readiness import evaluate_shadow_rollout_readiness

logger = logging.getLogger(__name__)


class CutoverGateError(RuntimeError):
    """Raised when process V2 flags precede durable cutover evidence."""

    def __init__(self, readiness: PlatformPluginCutoverReadiness) -> None:
        reasons = ", ".join(readiness.reasons) or "unknown cutover readiness failure"
        super().__init__(f"platform plugin V2 cutover gate failed: {reasons}")
        self.readiness = readiness


async def ensure_agent_v2_cutover_ready(
    session_factory: Callable[[], Any],
) -> PlatformPluginCutoverReadiness | None:
    """Refuse agent V2 startup unless durable shadow and drill gates pass."""
    from src.configuration.config import get_settings

    settings = get_settings()
    events_v2 = bool(getattr(settings, "platform_plugin_agent_events_v2", False))
    tools_v2 = bool(getattr(settings, "platform_plugin_agent_tools_v2", False))
    if not (events_v2 or tools_v2):
        return None

    checked_at = datetime.now(UTC)
    async with session_factory() as session:
        repository = PlatformPluginRepository(session)
        shadow = evaluate_shadow_rollout_readiness(
            summary=await repository.shadow_rollout_summary(),
            scope_counts=await repository.shadow_rollout_scope_counts(),
            checked_at=checked_at,
        )
        rollback_drill = evaluate_rollback_drill_readiness(
            events=_rollback_events(await repository.list_apply_state_events(limit=5_000)),
            checked_at=checked_at,
        )
    readiness = evaluate_platform_plugin_cutover_readiness(
        shadow=shadow,
        rollback_drill=rollback_drill,
    )
    if not readiness.ready:
        logger.error(
            "Platform plugin agent V2 startup rejected: %s",
            ", ".join(readiness.reasons),
        )
        raise CutoverGateError(readiness)
    logger.info("Platform plugin agent V2 startup passed the durable cutover gate")
    return readiness


def _rollback_events(
    events: Sequence[Any],
) -> list[Mapping[str, Any]]:
    return [
        {
            "id": event.id,
            "data_plane_id": event.data_plane_id,
            "requested_version": event.requested_version,
            "applied_version": event.applied_version,
            "status": event.status,
            "error_message": event.error_message,
            "recorded_at": event.recorded_at,
        }
        for event in events
    ]
