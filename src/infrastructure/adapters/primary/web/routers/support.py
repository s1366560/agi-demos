"""Support ticket management router."""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import SupportTicket, User

router = APIRouter(prefix="/support", tags=["support"])


@router.post("/tickets")
async def create_support_ticket(
    ticket_data: dict,
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
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """List support tickets for the current user."""

    query = select(SupportTicket).where(SupportTicket.user_id == current_user.id)

    if tenant_id:
        query = query.where(SupportTicket.tenant_id == tenant_id)

    if status:
        query = query.where(SupportTicket.status == status)

    query = query.order_by(SupportTicket.created_at.desc())

    result = await db.execute(query)
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
        ]
    }


@router.get("/tickets/{ticket_id}")
async def get_support_ticket(
    ticket_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get a specific support ticket."""

    result = await db.execute(
        select(SupportTicket).where(
            SupportTicket.id == ticket_id, SupportTicket.user_id == current_user.id
        )
    )
    ticket = result.scalar_one_or_none()

    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

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
    update_data: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Update a support ticket."""

    result = await db.execute(
        select(SupportTicket).where(
            SupportTicket.id == ticket_id, SupportTicket.user_id == current_user.id
        )
    )
    ticket = result.scalar_one_or_none()

    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

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
        select(SupportTicket).where(
            SupportTicket.id == ticket_id, SupportTicket.user_id == current_user.id
        )
    )
    ticket = result.scalar_one_or_none()

    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    ticket.status = "closed"
    ticket.resolved_at = datetime.now(UTC)

    await db.commit()
    await db.refresh(ticket)

    return {"id": ticket.id, "status": ticket.status, "resolved_at": ticket.resolved_at.isoformat()}
