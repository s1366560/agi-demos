"""System information and feature flag endpoints."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends

from src.configuration.config import get_settings
from src.configuration.features import get_feature_gate
from src.infrastructure.adapters.primary.web.dependencies.auth_dependencies import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/system", tags=["System"])


@router.get("/features", response_model=list[dict[str, Any]])
async def list_features(
    _current_user: Any = Depends(get_current_user),  # noqa: ANN401
) -> list[dict[str, Any]]:
    """Get list of all features and their enablement status."""
    gate = get_feature_gate()
    return gate.get_enabled_features()


@router.get("/info", response_model=dict[str, Any])
async def get_system_info(
    _current_user: Any = Depends(get_current_user),  # noqa: ANN401
) -> dict[str, Any]:
    """Get system info including edition and features."""
    gate = get_feature_gate()
    settings = get_settings()
    return {
        "edition": gate.edition,
        "features": gate.get_enabled_features(),
        "agent_runtime": {
            "mode": settings.agent_runtime_mode,
        },
        "memory_runtime": {
            "mode": settings.agent_memory_runtime_mode,
            "failure_persistence_enabled": settings.agent_memory_failure_persistence_enabled,
        },
    }
