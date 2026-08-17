"""Transport for canonical platform plugin snapshots and data-plane receipts."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.schemas.platform_plugins import (
    PlatformPluginApplyStateRequest,
    PlatformPluginApplyStateResponse,
    PlatformPluginSnapshotResponse,
)
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.adapters.secondary.persistence.platform_plugin_repository import (
    PlatformPluginRepository,
)
from src.infrastructure.i18n import gettext as _

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/platform-plugins", tags=["Platform Plugins"])


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
