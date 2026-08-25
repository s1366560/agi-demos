from __future__ import annotations

import logging
from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.schemas.invitation_schemas import (
    AcceptInvitationRequest,
    CreateInvitationRequest,
    InvitationListResponse,
    InvitationResponse,
    InvitationVerifyResponse,
)
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.invitation_application_authority_v2 import (
    invitation_application_authority_context_v2,
)
from src.infrastructure.adapters.primary.web.routers.agent.access import require_tenant_access
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User as DBUser
from src.infrastructure.i18n import gettext as _

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/tenants/{tenant_id}/invitations",
    tags=["invitations"],
)

public_router = APIRouter(
    prefix="/api/v1/invitations",
    tags=["invitations"],
)


def _invitation_conflict_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=_("Invitation already exists"),
    )


def _invitation_not_found_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=_("Invitation not found"),
    )


def _invitation_forbidden_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=_("Not authorized to manage this invitation"),
    )


def _invalid_invitation_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=_("Invalid or expired invitation"),
    )


async def _require_invitation_admin(
    db: AsyncSession,
    current_user: DBUser,
    tenant_id: str,
) -> None:
    if getattr(current_user, "is_superuser", False):
        return
    await require_tenant_access(
        db,
        cast(Any, current_user),
        tenant_id,
        require_admin=True,
    )


@router.post("", response_model=InvitationResponse, status_code=status.HTTP_201_CREATED)
async def create_invitation(
    tenant_id: str,
    body: CreateInvitationRequest,
    request: Request,
    current_user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> InvitationResponse:
    async with invitation_application_authority_context_v2(
        request=request,
        current_user=current_user,
        db=db,
        tenant_id=tenant_id,
    ) as authority:
        await _require_invitation_admin(authority.db, current_user, tenant_id)
        try:
            invitation = await authority.services.invitations.create_invitation(
                tenant_id=tenant_id,
                email=body.email,
                role=body.role,
                invited_by=current_user.id,
            )
        except ValueError as e:
            raise _invitation_conflict_error() from e
        await authority.db.commit()
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
    request: Request,
    current_user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> InvitationListResponse:
    async with invitation_application_authority_context_v2(
        request=request,
        current_user=current_user,
        db=db,
        tenant_id=tenant_id,
    ) as authority:
        await _require_invitation_admin(authority.db, current_user, tenant_id)
        items, total = await authority.services.invitations.list_pending(
            tenant_id,
            limit=limit,
            offset=offset,
        )
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
    request: Request,
    current_user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    async with invitation_application_authority_context_v2(
        request=request,
        current_user=current_user,
        db=db,
        tenant_id=tenant_id,
    ) as authority:
        await _require_invitation_admin(authority.db, current_user, tenant_id)
        try:
            await authority.services.invitations.cancel(invitation_id, tenant_id)
        except ValueError as e:
            raise _invitation_not_found_error() from e
        except PermissionError as e:
            raise _invitation_forbidden_error() from e
        await authority.db.commit()


@public_router.get("/verify/{token}", response_model=InvitationVerifyResponse)
async def verify_invitation(
    token: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> InvitationVerifyResponse:
    async with invitation_application_authority_context_v2(
        request=request,
        current_user=None,
        db=db,
        tenant_id=None,
    ) as authority:
        invitation = await authority.services.invitations.validate_token(token)
        await authority.db.commit()
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
    request: Request,
    current_user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> InvitationResponse:
    async with invitation_application_authority_context_v2(
        request=request,
        current_user=current_user,
        db=db,
        tenant_id=None,
    ) as authority:
        try:
            invitation = await authority.services.invitations.accept_invitation(
                token,
                current_user.id,
            )
        except ValueError as e:
            raise _invalid_invitation_error() from e

        await authority.services.memberships.ensure_membership(
            user_id=current_user.id,
            tenant_id=invitation.tenant_id,
            role=invitation.role,
        )
        await authority.db.commit()
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
