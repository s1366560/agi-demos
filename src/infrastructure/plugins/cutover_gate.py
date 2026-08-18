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
    evaluate_platform_plugin_cutover_readiness,
    evaluate_rollback_drill_readiness,
)
from .rollout_readiness import evaluate_shadow_rollout_readiness

logger = logging.getLogger(__name__)


class CutoverGateError(RuntimeError):
    """Raised when V2 flags precede a durable operator cutover approval."""

    def __init__(self, *, reason: str, reasons: tuple[str, ...]) -> None:
        joined = ", ".join(reasons) or "unknown cutover readiness failure"
        super().__init__(f"{reason}: {joined}")
        self.reasons = reasons


async def ensure_agent_v2_cutover_ready(
    session_factory: Callable[[], Any],
) -> bool:
    """Refuse agent V2 startup unless an operator approval is durable."""
    from src.configuration.config import get_settings

    settings = get_settings()
    events_v2 = bool(getattr(settings, "platform_plugin_agent_events_v2", False))
    tools_v2 = bool(getattr(settings, "platform_plugin_agent_tools_v2", False))
    if not (events_v2 or tools_v2):
        return False

    checked_at = datetime.now(UTC)
    async with session_factory() as session:
        repository = PlatformPluginRepository(session)
        approval = await repository.latest_active_cutover_approval(
            capability="agent_runtime",
            now=checked_at,
        )
        if approval is not None:
            logger.info(
                "Platform plugin agent V2 startup approved by %s at %s",
                approval.approved_by,
                approval.approved_at,
            )
            return True

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
        rejected_reasons = (*readiness.reasons, "operator_approval:missing")
    else:
        rejected_reasons = ("operator_approval:missing",)
    logger.error(
        "Platform plugin agent V2 startup rejected: %s",
        ", ".join(rejected_reasons),
    )
    raise CutoverGateError(
        reason="platform plugin V2 cutover gate failed",
        reasons=rejected_reasons,
    )


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
