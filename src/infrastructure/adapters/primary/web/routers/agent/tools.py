"""Tool-related endpoints.

Endpoints for listing tools and tool compositions.
"""

import logging
from collections import Counter

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User

from .schemas import (
    CapabilityDomainSummary,
    CapabilitySummaryResponse,
    PluginRuntimeCapabilitySummary,
    ToolCompositionResponse,
    ToolCompositionsListResponse,
    ToolInfo,
    ToolsListResponse,
)

router = APIRouter()
logger = logging.getLogger(__name__)

_CORE_TOOL_DEFINITIONS: tuple[tuple[str, str], ...] = (
    (
        "memory_search",
        "Search through stored memories and knowledge in the graph.",
    ),
    (
        "entity_lookup",
        "Look up specific entities and their relationships.",
    ),
    (
        "episode_retrieval",
        "Retrieve historical episodes and conversations.",
    ),
    (
        "memory_create",
        "Create a new memory entry in the knowledge graph.",
    ),
    (
        "graph_query",
        "Execute a custom Cypher query on the knowledge graph.",
    ),
    (
        "summary",
        "Generate a concise summary of provided information.",
    ),
)


def _build_core_tools() -> list[ToolInfo]:
    return [
        ToolInfo(name=name, description=description) for name, description in _CORE_TOOL_DEFINITIONS
    ]


def _classify_domain(tool_name: str) -> str:
    normalized = tool_name.lower()
    if normalized.startswith("memory_") or "entity" in normalized or "episode" in normalized:
        return "memory"
    if "graph" in normalized:
        return "graph"
    if "search" in normalized:
        return "search"
    if "summary" in normalized:
        return "reasoning"
    return "general"


@router.get("/tools", response_model=ToolsListResponse)
async def list_tools(
    current_user: User = Depends(get_current_user),
) -> ToolsListResponse:
    """List available agent tools."""
    return ToolsListResponse(tools=_build_core_tools())


@router.get("/tools/capabilities", response_model=CapabilitySummaryResponse)
async def get_tool_capabilities(
    current_user: User = Depends(get_current_user),
) -> CapabilitySummaryResponse:
    """Get aggregated capability catalog summary for agent tools and plugin runtime."""
    try:
        from src.infrastructure.agent.plugins.manager import get_plugin_runtime_manager
        from src.infrastructure.agent.plugins.registry import get_plugin_registry

        runtime_manager = get_plugin_runtime_manager()
        await runtime_manager.ensure_loaded()
        plugin_records, _ = runtime_manager.list_plugins(tenant_id=current_user.tenant_id)
        registry = get_plugin_registry()

        core_tools = _build_core_tools()
        domain_counter = Counter(_classify_domain(tool.name) for tool in core_tools)

        hook_handlers = registry.list_hooks()
        plugin_runtime = PluginRuntimeCapabilitySummary(
            plugins_total=len(plugin_records),
            plugins_enabled=sum(1 for plugin in plugin_records if bool(plugin.get("enabled"))),
            tool_factories=len(registry.list_tool_factories()),
            channel_types=len(registry.list_channel_type_metadata()),
            hook_handlers=sum(len(handlers) for handlers in hook_handlers.values()),
            commands=len(registry.list_commands()),
            services=len(registry.list_services()),
            providers=len(registry.list_providers()),
        )
        domain_breakdown = [
            CapabilityDomainSummary(domain=domain, tool_count=count)
            for domain, count in sorted(domain_counter.items())
        ]
        return CapabilitySummaryResponse(
            total_tools=len(core_tools),
            core_tools=len(core_tools),
            domain_breakdown=domain_breakdown,
            plugin_runtime=plugin_runtime,
        )
    except Exception as e:
        logger.error(f"Error getting tool capabilities: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to get tool capabilities: {e!s}"
        ) from e


@router.get("/tools/compositions", response_model=ToolCompositionsListResponse)
async def list_tool_compositions(
    tools: str | None = Query(None, description="Comma-separated list of tool names to filter by"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of compositions"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    request: Request | None = None,
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
        raise HTTPException(
            status_code=500, detail=f"Failed to list tool compositions: {e!s}"
        ) from e


@router.get("/tools/compositions/{composition_id}", response_model=ToolCompositionResponse)
async def get_tool_composition(
    composition_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    request: Request | None = None,
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
        raise HTTPException(status_code=500, detail=f"Failed to get tool composition: {e!s}") from e
