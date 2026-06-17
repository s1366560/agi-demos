from __future__ import annotations

from datetime import datetime
from typing import Any, cast

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.event_log_service import EventLogService
from src.configuration.features import require_feature
from src.infrastructure.adapters.primary.web.dependencies.auth_dependencies import (
    get_current_user,
    get_current_user_tenant,
)
from src.infrastructure.adapters.primary.web.routers.agent.access import require_tenant_access
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User as DBUser

router = APIRouter(
    prefix="/api/v1/events", tags=["events"], dependencies=[require_feature("events")]
)


class EventLogResponse(BaseModel):
    id: str
    tenant_id: str
    event_type: str
    message: str
    source: str
    metadata: dict[str, Any]
    created_at: datetime


class EventLogListResponse(BaseModel):
    items: list[EventLogResponse]
    total: int
    page: int
    page_size: int


async def get_event_service(
    db: Any = Depends(get_db),  # noqa: ANN401
) -> EventLogService:
    from src.infrastructure.adapters.secondary.persistence.sql_event_log_repository import (
        SqlEventLogRepository,
    )

    return EventLogService(SqlEventLogRepository(db))


async def get_selected_event_tenant(
    selected_tenant_id: str | None = Query(
        None,
        alias="tenant_id",
        min_length=1,
        description="Explicit tenant scope for multi-tenant callers.",
    ),
    fallback_tenant_id: str = Depends(get_current_user_tenant),
    current_user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> str:
    if selected_tenant_id is None:
        return fallback_tenant_id
    await require_tenant_access(db, cast(Any, current_user), selected_tenant_id)
    return selected_tenant_id


@router.get("", response_model=EventLogListResponse)
async def list_events(
    event_type: str | None = Query(None),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    tenant_id: str = Depends(get_selected_event_tenant),
    service: EventLogService = Depends(get_event_service),
) -> EventLogListResponse:
    items, total = await service.list_events(
        tenant_id=tenant_id,
        event_type=event_type,
        date_from=date_from,
        date_to=date_to,
        page=page,
        page_size=page_size,
    )
    return EventLogListResponse(
        items=[
            EventLogResponse(
                id=i.id,
                tenant_id=i.tenant_id,
                event_type=i.event_type,
                message=i.message,
                source=i.source,
                metadata=i.metadata,
                created_at=i.created_at,
            )
            for i in items
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/types", response_model=list[str])
async def list_event_types(
    tenant_id: str = Depends(get_selected_event_tenant),
    service: EventLogService = Depends(get_event_service),
) -> list[str]:
    return await service.get_event_types(tenant_id)
