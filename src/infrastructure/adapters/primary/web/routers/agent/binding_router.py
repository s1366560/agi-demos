"""CRUD endpoints for AgentBinding management."""

from __future__ import annotations

import logging
import uuid
from typing import Any, cast

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
from src.infrastructure.i18n import gettext as _

from .access import require_tenant_access
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


class TestBindingRequest(BaseModel):
    channel_type: str
    channel_id: str | None = None
    account_id: str | None = None
    peer_id: str | None = None


class BindingTraceEntry(BaseModel):
    binding_id: str
    agent_id: str
    specificity_score: int
    channel_type: str | None
    channel_id: str | None
    account_id: str | None
    peer_id: str | None
    priority: int
    eliminated: bool
    elimination_reason: str | None
    selected: bool


class TestBindingResponse(BaseModel):
    agent_id: str | None
    agent_name: str | None
    binding_id: str | None
    specificity_score: int
    confidence: float
    matched: bool
    trace: list[BindingTraceEntry]


@router.post("/bindings")
async def create_binding(
    body: CreateBindingRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        await require_tenant_access(db, current_user, tenant_id, require_admin=True)
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
        agent_registry = container.agent_registry()
        agent = await agent_registry.get_by_id(binding.agent_id, tenant_id=tenant_id)
        if agent is None or agent.project_id is not None:
            raise ValueError("Agent is not available for tenant-level binding")

        created = await repo.create(binding)
        await db.commit()
        return cast(dict[str, Any], created.to_dict())

    except ValueError as e:
        raise HTTPException(status_code=400, detail=_("Invalid binding request")) from e
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error creating binding")
        raise HTTPException(
            status_code=500,
            detail=_("Failed to create binding"),
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
        await require_tenant_access(db, current_user, tenant_id)
        container = get_container_with_db(request, db)
        repo = container.agent_binding_repository()

        if agent_id:
            bindings = [
                binding
                for binding in await repo.list_by_agent(
                    agent_id=agent_id,
                    enabled_only=enabled_only,
                )
                if binding.tenant_id == tenant_id
            ]
        else:
            bindings = await repo.list_by_tenant(
                tenant_id=tenant_id,
                enabled_only=enabled_only,
            )

        return [b.to_dict() for b in bindings]

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error listing bindings")
        raise HTTPException(
            status_code=500,
            detail=_("Failed to list bindings"),
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
        await require_tenant_access(db, current_user, tenant_id, require_admin=True)
        container = get_container_with_db(request, db)
        repo = container.agent_binding_repository()

        existing = await repo.get_by_id(binding_id)
        if existing is None:
            raise HTTPException(status_code=404, detail=_("Binding not found"))

        if existing.tenant_id != tenant_id:
            raise HTTPException(status_code=403, detail=_("Access denied"))

        await repo.delete(binding_id)
        await db.commit()
        return {"deleted": True, "id": binding_id}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error deleting binding")
        raise HTTPException(
            status_code=500,
            detail=_("Failed to delete binding"),
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
        await require_tenant_access(db, current_user, tenant_id, require_admin=True)
        container = get_container_with_db(request, db)
        repo = container.agent_binding_repository()

        existing = await repo.get_by_id(binding_id)
        if existing is None:
            raise HTTPException(status_code=404, detail=_("Binding not found"))

        if existing.tenant_id != tenant_id:
            raise HTTPException(status_code=403, detail=_("Access denied"))

        updated = await repo.set_enabled(binding_id, body.enabled)
        await db.commit()
        return cast(dict[str, Any], updated.to_dict())

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=_("Invalid binding update")) from e
    except Exception as e:
        logger.exception("Error updating binding")
        raise HTTPException(
            status_code=500,
            detail=_("Failed to update binding"),
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
        await require_tenant_access(db, current_user, tenant_id)
        container = get_container_with_db(request, db)
        repo = container.agent_binding_repository()

        bindings = await repo.find_by_group(
            tenant_id=tenant_id,
            group_id=group_id,
        )

        return [b.to_dict() for b in bindings]

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error listing group bindings")
        raise HTTPException(
            status_code=500,
            detail=_("Failed to list group bindings"),
        ) from e


@router.post("/bindings/test", response_model=TestBindingResponse)
async def test_binding_match(
    body: TestBindingRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> TestBindingResponse:
    """Test which SubAgent would handle a message with given context.

    Returns the matching SubAgent and confidence score.
    Uses specificity-based resolution (most-specific wins).

    Args:
        body: Test context with channel_type, channel_id, account_id, peer_id

    Returns:
        TestBindingResponse with matched agent info and confidence score
    """
    try:
        await require_tenant_access(db, current_user, tenant_id)
        container = get_container_with_db(request, db)
        binding_repo = container.agent_binding_repository()
        agent_registry = container.agent_registry()

        # Resolve binding using specificity-based matching (with trace)
        binding, raw_trace = await binding_repo.resolve_binding_with_trace(
            tenant_id=tenant_id,
            channel_type=body.channel_type,
            channel_id=body.channel_id,
            account_id=body.account_id,
            peer_id=body.peer_id,
        )
        trace_entries = [BindingTraceEntry(**entry) for entry in raw_trace]

        if binding is None:
            return TestBindingResponse(
                agent_id=None,
                agent_name=None,
                binding_id=None,
                specificity_score=0,
                confidence=0.0,
                matched=False,
                trace=trace_entries,
            )

        # Get agent details
        agent = await agent_registry.get_by_id(binding.agent_id, tenant_id=tenant_id)
        agent_name = agent.name if agent else None

        # Calculate confidence based on specificity score
        # Max theoretical score: 15 (1+2+4+8 + priority)
        # Normalized to 0-1 range
        max_score = 15
        confidence = min(1.0, binding.specificity_score / max_score)

        return TestBindingResponse(
            agent_id=binding.agent_id,
            agent_name=agent_name,
            binding_id=binding.id,
            specificity_score=binding.specificity_score,
            confidence=round(confidence, 2),
            matched=True,
            trace=trace_entries,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error testing binding match")
        raise HTTPException(
            status_code=500,
            detail=_("Failed to test binding"),
        ) from e
