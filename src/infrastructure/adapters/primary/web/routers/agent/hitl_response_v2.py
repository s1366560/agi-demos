"""Revisioned and idempotent REST authority for HITL responses."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from hmac import compare_digest
from typing import Any

from fastapi import HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.hitl_authority import classify_hitl_authority_conflict
from src.application.services.hitl_response_contract import (
    HITL_PENDING_AUTHORITY_REVISION,
    build_hitl_response_digest,
    hitl_authority_revision,
    read_hitl_response_contract_metadata,
)
from src.configuration.config import get_settings
from src.domain.model.agent.hitl_request import HITLRequest, HITLRequestStatus
from src.domain.model.auth.user import User
from src.infrastructure.adapters.secondary.persistence.sql_hitl_request_repository import (
    SqlHITLRequestRepository,
)
from src.infrastructure.i18n import gettext as _

from .schemas import HITLResponseRequest

ValidateResponse = Callable[..., tuple[str, str, dict[str, Any] | None]]
PersistPermissionGrant = Callable[..., Awaitable[None]]
PublishResponse = Callable[..., Awaitable[bool]]


def _authority_response(hitl_request: HITLRequest) -> JSONResponse:
    conflict = classify_hitl_authority_conflict(hitl_request)
    payload = conflict.payload()
    payload["detail"] = _(conflict.detail)
    return JSONResponse(status_code=conflict.status_code, content=payload)


def _contract_conflict_response(
    *,
    reason_code: str,
    detail: str,
    hitl_request: HITLRequest,
    expected_revision: int,
) -> JSONResponse:
    """Return a value-free V2 authority conflict."""
    return JSONResponse(
        status_code=409,
        content={
            "detail": _(detail),
            "reason_code": reason_code,
            "expected_revision": expected_revision,
            **_authority_snapshot_payload(hitl_request),
        },
    )


def _authority_snapshot_payload(hitl_request: HITLRequest) -> dict[str, Any]:
    """Return a value-free snapshot from persisted HITL authority fields."""
    return {
        "request_id": hitl_request.id,
        "authority_revision": hitl_authority_revision(hitl_request.status),
        "authority_status": hitl_request.status.value,
        "created_at": hitl_request.created_at.isoformat(),
        "answered_at": hitl_request.answered_at.isoformat() if hitl_request.answered_at else None,
        "expires_at": hitl_request.expires_at.isoformat() if hitl_request.expires_at else None,
        "observed_at": datetime.now(UTC).isoformat(),
    }


def _contract_success_response(
    *,
    hitl_request: HITLRequest,
    message: str,
    duplicate: bool,
) -> JSONResponse:
    """Return a stable success receipt for a V2 response command."""
    return JSONResponse(
        status_code=200,
        content={
            "success": True,
            "message": message,
            "status": hitl_request.status.value,
            "duplicate": duplicate,
            **_authority_snapshot_payload(hitl_request),
        },
    )


def _replay_matches(
    *,
    hitl_request: HITLRequest,
    idempotency_key: str,
    payload_digest: str,
) -> bool | None:
    """Return True/False for a matching receipt key, or None when it is a new key."""
    receipt = read_hitl_response_contract_metadata(hitl_request.response_metadata)
    if receipt is None or receipt.idempotency_key != idempotency_key:
        return None
    return compare_digest(receipt.payload_digest, payload_digest)


def _existing_contract_response(
    *,
    hitl_request: HITLRequest,
    expected_revision: int,
    idempotency_key: str,
    payload_digest: str,
    hitl_label: str,
) -> JSONResponse | None:
    """Resolve a settled authority as replay, idempotency conflict, or claimed state."""
    if hitl_request.status == HITLRequestStatus.PENDING:
        return None
    replay_matches = _replay_matches(
        hitl_request=hitl_request,
        idempotency_key=idempotency_key,
        payload_digest=payload_digest,
    )
    if replay_matches is True:
        return _contract_success_response(
            hitl_request=hitl_request,
            message=f"{hitl_label} response received",
            duplicate=True,
        )
    if replay_matches is False:
        return _contract_conflict_response(
            reason_code="hitl_idempotency_conflict",
            detail="HITL idempotency key was already used with a different response",
            hitl_request=hitl_request,
            expected_revision=expected_revision,
        )
    return _authority_response(hitl_request)


async def _settle_expired_claim(
    *,
    db: AsyncSession,
    repo: SqlHITLRequestRepository,
    hitl_request: HITLRequest,
) -> JSONResponse:
    """Persist timeout when possible and return the canonical expired authority."""
    authority = await repo.get_by_id(hitl_request.id) or hitl_request
    now = datetime.now(UTC)
    if (
        authority.status == HITLRequestStatus.PENDING
        and authority.expires_at is not None
        and authority.expires_at <= now
    ):
        timed_out = await repo.mark_timeout(authority.id)
        if timed_out is not None:
            await db.commit()
            authority = timed_out
        else:
            authority = await repo.get_by_id(authority.id) or authority
    return _authority_response(authority)


async def _resolve_failed_claim(
    *,
    db: AsyncSession,
    repo: SqlHITLRequestRepository,
    hitl_request: HITLRequest,
    expected_revision: int,
    idempotency_key: str,
    payload_digest: str,
    hitl_label: str,
) -> JSONResponse:
    """Reload a lost claim and return its canonical persisted authority."""
    authority = await repo.get_by_id(hitl_request.id) or hitl_request
    if authority.status == HITLRequestStatus.PENDING and authority.is_expired:
        return await _settle_expired_claim(
            db=db,
            repo=repo,
            hitl_request=authority,
        )
    existing_response = _existing_contract_response(
        hitl_request=authority,
        expected_revision=expected_revision,
        idempotency_key=idempotency_key,
        payload_digest=payload_digest,
        hitl_label=hitl_label,
    )
    if existing_response is not None:
        return existing_response
    return _authority_response(authority)


async def respond_to_hitl_v2(
    *,
    request: HITLResponseRequest,
    hitl_request: HITLRequest,
    repo: SqlHITLRequestRepository,
    current_user: User,
    tenant_id: str,
    db: AsyncSession,
    validate_response: ValidateResponse,
    persist_permission_grant: PersistPermissionGrant,
    publish_response: PublishResponse,
) -> JSONResponse:
    """Claim or replay a revisioned HITL response without exposing response values."""
    expected_revision = request.expected_revision
    idempotency_key = request.idempotency_key
    if expected_revision is None or idempotency_key is None:
        raise HTTPException(status_code=400, detail=_("Incomplete HITL authority command"))

    if hitl_request.status == HITLRequestStatus.PENDING and hitl_request.is_expired:
        return await _settle_expired_claim(
            db=db,
            repo=repo,
            hitl_request=hitl_request,
        )

    stored_hitl_type, response_str, response_metadata = validate_response(
        hitl_request=hitl_request,
        request=request,
        tenant_id=tenant_id,
    )
    try:
        payload_digest = build_hitl_response_digest(
            secret=get_settings().secret_key,
            request_id=request.request_id,
            hitl_type=stored_hitl_type,
            response_data=request.response_data,
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=_("Invalid HITL response")) from exc

    hitl_label = stored_hitl_type.replace("_", " ").title()
    existing_response = _existing_contract_response(
        hitl_request=hitl_request,
        expected_revision=expected_revision,
        idempotency_key=idempotency_key,
        payload_digest=payload_digest,
        hitl_label=hitl_label,
    )
    if existing_response is not None:
        return existing_response
    if expected_revision != HITL_PENDING_AUTHORITY_REVISION:
        return _contract_conflict_response(
            reason_code="hitl_revision_conflict",
            detail="HITL authority revision does not match",
            hitl_request=hitl_request,
            expected_revision=expected_revision,
        )

    updated_request = await repo.claim_response_v2(
        request_id=request.request_id,
        response=response_str,
        response_metadata=response_metadata,
        expected_revision=expected_revision,
        idempotency_key=idempotency_key,
        payload_digest=payload_digest,
    )
    if updated_request is None:
        return await _resolve_failed_claim(
            db=db,
            repo=repo,
            hitl_request=hitl_request,
            expected_revision=expected_revision,
            idempotency_key=idempotency_key,
            payload_digest=payload_digest,
            hitl_label=hitl_label,
        )

    if stored_hitl_type == "permission":
        await persist_permission_grant(
            db=db,
            hitl_request=updated_request,
            response_data=request.response_data,
            current_user=current_user,
        )
    await db.commit()

    redis_sent = await publish_response(
        tenant_id=tenant_id,
        project_id=updated_request.project_id,
        conversation_id=updated_request.conversation_id,
        message_id=updated_request.message_id,
        request_id=request.request_id,
        hitl_type=stored_hitl_type,
        response_data=request.response_data,
        user_id=str(current_user.id),
        agent_mode=(updated_request.metadata or {}).get("agent_mode", "default"),
    )
    message = (
        f"{hitl_label} response received"
        if redis_sent
        else f"{hitl_label} response saved. Delivery is pending."
    )
    return _contract_success_response(
        hitl_request=updated_request,
        message=message,
        duplicate=False,
    )


__all__ = ["respond_to_hitl_v2"]
