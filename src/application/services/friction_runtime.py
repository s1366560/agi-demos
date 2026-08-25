"""Application facade for generation-pinned friction ingestion."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.domain.model.flow.friction_signal import FrictionSignal


async def record_lane_change(
    *,
    project_id: str,
    task_id: str,
    from_lane: str,
    to_lane: str,
    metadata: Mapping[str, Any] | None = None,
) -> FrictionSignal | None:
    """Delegate one structural lane transition to the pinned V2 runtime."""
    from src.infrastructure.plugins.v2.reflection_runtime import (
        current_reflection_runtime_v2,
    )

    return await current_reflection_runtime_v2().record_lane_change(
        project_id=project_id,
        task_id=task_id,
        from_lane=from_lane,
        to_lane=to_lane,
        metadata=metadata,
    )


__all__ = ["record_lane_change"]
