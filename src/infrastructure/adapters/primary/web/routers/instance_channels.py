"""Instance Channel Configuration API endpoints."""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.instance_channel_service import (
    InstanceChannelService,
)
from src.domain.model.auth.user import User
from src.domain.model.instance.instance_channel import InstanceChannelConfig
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.routers.agent.access import (
    require_tenant_access,
)
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import InstanceModel
from src.infrastructure.adapters.secondary.persistence.sql_instance_channel_repository import (
    SqlInstanceChannelRepository,
)
from src.infrastructure.i18n import gettext as _

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/instances", tags=["Instance Channels"])


class CreateChannelRequest(BaseModel):
    """Request body for creating a channel config."""

    channel_type: str
    name: str
    config: dict[str, Any] = {}


class UpdateChannelRequest(BaseModel):
    """Request body for updating a channel config."""

    name: str | None = None
    config: dict[str, Any] | None = None


def _build_service(db: AsyncSession) -> InstanceChannelService:
    repo = SqlInstanceChannelRepository(db)
    return InstanceChannelService(channel_repo=repo)


def _serialize(entity: InstanceChannelConfig) -> dict[str, Any]:
    raw = asdict(entity)
    for key, val in raw.items():
        if hasattr(val, "isoformat"):
            raw[key] = val.isoformat()
    return raw


async def _require_instance_access(
    instance_id: str,
    current_user: User,
    db: AsyncSession,
    *,
    require_admin: bool = False,
) -> None:
    result = await db.execute(
        refresh_select_statement(
            select(InstanceModel.tenant_id).where(
                InstanceModel.id == instance_id,
                InstanceModel.deleted_at.is_(None),
            )
        )
    )
    tenant_id = result.scalar_one_or_none()
    if tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_("Instance not found"),
        )
    if getattr(current_user, "is_superuser", False):
        return
    await require_tenant_access(db, current_user, str(tenant_id), require_admin=require_admin)


@router.get("/{instance_id}/channels")
async def list_channels(
    instance_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """List all channel configs for an instance."""
    await _require_instance_access(instance_id, current_user, db)
    svc = _build_service(db)
    items = await svc.list_channels(instance_id)
    return {"items": [_serialize(c) for c in items]}


@router.post(
    "/{instance_id}/channels",
    status_code=status.HTTP_201_CREATED,
)
async def create_channel(
    instance_id: str,
    body: CreateChannelRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Create a new channel config for an instance."""
    await _require_instance_access(instance_id, current_user, db, require_admin=True)
    svc = _build_service(db)
    entity = await svc.create_channel(
        instance_id=instance_id,
        channel_type=body.channel_type,
        name=body.name,
        config=body.config,
    )
    await db.commit()
    return _serialize(entity)


@router.put("/{instance_id}/channels/{channel_id}")
async def update_channel(
    instance_id: str,
    channel_id: str,
    body: UpdateChannelRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Update a channel config."""
    await _require_instance_access(instance_id, current_user, db, require_admin=True)
    svc = _build_service(db)
    try:
        entity = await svc.update_channel(
            channel_id=channel_id,
            expected_instance_id=instance_id,
            name=body.name,
            config=body.config,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    await db.commit()
    return _serialize(entity)


@router.delete(
    "/{instance_id}/channels/{channel_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_channel(
    instance_id: str,
    channel_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a channel config (soft-delete)."""
    await _require_instance_access(instance_id, current_user, db, require_admin=True)
    svc = _build_service(db)
    try:
        await svc.delete_channel(channel_id, expected_instance_id=instance_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    await db.commit()


@router.post("/{instance_id}/channels/{channel_id}/test")
async def test_channel_connection(
    instance_id: str,
    channel_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Test a channel connection."""
    await _require_instance_access(instance_id, current_user, db, require_admin=True)
    svc = _build_service(db)
    try:
        result = await svc.test_connection(channel_id, expected_instance_id=instance_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    await db.commit()
    return result
