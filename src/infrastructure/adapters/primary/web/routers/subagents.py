"""
SubAgent Management API endpoints.

Provides REST API for managing subagents in the Agent SubAgent System (L3 layer).
SubAgents are specialized agents that handle specific types of tasks with
isolated tool access and custom system prompts.
"""

import logging
from datetime import UTC
from typing import Any, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent.subagent import AgentModel, AgentTrigger, SubAgent
from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user,
    get_current_user_tenant,
)
from src.infrastructure.adapters.primary.web.routers.agent.access import require_tenant_access
from src.infrastructure.adapters.primary.web.subagent_http_application_authority_v2 import (
    subagent_http_application_authority_v2,
)
from src.infrastructure.adapters.primary.web.subagent_selection_http_application_authority_v2 import (
    subagent_selection_http_application_authority_v2,
)
from src.infrastructure.adapters.primary.web.subagent_template_http_application_authority_v2 import (
    subagent_template_http_application_authority_v2,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.i18n import gettext as _
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.subagent_management_services import (
    SubAgentAccessDeniedV2,
    SubAgentAlreadyExistsV2,
    SubAgentNotFoundV2,
)
from src.infrastructure.plugins.v2.subagent_template_management_services import (
    SubAgentTemplateAlreadyExistsV2,
    SubAgentTemplateBuiltinMutationV2,
    SubAgentTemplateNotFoundV2,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/subagents", tags=["SubAgents"])


async def _get_selected_subagent_tenant_id(
    selected_tenant_id: str | None = Query(
        None,
        alias="tenant_id",
        min_length=1,
        description="Explicit tenant scope for multi-tenant callers",
    ),
    fallback_tenant_id: str = Depends(get_current_user_tenant),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> str:
    """Resolve the tenant for a SubAgent request and validate explicit tenant scope."""
    if selected_tenant_id is None:
        return fallback_tenant_id

    await require_tenant_access(db, cast(Any, current_user), selected_tenant_id)
    return selected_tenant_id


# === Pydantic Models ===


class SpawnPolicySchema(BaseModel):
    """Schema for spawn policy configuration."""

    max_depth: int = Field(2, ge=0, le=32, description="Maximum nesting depth")
    max_active_runs: int = Field(16, ge=1, le=32, description="Global cap on concurrent runs")
    max_children_per_requester: int = Field(
        8, ge=1, le=16, description="Per-parent cap on active children"
    )
    allowed_subagents: list[str] | None = Field(
        None, description="SubAgent IDs that can spawn this one (None = all)"
    )


class ToolPolicySchema(BaseModel):
    """Schema for tool policy configuration."""

    allow: list[str] = Field(default_factory=list, description="Tools to explicitly allow")
    deny: list[str] = Field(default_factory=list, description="Tools to explicitly deny")
    precedence: str = Field(
        "deny_first", pattern="^(allow_first|deny_first)$", description="Conflict resolution mode"
    )


class AgentIdentitySchema(BaseModel):
    """Schema for agent identity configuration."""

    name: str | None = Field(None, description="Identity name")
    description: str | None = Field(None, description="Identity description")
    metadata: dict[str, str] | None = Field(None, description="Identity metadata")


class SubAgentCreate(BaseModel):
    """Schema for creating a new subagent."""

    name: str = Field(..., min_length=1, max_length=100, description="Unique name identifier")
    display_name: str = Field(..., min_length=1, max_length=200, description="Display name")
    system_prompt: str = Field(..., min_length=1, description="System prompt")
    trigger_description: str = Field(..., min_length=1, description="Trigger description")
    trigger_examples: list[str] = Field(default_factory=list, description="Trigger examples")
    trigger_keywords: list[str] = Field(default_factory=list, description="Trigger keywords")
    model: str = Field("inherit", description="LLM model: inherit, qwen-max, gpt-4, etc.")
    color: str = Field("blue", description="UI display color")
    allowed_tools: list[str] = Field(default_factory=lambda: ["*"], description="Allowed tools")
    allowed_skills: list[str] = Field(default_factory=list, description="Allowed skill IDs")
    allowed_mcp_servers: list[str] = Field(default_factory=list, description="Allowed MCP servers")
    max_tokens: int = Field(4096, ge=1, le=32768, description="Max tokens")
    temperature: float = Field(0.7, ge=0.0, le=2.0, description="Temperature")
    max_iterations: int = Field(10, ge=1, le=50, description="Max ReAct iterations")
    project_id: str | None = Field(None, description="Optional project ID")
    metadata: dict[str, Any] | None = Field(None, description="Optional metadata")
    # Multi-agent policy fields
    spawn_policy: SpawnPolicySchema | None = Field(None, description="Spawn policy configuration")
    tool_policy: ToolPolicySchema | None = Field(None, description="Tool policy configuration")
    identity: AgentIdentitySchema | None = Field(None, description="Agent identity configuration")


class SubAgentUpdate(BaseModel):
    """Schema for updating a subagent."""

    name: str | None = Field(None, min_length=1, max_length=100)
    display_name: str | None = Field(None, min_length=1, max_length=200)
    system_prompt: str | None = Field(None, min_length=1)
    trigger_description: str | None = Field(None)
    trigger_examples: list[str] | None = Field(None)
    trigger_keywords: list[str] | None = Field(None)
    model: str | None = Field(None)
    color: str | None = Field(None)
    allowed_tools: list[str] | None = Field(None)
    allowed_skills: list[str] | None = Field(None)
    allowed_mcp_servers: list[str] | None = Field(None)
    max_tokens: int | None = Field(None, ge=1, le=32768)
    temperature: float | None = Field(None, ge=0.0, le=2.0)
    max_iterations: int | None = Field(None, ge=1, le=50)
    metadata: dict[str, Any] | None = Field(None)
    # Multi-agent policy fields
    spawn_policy: SpawnPolicySchema | None = Field(None, description="Spawn policy configuration")
    tool_policy: ToolPolicySchema | None = Field(None, description="Tool policy configuration")
    identity: AgentIdentitySchema | None = Field(None, description="Agent identity configuration")


class SubAgentResponse(BaseModel):
    """Schema for subagent response."""

    id: str
    tenant_id: str
    project_id: str | None
    name: str
    display_name: str
    system_prompt: str
    trigger: dict[str, Any]
    model: str
    color: str
    allowed_tools: list[str]
    allowed_skills: list[str]
    allowed_mcp_servers: list[str]
    max_tokens: int
    temperature: float
    max_iterations: int
    enabled: bool
    total_invocations: int
    avg_execution_time_ms: float
    success_rate: float
    created_at: str
    updated_at: str
    metadata: dict[str, Any] | None
    source: str = "database"
    file_path: str | None = None
    # Multi-agent policy fields
    spawn_policy: SpawnPolicySchema | None = None
    tool_policy: ToolPolicySchema | None = None
    identity: AgentIdentitySchema | None = None


class SubAgentListResponse(BaseModel):
    """Schema for subagent list response."""

    subagents: list[SubAgentResponse]
    total: int
    enabled_total: int = 0
    average_success_rate: float = 0.0
    total_invocations: int = 0


class SubAgentMatchRequest(BaseModel):
    """Schema for subagent matching request."""

    task_description: str = Field(..., min_length=1, max_length=8000, description="Task to match")


class SubAgentMatchResponse(BaseModel):
    """Schema for subagent match response."""

    subagent: SubAgentResponse | None
    confidence: float


class TemplateCreate(BaseModel):
    """Schema for creating a template."""

    name: str = Field(..., min_length=1, max_length=200)
    version: str = Field("1.0.0", max_length=20)
    display_name: str | None = Field(None, max_length=200)
    description: str | None = None
    category: str = Field("general", max_length=100)
    tags: list[str] = Field(default_factory=list)
    system_prompt: str = Field(..., min_length=1)
    trigger_description: str | None = None
    trigger_keywords: list[str] = Field(default_factory=list)
    trigger_examples: list[str] = Field(default_factory=list)
    model: str = Field("inherit")
    max_tokens: int = Field(4096, ge=1, le=32768)
    temperature: float = Field(0.7, ge=0.0, le=2.0)
    max_iterations: int = Field(10, ge=1, le=50)
    allowed_tools: list[str] = Field(default_factory=lambda: ["*"])
    author: str | None = None
    is_published: bool = True
    metadata: dict[str, Any] | None = None


class TemplateUpdate(BaseModel):
    """Schema for updating a template."""

    name: str | None = Field(None, min_length=1, max_length=200)
    display_name: str | None = Field(None, max_length=200)
    description: str | None = None
    category: str | None = Field(None, max_length=100)
    tags: list[str] | None = None
    system_prompt: str | None = None
    trigger_description: str | None = None
    trigger_keywords: list[str] | None = None
    trigger_examples: list[str] | None = None
    model: str | None = None
    max_tokens: int | None = Field(None, ge=1, le=32768)
    temperature: float | None = Field(None, ge=0.0, le=2.0)
    max_iterations: int | None = Field(None, ge=1, le=50)
    allowed_tools: list[str] | None = None
    author: str | None = None
    is_published: bool | None = None
    metadata: dict[str, Any] | None = None


class TemplateResponse(BaseModel):
    """Schema for template response."""

    id: str
    tenant_id: str
    name: str
    version: str
    display_name: str | None
    description: str | None
    category: str
    tags: list[str]
    system_prompt: str
    trigger_description: str | None
    trigger_keywords: list[str]
    trigger_examples: list[str]
    model: str
    max_tokens: int
    temperature: float
    max_iterations: int
    allowed_tools: list[str]
    author: str | None
    is_builtin: bool
    is_published: bool
    install_count: int
    rating: float
    metadata: dict[str, Any] | None
    created_at: str | None
    updated_at: str | None


class TemplateListResponse(BaseModel):
    """Schema for template list response."""

    templates: list[TemplateResponse]
    total: int


class SubAgentStatsResponse(BaseModel):
    """Schema for subagent statistics response."""

    subagent_id: str
    name: str
    display_name: str
    total_invocations: int
    avg_execution_time_ms: float
    success_rate: float
    enabled: bool


# === Helper Functions ===


def subagent_to_response(subagent: SubAgent) -> SubAgentResponse:
    """Convert domain SubAgent to response model."""
    return SubAgentResponse(
        id=subagent.id,
        tenant_id=subagent.tenant_id,
        project_id=subagent.project_id,
        name=subagent.name,
        display_name=subagent.display_name,
        system_prompt=subagent.system_prompt,
        trigger=subagent.trigger.to_dict(),
        model=subagent.model.value,
        color=subagent.color,
        allowed_tools=list(subagent.allowed_tools),
        allowed_skills=list(subagent.allowed_skills),
        allowed_mcp_servers=list(subagent.allowed_mcp_servers),
        max_tokens=subagent.max_tokens,
        temperature=subagent.temperature,
        max_iterations=subagent.max_iterations,
        enabled=subagent.enabled,
        total_invocations=subagent.total_invocations,
        avg_execution_time_ms=subagent.avg_execution_time_ms,
        success_rate=subagent.success_rate,
        created_at=subagent.created_at.isoformat(),
        updated_at=subagent.updated_at.isoformat(),
        metadata=subagent.metadata,
        source=subagent.source.value,
        file_path=subagent.file_path,
    )


SubAgentSortField = Literal["name", "invocations", "success_rate", "recent"]


def _filter_subagents_by_search(
    subagents: list[SubAgent],
    search: str | None,
) -> list[SubAgent]:
    query = (search or "").strip().lower()
    if not query:
        return subagents

    def matches(subagent: SubAgent) -> bool:
        searchable = [
            subagent.name,
            subagent.display_name,
            subagent.trigger.description,
            subagent.model.value,
            *(subagent.trigger.keywords or []),
        ]
        return any(query in value.lower() for value in searchable if value)

    return [subagent for subagent in subagents if matches(subagent)]


def _sort_subagents(
    subagents: list[SubAgent],
    sort: SubAgentSortField,
) -> list[SubAgent]:
    if sort == "invocations":
        return sorted(subagents, key=lambda subagent: subagent.total_invocations, reverse=True)
    if sort == "success_rate":
        return sorted(subagents, key=lambda subagent: subagent.success_rate, reverse=True)
    if sort == "recent":
        return sorted(subagents, key=lambda subagent: subagent.updated_at, reverse=True)
    return sorted(subagents, key=lambda subagent: subagent.display_name.lower())


def _subagent_list_metrics(subagents: list[SubAgent]) -> dict[str, int | float]:
    enabled_subagents = [subagent for subagent in subagents if subagent.enabled]
    rated_subagents = [subagent for subagent in enabled_subagents if subagent.total_invocations > 0]
    average_success_rate = (
        sum(subagent.success_rate for subagent in rated_subagents) / len(rated_subagents)
        if rated_subagents
        else 0.0
    )
    return {
        "enabled_total": len(enabled_subagents),
        "average_success_rate": average_success_rate,
        "total_invocations": sum(subagent.total_invocations for subagent in subagents),
    }


def _prepare_subagent_page(
    subagents: list[SubAgent],
    *,
    enabled_only: bool,
    search: str | None,
    sort: SubAgentSortField,
    limit: int,
    offset: int,
) -> tuple[list[SubAgent], int, dict[str, int | float]]:
    filtered = (
        [subagent for subagent in subagents if subagent.enabled] if enabled_only else subagents
    )
    filtered = _filter_subagents_by_search(filtered, search)
    filtered = _sort_subagents(filtered, sort)
    total = len(filtered)
    metrics = _subagent_list_metrics(filtered)
    return filtered[offset : offset + limit], total, metrics


# === API Endpoints ===


@router.post("/", response_model=SubAgentResponse, status_code=status.HTTP_201_CREATED)
async def create_subagent(
    request: Request,
    data: SubAgentCreate,
    tenant_id: str = Depends(_get_selected_subagent_tenant_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SubAgentResponse:
    """
    Create a new subagent.

    SubAgents are created at the tenant level and can optionally be scoped to a project.
    """
    try:
        async with subagent_http_application_authority_v2(
            request=request,
            tenant_id=tenant_id,
            current_user=current_user,
            db=db,
        ) as authority:
            subagent = SubAgent.create(
                tenant_id=authority.service.tenant_id,
                name=data.name,
                display_name=data.display_name,
                system_prompt=data.system_prompt,
                trigger_description=data.trigger_description,
                trigger_examples=data.trigger_examples,
                trigger_keywords=data.trigger_keywords,
                model=AgentModel(data.model),
                color=data.color,
                allowed_tools=data.allowed_tools,
                allowed_skills=data.allowed_skills,
                allowed_mcp_servers=data.allowed_mcp_servers,
                max_tokens=data.max_tokens,
                temperature=data.temperature,
                max_iterations=data.max_iterations,
                project_id=data.project_id,
                metadata=data.metadata,
            )
            created = await authority.service.create(subagent)
            logger.info("SubAgent created through V2: %s (%s)", created.id, created.name)
            return subagent_to_response(created)
    except SubAgentAlreadyExistsV2 as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_("SubAgent already exists"),
        ) from exc
    except SubAgentAccessDeniedV2 as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_("Access denied"),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_("Invalid subagent request"),
        ) from exc


@router.get("/", response_model=SubAgentListResponse)
async def list_subagents(
    request: Request,
    enabled_only: bool = Query(False, description="Only return enabled subagents"),
    search: str | None = Query(None, description="Search by name, model, or trigger keywords"),
    sort: SubAgentSortField = Query("name", description="Sort field"),
    source: str | None = Query(
        None, description="Filter by source: 'filesystem', 'database', or None for all"
    ),
    include_filesystem: bool = Query(True, description="Include filesystem SubAgents in results"),
    limit: int = Query(100, ge=1, le=500, description="Maximum results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    tenant_id: str = Depends(_get_selected_subagent_tenant_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SubAgentListResponse:
    """
    List all subagents for the current tenant.

    By default includes both database and filesystem SubAgents (merged, DB wins by name).
    Use `source` filter to show only one source, or `include_filesystem=false` to skip FS.
    """
    from pathlib import Path

    async with subagent_http_application_authority_v2(
        request=request,
        tenant_id=tenant_id,
        current_user=current_user,
        db=db,
    ) as authority:
        if source == "filesystem":
            from src.infrastructure.agent.subagent.filesystem_loader import (
                FileSystemSubAgentLoader,
            )

            loader = FileSystemSubAgentLoader(
                base_path=Path.cwd(),
                tenant_id=authority.service.tenant_id,
            )
            result = await loader.load_all()
            all_subagents = [loaded.subagent for loaded in result.subagents]
            page, total, metrics = _prepare_subagent_page(
                all_subagents,
                enabled_only=enabled_only,
                search=search,
                sort=sort,
                limit=limit,
                offset=offset,
            )
        elif source == "database" or not include_filesystem:
            all_subagents = await authority.service.list_accessible(enabled_only=enabled_only)
            page, total, metrics = _prepare_subagent_page(
                all_subagents,
                enabled_only=False,
                search=search,
                sort=sort,
                limit=limit,
                offset=offset,
            )
        else:
            from src.application.services.subagent_service import SubAgentService
            from src.infrastructure.agent.subagent.filesystem_loader import (
                FileSystemSubAgentLoader,
            )

            loader = FileSystemSubAgentLoader(
                base_path=Path.cwd(),
                tenant_id=authority.service.tenant_id,
            )
            merge_service = SubAgentService(filesystem_loader=loader)
            db_subagents = await authority.service.list_accessible(enabled_only=False)
            fs_subagents = await merge_service.load_filesystem_subagents()
            all_subagents = merge_service.merge(db_subagents, fs_subagents)
            page, total, metrics = _prepare_subagent_page(
                all_subagents,
                enabled_only=enabled_only,
                search=search,
                sort=sort,
                limit=limit,
                offset=offset,
            )

    return SubAgentListResponse(
        subagents=[subagent_to_response(s) for s in page],
        total=total,
        enabled_total=int(metrics["enabled_total"]),
        average_success_rate=float(metrics["average_success_rate"]),
        total_invocations=int(metrics["total_invocations"]),
    )


class FilesystemSubAgentResponse(BaseModel):
    """Schema for filesystem subagent summary."""

    name: str
    display_name: str
    description: str
    model: str
    tools: list[str]
    file_path: str
    source_type: str
    enabled: bool = True


class FilesystemSubAgentListResponse(BaseModel):
    """Schema for filesystem subagent list response."""

    subagents: list[FilesystemSubAgentResponse]
    total: int
    scanned_dirs: list[str]
    errors: list[str]


@router.get("/filesystem", response_model=FilesystemSubAgentListResponse)
async def list_filesystem_subagents(
    request: Request,
    tenant_id: str = Depends(_get_selected_subagent_tenant_id),
) -> FilesystemSubAgentListResponse:
    """
    List SubAgents available from the filesystem (.memstack/agents/*.md).

    These are pre-defined agent definitions that can be imported to the database
    for customization.
    """
    from pathlib import Path

    from src.infrastructure.agent.subagent.filesystem_loader import FileSystemSubAgentLoader

    loader = FileSystemSubAgentLoader(
        base_path=Path.cwd(),
        tenant_id=tenant_id,
    )
    result = await loader.load_all()

    subagents: list[FilesystemSubAgentResponse] = []
    for loaded in result.subagents:
        sa = loaded.subagent
        subagents.append(
            FilesystemSubAgentResponse(
                name=sa.name,
                display_name=sa.display_name,
                description=sa.trigger.description,
                model=sa.model.value,
                tools=list(sa.allowed_tools),
                file_path=sa.file_path or str(loaded.file_info.file_path),
                source_type=loaded.file_info.source_type,
                enabled=sa.enabled,
            )
        )

    return FilesystemSubAgentListResponse(
        subagents=subagents,
        total=len(subagents),
        scanned_dirs=[str(d) for d in getattr(result, "scanned_dirs", [])]
        if getattr(result, "scanned_dirs", None)
        else [],
        errors=result.errors,
    )


@router.post(
    "/filesystem/{name}/import",
    response_model=SubAgentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def import_filesystem_subagent(
    request: Request,
    name: str,
    project_id: str | None = Query(None, description="Optional project to scope to"),
    tenant_id: str = Depends(_get_selected_subagent_tenant_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SubAgentResponse:
    """
    Import a filesystem SubAgent into the database for customization.

    This copies the filesystem definition into the database, allowing the user
    to modify it. The database version will take precedence over the filesystem
    version in future loads.
    """
    from pathlib import Path

    from src.infrastructure.agent.subagent.filesystem_loader import FileSystemSubAgentLoader

    try:
        async with subagent_http_application_authority_v2(
            request=request,
            tenant_id=tenant_id,
            current_user=current_user,
            db=db,
        ) as authority:
            loader = FileSystemSubAgentLoader(
                base_path=Path.cwd(),
                tenant_id=authority.service.tenant_id,
            )
            result = await loader.load_all()
            target = next(
                (loaded for loaded in result.subagents if loaded.subagent.name == name),
                None,
            )
            if target is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=_("Filesystem SubAgent not found"),
                )

            fs_agent = target.subagent
            db_agent = SubAgent.create(
                tenant_id=authority.service.tenant_id,
                name=fs_agent.name,
                display_name=fs_agent.display_name,
                system_prompt=fs_agent.system_prompt,
                trigger_description=fs_agent.trigger.description,
                trigger_keywords=list(fs_agent.trigger.keywords),
                trigger_examples=list(fs_agent.trigger.examples),
                model=fs_agent.model,
                color=fs_agent.color,
                allowed_tools=list(fs_agent.allowed_tools),
                allowed_skills=list(fs_agent.allowed_skills),
                allowed_mcp_servers=list(fs_agent.allowed_mcp_servers),
                max_tokens=fs_agent.max_tokens,
                temperature=fs_agent.temperature,
                max_iterations=fs_agent.max_iterations,
                project_id=project_id,
                metadata={"imported_from": str(target.file_info.file_path)},
                max_retries=fs_agent.max_retries,
                fallback_models=list(fs_agent.fallback_models),
                spawn_policy=fs_agent.spawn_policy,
                tool_policy=fs_agent.tool_policy,
                identity=fs_agent.identity,
            )
            created = await authority.service.create(db_agent)
            logger.info(
                "Imported filesystem SubAgent through V2: %s (%s)",
                created.id,
                created.name,
            )
            return subagent_to_response(created)
    except SubAgentAlreadyExistsV2 as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_("SubAgent already exists"),
        ) from exc
    except SubAgentAccessDeniedV2 as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_("Access denied"),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_("Invalid subagent request"),
        ) from exc


@router.get("/templates/list", response_model=TemplateListResponse)
async def list_subagent_templates(
    request: Request,
    category: str | None = Query(None, description="Filter by category"),
    query: str | None = Query(None, description="Search query"),
    limit: int = Query(50, ge=1, le=100, description="Maximum results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    tenant_id: str = Depends(_get_selected_subagent_tenant_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TemplateListResponse:
    """
    List published subagent templates with optional filtering.
    """
    try:
        async with subagent_template_http_application_authority_v2(
            request=request,
            tenant_id=tenant_id,
            current_user=current_user,
            db=db,
        ) as authority:
            page = await authority.service.list_published(
                category=category,
                query=query,
                limit=limit,
                offset=offset,
            )
            return TemplateListResponse(
                templates=[TemplateResponse(**template) for template in page.templates],
                total=page.total,
            )
    except SubAgentTemplateNotFoundV2 as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_("Template not found"),
        ) from exc


@router.post(
    "/templates/",
    response_model=TemplateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_template(
    request: Request,
    data: TemplateCreate,
    tenant_id: str = Depends(_get_selected_subagent_tenant_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TemplateResponse:
    """
    Create a new subagent template.
    """
    try:
        async with subagent_template_http_application_authority_v2(
            request=request,
            tenant_id=tenant_id,
            current_user=current_user,
            db=db,
        ) as authority:
            created = await authority.service.create(data.model_dump())
            logger.info("Template created through V2: %s (%s)", created["id"], data.name)
            return TemplateResponse(**created)
    except SubAgentTemplateAlreadyExistsV2 as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_("Template already exists"),
        ) from exc


@router.get("/templates/categories")
async def list_template_categories(
    request: Request,
    tenant_id: str = Depends(_get_selected_subagent_tenant_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    List all available template categories.
    """
    async with subagent_template_http_application_authority_v2(
        request=request,
        tenant_id=tenant_id,
        current_user=current_user,
        db=db,
    ) as authority:
        categories = await authority.service.list_categories()
        return {"categories": categories}


@router.get("/templates/{template_id}", response_model=TemplateResponse)
async def get_template(
    request: Request,
    template_id: str,
    tenant_id: str = Depends(_get_selected_subagent_tenant_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TemplateResponse:
    """
    Get a specific template by ID.
    """
    try:
        async with subagent_template_http_application_authority_v2(
            request=request,
            tenant_id=tenant_id,
            current_user=current_user,
            db=db,
        ) as authority:
            template = await authority.service.require_template(template_id)
            return TemplateResponse(**template)
    except SubAgentTemplateNotFoundV2 as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_("Template not found"),
        ) from exc


@router.put("/templates/{template_id}", response_model=TemplateResponse)
async def update_template(
    request: Request,
    template_id: str,
    data: TemplateUpdate,
    tenant_id: str = Depends(_get_selected_subagent_tenant_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TemplateResponse:
    """
    Update an existing template.
    """
    try:
        async with subagent_template_http_application_authority_v2(
            request=request,
            tenant_id=tenant_id,
            current_user=current_user,
            db=db,
        ) as authority:
            updated = await authority.service.update(
                template_id,
                data.model_dump(exclude_unset=True),
            )
            logger.info("Template updated through V2: %s", template_id)
            return TemplateResponse(**updated)
    except SubAgentTemplateNotFoundV2 as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_("Template not found"),
        ) from exc
    except SubAgentTemplateBuiltinMutationV2 as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_("Cannot modify builtin templates"),
        ) from exc


@router.delete("/templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(
    request: Request,
    template_id: str,
    tenant_id: str = Depends(_get_selected_subagent_tenant_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """
    Delete a template.
    """
    try:
        async with subagent_template_http_application_authority_v2(
            request=request,
            tenant_id=tenant_id,
            current_user=current_user,
            db=db,
        ) as authority:
            await authority.service.delete(template_id)
            logger.info("Template deleted through V2: %s", template_id)
    except SubAgentTemplateNotFoundV2 as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_("Template not found"),
        ) from exc
    except SubAgentTemplateBuiltinMutationV2 as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_("Cannot delete builtin templates"),
        ) from exc


@router.post(
    "/templates/{template_id}/install",
    response_model=SubAgentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def install_template(
    request: Request,
    template_id: str,
    tenant_id: str = Depends(_get_selected_subagent_tenant_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SubAgentResponse:
    """
    Create a SubAgent from a template (install).
    """
    try:
        async with subagent_template_http_application_authority_v2(
            request=request,
            tenant_id=tenant_id,
            current_user=current_user,
            db=db,
        ) as authority:
            created = await authority.service.install(template_id)
            logger.info(
                "SubAgent installed from template through V2: %s (%s)",
                created.id,
                created.name,
            )
            return subagent_to_response(created)
    except SubAgentTemplateNotFoundV2 as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_("Template not found"),
        ) from exc
    except SubAgentAlreadyExistsV2 as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_("SubAgent already exists"),
        ) from exc


@router.post(
    "/templates/from-subagent/{subagent_id}",
    response_model=TemplateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def export_subagent_as_template(
    request: Request,
    subagent_id: str,
    tenant_id: str = Depends(_get_selected_subagent_tenant_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TemplateResponse:
    """
    Export an existing SubAgent as a reusable template.
    """
    try:
        async with subagent_template_http_application_authority_v2(
            request=request,
            tenant_id=tenant_id,
            current_user=current_user,
            db=db,
        ) as authority:
            created = await authority.service.export_subagent(subagent_id)
            logger.info(
                "SubAgent exported as template through V2: %s from %s",
                created["id"],
                subagent_id,
            )
            return TemplateResponse(**created)
    except SubAgentNotFoundV2 as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_("SubAgent not found"),
        ) from exc
    except SubAgentAccessDeniedV2 as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_("Access denied"),
        ) from exc


@router.get("/{subagent_id}", response_model=SubAgentResponse)
async def get_subagent(
    request: Request,
    subagent_id: str,
    tenant_id: str = Depends(_get_selected_subagent_tenant_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SubAgentResponse:
    """
    Get a specific subagent by ID.
    """
    try:
        async with subagent_http_application_authority_v2(
            request=request,
            tenant_id=tenant_id,
            current_user=current_user,
            db=db,
        ) as authority:
            access = await authority.service.require_access(subagent_id)
            return subagent_to_response(access.subagent)
    except SubAgentNotFoundV2 as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_("SubAgent not found"),
        ) from exc
    except SubAgentAccessDeniedV2 as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_("Access denied"),
        ) from exc


@router.put("/{subagent_id}", response_model=SubAgentResponse)
async def update_subagent(
    request: Request,
    subagent_id: str,
    data: SubAgentUpdate,
    tenant_id: str = Depends(_get_selected_subagent_tenant_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SubAgentResponse:
    """
    Update an existing subagent.
    """
    from datetime import datetime

    try:
        async with subagent_http_application_authority_v2(
            request=request,
            tenant_id=tenant_id,
            current_user=current_user,
            db=db,
        ) as authority:
            access = await authority.service.require_access(subagent_id)
            subagent = access.subagent
            trigger = AgentTrigger(
                description=data.trigger_description
                if data.trigger_description
                else subagent.trigger.description,
                examples=data.trigger_examples
                if data.trigger_examples is not None
                else subagent.trigger.examples,
                keywords=data.trigger_keywords
                if data.trigger_keywords is not None
                else subagent.trigger.keywords,
            )
            updated_subagent = SubAgent(
                id=subagent.id,
                tenant_id=subagent.tenant_id,
                project_id=subagent.project_id,
                name=data.name if data.name else subagent.name,
                display_name=data.display_name if data.display_name else subagent.display_name,
                system_prompt=data.system_prompt if data.system_prompt else subagent.system_prompt,
                trigger=trigger,
                model=AgentModel(data.model) if data.model else subagent.model,
                color=data.color if data.color else subagent.color,
                allowed_tools=data.allowed_tools
                if data.allowed_tools is not None
                else subagent.allowed_tools,
                allowed_skills=data.allowed_skills
                if data.allowed_skills is not None
                else subagent.allowed_skills,
                allowed_mcp_servers=data.allowed_mcp_servers
                if data.allowed_mcp_servers is not None
                else subagent.allowed_mcp_servers,
                max_tokens=data.max_tokens if data.max_tokens else subagent.max_tokens,
                temperature=data.temperature
                if data.temperature is not None
                else subagent.temperature,
                max_iterations=data.max_iterations
                if data.max_iterations
                else subagent.max_iterations,
                enabled=subagent.enabled,
                total_invocations=subagent.total_invocations,
                avg_execution_time_ms=subagent.avg_execution_time_ms,
                success_rate=subagent.success_rate,
                created_at=subagent.created_at,
                updated_at=datetime.now(UTC),
                metadata=data.metadata if data.metadata is not None else subagent.metadata,
                source=subagent.source,
                file_path=subagent.file_path,
                max_retries=subagent.max_retries,
                fallback_models=list(subagent.fallback_models),
                spawn_policy=subagent.spawn_policy,
                tool_policy=subagent.tool_policy,
                identity=subagent.identity,
            )
            result = await authority.service.update(access, updated_subagent)
            logger.info("SubAgent updated through V2: %s", subagent_id)
            return subagent_to_response(result)
    except SubAgentNotFoundV2 as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_("SubAgent not found"),
        ) from exc
    except SubAgentAlreadyExistsV2 as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_("SubAgent already exists"),
        ) from exc
    except SubAgentAccessDeniedV2 as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_("Access denied"),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_("Invalid subagent request"),
        ) from exc


@router.delete("/{subagent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_subagent(
    request: Request,
    subagent_id: str,
    tenant_id: str = Depends(_get_selected_subagent_tenant_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """
    Delete a subagent.
    """
    try:
        async with subagent_http_application_authority_v2(
            request=request,
            tenant_id=tenant_id,
            current_user=current_user,
            db=db,
        ) as authority:
            access = await authority.service.require_access(subagent_id)
            await authority.service.delete(access)
            logger.info("SubAgent deleted through V2: %s", subagent_id)
    except SubAgentNotFoundV2 as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_("SubAgent not found"),
        ) from exc
    except SubAgentAccessDeniedV2 as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_("Access denied"),
        ) from exc


@router.patch("/{subagent_id}/enable", response_model=SubAgentResponse)
async def toggle_subagent_enabled(
    request: Request,
    subagent_id: str,
    enabled: bool = Query(..., description="Enable or disable"),
    tenant_id: str = Depends(_get_selected_subagent_tenant_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SubAgentResponse:
    """
    Enable or disable a subagent.
    """
    try:
        async with subagent_http_application_authority_v2(
            request=request,
            tenant_id=tenant_id,
            current_user=current_user,
            db=db,
        ) as authority:
            access = await authority.service.require_access(subagent_id)
            result = await authority.service.set_enabled(access, enabled=enabled)
            logger.info(
                "SubAgent enabled state changed through V2: %s enabled=%s",
                subagent_id,
                enabled,
            )
            return subagent_to_response(result)
    except SubAgentNotFoundV2 as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_("SubAgent not found"),
        ) from exc
    except SubAgentAccessDeniedV2 as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_("Access denied"),
        ) from exc


@router.get("/{subagent_id}/stats", response_model=SubAgentStatsResponse)
async def get_subagent_stats(
    request: Request,
    subagent_id: str,
    tenant_id: str = Depends(_get_selected_subagent_tenant_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SubAgentStatsResponse:
    """
    Get statistics for a subagent.
    """
    try:
        async with subagent_http_application_authority_v2(
            request=request,
            tenant_id=tenant_id,
            current_user=current_user,
            db=db,
        ) as authority:
            access = await authority.service.require_access(subagent_id)
            subagent = access.subagent
            return SubAgentStatsResponse(
                subagent_id=subagent.id,
                name=subagent.name,
                display_name=subagent.display_name,
                total_invocations=subagent.total_invocations,
                avg_execution_time_ms=subagent.avg_execution_time_ms,
                success_rate=subagent.success_rate,
                enabled=subagent.enabled,
            )
    except SubAgentNotFoundV2 as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_("SubAgent not found"),
        ) from exc
    except SubAgentAccessDeniedV2 as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_("Access denied"),
        ) from exc


@router.post("/match", response_model=SubAgentMatchResponse)
async def match_subagent(
    request: Request,
    data: SubAgentMatchRequest,
    tenant_id: str = Depends(_get_selected_subagent_tenant_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SubAgentMatchResponse:
    """Select a SubAgent through the pinned generation's judgment authority."""
    try:
        async with subagent_selection_http_application_authority_v2(
            request=request,
            tenant_id=tenant_id,
            current_user=current_user,
            db=db,
        ) as authority:
            selection = await authority.service.match(data.task_description)
        return SubAgentMatchResponse(
            subagent=(
                subagent_to_response(selection.selected) if selection.selected is not None else None
            ),
            confidence=selection.confidence,
        )
    except RuntimeV2Error as exc:
        logger.warning("Pinned V2 SubAgent selection failed: code=%s", exc.code)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": exc.code,
                "message": _("SubAgent selection authority is unavailable"),
            },
        ) from exc


@router.post("/templates/seed")
async def seed_templates(
    request: Request,
    tenant_id: str = Depends(_get_selected_subagent_tenant_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Seed builtin templates for the current tenant.

    Idempotent: skips templates that already exist.
    """
    async with subagent_template_http_application_authority_v2(
        request=request,
        tenant_id=tenant_id,
        current_user=current_user,
        db=db,
    ) as authority:
        created = await authority.service.seed_builtin()
        return {
            "created": created,
            "message": _("Seeded %(count)s builtin templates") % {"count": created},
        }
