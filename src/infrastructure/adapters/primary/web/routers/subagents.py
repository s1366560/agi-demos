"""
SubAgent Management API endpoints.

Provides REST API for managing subagents in the Agent SubAgent System (L3 layer).
SubAgents are specialized agents that handle specific types of tasks with
isolated tool access and custom system prompts.
"""

import logging
from datetime import UTC
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.configuration.di_container import DIContainer
from src.domain.model.agent.subagent import AgentModel, AgentTrigger, SubAgent
from src.infrastructure.adapters.primary.web.dependencies import get_current_user_tenant
from src.infrastructure.adapters.secondary.persistence.database import get_db


def get_container_with_db(request: Request, db: AsyncSession) -> DIContainer:
    """
    Get DI container with database session for the current request.
    """
    app_container = request.app.state.container
    return DIContainer(
        db=db,
        graph_service=app_container.graph_service,
        redis_client=app_container._redis_client,
    )


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/subagents", tags=["SubAgents"])


# === Pydantic Models ===


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


class SubAgentListResponse(BaseModel):
    """Schema for subagent list response."""

    subagents: list[SubAgentResponse]
    total: int


class SubAgentMatchRequest(BaseModel):
    """Schema for subagent matching request."""

    task_description: str = Field(..., min_length=1, description="Task to match")


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


# === API Endpoints ===


