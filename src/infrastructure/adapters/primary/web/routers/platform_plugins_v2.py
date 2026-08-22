"""Breaking protocol-v2 distribution and data-plane receipt transport."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, NoReturn, cast

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.schemas.platform_plugins import (
    PlatformPluginApplyStateResponseV2,
    PlatformPluginDataPlaneReadinessResponseV2,
    PlatformPluginDistributionResponseV2,
    PlatformPluginPublicationReadinessResponseV2,
)
from src.domain.model.plugins.generated_v2 import SnapshotApplyReceiptV2
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.startup.plugin_runtime_v2 import (
    plugin_publication_policy_v2_from_app,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.adapters.secondary.persistence.platform_plugin_repository_v2 import (
    PYTHON_API_DATA_PLANE_ID_V2,
    PlatformPluginLedgerV2Error,
    PlatformPluginPublicationReadinessV2,
    PlatformPluginRepositoryV2,
)
from src.infrastructure.i18n import gettext as _
from src.infrastructure.plugins.v2.protocol import (
    PluginProtocolV2Error,
    parse_snapshot_apply_receipt_v2,
    snapshot_apply_receipt_v2_to_payload,
)
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

router = APIRouter(prefix="/v2", tags=["Platform Plugins V2"])


@dataclass(frozen=True, kw_only=True)
class DataPlaneReceiptRequestV2:
    data_plane_id: str
    nonce: str
    receipt: SnapshotApplyReceiptV2


@router.get("/distribution", response_model=PlatformPluginDistributionResponseV2)
async def get_distribution_v2(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PlatformPluginDistributionResponseV2:
    """Return the newest complete distribution; data planes project targets locally."""
    _require_platform_admin(current_user)
    distribution = await PlatformPluginRepositoryV2(db).latest_requested_distribution()
    if distribution is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_("No protocol v2 plugin distribution has been published"),
        )
    return PlatformPluginDistributionResponseV2(
        descriptor=distribution["descriptor"],
        snapshot=distribution["snapshot"],
        envelope=distribution["envelope"],
    )


@router.post("/data-plane-state", response_model=PlatformPluginApplyStateResponseV2)
async def record_data_plane_state_v2(
    payload: dict[str, Any] = Body(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PlatformPluginApplyStateResponseV2:
    """Persist one exact v2 ACK/NACK without accepting a legacy receipt shape."""
    _require_platform_admin(current_user)
    try:
        request = _parse_receipt_request_v2(payload)
    except PluginProtocolV2Error as exc:
        _raise_protocol_error(exc)
    try:
        _ = await PlatformPluginRepositoryV2(db).record_data_plane_receipt(
            data_plane_id=request.data_plane_id,
            nonce=request.nonce,
            receipt=request.receipt,
        )
    except PlatformPluginLedgerV2Error as exc:
        await db.rollback()
        _raise_ledger_error(exc)
    await db.commit()
    return PlatformPluginApplyStateResponseV2(
        data_plane_id=request.data_plane_id,
        nonce=request.nonce,
        receipt=snapshot_apply_receipt_v2_to_payload(request.receipt),
    )


@router.get(
    "/readiness",
    response_model=PlatformPluginPublicationReadinessResponseV2,
)
async def get_latest_publication_readiness_v2(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PlatformPluginPublicationReadinessResponseV2:
    """Return readiness for the latest immutable protocol-v2 publication."""
    _require_platform_admin(current_user)
    readiness = await PlatformPluginRepositoryV2(db).latest_publication_readiness()
    if readiness is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_("No protocol v2 plugin publication has been recorded"),
        )
    await db.commit()
    return _publication_readiness_response_v2(readiness)


@router.get(
    "/publications/{nonce}/readiness",
    response_model=PlatformPluginPublicationReadinessResponseV2,
)
async def get_publication_readiness_v2(
    nonce: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PlatformPluginPublicationReadinessResponseV2:
    """Return readiness for one exact protocol-v2 publication nonce."""
    _require_platform_admin(current_user)
    try:
        readiness = await PlatformPluginRepositoryV2(db).publication_readiness(nonce)
    except PlatformPluginLedgerV2Error as exc:
        await db.rollback()
        if exc.code == "publication_not_found":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=_("Protocol v2 plugin publication was not found"),
            ) from exc
        _raise_ledger_error(exc)
    await db.commit()
    return _publication_readiness_response_v2(readiness)


@router.post(
    "/publications/republish-last-ready",
    response_model=PlatformPluginPublicationReadinessResponseV2,
)
async def republish_last_ready_v2(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PlatformPluginPublicationReadinessResponseV2:
    """Create a new audited publication from the latest globally-ready snapshot."""
    _require_platform_admin(current_user)
    repository = PlatformPluginRepositoryV2(db)
    policy = plugin_publication_policy_v2_from_app(request.app)
    try:
        publication = await repository.republish_last_globally_ready(policy=policy)
    except PlatformPluginLedgerV2Error as exc:
        await db.rollback()
        _raise_ledger_error(exc)
    await db.commit()

    if PYTHON_API_DATA_PLANE_ID_V2 in publication.required_data_plane_ids:
        host = getattr(request.app.state, "platform_plugin_runtime_v2", None)
        if isinstance(host, PlatformPluginRuntimeHostV2):
            local = await host.apply_distribution(publication.distribution)
            try:
                _ = await repository.record_data_plane_receipt(
                    data_plane_id=PYTHON_API_DATA_PLANE_ID_V2,
                    nonce=publication.nonce,
                    receipt=local.receipt,
                )
            except PlatformPluginLedgerV2Error as exc:
                await db.rollback()
                _raise_ledger_error(exc)
            await db.commit()

    readiness = await repository.publication_readiness(publication.nonce)
    await db.commit()
    return _publication_readiness_response_v2(readiness)


def _publication_readiness_response_v2(
    readiness: PlatformPluginPublicationReadinessV2,
) -> PlatformPluginPublicationReadinessResponseV2:
    return PlatformPluginPublicationReadinessResponseV2(
        publication_id=readiness.publication_id,
        profile_id=readiness.profile_id,
        generation=readiness.generation,
        requested_version=readiness.requested_version,
        snapshot_digest=readiness.snapshot_digest,
        nonce=readiness.nonce,
        republished_from_nonce=readiness.republished_from_nonce,
        required_data_plane_ids=list(readiness.required_data_plane_ids),
        ack_deadline_at=readiness.ack_deadline_at,
        status=readiness.status.value,
        ready_at=readiness.ready_at,
        data_planes=[
            PlatformPluginDataPlaneReadinessResponseV2(
                data_plane_id=plane.data_plane_id,
                status=None if plane.status is None else plane.status.value,
                requested_version=plane.requested_version,
                requested_digest=plane.requested_digest,
                applied_version=plane.applied_version,
                applied_digest=plane.applied_digest,
                error_code=plane.error_code,
                error_message=plane.error_message,
            )
            for plane in readiness.data_planes
        ],
    )


def _parse_receipt_request_v2(payload: object) -> DataPlaneReceiptRequestV2:
    if not isinstance(payload, dict):
        raise PluginProtocolV2Error(
            "invalid_receipt_envelope", "receipt envelope must be an object"
        )
    raw = cast(dict[str, Any], payload)
    if raw.get("schema_version") != 2:
        raise PluginProtocolV2Error(
            "incompatible_schema_version",
            "plugin receipt schema_version must be 2; v1 is not accepted",
        )
    if set(raw) != {"schema_version", "data_plane_id", "nonce", "receipt"}:
        raise PluginProtocolV2Error(
            "schema_validation_failed",
            "receipt envelope has invalid fields",
        )
    data_plane_id = raw["data_plane_id"]
    nonce = raw["nonce"]
    if not isinstance(data_plane_id, str) or not data_plane_id.strip() or len(data_plane_id) > 255:
        raise PluginProtocolV2Error(
            "schema_validation_failed",
            "data_plane_id must be a non-empty string no longer than 255 characters",
        )
    if not isinstance(nonce, str) or not nonce or len(nonce) > 128:
        raise PluginProtocolV2Error(
            "schema_validation_failed",
            "nonce must be a non-empty string no longer than 128 characters",
        )
    return DataPlaneReceiptRequestV2(
        data_plane_id=data_plane_id,
        nonce=nonce,
        receipt=parse_snapshot_apply_receipt_v2(raw["receipt"]),
    )


def _require_platform_admin(user: User) -> None:
    if not user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_("Only a platform administrator may access plugin protocol v2"),
        )


def _raise_protocol_error(error: PluginProtocolV2Error) -> NoReturn:
    if error.code == "incompatible_schema_version":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "plugin_protocol_incompatible",
                "reason": error.code,
                "message": _("Plugin protocol v1 is not accepted by this endpoint"),
            },
        ) from error
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={
            "code": "plugin_protocol_invalid",
            "reason": error.code,
            "message": _("Plugin protocol payload is invalid"),
        },
    ) from error


def _raise_ledger_error(error: PlatformPluginLedgerV2Error) -> NoReturn:
    if error.code == "receipt_invalid":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "plugin_protocol_invalid",
                "reason": error.code,
                "message": _("Plugin protocol receipt is invalid"),
            },
        ) from error
    code = {
        "publication_not_found": "plugin_publication_unknown",
        "stale_receipt": "plugin_receipt_stale",
        "data_plane_not_required": "plugin_data_plane_unregistered",
        "globally_ready_not_found": "plugin_globally_ready_missing",
        "publication_nonce_conflict": "plugin_publication_nonce_conflict",
        "publication_nonce_invalid": "plugin_publication_nonce_invalid",
    }.get(error.code, "plugin_receipt_conflict")
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": code,
            "reason": error.code,
            "message": _("Plugin protocol receipt conflicts with control-plane state"),
        },
    ) from error


__all__ = ["router"]
