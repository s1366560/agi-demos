"""CRUD endpoints for Agent Definition management."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent.agent_definition import (
    LEGACY_DEFAULT_MAX_ITERATIONS,
    MAX_ITERATIONS_EXPLICIT_METADATA_KEY,
    Agent,
)
from src.domain.model.agent.delegate_config import DelegateConfig
from src.domain.model.agent.session_policy import SessionPolicy
from src.domain.model.agent.subagent import AgentModel, AgentTrigger
from src.domain.model.agent.workspace_config import WorkspaceConfig
from src.domain.model.auth.user import User
from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user,
)
from src.infrastructure.adapters.primary.web.dependencies.auth_dependencies import (
    get_current_user_tenant,
)
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import Project, UserProject
from src.infrastructure.agent.tools._agent_definition_policy import (
    normalize_new_agent_a2a,
    normalize_updated_agent_a2a,
)
from src.infrastructure.i18n import gettext as _

from .access import require_tenant_access
from .utils import get_container_with_db

logger = logging.getLogger(__name__)

router = APIRouter()


def _with_max_iterations_metadata(
    metadata: dict[str, Any] | None,
    *,
    explicit: bool | None,
) -> dict[str, Any] | None:
    if explicit is None:
        return metadata
    merged = dict(metadata or {})
    merged[MAX_ITERATIONS_EXPLICIT_METADATA_KEY] = explicit
    return merged


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
    agent_to_agent_allowlist: list[str] | None = None
    discoverable: bool = True
    max_retries: int = 0
    fallback_models: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] | None = None
    session_policy: dict[str, Any] | None = None
    delegate_config: dict[str, Any] | None = None
    spawn_policy: dict[str, Any] | None = None
    tool_policy: dict[str, Any] | None = None


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
    agent_to_agent_allowlist: list[str] | None = None
    discoverable: bool | None = None
    max_retries: int | None = None
    fallback_models: list[str] | None = None
    metadata: dict[str, Any] | None = None
    session_policy: dict[str, Any] | None = None
    delegate_config: dict[str, Any] | None = None
    spawn_policy: dict[str, Any] | None = None
    tool_policy: dict[str, Any] | None = None


class SetEnabledBody(BaseModel):
    enabled: bool


class DefinitionListResponse(BaseModel):
    definitions: list[dict[str, Any]]
    total: int
    limit: int
    offset: int


async def _ensure_project_definition_access(
    db: AsyncSession,
    *,
    current_user: User,
    tenant_id: str,
    project_id: str,
) -> None:
    result = await db.execute(
        refresh_select_statement(
            select(UserProject.id)
            .join(Project, UserProject.project_id == Project.id)
            .where(
                and_(
                    UserProject.user_id == current_user.id,
                    UserProject.project_id == project_id,
                    Project.tenant_id == tenant_id,
                )
            )
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_("Access denied"),
        )


async def _ensure_existing_definition_access(
    db: AsyncSession,
    *,
    current_user: User,
    tenant_id: str,
    agent: Agent,
) -> None:
    if agent.project_id is None:
        return
    await _ensure_project_definition_access(
        db,
        current_user=current_user,
        tenant_id=tenant_id,
        project_id=agent.project_id,
    )


async def _accessible_definition_project_ids(
    db: AsyncSession,
    *,
    current_user: User,
    tenant_id: str,
) -> set[str]:
    result = await db.execute(
        refresh_select_statement(
            select(UserProject.project_id)
            .join(Project, UserProject.project_id == Project.id)
            .where(
                and_(
                    UserProject.user_id == current_user.id,
                    Project.tenant_id == tenant_id,
                )
            )
        )
    )
    return {str(project_id) for project_id in result.scalars().all()}


def _filter_agents_by_project_access(
    agents: list[Agent],
    accessible_project_ids: set[str],
) -> list[Agent]:
    return [
        agent
        for agent in agents
        if agent.project_id is None or agent.project_id in accessible_project_ids
    ]


@router.post("/definitions")
async def create_definition(
    body: CreateDefinitionBody,
    request: Request,
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        await require_tenant_access(db, current_user, tenant_id, require_admin=True)
        if body.project_id is not None:
            await _ensure_project_definition_access(
                db,
                current_user=current_user,
                tenant_id=tenant_id,
                project_id=body.project_id,
            )
        container = get_container_with_db(request, db)
        orchestrator = container.agent_orchestrator()

        ws_config = (
            WorkspaceConfig.from_dict(body.workspace_config) if body.workspace_config else None
        )

        session_policy = (
            SessionPolicy.from_dict(body.session_policy) if body.session_policy else None
        )

        delegate_config = (
            DelegateConfig.from_dict(body.delegate_config) if body.delegate_config else None
        )
        spawn_policy = Agent._spawn_policy_from_dict(body.spawn_policy)
        tool_policy = Agent._tool_policy_from_dict(body.tool_policy)
        agent_to_agent_allowlist = normalize_new_agent_a2a(
            enabled=body.agent_to_agent_enabled,
            allowlist=body.agent_to_agent_allowlist,
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
            agent_to_agent_allowlist=agent_to_agent_allowlist,
            discoverable=body.discoverable,
            max_retries=body.max_retries,
            fallback_models=body.fallback_models,
            metadata=_with_max_iterations_metadata(
                body.metadata,
                explicit=body.max_iterations != LEGACY_DEFAULT_MAX_ITERATIONS,
            ),
            session_policy=session_policy,
            delegate_config=delegate_config,
            spawn_policy=spawn_policy,
            tool_policy=tool_policy,
        )

        created = await orchestrator.create_agent(agent)
        return cast(dict[str, Any], created.to_dict())

    except ValueError as e:
        status_code = 409 if "already exists" in str(e) else 400
        if status_code == 409:
            raise HTTPException(
                status_code=status_code, detail=_("Definition already exists")
            ) from e
        raise HTTPException(status_code=status_code, detail=_("Invalid definition request")) from e
    except IntegrityError as e:
        raise HTTPException(
            status_code=409,
            detail=_("Definition already exists"),
        ) from e
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
            detail=_("Failed to create definition"),
        ) from e


@router.get("/definitions")
async def list_definitions(  # noqa: PLR0913
    request: Request,
    project_id: str | None = None,
    scope: str | None = None,
    search: str | None = None,
    sort: str | None = None,
    enabled_only: bool = False,
    enabled: bool | None = None,
    limit: int = 100,
    offset: int = 0,
    include_total: bool = False,
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]] | DefinitionListResponse:
    try:
        await require_tenant_access(db, current_user, tenant_id)
        if scope not in {None, "all", "tenant"}:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=_("Invalid definition scope"),
            )
        if sort not in {None, "name", "recent", "invocations"}:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=_("Invalid definition sort"),
            )

        safe_limit = max(limit, 0)
        safe_offset = max(offset, 0)
        if project_id:
            await _ensure_project_definition_access(
                db,
                current_user=current_user,
                tenant_id=tenant_id,
                project_id=project_id,
            )
        container = get_container_with_db(request, db)
        registry = container.agent_registry()

        if project_id:
            agents = await registry.list_by_project(
                project_id=project_id,
                tenant_id=tenant_id,
                enabled_only=enabled_only,
                limit=safe_limit if include_total else None,
                offset=safe_offset,
                enabled=enabled,
                search=search,
                sort=sort,
            )
            total = (
                await registry.count_by_project(
                    project_id=project_id,
                    tenant_id=tenant_id,
                    enabled_only=enabled_only,
                    enabled=enabled,
                    search=search,
                )
                if include_total
                else len(agents)
            )
        else:
            if scope == "tenant":
                accessible_project_ids: set[str] = set()
            else:
                accessible_project_ids = await _accessible_definition_project_ids(
                    db,
                    current_user=current_user,
                    tenant_id=tenant_id,
                )
            agents = await registry.list_by_tenant(
                tenant_id=tenant_id,
                enabled_only=enabled_only,
                limit=safe_limit,
                offset=safe_offset,
                project_ids=accessible_project_ids,
                enabled=enabled,
                search=search,
                sort=sort,
            )
            agents = _filter_agents_by_project_access(agents, accessible_project_ids)
            total = (
                await registry.count_by_tenant(
                    tenant_id=tenant_id,
                    enabled_only=enabled_only,
                    project_ids=accessible_project_ids,
                    enabled=enabled,
                    search=search,
                )
                if include_total
                else len(agents)
            )

        definitions = [a.to_dict() for a in agents]
        if include_total:
            return DefinitionListResponse(
                definitions=definitions,
                total=total,
                limit=safe_limit,
                offset=safe_offset,
            )
        return definitions

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Error listing definitions: %s",
            e,
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail=_("Failed to list definitions"),
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
        await require_tenant_access(db, current_user, tenant_id)
        container = get_container_with_db(request, db)
        registry = container.agent_registry()

        agent = await registry.get_by_id(definition_id, tenant_id=tenant_id)
        if agent is None:
            raise HTTPException(
                status_code=404,
                detail=_("Definition not found"),
            )

        if agent.tenant_id != tenant_id:
            raise HTTPException(status_code=403, detail=_("Access denied"))
        await _ensure_existing_definition_access(
            db,
            current_user=current_user,
            tenant_id=tenant_id,
            agent=agent,
        )

        return cast(dict[str, Any], agent.to_dict())

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
            detail=_("Failed to get definition"),
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
        await require_tenant_access(db, current_user, tenant_id, require_admin=True)
        if body.project_id is not None:
            await _ensure_project_definition_access(
                db,
                current_user=current_user,
                tenant_id=tenant_id,
                project_id=body.project_id,
            )
        container = get_container_with_db(request, db)
        registry = container.agent_registry()

        existing = await registry.get_by_id(definition_id, tenant_id=tenant_id)
        if existing is None:
            raise HTTPException(
                status_code=404,
                detail=_("Definition not found"),
            )

        if existing.tenant_id != tenant_id:
            raise HTTPException(status_code=403, detail=_("Access denied"))
        await _ensure_existing_definition_access(
            db,
            current_user=current_user,
            tenant_id=tenant_id,
            agent=existing,
        )

        updates = body.model_dump(exclude_unset=True)
        if "max_iterations" in updates:
            updates["metadata"] = _with_max_iterations_metadata(
                updates.get("metadata", existing.metadata),
                explicit=True,
            )
        normalize_updated_agent_a2a(existing, updates)
        _apply_updates(existing, updates)
        existing.validate()
        existing.updated_at = datetime.now(UTC)

        updated = await registry.update(existing)
        await db.commit()
        return cast(dict[str, Any], updated.to_dict())

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=_("Invalid definition request")) from e
    except Exception as e:
        logger.error(
            "Error updating definition: %s",
            e,
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail=_("Failed to update definition"),
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
        await require_tenant_access(db, current_user, tenant_id, require_admin=True)
        container = get_container_with_db(request, db)
        registry = container.agent_registry()

        existing = await registry.get_by_id(definition_id, tenant_id=tenant_id)
        if existing is None:
            raise HTTPException(
                status_code=404,
                detail=_("Definition not found"),
            )

        if existing.tenant_id != tenant_id:
            raise HTTPException(status_code=403, detail=_("Access denied"))
        await _ensure_existing_definition_access(
            db,
            current_user=current_user,
            tenant_id=tenant_id,
            agent=existing,
        )

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
            detail=_("Failed to delete definition"),
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
        await require_tenant_access(db, current_user, tenant_id, require_admin=True)
        container = get_container_with_db(request, db)
        registry = container.agent_registry()

        existing = await registry.get_by_id(definition_id, tenant_id=tenant_id)
        if existing is None:
            raise HTTPException(
                status_code=404,
                detail=_("Definition not found"),
            )

        if existing.tenant_id != tenant_id:
            raise HTTPException(status_code=403, detail=_("Access denied"))
        await _ensure_existing_definition_access(
            db,
            current_user=current_user,
            tenant_id=tenant_id,
            agent=existing,
        )

        updated = await registry.set_enabled(definition_id, body.enabled)
        await db.commit()
        return cast(dict[str, Any], updated.to_dict())

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=_("Invalid definition request")) from e
    except Exception as e:
        logger.error(
            "Error updating definition: %s",
            e,
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail=_("Failed to update definition"),
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
        elif key == "workspace_config":
            agent.workspace_config = WorkspaceConfig()
        elif key == "model":
            agent.model = AgentModel(value) if value is not None else AgentModel.INHERIT
        elif key == "session_policy" and isinstance(value, dict):
            agent.session_policy = SessionPolicy.from_dict(value)
        elif key == "delegate_config" and isinstance(value, dict):
            agent.delegate_config = DelegateConfig.from_dict(value)
        elif key == "spawn_policy":
            agent.spawn_policy = Agent._spawn_policy_from_dict(value)
        elif key == "tool_policy":
            agent.tool_policy = Agent._tool_policy_from_dict(value)
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
