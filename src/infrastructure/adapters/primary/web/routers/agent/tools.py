"""Tool-related endpoints.

Endpoints for listing tools and tool compositions.
"""

import logging
from collections import Counter

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.tool_policy_debug_service import ToolPolicyDebugService
from src.domain.model.agent.sandbox_scope import SandboxScope
from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User

from .schemas import (
    CapabilityDomainSummary,
    CapabilitySummaryResponse,
    PluginRuntimeCapabilitySummary,
    PolicyLayerSummary,
    ToolCompositionResponse,
    ToolCompositionsListResponse,
    ToolInfo,
    ToolPolicyDebugRequest,
    ToolPolicyDebugResponse,
    ToolPolicyReportItem,
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
        plugin_records, _ = runtime_manager.list_plugins(tenant_id=current_user.tenant_id)  # type: ignore[attr-defined]
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
    request: Request,
    tools: str | None = Query(None, description="Comma-separated list of tool names to filter by"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of compositions"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
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
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
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


@router.post("/debug/tool-policy", response_model=ToolPolicyDebugResponse)
async def debug_tool_policy(
    body: ToolPolicyDebugRequest,
    current_user: User = Depends(get_current_user),
) -> ToolPolicyDebugResponse:
    """Evaluate tool access policies for a given agent context.

    Answers "why was this tool denied?" by building the multi-layer
    policy chain and reporting per-tool allow/deny with reasons.
    """
    try:
        scope = SandboxScope(body.sandbox_scope)
    except ValueError as exc:
        valid = [s.value for s in SandboxScope]
        raise HTTPException(
            status_code=422,
            detail=f"Invalid sandbox_scope '{body.sandbox_scope}'. Valid: {valid}",
        ) from exc

    sandbox_allowed = frozenset(body.sandbox_allowed_tools) if body.sandbox_allowed_tools else None
    sandbox_denied = frozenset(body.sandbox_denied_tools) if body.sandbox_denied_tools else None
    agent_allowed = frozenset(body.agent_allowed_tools) if body.agent_allowed_tools else None
    agent_denied = frozenset(body.agent_denied_tools) if body.agent_denied_tools else None

    result = ToolPolicyDebugService.evaluate(
        tool_names=body.tool_names,
        depth=body.depth,
        max_depth=body.max_depth,
        sandbox_scope=scope,
        sandbox_allowed_tools=sandbox_allowed,
        sandbox_denied_tools=sandbox_denied,
        agent_allowed_tools=agent_allowed,
        agent_denied_tools=agent_denied,
    )

    policies = [
        PolicyLayerSummary(
            source=p.source,
            precedence=p.precedence,
            allowed=sorted(p.allowed) if p.allowed is not None else None,
            denied=sorted(p.denied),
        )
        for p in result.policies
    ]

    tool_reports = [
        ToolPolicyReportItem(
            tool_name=r.tool_name,
            allowed=r.allowed,
            denial_reason=r.denial_reason,
        )
        for r in result.tool_reports
    ]

    return ToolPolicyDebugResponse(
        role=result.role.value,
        sandbox_scope=result.sandbox_scope.value,
        can_spawn=result.role_capabilities.can_spawn,
        denied_by_role=sorted(result.role_capabilities.denied_tools),
        policies=policies,
        tool_reports=tool_reports,
        total_tools=result.total_tools,
        allowed_count=result.allowed_count,
        denied_count=result.denied_count,
    )
