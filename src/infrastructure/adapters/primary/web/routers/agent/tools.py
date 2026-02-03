"""Tool-related endpoints.

Endpoints for listing tools and tool compositions.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User

from .schemas import (
    ToolCompositionResponse,
    ToolCompositionsListResponse,
    ToolInfo,
    ToolsListResponse,
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/tools", response_model=ToolsListResponse)
async def list_tools(
    current_user: User = Depends(get_current_user),
) -> ToolsListResponse:
    """List available agent tools."""
    tools = [
        ToolInfo(
            name="memory_search",
            description="Search through stored memories and knowledge in the graph.",
        ),
        ToolInfo(
            name="entity_lookup",
            description="Look up specific entities and their relationships.",
        ),
        ToolInfo(
            name="episode_retrieval",
            description="Retrieve historical episodes and conversations.",
        ),
        ToolInfo(
            name="memory_create",
            description="Create a new memory entry in the knowledge graph.",
        ),
        ToolInfo(
            name="graph_query",
            description="Execute a custom Cypher query on the knowledge graph.",
        ),
        ToolInfo(
            name="summary",
            description="Generate a concise summary of provided information.",
        ),
    ]
    return ToolsListResponse(tools=tools)


@router.get("/tools/compositions", response_model=ToolCompositionsListResponse)
async def list_tool_compositions(
    tools: Optional[str] = Query(
        None, description="Comma-separated list of tool names to filter by"
    ),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of compositions"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
) -> ToolCompositionsListResponse:
    """List tool compositions."""
    try:
        from src.infrastructure.adapters.secondary.persistence.sql_tool_composition_repository import (
            SqlToolCompositionRepository,
        )

        composition_repo = SqlToolCompositionRepository(db)

        if tools:
            tool_names = [t.strip() for t in tools.split(",") if t.strip()]
            compositions = await composition_repo.list_by_tools(tool_names)
        else:
            compositions = await composition_repo.list_all(limit)

        return ToolCompositionsListResponse(
            compositions=[
                ToolCompositionResponse(
                    id=c.id,
                    name=c.name,
                    description=c.description,
                    tools=list(c.tools),
                    execution_template=dict(c.execution_template),
                    success_rate=c.success_rate,
                    success_count=c.success_count,
                    failure_count=c.failure_count,
                    usage_count=c.usage_count,
                    created_at=c.created_at.isoformat(),
                    updated_at=c.updated_at.isoformat(),
                )
                for c in compositions
            ],
            total=len(compositions),
        )

    except Exception as e:
        logger.error(f"Error listing tool compositions: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list tool compositions: {str(e)}")


@router.get("/tools/compositions/{composition_id}", response_model=ToolCompositionResponse)
async def get_tool_composition(
    composition_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
) -> ToolCompositionResponse:
    """Get a specific tool composition."""
    try:
        from src.infrastructure.adapters.secondary.persistence.sql_tool_composition_repository import (
            SqlToolCompositionRepository,
        )

        composition_repo = SqlToolCompositionRepository(db)
        composition = await composition_repo.find_by_id(composition_id)

        if not composition:
            raise HTTPException(status_code=404, detail="Tool composition not found")

        return ToolCompositionResponse(
            id=composition.id,
            name=composition.name,
            description=composition.description,
            tools=list(composition.tools),
            execution_template=dict(composition.execution_template),
            success_rate=composition.success_rate,
            success_count=composition.success_count,
            failure_count=composition.failure_count,
            usage_count=composition.usage_count,
            created_at=composition.created_at.isoformat(),
            updated_at=composition.updated_at.isoformat(),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting tool composition: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get tool composition: {str(e)}")
