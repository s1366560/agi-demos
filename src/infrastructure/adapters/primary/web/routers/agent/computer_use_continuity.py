"""Renew lock continuity for a current task without extending its tool claim."""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.agent.native_computer_use.continuity import require_enable, require_source
from src.infrastructure.agent.native_computer_use.store import DeviceBridgeError, request_key
from src.infrastructure.i18n import gettext as _
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error

router = APIRouter()


class ContinuityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    device_id: str = Field(min_length=1, max_length=256)
    session_id: str = Field(min_length=1, max_length=256)
    cell_id: str | None = Field(default=None, min_length=1, max_length=256)
    step_id: str | None = Field(default=None, min_length=1, max_length=256)
    parent_request_id: str | None = Field(default=None, min_length=1, max_length=256)


@router.post("/device/requests/{request_id}/continuity-authority")
async def continuity_authority(
    request_id: str,
    body: ContinuityRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    from .computer_use_device import broker_from_request, require_request_authority
    from .computer_use_steps import current_agent_servers

    broker = broker_from_request(request)
    try:
        value = require_source(
            await broker.read(request_key(request_id)),
            user_id=current_user.id,
            device_id=body.device_id,
            session_id=body.session_id,
        )
        await require_enable(
            broker,
            value,
            cell_id=body.cell_id,
            step_id=body.step_id,
            parent_request_id=body.parent_request_id,
        )
        await require_request_authority(db, broker, value, current_user.id, resume=True)
        await current_agent_servers(db, value, "computer_locked_use")
        current = require_source(
            await broker.read(request_key(request_id)),
            user_id=current_user.id,
            device_id=body.device_id,
            session_id=body.session_id,
        )
        keys = (
            "request_id",
            "user_id",
            "tenant_id",
            "project_id",
            "device_id",
            "conversation_id",
            "run_id",
            "session_id",
            "authorization_revision",
        )
        if any(current.get(key) != value.get(key) for key in keys):
            raise DeviceBridgeError("computer_use_continuity_changed")
        await require_enable(
            broker,
            current,
            cell_id=body.cell_id,
            step_id=body.step_id,
            parent_request_id=body.parent_request_id,
        )
        return {
            **{key: value[key] for key in keys},
            "expires_at_ms": int(time.time() * 1000) + 5000,
        }
    except (DeviceBridgeError, RuntimeV2Error) as exc:
        raise HTTPException(
            status_code=409,
            detail=_("Computer Use continuity is unavailable or its authority changed"),
        ) from exc