@router.post("/", response_model=SubAgentResponse, status_code=status.HTTP_201_CREATED)
async def create_subagent(
    request: Request,
    data: SubAgentCreate,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> subagent_to_response:
    """
    Create a new subagent.

    SubAgents are created at the tenant level and can optionally be scoped to a project.
    """
    try:
        container = get_container_with_db(request, db)

        # Check if name already exists
        repo = container.subagent_repository()
        existing = await repo.get_by_name(tenant_id, data.name)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"SubAgent with name '{data.name}' already exists",
            )

        # Create subagent
        subagent = SubAgent.create(
            tenant_id=tenant_id,
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

        created = await repo.create(subagent)
        await db.commit()

        logger.info(f"SubAgent created: {created.id} ({created.name})")
        return subagent_to_response(created)

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e


@router.get("/", response_model=SubAgentListResponse)
async def list_subagents(
    request: Request,
    enabled_only: bool = Query(False, description="Only return enabled subagents"),
    source: str | None = Query(
        None, description="Filter by source: 'filesystem', 'database', or None for all"
    ),
    include_filesystem: bool = Query(True, description="Include filesystem SubAgents in results"),
    limit: int = Query(100, ge=1, le=500, description="Maximum results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> SubAgentListResponse:
    """
    List all subagents for the current tenant.

    By default includes both database and filesystem SubAgents (merged, DB wins by name).
    Use `source` filter to show only one source, or `include_filesystem=false` to skip FS.
    """
    from pathlib import Path

    container = get_container_with_db(request, db)
    repo = container.subagent_repository()

    if source == "filesystem":
        # Only filesystem SubAgents
        from src.infrastructure.agent.subagent.filesystem_loader import FileSystemSubAgentLoader

        loader = FileSystemSubAgentLoader(base_path=Path.cwd(), tenant_id=tenant_id)
        result = await loader.load_all()
        all_subagents = [loaded.subagent for loaded in result.subagents]
        if enabled_only:
            all_subagents = [s for s in all_subagents if s.enabled]
        total = len(all_subagents)
        page = all_subagents[offset : offset + limit]
    elif source == "database" or not include_filesystem:
        # Only database SubAgents
        page = await repo.list_by_tenant(
            tenant_id, enabled_only=enabled_only, limit=limit, offset=offset
        )
        total = await repo.count_by_tenant(tenant_id, enabled_only=enabled_only)
    else:
        # Merged: DB + FS (default)
        from src.application.services.subagent_service import SubAgentService
        from src.infrastructure.agent.subagent.filesystem_loader import FileSystemSubAgentLoader

        loader = FileSystemSubAgentLoader(base_path=Path.cwd(), tenant_id=tenant_id)
        service = SubAgentService(filesystem_loader=loader)
        db_subagents = await repo.list_by_tenant(tenant_id, enabled_only=False)
        fs_subagents = await service.load_filesystem_subagents()
        all_subagents = service.merge(db_subagents, fs_subagents)
        if enabled_only:
            all_subagents = [s for s in all_subagents if s.enabled]
        total = len(all_subagents)
        page = all_subagents[offset : offset + limit]

    return SubAgentListResponse(
        subagents=[subagent_to_response(s) for s in page],
        total=total,
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
    tenant_id: str = Depends(get_current_user_tenant),
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

    subagents = []
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
        scanned_dirs=[str(d) for d in result.scanned_dirs]
        if hasattr(result, "scanned_dirs")
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
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> subagent_to_response:
    """
    Import a filesystem SubAgent into the database for customization.

    This copies the filesystem definition into the database, allowing the user
    to modify it. The database version will take precedence over the filesystem
    version in future loads.
    """
    from pathlib import Path

    from src.infrastructure.agent.subagent.filesystem_loader import FileSystemSubAgentLoader

    loader = FileSystemSubAgentLoader(
        base_path=Path.cwd(),
        tenant_id=tenant_id,
    )
    result = await loader.load_all()
    target = None
    for loaded in result.subagents:
        if loaded.subagent.name == name:
            target = loaded
            break

    if not target:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Filesystem SubAgent '{name}' not found",
        )

    container = get_container_with_db(request, db)
    repo = container.subagent_repository()

    # Check if DB version already exists
    existing = await repo.get_by_name(tenant_id, name)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"SubAgent '{name}' already exists in database",
        )

    # Create a DB copy from the filesystem SubAgent
    fs_agent = target.subagent

    db_agent = SubAgent.create(
        tenant_id=tenant_id,
        name=fs_agent.name,
        display_name=fs_agent.display_name,
        system_prompt=fs_agent.system_prompt,
        trigger_description=fs_agent.trigger.description,
        trigger_keywords=list(fs_agent.trigger.keywords),
        trigger_examples=list(fs_agent.trigger.examples),
        model=fs_agent.model,
        color=fs_agent.color,
        allowed_tools=list(fs_agent.allowed_tools),
        max_tokens=fs_agent.max_tokens,
        temperature=fs_agent.temperature,
        max_iterations=fs_agent.max_iterations,
        project_id=project_id,
        metadata={"imported_from": str(target.file_info.file_path)},
    )

    created = await repo.create(db_agent)
    await db.commit()

    logger.info(f"Imported filesystem SubAgent to DB: {created.id} ({name})")
    return subagent_to_response(created)


@router.get("/templates/list", response_model=TemplateListResponse)
async def list_subagent_templates(
    request: Request,
    category: str | None = Query(None, description="Filter by category"),
    query: str | None = Query(None, description="Search query"),
    limit: int = Query(50, ge=1, le=100, description="Maximum results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> TemplateListResponse:
    """
    List published subagent templates with optional filtering.
    """
    container = get_container_with_db(request, db)
    repo = container.subagent_template_repository()
    templates = await repo.list_templates(
        tenant_id=tenant_id,
        category=category,
        query=query,
        published_only=True,
        limit=limit,
        offset=offset,
    )
    total = await repo.count_templates(tenant_id=tenant_id, category=category)

    return TemplateListResponse(
        templates=[TemplateResponse(**t) for t in templates],
        total=total,
    )


@router.post(
    "/templates/",
    response_model=TemplateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_template(
    request: Request,
    data: TemplateCreate,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> TemplateResponse:
    """
    Create a new subagent template.
    """
    container = get_container_with_db(request, db)
    repo = container.subagent_template_repository()

    # Check uniqueness
    existing = await repo.get_by_name(tenant_id, data.name, data.version)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Template '{data.name}' v{data.version} already exists",
        )

    template_data = data.model_dump()
    template_data["tenant_id"] = tenant_id
    created = await repo.create(template_data)
    await db.commit()

    logger.info(f"Template created: {created['id']} ({data.name})")
    return TemplateResponse(**created)


@router.get("/templates/categories")
async def list_template_categories(
    request: Request,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    List all available template categories.
    """
    container = get_container_with_db(request, db)
    repo = container.subagent_template_repository()
    categories = await repo.list_categories(tenant_id)
    return {"categories": categories}


@router.get("/templates/{template_id}", response_model=TemplateResponse)
async def get_template(
    request: Request,
    template_id: str,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> TemplateResponse:
    """
    Get a specific template by ID.
    """
    container = get_container_with_db(request, db)
    repo = container.subagent_template_repository()
    template = await repo.get_by_id(template_id)

    if not template or template["tenant_id"] != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Template not found",
        )

    return TemplateResponse(**template)


@router.put("/templates/{template_id}", response_model=TemplateResponse)
async def update_template(
    request: Request,
    template_id: str,
    data: TemplateUpdate,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> TemplateResponse:
    """
    Update an existing template.
    """
    container = get_container_with_db(request, db)
    repo = container.subagent_template_repository()
    template = await repo.get_by_id(template_id)

    if not template or template["tenant_id"] != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Template not found",
        )

    if template["is_builtin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot modify builtin templates",
        )

    update_data = data.model_dump(exclude_unset=True)
    updated = await repo.update(template_id, update_data)
    await db.commit()

    logger.info(f"Template updated: {template_id}")
    assert updated is not None
    return TemplateResponse(**updated)


@router.delete("/templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(
    request: Request,
    template_id: str,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> None:
    """
    Delete a template.
    """
    container = get_container_with_db(request, db)
    repo = container.subagent_template_repository()
    template = await repo.get_by_id(template_id)

    if not template or template["tenant_id"] != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Template not found",
        )

    if template["is_builtin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot delete builtin templates",
        )

    await repo.delete(template_id)
    await db.commit()
    logger.info(f"Template deleted: {template_id}")


@router.post(
    "/templates/{template_id}/install",
    response_model=SubAgentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def install_template(
    request: Request,
    template_id: str,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> subagent_to_response:
    """
    Create a SubAgent from a template (install).
    """
    container = get_container_with_db(request, db)
    template_repo = container.subagent_template_repository()
    template = await template_repo.get_by_id(template_id)

    if not template or template["tenant_id"] != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Template not found",
        )

    subagent_repo = container.subagent_repository()

    # Check if SubAgent already exists
    existing = await subagent_repo.get_by_name(tenant_id, template["name"])
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"SubAgent '{template['name']}' already exists",
        )

    subagent = SubAgent.create(
        tenant_id=tenant_id,
        name=template["name"],
        display_name=template.get("display_name") or template["name"],
        system_prompt=template["system_prompt"],
        trigger_description=template.get("trigger_description") or template["name"],
        trigger_keywords=template.get("trigger_keywords", []),
        trigger_examples=template.get("trigger_examples", []),
        model=AgentModel(template.get("model", "inherit")),
        max_tokens=template.get("max_tokens", 4096),
        temperature=template.get("temperature", 0.7),
        max_iterations=template.get("max_iterations", 10),
        allowed_tools=template.get("allowed_tools", ["*"]),
    )

    created = await subagent_repo.create(subagent)
    await template_repo.increment_install_count(template_id)
    await db.commit()

    logger.info(f"SubAgent installed from template: {created.id} ({template['name']})")
    return subagent_to_response(created)


@router.post(
    "/templates/from-subagent/{subagent_id}",
    response_model=TemplateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def export_subagent_as_template(
    request: Request,
    subagent_id: str,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> TemplateResponse:
    """
    Export an existing SubAgent as a reusable template.
    """
    container = get_container_with_db(request, db)
    subagent_repo = container.subagent_repository()
    subagent = await subagent_repo.get_by_id(subagent_id)

    if not subagent or subagent.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="SubAgent not found",
        )

    template_repo = container.subagent_template_repository()

    template_data = {
        "tenant_id": tenant_id,
        "name": subagent.name,
        "display_name": subagent.display_name,
        "description": f"Exported from SubAgent: {subagent.display_name}",
        "category": "custom",
        "system_prompt": subagent.system_prompt,
        "trigger_description": subagent.trigger.description,
        "trigger_keywords": list(subagent.trigger.keywords),
        "trigger_examples": list(subagent.trigger.examples),
        "model": subagent.model.value,
        "max_tokens": subagent.max_tokens,
        "temperature": subagent.temperature,
        "max_iterations": subagent.max_iterations,
        "allowed_tools": list(subagent.allowed_tools),
        "is_published": True,
    }

    created = await template_repo.create(template_data)
    await db.commit()

    logger.info(f"SubAgent exported as template: {created['id']} from {subagent_id}")
    return TemplateResponse(**created)


@router.get("/{subagent_id}", response_model=SubAgentResponse)
async def get_subagent(
    request: Request,
    subagent_id: str,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> subagent_to_response:
    """
    Get a specific subagent by ID.
    """
    container = get_container_with_db(request, db)
    repo = container.subagent_repository()
    subagent = await repo.get_by_id(subagent_id)

    if not subagent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="SubAgent not found",
        )

    # Verify tenant access
    if subagent.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="SubAgent not found",
        )

    return subagent_to_response(subagent)


@router.put("/{subagent_id}", response_model=SubAgentResponse)
async def update_subagent(
    request: Request,
    subagent_id: str,
    data: SubAgentUpdate,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> subagent_to_response:
    """
    Update an existing subagent.
    """
    container = get_container_with_db(request, db)
    repo = container.subagent_repository()
    subagent = await repo.get_by_id(subagent_id)

    if not subagent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="SubAgent not found",
        )

    # Verify tenant access
    if subagent.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="SubAgent not found",
        )

    # Check name uniqueness if changing
    if data.name and data.name != subagent.name:
        existing = await repo.get_by_name(subagent.tenant_id, data.name)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"SubAgent with name '{data.name}' already exists",
            )

    # Update fields
    from datetime import datetime

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
        temperature=data.temperature if data.temperature is not None else subagent.temperature,
        max_iterations=data.max_iterations if data.max_iterations else subagent.max_iterations,
        enabled=subagent.enabled,
        total_invocations=subagent.total_invocations,
        avg_execution_time_ms=subagent.avg_execution_time_ms,
        success_rate=subagent.success_rate,
        created_at=subagent.created_at,
        updated_at=datetime.now(UTC),
        metadata=data.metadata if data.metadata is not None else subagent.metadata,
    )

    result = await repo.update(updated_subagent)
    await db.commit()

    logger.info(f"SubAgent updated: {subagent_id}")
    return subagent_to_response(result)


@router.delete("/{subagent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_subagent(
    request: Request,
    subagent_id: str,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> None:
    """
    Delete a subagent.
    """
    container = get_container_with_db(request, db)
    repo = container.subagent_repository()
    subagent = await repo.get_by_id(subagent_id)

    if not subagent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="SubAgent not found",
        )

    # Verify tenant access
    if subagent.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="SubAgent not found",
        )

    await repo.delete(subagent_id)
    await db.commit()

    logger.info(f"SubAgent deleted: {subagent_id}")


@router.patch("/{subagent_id}/enable", response_model=SubAgentResponse)
async def toggle_subagent_enabled(
    request: Request,
    subagent_id: str,
    enabled: bool = Query(..., description="Enable or disable"),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> subagent_to_response:
    """
    Enable or disable a subagent.
    """
    container = get_container_with_db(request, db)
    repo = container.subagent_repository()
    subagent = await repo.get_by_id(subagent_id)

    if not subagent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="SubAgent not found",
        )

    # Verify tenant access
    if subagent.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="SubAgent not found",
        )

    result = await repo.set_enabled(subagent_id, enabled)
    await db.commit()

    logger.info(f"SubAgent {'enabled' if enabled else 'disabled'}: {subagent_id}")
    assert result is not None
    return subagent_to_response(result)


@router.get("/{subagent_id}/stats", response_model=SubAgentStatsResponse)
async def get_subagent_stats(
    request: Request,
    subagent_id: str,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> SubAgentStatsResponse:
    """
    Get statistics for a subagent.
    """
    container = get_container_with_db(request, db)
    repo = container.subagent_repository()
    subagent = await repo.get_by_id(subagent_id)

    if not subagent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="SubAgent not found",
        )

    # Verify tenant access
    if subagent.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="SubAgent not found",
        )

    return SubAgentStatsResponse(
        subagent_id=subagent.id,
        name=subagent.name,
        display_name=subagent.display_name,
        total_invocations=subagent.total_invocations,
        avg_execution_time_ms=subagent.avg_execution_time_ms,
        success_rate=subagent.success_rate,
        enabled=subagent.enabled,
    )


@router.post("/match", response_model=SubAgentMatchResponse)
async def match_subagent(
    request: Request,
    data: SubAgentMatchRequest,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> SubAgentMatchResponse:
    """
    Find the best matching subagent for a task description.

    Uses trigger keywords and LLM-based matching to find the most suitable subagent.
    """
    container = get_container_with_db(request, db)
    repo = container.subagent_repository()

    # First try keyword matching
    keyword_matches = await repo.find_by_keywords(
        tenant_id, data.task_description, enabled_only=True
    )

    if keyword_matches:
        # Return the first keyword match with high confidence
        return SubAgentMatchResponse(
            subagent=subagent_to_response(keyword_matches[0]),
            confidence=0.8,
        )

    # No keyword match found
    return SubAgentMatchResponse(
        subagent=None,
        confidence=0.0,
    )


@router.post("/templates/seed")
async def seed_templates(
    request: Request,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Seed builtin templates for the current tenant.

    Idempotent: skips templates that already exist.
    """
    from src.infrastructure.adapters.secondary.persistence.seed_templates import (
        seed_builtin_templates,
    )

    container = get_container_with_db(request, db)
    repo = container.subagent_template_repository()
    created = await seed_builtin_templates(repo, tenant_id)
    await db.commit()

    return {"created": created, "message": f"Seeded {created} builtin templates"}
