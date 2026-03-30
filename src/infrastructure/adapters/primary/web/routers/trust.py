"""Trust System router -- graduated autonomy policies and approval decisions."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.schemas.trust_schemas import (
    ApprovalRequestCreate,
    ApprovalResolveRequest,
    DecisionRecordListResponse,
    DecisionRecordResponse,
    TrustCheckResponse,
    TrustPolicyCreate,
    TrustPolicyListResponse,
    TrustPolicyResponse,
)
from src.application.services.trust_service import TrustService
from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user_tenant,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.sql_decision_record_repository import (
    SqlDecisionRecordRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_trust_policy_repository import (
    SqlTrustPolicyRepository,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/tenants/{tenant_id}/trust",
    tags=["trust"],
)


def _build_service(db: AsyncSession) -> TrustService:
    return TrustService(
        policy_repo=SqlTrustPolicyRepository(db),
        record_repo=SqlDecisionRecordRepository(db),
    )


# ---------------------------------------------------------------------------
# Trust Policies
# ---------------------------------------------------------------------------


@router.get("/policies", response_model=TrustPolicyListResponse)
async def list_trust_policies(
    tenant_id: str,
    _current_tenant: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
    workspace_id: str = Query(...),
    agent_instance_id: str | None = Query(default=None),
) -> TrustPolicyListResponse:
    service = _build_service(db)
    items = await service.list_policies(workspace_id, agent_instance_id=agent_instance_id)
    return TrustPolicyListResponse(
        items=[
            TrustPolicyResponse(
                id=p.id,
                tenant_id=p.tenant_id,
                workspace_id=p.workspace_id,
                agent_instance_id=p.agent_instance_id,
                action_type=p.action_type,
                granted_by=p.granted_by,
                grant_type=p.grant_type,
                created_at=p.created_at,
                deleted_at=p.deleted_at,
            )
            for p in items
        ]
    )


@router.post("/policies", response_model=TrustPolicyResponse, status_code=201)
async def create_trust_policy(
    tenant_id: str,
    body: TrustPolicyCreate,
    _current_tenant: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> TrustPolicyResponse:
    service = _build_service(db)
    policy = await service.create_policy(
        tenant_id=tenant_id,
        workspace_id=body.workspace_id,
        agent_instance_id=body.agent_instance_id,
        action_type=body.action_type,
        granted_by=_current_tenant,
        grant_type=body.grant_type,
    )
    await db.commit()
    return TrustPolicyResponse(
        id=policy.id,
        tenant_id=policy.tenant_id,
        workspace_id=policy.workspace_id,
        agent_instance_id=policy.agent_instance_id,
        action_type=policy.action_type,
        granted_by=policy.granted_by,
        grant_type=policy.grant_type,
        created_at=policy.created_at,
        deleted_at=policy.deleted_at,
    )


@router.get("/policies/check", response_model=TrustCheckResponse)
async def check_trust(
    tenant_id: str,
    _current_tenant: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
    workspace_id: str = Query(...),
    agent_instance_id: str = Query(...),
    action_type: str = Query(...),
) -> TrustCheckResponse:
    service = _build_service(db)
    trusted = await service.check_trust(workspace_id, agent_instance_id, action_type)
    return TrustCheckResponse(trusted=trusted)


# ---------------------------------------------------------------------------
# Approval Requests / Decision Records
# ---------------------------------------------------------------------------


@router.post(
    "/approval-requests",
    response_model=DecisionRecordResponse,
    status_code=201,
)
async def submit_approval_request(
    tenant_id: str,
    body: ApprovalRequestCreate,
    _current_tenant: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> DecisionRecordResponse:
    service = _build_service(db)
    record = await service.submit_approval(
        tenant_id=tenant_id,
        workspace_id=body.workspace_id,
        agent_instance_id=body.agent_instance_id,
        action_type=body.action_type,
        proposal=body.proposal,
        context_summary=body.context_summary,
    )
    await db.commit()
    return _record_response(record)


@router.post(
    "/approval-requests/{record_id}/resolve",
    response_model=DecisionRecordResponse,
)
async def resolve_approval_request(
    tenant_id: str,
    record_id: str,
    body: ApprovalResolveRequest,
    _current_tenant: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> DecisionRecordResponse:
    service = _build_service(db)
    try:
        record = await service.resolve_approval(
            record_id,
            reviewer_id=_current_tenant,
            decision=body.decision,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await db.commit()
    return _record_response(record)


@router.get("/decision-records", response_model=DecisionRecordListResponse)
async def list_decision_records(
    tenant_id: str,
    _current_tenant: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
    workspace_id: str = Query(...),
    agent_id: str | None = Query(default=None),
    decision_type: str | None = Query(default=None),
) -> DecisionRecordListResponse:
    service = _build_service(db)
    items = await service.list_decision_records(
        workspace_id, agent_id=agent_id, decision_type=decision_type
    )
    return DecisionRecordListResponse(items=[_record_response(r) for r in items])


@router.get(
    "/decision-records/{record_id}",
    response_model=DecisionRecordResponse,
)
async def get_decision_record(
    tenant_id: str,
    record_id: str,
    _current_tenant: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
    workspace_id: str = Query(...),
) -> DecisionRecordResponse:
    service = _build_service(db)
    record = await service.get_decision_record(record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Decision record not found")
    return _record_response(record)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _record_response(r: object) -> DecisionRecordResponse:
    """Map a DecisionRecord domain entity to its API response model."""
    from src.domain.model.trust.decision_record import DecisionRecord

    assert isinstance(r, DecisionRecord)
    return DecisionRecordResponse(
        id=r.id,
        tenant_id=r.tenant_id,
        workspace_id=r.workspace_id,
        agent_instance_id=r.agent_instance_id,
        decision_type=r.decision_type,
        context_summary=r.context_summary,
        proposal=r.proposal,
        outcome=r.outcome,
        reviewer_id=r.reviewer_id,
        review_type=r.review_type,
        review_comment=r.review_comment,
        resolved_at=r.resolved_at,
        created_at=r.created_at,
        updated_at=r.updated_at,
        deleted_at=r.deleted_at,
    )
