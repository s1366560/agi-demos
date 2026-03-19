"""CRUD endpoints for Agent Definition management."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent.agent_definition import Agent, AgentModel
from src.domain.model.agent.subagent import AgentTrigger
from src.domain.model.agent.workspace_config import WorkspaceConfig
from src.domain.model.auth.user import User
from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user,
)
from src.infrastructure.adapters.primary.web.dependencies.auth_dependencies import (
    get_current_user_tenant,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db

from .utils import get_container_with_db

logger = logging.getLogger(__name__)

router = APIRouter()


class CreateDefinitionBody(BaseModel):
    name: str
    display_name: str
    system_prompt: str
    project_id: str | None = None
    trigger_description: str = "Default agent trigger"
    trigger_examples: list[str] = Field(default_factory=list)
    trigger_keywords: list[str] = Field(default_factory=list)
    persona_files: list[str] = Field(default_factory=list)
    model: str | None = None
    temperature: float = 0.7
    max_tokens: int = 4096
    max_iterations: int = 10
    allowed_tools: list[str] | None = None
    allowed_skills: list[str] | None = None
    allowed_mcp_servers: list[str] | None = None
    workspace_dir: str | None = None
    workspace_config: dict[str, Any] | None = None
    can_spawn: bool = False
    max_spawn_depth: int = 3
    agent_to_agent_enabled: bool = False
    discoverable: bool = True
    max_retries: int = 0
    fallback_models: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] | None = None


class UpdateDefinitionBody(BaseModel):
    name: str | None = None
    display_name: str | None = None
    system_prompt: str | None = None
    project_id: str | None = None
    trigger_description: str | None = None
    trigger_examples: list[str] | None = None
    trigger_keywords: list[str] | None = None
    persona_files: list[str] | None = None
    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    max_iterations: int | None = None
    allowed_tools: list[str] | None = None
    allowed_skills: list[str] | None = None
    allowed_mcp_servers: list[str] | None = None
    workspace_dir: str | None = None
    workspace_config: dict[str, Any] | None = None
    can_spawn: bool | None = None
    max_spawn_depth: int | None = None
    agent_to_agent_enabled: bool | None = None
    discoverable: bool | None = None
    max_retries: int | None = None
    fallback_models: list[str] | None = None
    metadata: dict[str, Any] | None = None


class SetEnabledBody(BaseModel):
    enabled: bool


@router.post("/definitions")
async def create_definition(
    body: CreateDefinitionBody,
    request: Request,
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        container = get_container_with_db(request, db)
        registry = container.agent_registry()

        ws_config = (
            WorkspaceConfig.from_dict(body.workspace_config) if body.workspace_config else None
        )

        agent = Agent.create(
            tenant_id=tenant_id,
            name=body.name,
            display_name=body.display_name,
            system_prompt=body.system_prompt,
            project_id=body.project_id,
            trigger_description=body.trigger_description,
            trigger_examples=body.trigger_examples,
            trigger_keywords=body.trigger_keywords,
            persona_files=body.persona_files,
            model=AgentModel(body.model) if body.model else AgentModel.INHERIT,
            temperature=body.temperature,
            max_tokens=body.max_tokens,
            max_iterations=body.max_iterations,
            allowed_tools=body.allowed_tools,
            allowed_skills=body.allowed_skills,
            allowed_mcp_servers=body.allowed_mcp_servers,
            workspace_dir=body.workspace_dir,
            workspace_config=ws_config,
            can_spawn=body.can_spawn,
            max_spawn_depth=body.max_spawn_depth,
            agent_to_agent_enabled=body.agent_to_agent_enabled,
            discoverable=body.discoverable,
            max_retries=body.max_retries,
            fallback_models=body.fallback_models,
            metadata=body.metadata,
        )

        created = await registry.create(agent)
        await db.commit()
        return created.to_dict()

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Error creating definition: %s",
            e,
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create definition: {e!s}",
        ) from e


@router.get("/definitions")
async def list_definitions(
    request: Request,
    project_id: str | None = None,
    enabled_only: bool = False,
    limit: int = 100,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    try:
        container = get_container_with_db(request, db)
        registry = container.agent_registry()

        if project_id:
            agents = await registry.list_by_project(
                project_id=project_id,
                tenant_id=tenant_id,
                enabled_only=enabled_only,
            )
        else:
            agents = await registry.list_by_tenant(
                tenant_id=tenant_id,
                enabled_only=enabled_only,
                limit=limit,
                offset=offset,
            )

        return [a.to_dict() for a in agents]

    except Exception as e:
        logger.error(
            "Error listing definitions: %s",
            e,
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list definitions: {e!s}",
        ) from e


@router.get("/definitions/{definition_id}")
async def get_definition(
    definition_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        container = get_container_with_db(request, db)
        registry = container.agent_registry()

        agent = await registry.get_by_id(definition_id)
        if agent is None:
            raise HTTPException(
                status_code=404,
                detail="Definition not found",
            )

        if agent.tenant_id != tenant_id:
            raise HTTPException(status_code=403, detail="Access denied")

        return agent.to_dict()

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Error getting definition: %s",
            e,
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get definition: {e!s}",
        ) from e


@router.put("/definitions/{definition_id}")
async def update_definition(
    definition_id: str,
    body: UpdateDefinitionBody,
    request: Request,
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        container = get_container_with_db(request, db)
        registry = container.agent_registry()

        existing = await registry.get_by_id(definition_id)
        if existing is None:
            raise HTTPException(
                status_code=404,
                detail="Definition not found",
            )

        if existing.tenant_id != tenant_id:
            raise HTTPException(status_code=403, detail="Access denied")

        updates = body.model_dump(exclude_unset=True)
        _apply_updates(existing, updates)
        existing.updated_at = datetime.now(UTC)

        updated = await registry.update(existing)
        await db.commit()
        return updated.to_dict()

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.error(
            "Error updating definition: %s",
            e,
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update definition: {e!s}",
        ) from e


@router.delete("/definitions/{definition_id}")
async def delete_definition(
    definition_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        container = get_container_with_db(request, db)
        registry = container.agent_registry()

        existing = await registry.get_by_id(definition_id)
        if existing is None:
            raise HTTPException(
                status_code=404,
                detail="Definition not found",
            )

        if existing.tenant_id != tenant_id:
            raise HTTPException(status_code=403, detail="Access denied")

        await registry.delete(definition_id)
        await db.commit()
        return {"deleted": True, "id": definition_id}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Error deleting definition: %s",
            e,
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete definition: {e!s}",
        ) from e


@router.patch("/definitions/{definition_id}/enabled")
async def set_definition_enabled(
    definition_id: str,
    body: SetEnabledBody,
    request: Request,
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        container = get_container_with_db(request, db)
        registry = container.agent_registry()

        existing = await registry.get_by_id(definition_id)
        if existing is None:
            raise HTTPException(
                status_code=404,
                detail="Definition not found",
            )

        if existing.tenant_id != tenant_id:
            raise HTTPException(status_code=403, detail="Access denied")

        updated = await registry.set_enabled(definition_id, body.enabled)
        await db.commit()
        return updated.to_dict()

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.error(
            "Error updating definition: %s",
            e,
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update definition: {e!s}",
        ) from e


def _apply_updates(
    agent: Agent,
    updates: dict[str, Any],
) -> None:
    trigger_fields = {
        "trigger_description",
        "trigger_examples",
        "trigger_keywords",
    }
    has_trigger_update = bool(trigger_fields & updates.keys())

    for key, value in updates.items():
        if key in trigger_fields:
            continue
        if key == "workspace_config" and isinstance(value, dict):
            agent.workspace_config = WorkspaceConfig.from_dict(value)
        elif hasattr(agent, key):
            setattr(agent, key, value)

    if has_trigger_update:
        agent.trigger = AgentTrigger(
            description=updates.get(
                "trigger_description",
                agent.trigger.description,
            ),
            examples=updates.get(
                "trigger_examples",
                agent.trigger.examples,
            ),
            keywords=updates.get(
                "trigger_keywords",
                agent.trigger.keywords,
            ),
        )
