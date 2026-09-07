"""Support ticket management backed exclusively by a pinned V2 generation."""

from collections.abc import Awaitable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.support_ticket_application_authority_v2 import (
    SupportTicketApplicationAuthorityV2,
    support_ticket_application_authority_dependency_v2,
)
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.i18n import gettext as _
from src.infrastructure.plugins.v2.support_ticket_services import (
    SupportTenantAccessDeniedV2,
    SupportTicketNotFoundV2,
    SupportTicketSnapshotV2,
)

router = APIRouter(prefix="/support", tags=["support"])


async def _support_call[ResultT](operation: Awaitable[ResultT]) -> ResultT:
    try:
        return await operation
    except SupportTicketNotFoundV2 as error:
        raise HTTPException(status_code=404, detail=_("Ticket not found")) from error
    except SupportTenantAccessDeniedV2 as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_("Access denied"),
        ) from error


@router.post("/tickets")
async def create_support_ticket(
    ticket_data: dict[str, Any],
    current_user: User = Depends(get_current_user),
    support_application: SupportTicketApplicationAuthorityV2 = Depends(
        support_ticket_application_authority_dependency_v2
    ),
) -> dict[str, Any]:
    """Create a new support ticket."""
    ticket = await _support_call(
        support_application.services.create_ticket(
            user_id=current_user.id,
            is_superuser=bool(current_user.is_superuser),
            data=ticket_data,
        )
    )
    return {
        "id": ticket.id,
        "subject": ticket.subject,
        "message": ticket.message,
        "priority": ticket.priority,
        "status": ticket.status,
        "created_at": ticket.created_at.isoformat(),
        "updated_at": ticket.updated_at.isoformat(),
    }


@router.get("/tickets")
async def list_support_tickets(
    tenant_id: str | None = None,
    status: str | None = None,
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    support_application: SupportTicketApplicationAuthorityV2 = Depends(
        support_ticket_application_authority_dependency_v2
    ),
) -> dict[str, Any]:
    """List support tickets for the current user."""
    page = await _support_call(
        support_application.services.list_tickets(
            user_id=current_user.id,
            is_superuser=bool(current_user.is_superuser),
            tenant_id=tenant_id,
            status=status,
            limit=limit,
            offset=offset,
        )
    )
    return {
        "tickets": [
            _support_ticket_payload(ticket, include_tenant=True) for ticket in page.tickets
        ],
        "total": page.total,
        "limit": page.limit,
        "offset": page.offset,
        "has_more": page.offset + len(page.tickets) < page.total,
    }


@router.get("/tickets/{ticket_id}")
async def get_support_ticket(
    ticket_id: str,
    current_user: User = Depends(get_current_user),
    support_application: SupportTicketApplicationAuthorityV2 = Depends(
        support_ticket_application_authority_dependency_v2
    ),
) -> dict[str, Any]:
    """Get a specific support ticket."""
    ticket = await _support_call(
        support_application.services.get_ticket(
            user_id=current_user.id,
            ticket_id=ticket_id,
        )
    )
    return _support_ticket_payload(ticket, include_tenant=True)


@router.put("/tickets/{ticket_id}")
async def update_support_ticket(
    ticket_id: str,
    update_data: dict[str, Any],
    current_user: User = Depends(get_current_user),
    support_application: SupportTicketApplicationAuthorityV2 = Depends(
        support_ticket_application_authority_dependency_v2
    ),
) -> dict[str, Any]:
    """Update a support ticket."""
    ticket = await _support_call(
        support_application.services.update_ticket(
            user_id=current_user.id,
            ticket_id=ticket_id,
            data=update_data,
        )
    )
    return _support_ticket_payload(ticket, include_tenant=False)


@router.post("/tickets/{ticket_id}/close")
async def close_support_ticket(
    ticket_id: str,
    current_user: User = Depends(get_current_user),
    support_application: SupportTicketApplicationAuthorityV2 = Depends(
        support_ticket_application_authority_dependency_v2
    ),
) -> dict[str, Any]:
    """Close a support ticket."""
    ticket = await _support_call(
        support_application.services.close_ticket(
            user_id=current_user.id,
            ticket_id=ticket_id,
        )
    )
    return {
        "id": ticket.id,
        "status": ticket.status,
        "resolved_at": ticket.resolved_at.isoformat() if ticket.resolved_at else None,
    }


def _support_ticket_payload(
    ticket: SupportTicketSnapshotV2,
    *,
    include_tenant: bool,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": ticket.id,
        "subject": ticket.subject,
        "message": ticket.message,
        "priority": ticket.priority,
        "status": ticket.status,
        "created_at": ticket.created_at.isoformat(),
        "updated_at": ticket.updated_at.isoformat(),
        "resolved_at": ticket.resolved_at.isoformat() if ticket.resolved_at else None,
    }
    if include_tenant:
        payload = {"id": ticket.id, "tenant_id": ticket.tenant_id, **payload}
    return payload
