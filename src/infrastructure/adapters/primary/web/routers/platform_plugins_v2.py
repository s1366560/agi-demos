"""Breaking protocol-v2 distribution and data-plane receipt transport."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, NoReturn, cast

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.schemas.platform_plugins import (
    PlatformPluginApplyStateResponseV2,
    PlatformPluginDataPlaneCredentialIssuedResponseV2,
    PlatformPluginDataPlaneCredentialIssueRequestV2,
    PlatformPluginDataPlaneCredentialResponseV2,
    PlatformPluginDataPlaneCredentialRotateRequestV2,
    PlatformPluginDataPlaneReadinessResponseV2,
    PlatformPluginDesiredBundleSetResponseV2,
    PlatformPluginDistributionResponseV2,
    PlatformPluginPublicationReadinessResponseV2,
    PlatformPluginRouteAuthorityReadinessResponseV2,
)
from src.domain.model.plugins.generated_v2 import (
    DesiredBundleSetV2,
    ScopeKindV2,
    ScopeV2,
    SnapshotApplyReceiptV2,
)
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.dependencies.plugin_data_plane_auth_v2 import (
    PlatformPluginDataPlanePrincipalV2,
    get_plugin_data_plane_principal_v2,
)
from src.infrastructure.adapters.primary.web.startup.plugin_runtime_v2 import (
    plugin_publication_policy_v2_from_app,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import (
    PlatformPluginV2DataPlaneCredentialModel,
    User,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_data_plane_credential_repository_v2 import (
    IssuedPlatformPluginDataPlaneCredentialV2,
    PlatformPluginDataPlaneCredentialRepositoryV2,
    PlatformPluginDataPlaneCredentialV2Error,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_desired_bundle_repository_v2 import (
    PlatformPluginDesiredBundleSetRecordV2,
    PlatformPluginDesiredBundleSetRepositoryV2,
    PlatformPluginDesiredBundleSetV2Error,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_governance_repository import (
    PlatformPluginGovernanceRepository,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_repository_v2 import (
    PYTHON_API_DATA_PLANE_ID_V2,
    PlatformPluginLedgerV2Error,
    PlatformPluginPublicationReadinessV2,
    PlatformPluginRepositoryV2,
)
from src.infrastructure.i18n import gettext as _
from src.infrastructure.plugins.v2.boundary import current_generation_v2
from src.infrastructure.plugins.v2.http_routes import RouteDefinitionV2, RouteTableBuilderV2
from src.infrastructure.plugins.v2.protocol import (
    PluginProtocolV2Error,
    desired_bundle_set_v2_to_payload,
    parse_desired_bundle_set_v2,
    parse_snapshot_apply_receipt_v2,
    snapshot_apply_receipt_v2_to_payload,
)
from src.infrastructure.plugins.v2.route_authority import (
    ROUTE_AUTHORITY_CATALOG_SERVICE_V2,
    RouteAuthorityCatalogV2,
    verify_bundle_route_authority_v2,
)
from src.infrastructure.plugins.v2.route_effects import ROUTE_TABLE_BUILDER_SERVICE_V2
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2
from src.infrastructure.plugins.v2.scope import parse_scope_v2, scope_v2_to_payload

router = APIRouter(prefix="/v2", tags=["Platform Plugins V2"])


@dataclass(frozen=True, kw_only=True)
class DataPlaneReceiptRequestV2:
    data_plane_id: str
    nonce: str
    receipt: SnapshotApplyReceiptV2


@dataclass(frozen=True, kw_only=True)
class DesiredBundleSetRequestV2:
    scope: ScopeV2
    expected_revision: int | None
    desired_set: DesiredBundleSetV2


@router.put(
    "/desired-bundle-sets/current",
    response_model=PlatformPluginDesiredBundleSetResponseV2,
)
async def put_current_desired_bundle_set_v2(
    payload: dict[str, Any] = Body(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PlatformPluginDesiredBundleSetResponseV2:
    """Append one exact desired-set revision with compare-and-swap."""
    _require_platform_admin(current_user)
    try:
        request = _parse_desired_bundle_set_request_v2(payload)
    except PluginProtocolV2Error as exc:
        _raise_protocol_error(exc)
    try:
        record = await PlatformPluginDesiredBundleSetRepositoryV2(db).record_desired_set(
            scope=request.scope,
            desired_set=request.desired_set,
            expected_revision=request.expected_revision,
            actor_id=current_user.id,
        )
    except PlatformPluginDesiredBundleSetV2Error as exc:
        await db.rollback()
        _raise_desired_bundle_set_error(exc)
    await db.commit()
    return _desired_bundle_set_response_v2(record)


@router.get(
    "/desired-bundle-sets/current",
    response_model=PlatformPluginDesiredBundleSetResponseV2,
)
async def get_current_desired_bundle_set_v2(
    scope_kind: str = Query(...),
    tenant_id: str | None = Query(default=None),
    project_id: str | None = Query(default=None),
    session_id: str | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PlatformPluginDesiredBundleSetResponseV2:
    """Return the latest exact desired-set revision for one scope."""
    _require_platform_admin(current_user)
    try:
        scope = _parse_scope_query_v2(scope_kind, tenant_id, project_id, session_id)
    except PluginProtocolV2Error as exc:
        _raise_protocol_error(exc)
    record = await PlatformPluginDesiredBundleSetRepositoryV2(db).current_desired_set(scope)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_("No protocol v2 desired bundle set exists for this scope"),
        )
    return _desired_bundle_set_response_v2(record)


@router.get(
    "/desired-bundle-sets/history",
    response_model=list[PlatformPluginDesiredBundleSetResponseV2],
)
async def list_desired_bundle_set_history_v2(
    scope_kind: str = Query(...),
    tenant_id: str | None = Query(default=None),
    project_id: str | None = Query(default=None),
    session_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[PlatformPluginDesiredBundleSetResponseV2]:
    """Return newest-first desired-state history for one scope."""
    _require_platform_admin(current_user)
    try:
        scope = _parse_scope_query_v2(scope_kind, tenant_id, project_id, session_id)
    except PluginProtocolV2Error as exc:
        _raise_protocol_error(exc)
    records = await PlatformPluginDesiredBundleSetRepositoryV2(db).list_history(
        scope,
        limit=limit,
    )
    return [_desired_bundle_set_response_v2(record) for record in records]


@router.post(
    "/data-plane-credentials",
    response_model=PlatformPluginDataPlaneCredentialIssuedResponseV2,
    status_code=status.HTTP_201_CREATED,
)
async def issue_data_plane_credential_v2(
    payload: PlatformPluginDataPlaneCredentialIssueRequestV2,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PlatformPluginDataPlaneCredentialIssuedResponseV2:
    """Issue one dedicated workload credential and reveal its secret once."""
    _require_platform_admin(current_user)
    try:
        issued = await PlatformPluginDataPlaneCredentialRepositoryV2(db).issue(
            data_plane_id=payload.data_plane_id,
            actor_id=current_user.id,
            expires_at=payload.expires_at,
        )
    except ValueError as exc:
        await db.rollback()
        _raise_data_plane_credential_invalid(exc)
    await db.commit()
    return _issued_data_plane_credential_response_v2(issued)


@router.get(
    "/data-plane-credentials",
    response_model=list[PlatformPluginDataPlaneCredentialResponseV2],
)
async def list_data_plane_credentials_v2(
    data_plane_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[PlatformPluginDataPlaneCredentialResponseV2]:
    """List credential metadata without ever returning stored secret material."""
    _require_platform_admin(current_user)
    try:
        credentials = await PlatformPluginDataPlaneCredentialRepositoryV2(db).list_credentials(
            data_plane_id=data_plane_id,
            limit=limit,
        )
    except ValueError as exc:
        _raise_data_plane_credential_invalid(exc)
    return [_data_plane_credential_response_v2(credential) for credential in credentials]


@router.post(
    "/data-plane-credentials/{credential_id}/rotate",
    response_model=PlatformPluginDataPlaneCredentialIssuedResponseV2,
    status_code=status.HTTP_201_CREATED,
)
async def rotate_data_plane_credential_v2(
    credential_id: str,
    payload: PlatformPluginDataPlaneCredentialRotateRequestV2,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PlatformPluginDataPlaneCredentialIssuedResponseV2:
    """Revoke one workload credential and reveal its bound successor once."""
    _require_platform_admin(current_user)
    try:
        issued = await PlatformPluginDataPlaneCredentialRepositoryV2(db).rotate(
            credential_id,
            actor_id=current_user.id,
            expires_at=payload.expires_at,
        )
    except PlatformPluginDataPlaneCredentialV2Error as exc:
        await db.rollback()
        _raise_data_plane_credential_error(exc)
    except ValueError as exc:
        await db.rollback()
        _raise_data_plane_credential_invalid(exc)
    await db.commit()
    return _issued_data_plane_credential_response_v2(issued)


@router.delete(
    "/data-plane-credentials/{credential_id}",
    response_model=PlatformPluginDataPlaneCredentialResponseV2,
)
async def revoke_data_plane_credential_v2(
    credential_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PlatformPluginDataPlaneCredentialResponseV2:
    """Idempotently revoke one workload credential while retaining its audit row."""
    _require_platform_admin(current_user)
    try:
        credential = await PlatformPluginDataPlaneCredentialRepositoryV2(db).revoke(
            credential_id,
            actor_id=current_user.id,
        )
    except PlatformPluginDataPlaneCredentialV2Error as exc:
        await db.rollback()
        _raise_data_plane_credential_error(exc)
    await db.commit()
    return _data_plane_credential_response_v2(credential)


@router.get("/distribution", response_model=PlatformPluginDistributionResponseV2)
async def get_distribution_v2(
    _principal: PlatformPluginDataPlanePrincipalV2 = Depends(get_plugin_data_plane_principal_v2),
    db: AsyncSession = Depends(get_db),
) -> PlatformPluginDistributionResponseV2:
    """Return the newest complete distribution; data planes project targets locally."""
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
    principal: PlatformPluginDataPlanePrincipalV2 = Depends(get_plugin_data_plane_principal_v2),
    db: AsyncSession = Depends(get_db),
) -> PlatformPluginApplyStateResponseV2:
    """Persist one exact v2 ACK/NACK without accepting a legacy receipt shape."""
    try:
        request = _parse_receipt_request_v2(payload)
    except PluginProtocolV2Error as exc:
        _raise_protocol_error(exc)
    _require_data_plane_binding_v2(request=request, principal=principal)
    try:
        _ = await PlatformPluginRepositoryV2(db).record_data_plane_receipt(
            data_plane_id=principal.data_plane_id,
            nonce=request.nonce,
            receipt=request.receipt,
        )
    except PlatformPluginLedgerV2Error as exc:
        await db.rollback()
        _raise_ledger_error(exc)
    await db.commit()
    return PlatformPluginApplyStateResponseV2(
        data_plane_id=principal.data_plane_id,
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
    "/route-authority/readiness",
    response_model=PlatformPluginRouteAuthorityReadinessResponseV2,
)
async def get_route_authority_readiness_v2(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PlatformPluginRouteAuthorityReadinessResponseV2:
    """Prove every active desired route is owned by an exact non-bridge V2 effect."""
    _require_platform_admin(current_user)
    generation = current_generation_v2()
    root_scope = ScopeV2(kind=ScopeKindV2.ROOT)
    builder = generation.resolve(ROUTE_TABLE_BUILDER_SERVICE_V2, root_scope)
    authority_catalog = generation.resolve(ROUTE_AUTHORITY_CATALOG_SERVICE_V2, root_scope)
    if not isinstance(builder, RouteTableBuilderV2):
        raise TypeError("plugin runtime v2 resolved an invalid route table builder")
    if not isinstance(authority_catalog, RouteAuthorityCatalogV2):
        raise TypeError("plugin runtime v2 resolved an invalid route authority catalog")
    desired_rows = await PlatformPluginGovernanceRepository(db).list_http_routes()
    evidence = verify_bundle_route_authority_v2(
        snapshot=generation.snapshot,
        route_definitions=cast("tuple[RouteDefinitionV2, ...]", builder.definitions),
        authorities=authority_catalog.authorities,
        desired_rows=desired_rows,
    )
    return PlatformPluginRouteAuthorityReadinessResponseV2.model_validate(evidence.to_payload())


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


def _desired_bundle_set_response_v2(
    record: PlatformPluginDesiredBundleSetRecordV2,
) -> PlatformPluginDesiredBundleSetResponseV2:
    return PlatformPluginDesiredBundleSetResponseV2(
        record_id=record.record_id,
        scope=scope_v2_to_payload(record.scope),
        desired_bundle_set=desired_bundle_set_v2_to_payload(record.desired_set),
        actor_id=record.actor_id,
        created_at=record.created_at,
    )


def _data_plane_credential_response_v2(
    credential: PlatformPluginV2DataPlaneCredentialModel,
) -> PlatformPluginDataPlaneCredentialResponseV2:
    return PlatformPluginDataPlaneCredentialResponseV2(
        credential_id=credential.id,
        data_plane_id=credential.data_plane_id,
        key_prefix=credential.key_prefix,
        created_by_user_id=credential.created_by_user_id,
        created_at=credential.created_at,
        expires_at=credential.expires_at,
        revoked_at=credential.revoked_at,
        revoked_by_user_id=credential.revoked_by_user_id,
        rotated_from_id=credential.rotated_from_id,
    )


def _issued_data_plane_credential_response_v2(
    issued: IssuedPlatformPluginDataPlaneCredentialV2,
) -> PlatformPluginDataPlaneCredentialIssuedResponseV2:
    metadata = _data_plane_credential_response_v2(issued.credential)
    return PlatformPluginDataPlaneCredentialIssuedResponseV2(
        **metadata.model_dump(),
        secret=issued.secret,
    )


def _parse_desired_bundle_set_request_v2(payload: object) -> DesiredBundleSetRequestV2:
    if not isinstance(payload, dict):
        raise PluginProtocolV2Error(
            "invalid_desired_bundle_set_envelope",
            "desired bundle set envelope must be an object",
        )
    raw = cast(dict[str, Any], payload)
    if raw.get("schema_version") != 2:
        raise PluginProtocolV2Error(
            "incompatible_schema_version",
            "desired bundle set envelope schema_version must be 2; v1 is not accepted",
        )
    if set(raw) != {
        "schema_version",
        "scope",
        "expected_revision",
        "desired_bundle_set",
    }:
        raise PluginProtocolV2Error(
            "schema_validation_failed",
            "desired bundle set envelope has invalid fields",
        )
    expected_revision = raw["expected_revision"]
    if expected_revision is not None and (
        isinstance(expected_revision, bool)
        or not isinstance(expected_revision, int)
        or expected_revision < 1
    ):
        raise PluginProtocolV2Error(
            "schema_validation_failed",
            "expected_revision must be null or a positive integer",
        )
    return DesiredBundleSetRequestV2(
        scope=parse_scope_v2(raw["scope"]),
        expected_revision=expected_revision,
        desired_set=parse_desired_bundle_set_v2(raw["desired_bundle_set"]),
    )


def _parse_scope_query_v2(
    scope_kind: str,
    tenant_id: str | None,
    project_id: str | None,
    session_id: str | None,
) -> ScopeV2:
    payload = {"kind": scope_kind}
    for key, value in (
        ("tenant_id", tenant_id),
        ("project_id", project_id),
        ("session_id", session_id),
    ):
        if value is not None:
            payload[key] = value
    return parse_scope_v2(payload)


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


def _require_data_plane_binding_v2(
    *,
    request: DataPlaneReceiptRequestV2,
    principal: PlatformPluginDataPlanePrincipalV2,
) -> None:
    if request.data_plane_id != principal.data_plane_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "plugin_data_plane_identity_mismatch",
                "message": _("Plugin data-plane credential is not bound to the receipt data plane"),
            },
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


def _raise_data_plane_credential_error(
    error: PlatformPluginDataPlaneCredentialV2Error,
) -> NoReturn:
    if error.code == "credential_not_found":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "plugin_data_plane_credential_not_found",
                "reason": error.code,
                "message": _("Plugin data-plane credential was not found"),
            },
        ) from error
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "plugin_data_plane_credential_conflict",
            "reason": error.code,
            "message": _("Plugin data-plane credential conflicts with current state"),
        },
    ) from error


def _raise_data_plane_credential_invalid(error: ValueError) -> NoReturn:
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={
            "code": "plugin_data_plane_credential_invalid",
            "message": _("Plugin data-plane credential request is invalid"),
        },
    ) from error


def _raise_desired_bundle_set_error(error: PlatformPluginDesiredBundleSetV2Error) -> NoReturn:
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "plugin_desired_bundle_set_conflict",
            "reason": error.code,
            "message": _("Protocol v2 desired bundle set conflicts with current state"),
        },
    ) from error


__all__ = ["router"]
