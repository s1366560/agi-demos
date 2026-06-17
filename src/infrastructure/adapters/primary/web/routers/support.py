"""Support ticket management router."""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import SupportTicket, User
from src.infrastructure.i18n import gettext as _

router = APIRouter(prefix="/support", tags=["support"])


@router.post("/tickets")
async def create_support_ticket(
    ticket_data: dict[str, Any],
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Create a new support ticket."""

    ticket_id = str(uuid4())
    ticket = SupportTicket(
        id=ticket_id,
        tenant_id=ticket_data.get("tenant_id"),
        user_id=current_user.id,
        subject=ticket_data.get("subject"),
        message=ticket_data.get("message"),
        priority=ticket_data.get("priority", "medium"),
        status="open",
    )

    db.add(ticket)
    await db.commit()
    await db.refresh(ticket)

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
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """List support tickets for the current user."""

    filters = [SupportTicket.user_id == current_user.id]

    if tenant_id:
        filters.append(SupportTicket.tenant_id == tenant_id)

    if status:
        filters.append(SupportTicket.status == status)

    total_result = await db.execute(
        refresh_select_statement(select(func.count()).select_from(SupportTicket).where(*filters))
    )
    total = int(total_result.scalar_one())

    query = (
        select(SupportTicket)
        .where(*filters)
        .order_by(SupportTicket.created_at.desc())
        .limit(limit)
        .offset(offset)
    )

    result = await db.execute(refresh_select_statement(query))
    tickets = result.scalars().all()

    return {
        "tickets": [
            {
                "id": ticket.id,
                "tenant_id": ticket.tenant_id,
                "subject": ticket.subject,
                "message": ticket.message,
                "priority": ticket.priority,
                "status": ticket.status,
                "created_at": ticket.created_at.isoformat(),
                "updated_at": ticket.updated_at.isoformat(),
                "resolved_at": ticket.resolved_at.isoformat() if ticket.resolved_at else None,
            }
            for ticket in tickets
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(tickets) < total,
    }


@router.get("/tickets/{ticket_id}")
async def get_support_ticket(
    ticket_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get a specific support ticket."""

    result = await db.execute(
        refresh_select_statement(
            select(SupportTicket).where(
                SupportTicket.id == ticket_id, SupportTicket.user_id == current_user.id
            )
        )
    )
    ticket = result.scalar_one_or_none()

    if not ticket:
        raise HTTPException(status_code=404, detail=_("Ticket not found"))

    return {
        "id": ticket.id,
        "tenant_id": ticket.tenant_id,
        "subject": ticket.subject,
        "message": ticket.message,
        "priority": ticket.priority,
        "status": ticket.status,
        "created_at": ticket.created_at.isoformat(),
        "updated_at": ticket.updated_at.isoformat(),
        "resolved_at": ticket.resolved_at.isoformat() if ticket.resolved_at else None,
    }


@router.put("/tickets/{ticket_id}")
async def update_support_ticket(
    ticket_id: str,
    update_data: dict[str, Any],
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Update a support ticket."""

    result = await db.execute(
        refresh_select_statement(
            select(SupportTicket).where(
                SupportTicket.id == ticket_id, SupportTicket.user_id == current_user.id
            )
        )
    )
    ticket = result.scalar_one_or_none()

    if not ticket:
        raise HTTPException(status_code=404, detail=_("Ticket not found"))

    # Update allowed fields
    if "subject" in update_data:
        ticket.subject = update_data["subject"]
    if "message" in update_data:
        ticket.message = update_data["message"]
    if "priority" in update_data:
        ticket.priority = update_data["priority"]

    await db.commit()
    await db.refresh(ticket)

    return {
        "id": ticket.id,
        "subject": ticket.subject,
        "message": ticket.message,
        "priority": ticket.priority,
        "status": ticket.status,
        "created_at": ticket.created_at.isoformat(),
        "updated_at": ticket.updated_at.isoformat(),
        "resolved_at": ticket.resolved_at.isoformat() if ticket.resolved_at else None,
    }


@router.post("/tickets/{ticket_id}/close")
async def close_support_ticket(
    ticket_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Close a support ticket."""

    result = await db.execute(
        refresh_select_statement(
            select(SupportTicket).where(
                SupportTicket.id == ticket_id, SupportTicket.user_id == current_user.id
            )
        )
    )
    ticket = result.scalar_one_or_none()

    if not ticket:
        raise HTTPException(status_code=404, detail=_("Ticket not found"))

    ticket.status = "closed"
    ticket.resolved_at = datetime.now(UTC)

    await db.commit()
    await db.refresh(ticket)

    return {"id": ticket.id, "status": ticket.status, "resolved_at": ticket.resolved_at.isoformat()}
