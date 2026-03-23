"""CRUD endpoints for AgentBinding management."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent.agent_binding import AgentBinding
from src.domain.model.auth.user import User
from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user,
)
from src.infrastructure.adapters.primary.web.dependencies.auth_dependencies import (
    get_current_user_tenant,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db

from .utils import get_container_with_db

logger = logging.getLogger(__name__)

router = APIRouter()


class CreateBindingRequest(BaseModel):
    agent_id: str
    channel_type: str | None = None
    channel_id: str | None = None
    account_id: str | None = None
    peer_id: str | None = None
    group_id: str | None = None
    priority: int = 0


class SetEnabledRequest(BaseModel):
    enabled: bool


@router.post("/bindings")
async def create_binding(
    body: CreateBindingRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        container = get_container_with_db(request, db)
        repo = container.agent_binding_repository()

        binding = AgentBinding(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            agent_id=body.agent_id,
            channel_type=body.channel_type,
            channel_id=body.channel_id,
            account_id=body.account_id,
            peer_id=body.peer_id,
            group_id=body.group_id,
            priority=body.priority,
        )

        created = await repo.create(binding)
        await db.commit()
        return created.to_dict()

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error creating binding: %s", e, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create binding: {e!s}",
        ) from e


@router.get("/bindings")
async def list_bindings(
    request: Request,
    agent_id: str | None = None,
    enabled_only: bool = False,
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    try:
        container = get_container_with_db(request, db)
        repo = container.agent_binding_repository()

        if agent_id:
            bindings = await repo.list_by_agent(
                agent_id=agent_id,
                enabled_only=enabled_only,
            )
        else:
            bindings = await repo.list_by_tenant(
                tenant_id=tenant_id,
                enabled_only=enabled_only,
            )

        return [b.to_dict() for b in bindings]

    except Exception as e:
        logger.error("Error listing bindings: %s", e, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list bindings: {e!s}",
        ) from e


@router.delete("/bindings/{binding_id}")
async def delete_binding(
    binding_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        container = get_container_with_db(request, db)
        repo = container.agent_binding_repository()

        existing = await repo.get_by_id(binding_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="Binding not found")

        if existing.tenant_id != tenant_id:
            raise HTTPException(status_code=403, detail="Access denied")

        await repo.delete(binding_id)
        await db.commit()
        return {"deleted": True, "id": binding_id}

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error deleting binding: %s", e, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete binding: {e!s}",
        ) from e


@router.patch("/bindings/{binding_id}/enabled")
async def set_binding_enabled(
    binding_id: str,
    body: SetEnabledRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        container = get_container_with_db(request, db)
        repo = container.agent_binding_repository()

        existing = await repo.get_by_id(binding_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="Binding not found")

        if existing.tenant_id != tenant_id:
            raise HTTPException(status_code=403, detail="Access denied")

        updated = await repo.set_enabled(binding_id, body.enabled)
        await db.commit()
        return updated.to_dict()

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.error("Error updating binding: %s", e, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update binding: {e!s}",
        ) from e


@router.get("/bindings/groups/{group_id}")
async def list_group_bindings(
    group_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    try:
        container = get_container_with_db(request, db)
        repo = container.agent_binding_repository()

        bindings = await repo.find_by_group(
            tenant_id=tenant_id,
            group_id=group_id,
        )

        return [b.to_dict() for b in bindings]

    except Exception as e:
        logger.error("Error listing group bindings: %s", e, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list group bindings: {e!s}",
        ) from e
