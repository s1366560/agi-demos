"""Notification API endpoints backed exclusively by a pinned V2 generation."""

from __future__ import annotations

import logging
from collections.abc import Awaitable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.notification_application_authority_v2 import (
    NotificationApplicationAuthorityV2,
    notification_application_authority_dependency_v2,
)
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.i18n import gettext as _
from src.infrastructure.plugins.v2.notification_services import (
    NotificationAccessDeniedV2,
    NotificationInvalidExpirationV2,
    NotificationNotFoundV2,
)

router = APIRouter(prefix="/api/v1", tags=["notifications"])
logger = logging.getLogger(__name__)


async def _notification_call[ResultT](operation: Awaitable[ResultT]) -> ResultT:
    try:
        return await operation
    except NotificationNotFoundV2 as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_("Notification not found"),
        ) from error
    except NotificationAccessDeniedV2 as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_("Cannot create notifications for another user"),
        ) from error
    except NotificationInvalidExpirationV2 as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_("Invalid notification expiration timestamp"),
        ) from error


@router.get("/notifications/")
async def list_notifications(
    unread_only: bool = Query(False),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    notification_application: NotificationApplicationAuthorityV2 = Depends(
        notification_application_authority_dependency_v2
    ),
) -> dict[str, Any]:
    """List live notifications for the current user."""
    notifications = await _notification_call(
        notification_application.services.list_notifications(
            user_id=current_user.id,
            unread_only=unread_only,
            limit=limit,
        )
    )
    return {
        "notifications": [
            {
                "id": notification.id,
                "type": notification.type,
                "title": notification.title,
                "message": notification.message,
                "data": notification.data,
                "is_read": notification.is_read,
                "action_url": notification.action_url,
                "created_at": notification.created_at.isoformat(),
                "expires_at": (
                    notification.expires_at.isoformat() if notification.expires_at else None
                ),
            }
            for notification in notifications
        ]
    }


@router.put("/notifications/{notification_id}/read")
async def mark_notification_read(
    notification_id: str,
    current_user: User = Depends(get_current_user),
    notification_application: NotificationApplicationAuthorityV2 = Depends(
        notification_application_authority_dependency_v2
    ),
) -> dict[str, Any]:
    """Mark a current-user notification as read."""
    await _notification_call(
        notification_application.services.mark_notification_read(
            user_id=current_user.id,
            notification_id=notification_id,
        )
    )
    return {"success": True}


@router.put("/notifications/read-all")
async def mark_all_read(
    current_user: User = Depends(get_current_user),
    notification_application: NotificationApplicationAuthorityV2 = Depends(
        notification_application_authority_dependency_v2
    ),
) -> dict[str, Any]:
    """Mark all unread notifications as read for the current user."""
    count = await _notification_call(
        notification_application.services.mark_all_read(user_id=current_user.id)
    )
    return {"success": True, "count": count}


@router.delete("/notifications/{notification_id}")
async def delete_notification(
    notification_id: str,
    current_user: User = Depends(get_current_user),
    notification_application: NotificationApplicationAuthorityV2 = Depends(
        notification_application_authority_dependency_v2
    ),
) -> dict[str, Any]:
    """Delete a current-user notification."""
    await _notification_call(
        notification_application.services.delete_notification(
            user_id=current_user.id,
            notification_id=notification_id,
        )
    )
    logger.info("Deleted notification %s for user %s", notification_id, current_user.id)
    return {"success": True}


@router.post("/notifications/create")
async def create_notification(
    notification_data: dict[str, Any],
    current_user: User = Depends(get_current_user),
    notification_application: NotificationApplicationAuthorityV2 = Depends(
        notification_application_authority_dependency_v2
    ),
) -> dict[str, Any]:
    """Create a notification through the generation-owned application service."""
    notification = await _notification_call(
        notification_application.services.create_notification(
            user_id=current_user.id,
            is_superuser=bool(current_user.is_superuser),
            data=notification_data,
        )
    )
    logger.info("Created notification %s for user %s", notification.id, notification.user_id)
    return {"id": notification.id, "success": True}
