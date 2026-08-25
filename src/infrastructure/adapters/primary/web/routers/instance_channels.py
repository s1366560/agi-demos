"""Instance Channel Configuration API endpoints."""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from src.domain.model.instance.instance_channel import InstanceChannelConfig
from src.infrastructure.adapters.primary.web.instance_channel_application_authority_v2 import (
    InstanceChannelApplicationAuthorityV2,
    instance_channel_application_authority_dependency_v2,
)
from src.infrastructure.adapters.primary.web.routers.agent.access import (
    require_tenant_access,
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


def _serialize(entity: InstanceChannelConfig) -> dict[str, Any]:
    raw = asdict(entity)
    for key, val in raw.items():
        if hasattr(val, "isoformat"):
            raw[key] = val.isoformat()
    return raw


def _channel_not_found_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=_("Instance channel not found"),
    )


async def _require_instance_access(
    authority: InstanceChannelApplicationAuthorityV2,
    instance_id: str,
    *,
    require_admin: bool = False,
) -> None:
    tenant_id = await authority.services.access.tenant_id_for_instance(instance_id)
    if tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_("Instance not found"),
        )
    if getattr(authority.current_user, "is_superuser", False):
        return
    await require_tenant_access(
        authority.db,
        authority.current_user,
        tenant_id,
        require_admin=require_admin,
    )


@router.get("/{instance_id}/channels")
async def list_channels(
    instance_id: str,
    authority: InstanceChannelApplicationAuthorityV2 = Depends(
        instance_channel_application_authority_dependency_v2
    ),
) -> dict[str, Any]:
    """List all channel configs for an instance."""
    await _require_instance_access(authority, instance_id)
    svc = authority.services.channels
    items = await svc.list_channels(instance_id)
    return {"items": [_serialize(c) for c in items]}


@router.post(
    "/{instance_id}/channels",
    status_code=status.HTTP_201_CREATED,
)
async def create_channel(
    instance_id: str,
    body: CreateChannelRequest,
    authority: InstanceChannelApplicationAuthorityV2 = Depends(
        instance_channel_application_authority_dependency_v2
    ),
) -> dict[str, Any]:
    """Create a new channel config for an instance."""
    await _require_instance_access(authority, instance_id, require_admin=True)
    svc = authority.services.channels
    entity = await svc.create_channel(
        instance_id=instance_id,
        channel_type=body.channel_type,
        name=body.name,
        config=body.config,
    )
    await authority.db.commit()
    return _serialize(entity)


@router.put("/{instance_id}/channels/{channel_id}")
async def update_channel(
    instance_id: str,
    channel_id: str,
    body: UpdateChannelRequest,
    authority: InstanceChannelApplicationAuthorityV2 = Depends(
        instance_channel_application_authority_dependency_v2
    ),
) -> dict[str, Any]:
    """Update a channel config."""
    await _require_instance_access(authority, instance_id, require_admin=True)
    svc = authority.services.channels
    try:
        entity = await svc.update_channel(
            channel_id=channel_id,
            expected_instance_id=instance_id,
            name=body.name,
            config=body.config,
        )
    except ValueError as exc:
        raise _channel_not_found_error() from exc
    await authority.db.commit()
    return _serialize(entity)


@router.delete(
    "/{instance_id}/channels/{channel_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_channel(
    instance_id: str,
    channel_id: str,
    authority: InstanceChannelApplicationAuthorityV2 = Depends(
        instance_channel_application_authority_dependency_v2
    ),
) -> None:
    """Delete a channel config (soft-delete)."""
    await _require_instance_access(authority, instance_id, require_admin=True)
    svc = authority.services.channels
    try:
        await svc.delete_channel(channel_id, expected_instance_id=instance_id)
    except ValueError as exc:
        raise _channel_not_found_error() from exc
    await authority.db.commit()


@router.post("/{instance_id}/channels/{channel_id}/test")
async def test_channel_connection(
    instance_id: str,
    channel_id: str,
    authority: InstanceChannelApplicationAuthorityV2 = Depends(
        instance_channel_application_authority_dependency_v2
    ),
) -> dict[str, str]:
    """Test a channel connection."""
    await _require_instance_access(authority, instance_id, require_admin=True)
    svc = authority.services.channels
    try:
        result = await svc.test_connection(channel_id, expected_instance_id=instance_id)
    except ValueError as exc:
        raise _channel_not_found_error() from exc
    await authority.db.commit()
    return result
