"""Notification API endpoints."""

import logging
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import Notification, User

router = APIRouter(prefix="/api/v1", tags=["notifications"])
logger = logging.getLogger(__name__)


@router.get("/notifications/")
async def list_notifications(
    unread_only: bool = Query(False),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List notifications for the current user."""
    query = select(Notification).where(Notification.user_id == current_user.id)

    if unread_only:
        query = query.where(Notification.is_read.is_(False))

    query = query.order_by(Notification.created_at.desc()).limit(limit)

    result = await db.execute(query)
    notifications = result.scalars().all()

    # Filter out expired notifications
    valid_notifications = []
    now_utc = datetime.now(timezone.utc)
    for notif in notifications:
        # Include notification if not expired (no expires_at or expires_at is in future)
        if not notif.expires_at:
            valid_notifications.append(notif)
        else:
            exp = notif.expires_at
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if exp > now_utc:
                valid_notifications.append(notif)

    return {
        "notifications": [
            {
                "id": notif.id,
                "type": notif.type,
                "title": notif.title,
                "message": notif.message,
                "data": notif.data,
                "is_read": notif.is_read,
                "action_url": notif.action_url,
                "created_at": notif.created_at.isoformat(),
                "expires_at": notif.expires_at.isoformat() if notif.expires_at else None,
            }
            for notif in valid_notifications
        ]
    }


@router.put("/notifications/{notification_id}/read")
async def mark_notification_read(
    notification_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark a notification as read."""
    result = await db.execute(
        select(Notification).where(
            and_(Notification.id == notification_id, Notification.user_id == current_user.id)
        )
    )
    notification = result.scalar_one_or_none()

    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")

    notification.is_read = True
    await db.commit()

    return {"success": True}


@router.put("/notifications/read-all")
async def mark_all_read(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark all notifications as read for the current user."""
    result = await db.execute(
        select(Notification).where(
            and_(Notification.user_id == current_user.id, Notification.is_read.is_(False))
        )
    )
    notifications = result.scalars().all()

    for notif in notifications:
        notif.is_read = True

    await db.commit()

    return {"success": True, "count": len(notifications)}


@router.delete("/notifications/{notification_id}")
async def delete_notification(
    notification_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a notification."""
    result = await db.execute(
        select(Notification).where(
            and_(Notification.id == notification_id, Notification.user_id == current_user.id)
        )
    )
    notification = result.scalar_one_or_none()

    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")

    await db.delete(notification)
    await db.commit()

    logger.info(f"Deleted notification {notification_id} for user {current_user.id}")

    return {"success": True}


@router.post("/notifications/create")
async def create_notification(
    notification_data: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new notification (for internal use)."""
    notification = Notification(
        id=str(uuid4()),
        user_id=notification_data.get("user_id", current_user.id),
        type=notification_data.get("type", "general"),
        title=notification_data.get("title", "Notification"),
        message=notification_data.get("message", ""),
        data=notification_data.get("data", {}),
        action_url=notification_data.get("action_url"),
    )

    db.add(notification)
    await db.commit()

    logger.info(f"Created notification {notification.id} for user {notification.user_id}")

    return {"id": notification.id, "success": True}
