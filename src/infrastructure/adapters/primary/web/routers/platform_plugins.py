"""Transport for canonical platform plugin snapshots and data-plane receipts."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.schemas.platform_plugins import (
    PlatformPluginApplyStateRequest,
    PlatformPluginApplyStateResponse,
    PlatformPluginShadowRolloutCapabilityReadinessResponse,
    PlatformPluginShadowRolloutEventResponse,
    PlatformPluginShadowRolloutReadinessResponse,
    PlatformPluginShadowRolloutResponse,
    PlatformPluginShadowRolloutSummaryResponse,
    PlatformPluginSnapshotResponse,
)
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.adapters.secondary.persistence.platform_plugin_repository import (
    PlatformPluginRepository,
)
from src.infrastructure.i18n import gettext as _
from src.infrastructure.plugins.rollout_readiness import (
    evaluate_shadow_rollout_readiness,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/platform-plugins", tags=["Platform Plugins"])


@router.get("/shadow-rollout", response_model=PlatformPluginShadowRolloutResponse)
async def get_shadow_rollout_evidence(
    only_diffs: bool = False,
    limit: int = 50,
    _current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PlatformPluginShadowRolloutResponse:
    """Return durable shadow rollout summaries and recent comparison evidence."""
    repository = PlatformPluginRepository(db)
    summary = await repository.shadow_rollout_summary()
    events = await repository.list_shadow_rollout_events(
        limit=limit,
        only_diffs=only_diffs,
    )
    return PlatformPluginShadowRolloutResponse(
        summary=[PlatformPluginShadowRolloutSummaryResponse.model_validate(row) for row in summary],
        events=[
            PlatformPluginShadowRolloutEventResponse.model_validate(
                {
                    "capability": event.capability,
                    "event_name": event.event_name,
                    "hook_name": event.hook_name,
                    "scope_type": event.scope_type,
                    "scope_id": event.scope_id,
                    "equal": event.equal,
                    "legacy_payload": event.legacy_payload,
                    "typed_payload": event.typed_payload,
                    "occurred_at": event.occurred_at,
                }
            )
            for event in events
        ],
    )


@router.get(
    "/shadow-rollout/readiness",
    response_model=PlatformPluginShadowRolloutReadinessResponse,
)
async def get_shadow_rollout_readiness(
    minimum_samples_per_event: int = Query(default=100, ge=1, le=1_000_000),
    minimum_distinct_scopes: int = Query(default=10, ge=1, le=100_000),
    maximum_evidence_age_seconds: int = Query(default=900, ge=1, le=86_400),
    _current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PlatformPluginShadowRolloutReadinessResponse:
    """Return a fail-closed promotion gate for the staged agent rollout."""
    repository = PlatformPluginRepository(db)
    readiness = evaluate_shadow_rollout_readiness(
        summary=await repository.shadow_rollout_summary(),
        scope_counts=await repository.shadow_rollout_scope_counts(),
        checked_at=datetime.now(UTC),
        minimum_samples_per_event=minimum_samples_per_event,
        minimum_distinct_scopes=minimum_distinct_scopes,
        maximum_evidence_age_seconds=maximum_evidence_age_seconds,
    )
    return PlatformPluginShadowRolloutReadinessResponse(
        ready=readiness.ready,
        checked_at=readiness.checked_at,
        minimum_samples_per_event=readiness.minimum_samples_per_event,
        minimum_distinct_scopes=readiness.minimum_distinct_scopes,
        maximum_evidence_age_seconds=readiness.maximum_evidence_age_seconds,
        capabilities=[
            PlatformPluginShadowRolloutCapabilityReadinessResponse.model_validate(
                {
                    "capability": item.capability,
                    "ready": item.ready,
                    "total_count": item.total_count,
                    "equal_count": item.equal_count,
                    "diff_count": item.diff_count,
                    "distinct_scope_count": item.distinct_scope_count,
                    "observed_event_count": item.observed_event_count,
                    "required_event_count": item.required_event_count,
                    "last_occurred_at": item.last_occurred_at,
                    "reasons": list(item.reasons),
                }
            )
            for item in readiness.capabilities
        ],
        reasons=list(readiness.reasons),
    )


@router.get("/snapshot", response_model=PlatformPluginSnapshotResponse)
async def get_snapshot(
    _current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PlatformPluginSnapshotResponse:
    """Return the newest canonical profile snapshot."""
    snapshot = await PlatformPluginRepository(db).latest_snapshot()
    if snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_("No platform plugin snapshot has been published"),
        )
    return PlatformPluginSnapshotResponse(
        version=snapshot.version,
        nonce=snapshot.nonce,
        profile_id=snapshot.profile_id,
        digest=snapshot.digest,
        payload=snapshot.payload,
    )


@router.post("/data-plane-state", response_model=PlatformPluginApplyStateResponse)
async def record_data_plane_state(
    request: PlatformPluginApplyStateRequest,
    _current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PlatformPluginApplyStateResponse:
    """Persist one data-plane ACK/NACK receipt."""
    repository = PlatformPluginRepository(db)
    snapshot = await repository.latest_snapshot()
    if (
        snapshot is None
        or snapshot.version != request.requested_version
        or snapshot.digest != request.snapshot_digest
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_("Snapshot version and digest do not match the latest control-plane snapshot"),
        )
    if request.status == "nack" and not (request.error_message or "").strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=_("A NACK receipt requires an error message"),
        )
    if request.status == "ack" and request.applied_version != request.requested_version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_("An ACK receipt must apply the requested snapshot version"),
        )
    await repository.record_apply_state(
        data_plane_id=request.data_plane_id,
        snapshot_digest=request.snapshot_digest,
        requested_version=request.requested_version,
        applied_version=request.applied_version,
        status=request.status,
        error_message=request.error_message,
    )
    await db.commit()
    return PlatformPluginApplyStateResponse(
        data_plane_id=request.data_plane_id,
        snapshot_digest=request.snapshot_digest,
        requested_version=request.requested_version,
        applied_version=request.applied_version,
        status=request.status,
    )
