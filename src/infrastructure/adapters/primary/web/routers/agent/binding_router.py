"""CRUD endpoints for AgentBinding management."""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent.agent_binding import AgentBinding
from src.domain.model.auth.user import User
from src.infrastructure.adapters.primary.web.agent_binding_http_application_authority_v2 import (
    AgentBindingHttpApplicationAuthorityV2,
    agent_binding_http_application_authority_v2,
)
from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user,
)
from src.infrastructure.adapters.primary.web.dependencies.auth_dependencies import (
    get_current_user_tenant,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.i18n import gettext as _
from src.infrastructure.plugins.v2.agent_binding_services import (
    AgentBindingAgentUnavailableV2,
    AgentBindingNotFoundV2,
    AgentBindingScopeMismatchV2,
)

from .access import require_tenant_access

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


async def _get_selected_binding_tenant_id(
    selected_tenant_id: str | None = Query(
        None,
        alias="tenant_id",
        min_length=1,
        description="Explicit tenant scope for multi-tenant callers.",
    ),
    fallback_tenant_id: str = Depends(get_current_user_tenant),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> str:
    if selected_tenant_id is None:
        return fallback_tenant_id
    await require_tenant_access(db, cast(Any, current_user), selected_tenant_id)
    return selected_tenant_id


async def agent_binding_http_application_authority_dependency_v2(
    request: Request,
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(_get_selected_binding_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> AsyncIterator[AgentBindingHttpApplicationAuthorityV2]:
    async with agent_binding_http_application_authority_v2(
        request=request,
        current_user=current_user,
        tenant_id=tenant_id,
        db=db,
    ) as authority:
        yield authority


@router.post("/bindings")
async def create_binding(
    body: CreateBindingRequest,
    current_user: User = Depends(get_current_user),
    binding_authority: AgentBindingHttpApplicationAuthorityV2 = Depends(
        agent_binding_http_application_authority_dependency_v2
    ),
) -> dict[str, Any]:
    try:
        await require_tenant_access(
            binding_authority.db,
            current_user,
            binding_authority.tenant_id,
            require_admin=True,
        )

        binding = AgentBinding(
            id=str(uuid.uuid4()),
            tenant_id=binding_authority.tenant_id,
            agent_id=body.agent_id,
            channel_type=body.channel_type,
            channel_id=body.channel_id,
            account_id=body.account_id,
            peer_id=body.peer_id,
            group_id=body.group_id,
            priority=body.priority,
        )
        created = await binding_authority.service.create(binding)
        await binding_authority.db.commit()
        return created.to_dict()

    except (
        AgentBindingAgentUnavailableV2,
        AgentBindingScopeMismatchV2,
        ValueError,
    ) as e:
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
    agent_id: str | None = None,
    enabled_only: bool = False,
    current_user: User = Depends(get_current_user),
    binding_authority: AgentBindingHttpApplicationAuthorityV2 = Depends(
        agent_binding_http_application_authority_dependency_v2
    ),
) -> list[dict[str, Any]]:
    try:
        await require_tenant_access(
            binding_authority.db,
            current_user,
            binding_authority.tenant_id,
        )
        bindings = await binding_authority.service.list_bindings(
            agent_id=agent_id,
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
    current_user: User = Depends(get_current_user),
    binding_authority: AgentBindingHttpApplicationAuthorityV2 = Depends(
        agent_binding_http_application_authority_dependency_v2
    ),
) -> dict[str, Any]:
    try:
        await require_tenant_access(
            binding_authority.db,
            current_user,
            binding_authority.tenant_id,
            require_admin=True,
        )
        deleted = await binding_authority.service.delete(binding_id)
        await binding_authority.db.commit()
        return {"deleted": deleted, "id": binding_id}

    except AgentBindingNotFoundV2 as e:
        raise HTTPException(status_code=404, detail=_("Binding not found")) from e
    except AgentBindingScopeMismatchV2 as e:
        raise HTTPException(status_code=403, detail=_("Access denied")) from e
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
    current_user: User = Depends(get_current_user),
    binding_authority: AgentBindingHttpApplicationAuthorityV2 = Depends(
        agent_binding_http_application_authority_dependency_v2
    ),
) -> dict[str, Any]:
    try:
        await require_tenant_access(
            binding_authority.db,
            current_user,
            binding_authority.tenant_id,
            require_admin=True,
        )
        updated = await binding_authority.service.set_enabled(
            binding_id,
            enabled=body.enabled,
        )
        await binding_authority.db.commit()
        return updated.to_dict()

    except AgentBindingNotFoundV2 as e:
        raise HTTPException(status_code=404, detail=_("Binding not found")) from e
    except AgentBindingScopeMismatchV2 as e:
        raise HTTPException(status_code=403, detail=_("Access denied")) from e
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
    current_user: User = Depends(get_current_user),
    binding_authority: AgentBindingHttpApplicationAuthorityV2 = Depends(
        agent_binding_http_application_authority_dependency_v2
    ),
) -> list[dict[str, Any]]:
    try:
        await require_tenant_access(
            binding_authority.db,
            current_user,
            binding_authority.tenant_id,
        )
        bindings = await binding_authority.service.list_group(group_id)

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
    current_user: User = Depends(get_current_user),
    binding_authority: AgentBindingHttpApplicationAuthorityV2 = Depends(
        agent_binding_http_application_authority_dependency_v2
    ),
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
        await require_tenant_access(
            binding_authority.db,
            current_user,
            binding_authority.tenant_id,
        )
        match = await binding_authority.service.resolve_with_trace(
            channel_type=body.channel_type,
            channel_id=body.channel_id,
            account_id=body.account_id,
            peer_id=body.peer_id,
        )
        trace_entries = [BindingTraceEntry.model_validate(entry) for entry in match.trace]

        if match.binding is None:
            return TestBindingResponse(
                agent_id=None,
                agent_name=None,
                binding_id=None,
                specificity_score=0,
                confidence=0.0,
                matched=False,
                trace=trace_entries,
            )

        # Calculate confidence based on specificity score
        # Max theoretical score: 15 (1+2+4+8 + priority)
        # Normalized to 0-1 range
        max_score = 15
        confidence = min(1.0, match.binding.specificity_score / max_score)

        return TestBindingResponse(
            agent_id=match.binding.agent_id,
            agent_name=match.agent_name,
            binding_id=match.binding.id,
            specificity_score=match.binding.specificity_score,
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
