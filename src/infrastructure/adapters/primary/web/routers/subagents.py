"""
SubAgent Management API endpoints.

Provides REST API for managing subagents in the Agent SubAgent System (L3 layer).
SubAgents are specialized agents that handle specific types of tasks with
isolated tool access and custom system prompts.
"""

import logging
from typing import Any, Dict, List, Optional

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
        mcp_temporal_adapter=app_container._mcp_temporal_adapter,
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
    trigger_examples: List[str] = Field(default_factory=list, description="Trigger examples")
    trigger_keywords: List[str] = Field(default_factory=list, description="Trigger keywords")
    model: str = Field("inherit", description="LLM model: inherit, qwen-max, gpt-4, etc.")
    color: str = Field("blue", description="UI display color")
    allowed_tools: List[str] = Field(default_factory=lambda: ["*"], description="Allowed tools")
    allowed_skills: List[str] = Field(default_factory=list, description="Allowed skill IDs")
    allowed_mcp_servers: List[str] = Field(default_factory=list, description="Allowed MCP servers")
    max_tokens: int = Field(4096, ge=1, le=32768, description="Max tokens")
    temperature: float = Field(0.7, ge=0.0, le=2.0, description="Temperature")
    max_iterations: int = Field(10, ge=1, le=50, description="Max ReAct iterations")
    project_id: Optional[str] = Field(None, description="Optional project ID")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Optional metadata")


class SubAgentUpdate(BaseModel):
    """Schema for updating a subagent."""

    name: Optional[str] = Field(None, min_length=1, max_length=100)
    display_name: Optional[str] = Field(None, min_length=1, max_length=200)
    system_prompt: Optional[str] = Field(None, min_length=1)
    trigger_description: Optional[str] = Field(None)
    trigger_examples: Optional[List[str]] = Field(None)
    trigger_keywords: Optional[List[str]] = Field(None)
    model: Optional[str] = Field(None)
    color: Optional[str] = Field(None)
    allowed_tools: Optional[List[str]] = Field(None)
    allowed_skills: Optional[List[str]] = Field(None)
    allowed_mcp_servers: Optional[List[str]] = Field(None)
    max_tokens: Optional[int] = Field(None, ge=1, le=32768)
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0)
    max_iterations: Optional[int] = Field(None, ge=1, le=50)
    metadata: Optional[Dict[str, Any]] = Field(None)


class SubAgentResponse(BaseModel):
    """Schema for subagent response."""

    id: str
    tenant_id: str
    project_id: Optional[str]
    name: str
    display_name: str
    system_prompt: str
    trigger: Dict[str, Any]
    model: str
    color: str
    allowed_tools: List[str]
    allowed_skills: List[str]
    allowed_mcp_servers: List[str]
    max_tokens: int
    temperature: float
    max_iterations: int
    enabled: bool
    total_invocations: int
    avg_execution_time_ms: float
    success_rate: float
    created_at: str
    updated_at: str
    metadata: Optional[Dict[str, Any]]


class SubAgentListResponse(BaseModel):
    """Schema for subagent list response."""

    subagents: List[SubAgentResponse]
    total: int


class SubAgentMatchRequest(BaseModel):
    """Schema for subagent matching request."""

    task_description: str = Field(..., min_length=1, description="Task to match")


class SubAgentMatchResponse(BaseModel):
    """Schema for subagent match response."""

    subagent: Optional[SubAgentResponse]
    confidence: float


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
    )


# === API Endpoints ===


@router.post("/", response_model=SubAgentResponse, status_code=status.HTTP_201_CREATED)
async def create_subagent(
    request: Request,
    data: SubAgentCreate,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
):
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
        )


@router.get("/", response_model=SubAgentListResponse)
async def list_subagents(
    request: Request,
    enabled_only: bool = Query(False, description="Only return enabled subagents"),
    limit: int = Query(100, ge=1, le=500, description="Maximum results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
):
    """
    List all subagents for the current tenant.
    """
    container = get_container_with_db(request, db)
    repo = container.subagent_repository()
    subagents = await repo.list_by_tenant(
        tenant_id, enabled_only=enabled_only, limit=limit, offset=offset
    )
    total = await repo.count_by_tenant(tenant_id, enabled_only=enabled_only)

    return SubAgentListResponse(
        subagents=[subagent_to_response(s) for s in subagents],
        total=total,
    )


@router.get("/templates/list")
async def list_subagent_templates(
    tenant_id: str = Depends(get_current_user_tenant),
):
    """
    List predefined subagent templates.
    """
    from src.domain.model.agent.subagent import (
        CODER_SUBAGENT_TEMPLATE,
        RESEARCHER_SUBAGENT_TEMPLATE,
        WRITER_SUBAGENT_TEMPLATE,
    )

    return {
        "templates": [
            {
                "name": RESEARCHER_SUBAGENT_TEMPLATE["name"],
                "display_name": RESEARCHER_SUBAGENT_TEMPLATE["display_name"],
                "description": RESEARCHER_SUBAGENT_TEMPLATE["trigger_description"],
            },
            {
                "name": CODER_SUBAGENT_TEMPLATE["name"],
                "display_name": CODER_SUBAGENT_TEMPLATE["display_name"],
                "description": CODER_SUBAGENT_TEMPLATE["trigger_description"],
            },
            {
                "name": WRITER_SUBAGENT_TEMPLATE["name"],
                "display_name": WRITER_SUBAGENT_TEMPLATE["display_name"],
                "description": WRITER_SUBAGENT_TEMPLATE["trigger_description"],
            },
        ]
    }


@router.post(
    "/templates/{template_name}",
    response_model=SubAgentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_from_template(
    request: Request,
    template_name: str,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a subagent from a predefined template.
    """
    from src.domain.model.agent.subagent import (
        CODER_SUBAGENT_TEMPLATE,
        RESEARCHER_SUBAGENT_TEMPLATE,
        WRITER_SUBAGENT_TEMPLATE,
    )

    templates = {
        "researcher": RESEARCHER_SUBAGENT_TEMPLATE,
        "coder": CODER_SUBAGENT_TEMPLATE,
        "writer": WRITER_SUBAGENT_TEMPLATE,
    }

    if template_name not in templates:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Template '{template_name}' not found. Available templates: {list(templates.keys())}",
        )

    template = templates[template_name]
    container = get_container_with_db(request, db)
    repo = container.subagent_repository()

    # Check if already exists
    existing = await repo.get_by_name(tenant_id, template["name"])
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"SubAgent with name '{template['name']}' already exists",
        )

    subagent = SubAgent.create(
        tenant_id=tenant_id,
        name=template["name"],
        display_name=template["display_name"],
        system_prompt=template["system_prompt"],
        trigger_description=template["trigger_description"],
        trigger_keywords=template.get("trigger_keywords", []),
        allowed_tools=template.get("allowed_tools", ["*"]),
        color=template.get("color", "blue"),
    )

    created = await repo.create(subagent)
    await db.commit()

    logger.info(f"SubAgent created from template: {created.id} ({template_name})")
    return subagent_to_response(created)


@router.get("/{subagent_id}", response_model=SubAgentResponse)
async def get_subagent(
    request: Request,
    subagent_id: str,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
):
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
):
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
    from datetime import datetime, timezone

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
        updated_at=datetime.now(timezone.utc),
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
):
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
):
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
    return subagent_to_response(result)


@router.get("/{subagent_id}/stats", response_model=SubAgentStatsResponse)
async def get_subagent_stats(
    request: Request,
    subagent_id: str,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
):
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
):
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
