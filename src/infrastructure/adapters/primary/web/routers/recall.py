"""Recall API routes for short-term memory retrieval."""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

# Use Cases & DI Container
from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user,
    get_graphiti_client,
)
from src.infrastructure.adapters.primary.web.routers.graph import _graph_project_scope
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.i18n import gettext as _

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/recall", tags=["recall"])


# --- Schemas ---


class ShortTermRecallQuery(BaseModel):
    window_minutes: int = 1440  # Default 24 hours
    limit: int = 100
    tenant_id: str | None = None
    project_id: str | None = None


class MemoryItem(BaseModel):
    uuid: str
    name: str
    content: str
    created_at: str | None = None
    metadata: dict[str, Any] | None = None


class ShortTermRecallResponse(BaseModel):
    results: list[Any]
    total: int
    window_minutes: int


# --- Endpoints ---


@router.post("/short", response_model=ShortTermRecallResponse)
async def short_term_recall(
    payload: ShortTermRecallQuery,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    graphiti_client: Any = Depends(get_graphiti_client),
) -> ShortTermRecallResponse:
    """
    Recall short-term episodic memories within the given time window.
    """
    try:
        logger.info(
            f"Short-term recall by user {current_user.id}: "
            f"window={payload.window_minutes}m project={payload.project_id}"
        )

        # Calculate time window
        since_date = datetime.now(UTC) - timedelta(minutes=payload.window_minutes)

        # Build query
        conditions = ["e.created_at >= datetime($since_date)"]
        params: dict[str, Any] = {
            "since_date": since_date.isoformat(),
            "limit": payload.limit,
        }

        is_superuser, allowed_project_ids = await _graph_project_scope(
            payload.project_id, current_user, db
        )
        if not is_superuser and not allowed_project_ids:
            return ShortTermRecallResponse(
                results=[],
                total=0,
                window_minutes=payload.window_minutes,
            )

        if payload.project_id:
            conditions.append("e.project_id = $project_id")
            params["project_id"] = payload.project_id
        elif not is_superuser:
            conditions.append("e.project_id IN $project_ids")
            params["project_ids"] = allowed_project_ids

        if payload.tenant_id:
            conditions.append("e.tenant_id = $tenant_id")
            params["tenant_id"] = payload.tenant_id

        where_clause = "WHERE " + " AND ".join(conditions)

        query = f"""
        MATCH (e:Episodic)
        {where_clause}
        RETURN properties(e) as props
        ORDER BY e.created_at DESC
        LIMIT $limit
        """

        result = await graphiti_client.driver.execute_query(query, **params)

        items = []
        for r in result.records:
            props = r["props"]
            # Convert Neo4j DateTime to ISO string if needed
            created_at = props.get("created_at")
            if created_at is not None and hasattr(created_at, "isoformat"):
                created_at = created_at.isoformat()
            elif created_at is not None and not isinstance(created_at, str):
                created_at = str(created_at)
            items.append(
                MemoryItem(
                    uuid=props.get("uuid", ""),
                    name=props.get("name", ""),
                    content=props.get("content", ""),
                    created_at=created_at,
                    metadata={
                        "tenant_id": props.get("tenant_id"),
                        "project_id": props.get("project_id"),
                        "user_id": props.get("user_id"),
                    },
                ).model_dump()
            )

        return ShortTermRecallResponse(
            results=items, total=len(items), window_minutes=payload.window_minutes
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Short-term recall failed")
        raise HTTPException(status_code=500, detail=_("Short-term recall failed")) from e
