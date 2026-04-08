"""SubAgent run trace and execution history endpoints."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent.subagent_run import SubAgentRun, SubAgentRunStatus
from src.domain.model.auth.user import User
from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import (
    Conversation as DBConversation,
    UserTenant as DBUserTenant,
)

from .access import (
    _get_user_id,
    has_global_admin_access,
    has_tenant_admin_access,
    require_tenant_access,
)
from .schemas import (
    ActiveRunCountResponse,
    DescendantTreeResponse,
    SubAgentRunListResponse,
    SubAgentRunResponse,
    TenantActiveRunCountResponse,
    TenantSubAgentRunListResponse,
    TraceChainResponse,
)
from .utils import get_container_with_db

logger = logging.getLogger(__name__)

router = APIRouter()

DEFAULT_TENANT_TRACE_LIMIT = 20
MAX_TENANT_TRACE_LIMIT = 100
DEFAULT_CONVERSATION_TRACE_LIMIT = 100
MAX_CONVERSATION_TRACE_LIMIT = 500
DEFAULT_TRACE_CHAIN_LIMIT = 200
MAX_TRACE_CHAIN_LIMIT = 500
DEFAULT_DESCENDANT_LIMIT = 200
MAX_DESCENDANT_LIMIT = 500
INTERNAL_ERROR_DETAIL = "Internal server error"


def run_to_response(
    run: SubAgentRun,
    *,
    redact_sensitive_fields: bool = False,
) -> SubAgentRunResponse:
    data: dict[str, Any] = run.to_event_data()
    if redact_sensitive_fields:
        data["metadata"] = {}
        data["frozen_result_text"] = None
    return SubAgentRunResponse(**data)


def parse_statuses(status_csv: str | None) -> list[SubAgentRunStatus] | None:
    if not status_csv:
        return None
    raw = [s.strip() for s in status_csv.split(",") if s.strip()]
    statuses: list[SubAgentRunStatus] = []
    for s in raw:
        try:
            statuses.append(SubAgentRunStatus(s))
        except ValueError as err:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status filter value: {s}",
            ) from err
    return statuses or None


async def _get_conversation(
    db: AsyncSession,
    conversation_id: str,
) -> DBConversation | None:
    """Load one conversation row for trace authorization."""
    result = await db.execute(select(DBConversation).where(DBConversation.id == conversation_id))
    return result.scalar_one_or_none()


async def _get_accessible_conversation(
    db: AsyncSession,
    current_user: User,
    conversation_id: str,
) -> DBConversation:
    """Require access to a conversation before returning it."""
    conversation = await _get_conversation(db, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail=f"Conversation {conversation_id} not found")

    current_user_id = _get_user_id(current_user)
    if conversation.user_id == current_user_id:
        try:
            await require_tenant_access(db, current_user, conversation.tenant_id)
        except HTTPException as exc:
            if exc.status_code == 403:
                raise HTTPException(
                    status_code=404,
                    detail=f"Conversation {conversation_id} not found",
                ) from exc
            raise
        return conversation

    if await has_tenant_admin_access(db, current_user, conversation.tenant_id):
        return conversation

    raise HTTPException(status_code=404, detail=f"Conversation {conversation_id} not found")


async def _list_accessible_tenant_conversation_ids(
    db: AsyncSession,
    current_user: User,
    tenant_id: str,
) -> list[str]:
    """List conversation ids the caller may inspect for one tenant."""
    await require_tenant_access(db, current_user, tenant_id)

    current_user_id = _get_user_id(current_user)
    query = (
        select(DBConversation.id)
        .where(DBConversation.tenant_id == tenant_id)
        .order_by(desc(DBConversation.updated_at), desc(DBConversation.created_at))
    )
    if not await has_tenant_admin_access(db, current_user, tenant_id):
        query = query.where(DBConversation.user_id == current_user_id)

    result = await db.execute(query)
    return list(result.scalars().all())


async def _list_user_conversation_ids(
    db: AsyncSession,
    current_user: User,
) -> list[str]:
    """List conversation ids the caller still has membership to."""
    current_user_id = _get_user_id(current_user)
    query = select(DBConversation.id).where(DBConversation.user_id == current_user_id)
    if not await has_global_admin_access(db, current_user):
        query = query.join(
            DBUserTenant,
            (DBUserTenant.user_id == current_user_id)
            & (DBUserTenant.tenant_id == DBConversation.tenant_id),
        )

    result = await db.execute(query.distinct())
    return list(result.scalars().all())


# --- Static routes MUST be registered before parameterised routes ---


@router.get(
    "/runs/tenant/{tenant_id}/active/count",
    response_model=TenantActiveRunCountResponse,
)
async def get_tenant_active_run_count(
    tenant_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TenantActiveRunCountResponse:
    try:
        container = get_container_with_db(request, db)
        registry = container.subagent_run_registry()

        conversation_ids = await _list_accessible_tenant_conversation_ids(
            db, current_user, tenant_id
        )
        count = registry.count_active_runs_for_conversations(conversation_ids)

        return TenantActiveRunCountResponse(
            tenant_id=tenant_id,
            active_count=count,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Error getting active run count for tenant %s: %s", tenant_id, e, exc_info=True
        )
        raise HTTPException(status_code=500, detail=INTERNAL_ERROR_DETAIL) from e


@router.get(
    "/runs/tenant/{tenant_id}",
    response_model=TenantSubAgentRunListResponse,
)
async def list_tenant_runs(
    tenant_id: str,
    request: Request,
    status: str | None = Query(None, description="Comma-separated status filter"),
    limit: int = Query(
        DEFAULT_TENANT_TRACE_LIMIT,
        ge=1,
        le=MAX_TENANT_TRACE_LIMIT,
        description="Maximum number of runs to return",
    ),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TenantSubAgentRunListResponse:
    try:
        container = get_container_with_db(request, db)
        registry = container.subagent_run_registry()

        statuses = parse_statuses(status)
        conversation_ids = await _list_accessible_tenant_conversation_ids(
            db, current_user, tenant_id
        )
        runs = registry.list_runs_for_conversations(
            conversation_ids,
            statuses=statuses,
            limit=limit,
        )
        response_runs = [run_to_response(run, redact_sensitive_fields=True) for run in runs]
        return TenantSubAgentRunListResponse(
            tenant_id=tenant_id,
            runs=response_runs,
            total=len(response_runs),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error listing runs for tenant %s: %s", tenant_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail=INTERNAL_ERROR_DETAIL) from e


@router.get(
    "/runs/active/count",
    response_model=ActiveRunCountResponse,
)
async def get_active_run_count(
    request: Request,
    conversation_id: str | None = Query(None, description="Scope to specific conversation"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ActiveRunCountResponse:
    try:
        container = get_container_with_db(request, db)
        registry = container.subagent_run_registry()

        if conversation_id:
            conversation = await _get_accessible_conversation(db, current_user, conversation_id)
            count = registry.count_active_runs(conversation.id)
        else:
            conversation_ids = await _list_user_conversation_ids(db, current_user)
            count = registry.count_active_runs_for_conversations(conversation_ids)

        return ActiveRunCountResponse(
            active_count=count,
            conversation_id=conversation_id,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting active run count: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=INTERNAL_ERROR_DETAIL) from e


@router.get(
    "/runs/{conversation_id}",
    response_model=SubAgentRunListResponse,
)
async def list_runs(
    conversation_id: str,
    request: Request,
    status: str | None = Query(None, description="Comma-separated status filter"),
    trace_id: str | None = Query(None, description="Filter by trace_id"),
    limit: int | None = Query(
        None,
        ge=1,
        le=MAX_CONVERSATION_TRACE_LIMIT,
        description="Maximum number of runs to return",
    ),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SubAgentRunListResponse:
    try:
        conversation = await _get_accessible_conversation(db, current_user, conversation_id)
        container = get_container_with_db(request, db)
        registry = container.subagent_run_registry()

        statuses = parse_statuses(status)
        matching_runs: list[SubAgentRun]
        if trace_id:
            matching_runs = registry.list_trace_runs(
                conversation.id,
                trace_id,
                statuses=statuses,
            )
        else:
            matching_runs = registry.list_runs(conversation.id, statuses=statuses)

        runs = matching_runs[:limit] if limit is not None else matching_runs

        response_runs = [run_to_response(r) for r in runs]
        return SubAgentRunListResponse(
            conversation_id=conversation.id,
            runs=response_runs,
            total=len(matching_runs),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing runs for {conversation_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=INTERNAL_ERROR_DETAIL) from e


@router.get(
    "/runs/{conversation_id}/trace/{trace_id}",
    response_model=TraceChainResponse,
)
async def get_trace_chain(
    conversation_id: str,
    trace_id: str,
    request: Request,
    limit: int | None = Query(
        None,
        ge=1,
        le=MAX_TRACE_CHAIN_LIMIT,
        description="Maximum number of trace runs to return",
    ),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TraceChainResponse:
    try:
        conversation = await _get_accessible_conversation(db, current_user, conversation_id)
        container = get_container_with_db(request, db)
        registry = container.subagent_run_registry()

        matching_chain = registry.list_trace_runs(
            conversation.id,
            trace_id,
            reverse=False,
        )
        chain = matching_chain[:limit] if limit is not None else matching_chain

        response_runs = [run_to_response(r) for r in chain]
        return TraceChainResponse(
            trace_id=trace_id,
            conversation_id=conversation.id,
            runs=response_runs,
            total=len(matching_chain),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting trace chain {trace_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=INTERNAL_ERROR_DETAIL) from e


@router.get(
    "/runs/{conversation_id}/{run_id}/descendants",
    response_model=DescendantTreeResponse,
)
async def get_descendants(
    conversation_id: str,
    run_id: str,
    request: Request,
    include_terminal: bool = Query(True, description="Include terminal (completed/failed) runs"),
    limit: int | None = Query(
        None,
        ge=1,
        le=MAX_DESCENDANT_LIMIT,
        description="Maximum number of descendant runs to return",
    ),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DescendantTreeResponse:
    try:
        conversation = await _get_accessible_conversation(db, current_user, conversation_id)
        container = get_container_with_db(request, db)
        registry = container.subagent_run_registry()

        matching_descendants: list[SubAgentRun] = registry.list_descendant_runs(
            conversation.id,
            run_id,
            include_terminal=include_terminal,
        )
        descendants = matching_descendants[:limit] if limit is not None else matching_descendants

        response_runs = [run_to_response(r) for r in descendants]
        return DescendantTreeResponse(
            parent_run_id=run_id,
            conversation_id=conversation.id,
            descendants=response_runs,
            total=len(matching_descendants),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting descendants for {run_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=INTERNAL_ERROR_DETAIL) from e


@router.get(
    "/runs/{conversation_id}/{run_id}",
    response_model=SubAgentRunResponse,
)
async def get_run(
    conversation_id: str,
    run_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SubAgentRunResponse:
    try:
        conversation = await _get_accessible_conversation(db, current_user, conversation_id)
        container = get_container_with_db(request, db)
        registry = container.subagent_run_registry()

        run = registry.get_run(conversation.id, run_id)
        if run is None:
            raise HTTPException(
                status_code=404,
                detail=f"Run {run_id} not found in conversation {conversation.id}",
            )
        return run_to_response(run)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting run {run_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=INTERNAL_ERROR_DETAIL) from e
