from __future__ import annotations

import logging
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.schemas.invitation_schemas import (
    AcceptInvitationRequest,
    CreateInvitationRequest,
    InvitationListResponse,
    InvitationResponse,
    InvitationVerifyResponse,
)
from src.application.services.invitation_service import InvitationService
from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user,
    get_current_user_tenant,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import (
    User as DBUser,
    UserTenant,
)
from src.infrastructure.adapters.secondary.persistence.sql_invitation_repository import (
    SqlInvitationRepository,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/tenants/{tenant_id}/invitations",
    tags=["invitations"],
)

public_router = APIRouter(
    prefix="/api/v1/invitations",
    tags=["invitations"],
)


def _build_service(db: AsyncSession) -> InvitationService:
    return InvitationService(invitation_repo=SqlInvitationRepository(db))


@router.post("", response_model=InvitationResponse, status_code=status.HTTP_201_CREATED)
async def create_invitation(
    tenant_id: str,
    body: CreateInvitationRequest,
    current_user: DBUser = Depends(get_current_user),
    _current_tenant: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> InvitationResponse:
    service = _build_service(db)
    try:
        invitation = await service.create_invitation(
            tenant_id=tenant_id,
            email=body.email,
            role=body.role,
            invited_by=current_user.id,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
    await db.commit()
    return InvitationResponse(
        id=invitation.id,
        tenant_id=invitation.tenant_id,
        email=invitation.email,
        role=invitation.role,
        status=invitation.status,
        invited_by=invitation.invited_by,
        expires_at=invitation.expires_at,
        created_at=invitation.created_at,
    )


@router.get("", response_model=InvitationListResponse)
async def list_pending_invitations(
    tenant_id: str,
    _current_tenant: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> InvitationListResponse:
    service = _build_service(db)
    items, total = await service.list_pending(tenant_id, limit=limit, offset=offset)
    return InvitationListResponse(
        items=[
            InvitationResponse(
                id=inv.id,
                tenant_id=inv.tenant_id,
                email=inv.email,
                role=inv.role,
                status=inv.status,
                invited_by=inv.invited_by,
                expires_at=inv.expires_at,
                created_at=inv.created_at,
            )
            for inv in items
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.delete("/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_invitation(
    tenant_id: str,
    invitation_id: str,
    _current_tenant: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> None:
    service = _build_service(db)
    try:
        await service.cancel(invitation_id, tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e)) from e
    await db.commit()


@public_router.get("/verify/{token}", response_model=InvitationVerifyResponse)
async def verify_invitation(
    token: str,
    db: AsyncSession = Depends(get_db),
) -> InvitationVerifyResponse:
    service = _build_service(db)
    invitation = await service.validate_token(token)
    await db.commit()
    if invitation is None:
        return InvitationVerifyResponse(valid=False)
    return InvitationVerifyResponse(
        valid=True,
        email=invitation.email,
        tenant_id=invitation.tenant_id,
        role=invitation.role,
        expires_at=invitation.expires_at,
    )


@public_router.post("/accept/{token}", response_model=InvitationResponse)
async def accept_invitation(
    token: str,
    body: AcceptInvitationRequest,
    current_user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> InvitationResponse:
    service = _build_service(db)
    try:
        invitation = await service.accept_invitation(token, current_user.id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

    existing = await db.execute(
        select(UserTenant).where(
            UserTenant.user_id == current_user.id,
            UserTenant.tenant_id == invitation.tenant_id,
        )
    )
    if existing.scalar_one_or_none() is None:
        membership = UserTenant(
            id=str(uuid4()),
            user_id=current_user.id,
            tenant_id=invitation.tenant_id,
            role=invitation.role,
        )
        db.add(membership)

    await db.commit()
    return InvitationResponse(
        id=invitation.id,
        tenant_id=invitation.tenant_id,
        email=invitation.email,
        role=invitation.role,
        status=invitation.status,
        invited_by=invitation.invited_by,
        expires_at=invitation.expires_at,
        created_at=invitation.created_at,
    )
