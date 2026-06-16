"""
Skill Management API endpoints.

Provides REST API for managing skills in the Agent Skill System (L2 layer).
Skills encapsulate domain knowledge and tool compositions for specific task patterns.

Three-level scoping for multi-tenant isolation:
- system: Built-in skills shared by all tenants (can be disabled/overridden)
- tenant: Tenant-level skills shared within a tenant
- project: Project-specific skills (highest priority)
"""

import json
import logging
import uuid
import zipfile
from base64 import b64encode
from collections.abc import Collection, Mapping
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Any, cast

import yaml
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from pydantic import BaseModel, Field
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.configuration.di_container import DIContainer
from src.domain.model.agent.skill import Skill, SkillScope, SkillStatus
from src.domain.model.agent.skill.skill_version import SkillVersion
from src.domain.model.agent.skill_source import SkillSource
from src.domain.ports.repositories.skill_repository import SkillRepositoryPort
from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user,
    get_current_user_tenant,
)
from src.infrastructure.adapters.primary.web.routers.agent.access import require_tenant_access
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import Project, User, UserProject
from src.infrastructure.i18n import gettext as _
from src.infrastructure.skill.markdown_parser import MarkdownParser, SkillMarkdown
from src.infrastructure.skill.validator import AgentSkillsValidator


def get_container_with_db(request: Request, db: AsyncSession) -> DIContainer:
    """
    Get DI container with database session for the current request.
    """
    app_container = request.app.state.container
    if hasattr(app_container, "with_db"):
        return cast(DIContainer, app_container.with_db(db))
    return DIContainer(
        db=db,
        graph_service=app_container.graph_service,
        redis_client=app_container.redis_client,
    )


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/skills", tags=["Skills"])
_PROJECT_SKILL_WRITE_ROLES = ("owner", "admin", "member")
ParsedSkillPayload = tuple[
    str | None,
    str | None,
    str | None,
    list[str] | None,
    dict[str, Any] | None,
    str | None,
]


async def _get_selected_skill_tenant_id(
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
    """Resolve the tenant for a skill request and validate explicit tenant scope."""
    if selected_tenant_id is None:
        return fallback_tenant_id

    await require_tenant_access(db, cast(Any, current_user), selected_tenant_id)
    return selected_tenant_id


# === Pydantic Models ===


class SkillCreate(BaseModel):
    """Schema for creating a new skill."""

    name: str = Field(..., min_length=1, max_length=64, description="Skill name")
    description: str = Field(..., min_length=1, max_length=1024, description="Skill description")
    tools: list[str] = Field(..., min_length=1, description="List of tool names")
    full_content: str | None = Field(None, description="Full SKILL.md content")
    project_id: str | None = Field(
        None, description="Optional project ID (required for PROJECT scope)"
    )
    scope: str = Field(
        "tenant", description="Skill scope: tenant or project (cannot create system)"
    )
    metadata: dict[str, Any] | None = Field(None, description="Optional metadata")
    license: str | None = Field(None, max_length=200, description="Optional skill license")
    compatibility: str | None = Field(
        None, max_length=500, description="Optional compatibility notes"
    )
    allowed_tools_raw: str | None = Field(
        None, max_length=2000, description="Raw AgentSkills allowed-tools value"
    )
    spec_version: str | None = Field(None, max_length=32, description="AgentSkills spec version")


class SkillUpdate(BaseModel):
    """Schema for updating a skill."""

    name: str | None = Field(None, min_length=1, max_length=64)
    description: str | None = Field(None, min_length=1, max_length=1024)
    tools: list[str] | None = Field(None, min_length=1)
    full_content: str | None = Field(None, description="Full SKILL.md content")
    status: str | None = Field(None)
    metadata: dict[str, Any] | None = Field(None)
    license: str | None = Field(None, max_length=200)
    compatibility: str | None = Field(None, max_length=500)
    allowed_tools_raw: str | None = Field(None, max_length=2000)
    spec_version: str | None = Field(None, max_length=32)


class SkillResponse(BaseModel):
    """Schema for skill response."""

    id: str
    tenant_id: str
    project_id: str | None
    name: str
    description: str
    tools: list[str]
    full_content: str | None = None
    status: str
    scope: str
    is_system_skill: bool = False
    source: str = "database"
    file_path: str | None = None
    created_at: str
    updated_at: str
    metadata: dict[str, Any] | None
    resource_files: dict[str, str] = Field(default_factory=dict)
    agent_modes: list[str] = Field(default_factory=lambda: ["*"])
    license: str | None = None
    compatibility: str | None = None
    allowed_tools_raw: str | None = None
    spec_version: str = "1.0"
    current_version: int = 0
    version_label: str | None = None


class SkillEvolutionOverviewStatsResponse(BaseModel):
    """Tenant-level skill evolution capture and job totals."""

    total_sessions: int
    skill_sessions: int
    no_skill_sessions: int
    unprocessed_sessions: int
    processed_sessions: int
    scored_sessions: int
    successful_sessions: int
    avg_score: float | None
    total_jobs: int
    pending_jobs: int
    applied_jobs: int
    skipped_jobs: int
    rejected_jobs: int


class SkillEvolutionSkillSummaryResponse(BaseModel):
    """Aggregated evolution evidence for one skill name."""

    skill_id: str | None = None
    project_id: str | None = None
    skill_name: str
    session_count: int
    success_count: int
    unprocessed_count: int
    scored_count: int
    avg_score: float | None
    latest_session_at: str | None
    job_count: int
    pending_job_count: int
    latest_job_at: str | None


class SkillEvolutionSessionResponse(BaseModel):
    """Captured skill evolution session for UI inspection."""

    id: str
    skill_name: str
    conversation_id: str
    project_id: str | None
    user_query: str
    summary: str | None
    judge_scores: dict[str, Any] | None
    overall_score: float | None
    success: bool
    execution_time_ms: int
    tool_call_count: int
    processed: bool
    created_at: str


class SkillListResponse(BaseModel):
    """Schema for skill list response."""

    skills: list[SkillResponse]
    total: int


class SkillPackagePayload(BaseModel):
    """AgentSkills.io package payload for import/export operations."""

    skill_md_content: str = Field(..., min_length=1, description="Complete SKILL.md content")
    resource_files: dict[str, str] = Field(
        default_factory=dict,
        description="Resource files keyed by relative path",
    )


class SkillImportRequest(SkillPackagePayload):
    """Schema for importing an AgentSkills.io package into a tenant/project library."""

    scope: str = Field("tenant", description="Skill scope: tenant or project")
    project_id: str | None = None
    overwrite: bool = Field(False, description="Update an existing skill with the same name")
    change_summary: str | None = Field(None, max_length=2000)


class SkillLifecycleResponse(BaseModel):
    """Schema for skill import and versioning responses."""

    action: str
    skill: SkillResponse
    version_number: int | None = None
    version_label: str | None = None


class SkillPackageResponse(SkillPackagePayload):
    """Schema for exported AgentSkills.io packages."""

    format: str = "agentskills.io/skill-package"
    skill: SkillResponse
    version_number: int | None = None
    version_label: str | None = None


# === Helper Functions ===


def skill_to_response(skill: Skill) -> SkillResponse:
    """Convert domain Skill to response model."""
    agentskills = _agentskills_metadata(skill)
    return SkillResponse(
        id=skill.id,
        tenant_id=skill.tenant_id,
        project_id=skill.project_id,
        name=skill.name,
        description=skill.description,
        tools=list(skill.tools),
        full_content=skill.full_content,
        status=skill.status.value,
        scope=skill.scope.value,
        is_system_skill=skill.is_system_skill,
        source=skill.source.value if getattr(skill, "source", None) else "database",
        file_path=getattr(skill, "file_path", None),
        created_at=skill.created_at.isoformat(),
        updated_at=skill.updated_at.isoformat(),
        metadata=skill.metadata,
        resource_files=dict(getattr(skill, "resource_files", {}) or {}),
        agent_modes=list(getattr(skill, "agent_modes", ["*"]) or ["*"]),
        license=getattr(skill, "license", None) or agentskills.get("license"),
        compatibility=getattr(skill, "compatibility", None) or agentskills.get("compatibility"),
        allowed_tools_raw=getattr(skill, "allowed_tools_raw", None)
        or agentskills.get("allowed_tools"),
        spec_version=str(
            getattr(skill, "spec_version", None) or agentskills.get("spec_version") or "1.0"
        ),
        current_version=getattr(skill, "current_version", 0),
        version_label=getattr(skill, "version_label", None),
    )


def _invalid_skill_request_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=_("Invalid skill request"),
    )


def _skill_version_not_found_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=_("Skill version not found"),
    )


def _normalize_tenant_id(tenant: str | dict[str, Any]) -> str:
    if isinstance(tenant, dict):
        value = tenant.get("tenant_id") or tenant.get("id")
        return str(value) if value else ""
    return tenant


def _agentskills_metadata(skill: Skill) -> dict[str, Any]:
    metadata = skill.metadata if isinstance(skill.metadata, dict) else {}
    agentskills = metadata.get("agentskills")
    return agentskills if isinstance(agentskills, dict) else {}


def _coerce_any_dict(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): item for key, item in value.items()}


def _merge_agentskills_metadata(
    metadata: dict[str, Any] | None,
    *,
    license_value: str | None = None,
    compatibility: str | None = None,
    allowed_tools_raw: str | None = None,
    spec_version: str | None = None,
    cleared_fields: set[str] | None = None,
) -> dict[str, Any] | None:
    merged = _coerce_any_dict(metadata)
    agentskills = _coerce_any_dict(merged.get("agentskills"))
    updates = {
        "license": license_value,
        "compatibility": compatibility,
        "allowed_tools": allowed_tools_raw,
        "spec_version": spec_version,
    }
    clear_keys = cleared_fields or set()
    for key, value in updates.items():
        if key in clear_keys:
            agentskills.pop(key, None)
        elif value is not None and value != "":
            agentskills[key] = value
    if agentskills:
        merged["agentskills"] = agentskills
    else:
        merged.pop("agentskills", None)
    return merged or None


def _model_fields_set(model: BaseModel) -> set[str]:
    fields_set = getattr(model, "model_fields_set", None)
    if fields_set is None:
        fields_set = getattr(model, "__fields_set__", set())
    if fields_set is None:
        return set()
    return set(fields_set)


def _cleared_agentskills_fields(data: SkillUpdate, fields_set: set[str]) -> set[str]:
    field_to_metadata_key = {
        "license": "license",
        "compatibility": "compatibility",
        "allowed_tools_raw": "allowed_tools",
        "spec_version": "spec_version",
    }
    return {
        metadata_key
        for field_name, metadata_key in field_to_metadata_key.items()
        if field_name in fields_set and not getattr(data, field_name)
    }


def _resolve_optional_update_value(
    *,
    data: SkillUpdate,
    field_name: str,
    fields_set: set[str],
    metadata_value: object | None,
    current_value: str | None,
) -> str | None:
    if field_name in fields_set:
        value = getattr(data, field_name)
        return str(value) if value else None
    return str(metadata_value) if metadata_value is not None else current_value


def _resolve_spec_version_update(
    *,
    data: SkillUpdate,
    fields_set: set[str],
    metadata_value: object | None,
    current_value: str,
) -> str:
    if "spec_version" in fields_set:
        return data.spec_version or "1.0"
    return str(metadata_value or current_value or "1.0")


def _validate_skill_scope(scope_value: str, project_id: str | None) -> SkillScope:
    try:
        scope = SkillScope(scope_value)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_("Invalid skill scope"),
        ) from None

    if scope == SkillScope.SYSTEM:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_("Cannot create system-level skills via API"),
        )
    if scope == SkillScope.PROJECT and not project_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_("project_id is required for project-scoped skills"),
        )
    return scope


def _skill_matches_search(skill: Skill, search: str | None) -> bool:
    if not search:
        return True
    query = search.lower().strip()
    if not query:
        return True
    metadata_text = json.dumps(skill.metadata or {}, ensure_ascii=False).lower()
    haystack = " ".join(
        [
            skill.name,
            skill.description,
            skill.version_label or "",
            skill.source.value if getattr(skill, "source", None) else "",
            getattr(skill, "file_path", None) or "",
            metadata_text,
        ]
    ).lower()
    return query in haystack


def _is_database_backed(skill: Skill) -> bool:
    return skill.source in {SkillSource.DATABASE, SkillSource.HYBRID}


def _safe_zip_member_path(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_("Invalid skill zip package"),
        )
    return path


def _resource_text_from_zip(content: bytes) -> str:
    return _resource_text_from_bytes(content)


def _resource_text_from_bytes(content: bytes) -> str:
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return "base64:" + b64encode(content).decode("ascii")


def _filesystem_skill_resource_files(skill: Skill) -> dict[str, str]:
    file_path = getattr(skill, "file_path", None)
    if not file_path:
        return dict(getattr(skill, "resource_files", {}) or {})

    skill_md_path = Path(file_path)
    skill_dir = skill_md_path.parent
    if not skill_dir.exists() or not skill_dir.is_dir():
        return dict(getattr(skill, "resource_files", {}) or {})

    resource_files: dict[str, str] = {}
    for path in sorted(skill_dir.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        relative_path = path.relative_to(skill_dir)
        if relative_path == Path("SKILL.md"):
            continue
        resource_files[relative_path.as_posix()] = _resource_text_from_bytes(path.read_bytes())
    return resource_files


def _is_ignored_zip_member(path: PurePosixPath) -> bool:
    return any(part == "__MACOSX" for part in path.parts) or path.name == ".DS_Store"


def _parse_skill_zip_package(content: bytes) -> tuple[str, dict[str, str]]:
    try:
        archive = zipfile.ZipFile(BytesIO(content))
    except zipfile.BadZipFile:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_("Invalid skill zip package"),
        ) from None

    with archive:
        file_infos = [
            info
            for info in archive.infolist()
            if not info.is_dir()
            and not _is_ignored_zip_member(_safe_zip_member_path(info.filename))
        ]
        skill_md_infos = [
            info for info in file_infos if _safe_zip_member_path(info.filename).name == "SKILL.md"
        ]
        if not skill_md_infos:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=_("Skill zip package must contain SKILL.md"),
            )
        if len(skill_md_infos) > 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=_("Skill zip package must contain exactly one SKILL.md"),
            )

        skill_md_info = skill_md_infos[0]
        skill_md_path = _safe_zip_member_path(skill_md_info.filename)
        skill_root = skill_md_path.parent
        try:
            skill_md_content = archive.read(skill_md_info).decode("utf-8")
        except UnicodeDecodeError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=_("SKILL.md must be UTF-8 text"),
            ) from None

        resource_files: dict[str, str] = {}
        for info in file_infos:
            path = _safe_zip_member_path(info.filename)
            if path == skill_md_path:
                continue
            try:
                relative_path = path.relative_to(skill_root) if str(skill_root) != "." else path
            except ValueError:
                continue
            if not relative_path.parts or relative_path.name == "":
                continue
            resource_files[str(relative_path)] = _resource_text_from_zip(archive.read(info))

        return skill_md_content, resource_files


async def _get_tenant_skill_or_404(
    repo: SkillRepositoryPort,
    skill_id: str,
    tenant_id: str,
    *,
    allow_system: bool = False,
) -> Skill:
    skill = await repo.get_by_id(skill_id)
    if not skill:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_("Skill not found"),
        )
    if not (allow_system and skill.is_system_skill) and skill.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_("Skill not found"),
        )
    return skill


async def _get_readable_skill_or_404(
    db: AsyncSession,
    repo: SkillRepositoryPort,
    skill_id: str,
    tenant_id: str,
    *,
    allow_system: bool = False,
) -> Skill:
    skill = await repo.get_by_id(skill_id)
    if skill:
        if not (allow_system and skill.is_system_skill) and skill.tenant_id != tenant_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=_("Skill not found"),
            )
        return skill

    from pathlib import Path

    from src.application.services.skill_service import SkillService

    skill_service = SkillService.create(
        skill_repository=repo,
        base_path=Path.cwd(),
        tenant_id=tenant_id,
        include_system=True,
    )
    candidates = await skill_service.list_available_skills(
        tenant_id=tenant_id,
        tier=3,
    )
    for candidate in candidates:
        if candidate.id == skill_id or candidate.name == skill_id:
            if not allow_system and candidate.is_system_skill:
                break
            return candidate

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=_("Skill not found"),
    )


async def _find_existing_skill(
    repo: SkillRepositoryPort,
    tenant_id: str,
    name: str,
    scope: SkillScope,
    project_id: str | None,
) -> Skill | None:
    if scope == SkillScope.PROJECT and project_id:
        project_skills = await repo.list_by_project(
            project_id=project_id,
            tenant_id=tenant_id,
            scope=SkillScope.PROJECT,
        )
        return next(
            (
                skill
                for skill in project_skills
                if skill.tenant_id == tenant_id and skill.name == name
            ),
            None,
        )
    return await repo.get_by_name(tenant_id=tenant_id, name=name, scope=scope)


async def _ensure_project_skill_access(
    db: AsyncSession,
    *,
    current_user: User,
    tenant_id: str,
    project_id: str,
    required_roles: Collection[str] | None = None,
) -> None:
    query = (
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
    if required_roles is not None:
        query = query.where(UserProject.role.in_(required_roles))

    result = await db.execute(refresh_select_statement(query))
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_("Project skill write access required")
            if required_roles is not None
            else _("Access denied"),
        )


async def _ensure_tenant_skill_write_access(
    db: AsyncSession,
    *,
    current_user: User,
    tenant_id: str,
) -> None:
    await require_tenant_access(
        db,
        cast(Any, current_user),
        tenant_id,
        require_admin=True,
    )


async def _ensure_skill_scope_write_access(
    db: AsyncSession,
    *,
    current_user: User,
    tenant_id: str,
    scope: SkillScope,
    project_id: str | None,
) -> None:
    if scope == SkillScope.PROJECT:
        if project_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=_("project_id is required for project-scoped skills"),
            )
        await _ensure_project_skill_access(
            db,
            current_user=current_user,
            tenant_id=tenant_id,
            project_id=project_id,
            required_roles=_PROJECT_SKILL_WRITE_ROLES,
        )
        return

    await _ensure_tenant_skill_write_access(
        db,
        current_user=current_user,
        tenant_id=tenant_id,
    )


async def _ensure_existing_skill_write_access(
    db: AsyncSession,
    *,
    current_user: User,
    tenant_id: str,
    skill: Skill,
) -> None:
    if skill.is_system_skill or skill.scope == SkillScope.SYSTEM:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_("Cannot modify system skills. Use tenant skill config to override instead."),
        )

    await _ensure_skill_scope_write_access(
        db,
        current_user=current_user,
        tenant_id=tenant_id,
        scope=skill.scope,
        project_id=skill.project_id,
    )


async def _accessible_skill_project_ids(
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


async def _ensure_existing_project_skill_access(
    db: AsyncSession,
    *,
    current_user: User,
    tenant_id: str,
    skill: Skill,
) -> None:
    if skill.scope != SkillScope.PROJECT or not skill.project_id:
        return
    await _ensure_project_skill_access(
        db,
        current_user=current_user,
        tenant_id=tenant_id,
        project_id=skill.project_id,
    )


def _extract_version_label_from_parsed(parsed: SkillMarkdown) -> str | None:
    if getattr(parsed, "version", None):
        return str(parsed.version)
    metadata = getattr(parsed, "metadata", {}) or {}
    version = metadata.get("version") if isinstance(metadata, dict) else None
    return str(version) if version is not None else None


def _parse_skill_package(skill_md_content: str) -> tuple[SkillMarkdown, dict[str, Any], list[str]]:
    validator = AgentSkillsValidator(strict=False)
    validation = validator.validate_content(skill_md_content)
    if not validation.is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_("Invalid Agent Skill package"),
        )

    parsed = MarkdownParser().parse(skill_md_content)
    tools = parsed.tools or parsed.allowed_tools or ["*"]
    metadata = dict(parsed.metadata or {})
    metadata["agentskills"] = {
        "license": parsed.license,
        "compatibility": parsed.compatibility,
        "allowed_tools": parsed.allowed_tools_raw,
        "validation": validation.to_dict(),
    }
    return parsed, metadata, tools


def _parsed_skill_payload(
    *,
    skill_md_content: str | None,
    name: str | None,
    description: str | None,
    tools: list[str] | None,
) -> ParsedSkillPayload:
    if not skill_md_content:
        return None, name, description, tools, None, None

    parsed, metadata, parsed_tools = _parse_skill_package(skill_md_content)
    if name is not None and name != parsed.name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_("Skill name must match SKILL.md frontmatter"),
        )
    if description is not None and description != parsed.description:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_("Skill description must match SKILL.md frontmatter"),
        )
    if tools is not None and tools != parsed_tools:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_("Skill tools must match SKILL.md allowed-tools"),
        )

    return (
        skill_md_content,
        parsed.name,
        parsed.description,
        parsed_tools,
        metadata,
        _extract_version_label_from_parsed(parsed),
    )


def _build_skill_md_from_payload(payload: dict[str, Any], version_label: str | None = None) -> str:
    name = str(payload.get("name") or "skill")
    description = str(payload.get("description") or "")
    tools = payload.get("tools") if isinstance(payload.get("tools"), list) else []
    metadata = _coerce_any_dict(payload.get("metadata"))
    agentskills = _coerce_any_dict(metadata.get("agentskills"))
    if version_label and "version" not in metadata:
        metadata["version"] = version_label

    frontmatter: dict[str, Any] = {
        "name": name,
        "description": description,
    }
    license_value = payload.get("license") or agentskills.get("license")
    compatibility = payload.get("compatibility") or agentskills.get("compatibility")
    allowed_tools_raw = payload.get("allowed_tools_raw") or agentskills.get("allowed_tools")
    if license_value:
        frontmatter["license"] = str(license_value)
    if compatibility:
        frontmatter["compatibility"] = str(compatibility)
    if allowed_tools_raw:
        frontmatter["allowed-tools"] = str(allowed_tools_raw)
    elif tools:
        frontmatter["allowed-tools"] = " ".join(str(tool) for tool in tools)
    if metadata:
        frontmatter["metadata"] = metadata

    body = str(payload.get("body") or "").strip()
    if not body:
        body = f"# {name}\n\n{description}".strip()

    yaml_text = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True).strip()
    return f"---\n{yaml_text}\n---\n\n{body}\n"


def _version_label_from_content(skill_md_content: str, fallback: str) -> str:
    try:
        parsed, _, _ = _parse_skill_package(skill_md_content)
        return _extract_version_label_from_parsed(parsed) or fallback
    except HTTPException:
        return fallback


async def _create_skill_version_snapshot(
    db: AsyncSession,
    repo: SkillRepositoryPort,
    skill: Skill,
    *,
    skill_md_content: str,
    resource_files: dict[str, str],
    change_summary: str | None,
    created_by: str,
) -> SkillVersion:
    from src.infrastructure.adapters.secondary.persistence.sql_skill_version_repository import (
        SqlSkillVersionRepository,
    )

    version_repo = SqlSkillVersionRepository(db)
    max_version = await version_repo.get_max_version_number(skill.id)
    next_version = max_version + 1
    version_label = _version_label_from_content(skill_md_content, str(next_version))
    skill.resource_files = dict(resource_files)
    version = SkillVersion(
        id=str(uuid.uuid4()),
        skill_id=skill.id,
        version_number=next_version,
        version_label=version_label,
        skill_md_content=skill_md_content,
        resource_files=resource_files,
        change_summary=change_summary or f"Version {next_version}",
        created_by=created_by,
    )
    await version_repo.create(version)

    skill.current_version = version.version_number
    skill.version_label = version.version_label
    skill.updated_at = datetime.now(UTC)
    await repo.update(skill)
    return version


# === API Endpoints ===


@router.post("/", response_model=SkillResponse, status_code=status.HTTP_201_CREATED)
async def create_skill(
    request: Request,
    data: SkillCreate,
    tenant_id: str = Depends(_get_selected_skill_tenant_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SkillResponse:
    """
    Create a new skill.

    Skills can be created at tenant or project level. System-level skills
    cannot be created via API (they are loaded from the builtin directory).
    """
    try:
        # Validate scope
        try:
            scope = SkillScope(data.scope)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=_("Invalid skill scope"),
            ) from None

        if scope == SkillScope.SYSTEM:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=_("Cannot create system-level skills via API"),
            )

        await _ensure_skill_scope_write_access(
            db,
            current_user=current_user,
            tenant_id=tenant_id,
            scope=scope,
            project_id=data.project_id,
        )

        container = get_container_with_db(request, db)
        repo = container.skill_repository()

        full_content, name, description, tools, package_metadata, version_label = (
            _parsed_skill_payload(
                skill_md_content=data.full_content,
                name=data.name,
                description=data.description,
                tools=data.tools,
            )
        )
        metadata = _merge_agentskills_metadata(
            package_metadata if package_metadata is not None else data.metadata,
            license_value=data.license,
            compatibility=data.compatibility,
            allowed_tools_raw=data.allowed_tools_raw,
            spec_version=data.spec_version,
        )
        existing = await _find_existing_skill(
            repo,
            tenant_id=tenant_id,
            name=name or data.name,
            scope=scope,
            project_id=data.project_id,
        )
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=_("Skill already exists"),
            )
        skill = Skill.create(
            tenant_id=tenant_id,
            name=name or data.name,
            description=description or data.description,
            tools=tools or data.tools,
            project_id=data.project_id,
            full_content=full_content,
            metadata=metadata,
            scope=scope,
            is_system_skill=False,
            license=data.license,
            compatibility=data.compatibility,
            allowed_tools_raw=data.allowed_tools_raw,
        )
        if package_metadata is not None:
            agentskills = metadata.get("agentskills", {}) if isinstance(metadata, dict) else {}
            skill.license = data.license or agentskills.get("license")
            skill.compatibility = data.compatibility or agentskills.get("compatibility")
            skill.allowed_tools_raw = data.allowed_tools_raw or agentskills.get("allowed_tools")
        if version_label:
            skill.version_label = version_label
        if data.spec_version:
            skill.spec_version = data.spec_version

        created_skill = await repo.create(skill)
        await db.commit()

        logger.info(f"Skill created: {created_skill.id} (scope: {scope.value})")
        return skill_to_response(created_skill)

    except HTTPException:
        raise
    except ValueError as e:
        raise _invalid_skill_request_error() from e


@router.get("/", response_model=SkillListResponse)
async def list_skills(
    request: Request,
    search_query: str | None = Query(
        None, alias="search", description="Search by name/description"
    ),
    q: str | None = Query(None, description="Alias for search"),
    status_filter: str | None = Query(None, alias="status", description="Filter by status"),
    scope_filter: str | None = Query(
        None, alias="scope", description="Filter by scope: system, tenant, project"
    ),
    project_id: str | None = Query(None, description="Filter project-scoped skills"),
    limit: int = Query(100, ge=1, le=500, description="Maximum results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    skip: int | None = Query(None, ge=0, description="Legacy offset alias"),
    tenant_id: str = Depends(_get_selected_skill_tenant_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SkillListResponse:
    """
    List all skills for the current tenant.

    Merges skills from both filesystem (SKILL.md) and database sources.
    Optionally filter by scope (system, tenant, project) and status.
    """
    from pathlib import Path

    from src.application.services.skill_service import SkillService

    container = get_container_with_db(request, db)
    skill_repo = container.skill_repository()

    skill_status = SkillStatus(status_filter) if status_filter else None
    skill_scope = SkillScope(scope_filter) if scope_filter else None

    if project_id:
        await _ensure_project_skill_access(
            db,
            current_user=current_user,
            tenant_id=tenant_id,
            project_id=project_id,
        )

    skill_service = SkillService.create(
        skill_repository=skill_repo,
        base_path=Path.cwd(),
        tenant_id=tenant_id,
        include_system=True,
    )

    skills = await skill_service.list_available_skills(
        tenant_id=tenant_id,
        project_id=project_id,
        tier=2,
        status=skill_status,
        scope=skill_scope,
    )

    search = search_query or q
    skills = [skill for skill in skills if _skill_matches_search(skill, search)]

    # Apply pagination
    total = len(skills)
    offset = skip if skip is not None else offset
    skills = skills[offset : offset + limit]

    return SkillListResponse(
        skills=[skill_to_response(s) for s in skills],
        total=total,
    )


@router.get("/{skill_id}", response_model=SkillResponse)
async def get_skill(
    request: Request,
    skill_id: str,
    tenant_id: str = Depends(_get_selected_skill_tenant_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SkillResponse:
    """
    Get a specific skill by ID.
    """
    container = get_container_with_db(request, db)
    repo = container.skill_repository()
    skill = await _get_readable_skill_or_404(
        db=db,
        repo=repo,
        skill_id=skill_id,
        tenant_id=tenant_id,
        allow_system=True,
    )
    await _ensure_existing_project_skill_access(
        db,
        current_user=current_user,
        tenant_id=tenant_id,
        skill=skill,
    )

    return skill_to_response(skill)


@router.put("/{skill_id}", response_model=SkillResponse)
async def update_skill(
    request: Request,
    skill_id: str,
    data: SkillUpdate,
    tenant_id: str = Depends(_get_selected_skill_tenant_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SkillResponse:
    """
    Update an existing skill.
    """
    container = get_container_with_db(request, db)
    repo = container.skill_repository()
    skill = await repo.get_by_id(skill_id)

    if not skill:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_("Skill not found"),
        )

    # Verify tenant access
    if skill.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_("Skill not found"),
        )
    await _ensure_existing_skill_write_access(
        db,
        current_user=current_user,
        tenant_id=tenant_id,
        skill=skill,
    )

    # Update fields
    from datetime import datetime

    full_content, name, description, tools, package_metadata, version_label = _parsed_skill_payload(
        skill_md_content=data.full_content,
        name=data.name,
        description=data.description,
        tools=data.tools,
    )
    fields_set = _model_fields_set(data)
    metadata = _merge_agentskills_metadata(
        package_metadata
        if package_metadata is not None
        else data.metadata
        if data.metadata is not None
        else skill.metadata,
        license_value=data.license,
        compatibility=data.compatibility,
        allowed_tools_raw=data.allowed_tools_raw,
        spec_version=data.spec_version,
        cleared_fields=_cleared_agentskills_fields(data, fields_set),
    )
    next_name = name or data.name or skill.name
    agentskills = metadata.get("agentskills", {}) if isinstance(metadata, dict) else {}
    next_license = _resolve_optional_update_value(
        data=data,
        field_name="license",
        fields_set=fields_set,
        metadata_value=agentskills.get("license"),
        current_value=skill.license,
    )
    next_compatibility = _resolve_optional_update_value(
        data=data,
        field_name="compatibility",
        fields_set=fields_set,
        metadata_value=agentskills.get("compatibility"),
        current_value=skill.compatibility,
    )
    next_allowed_tools_raw = _resolve_optional_update_value(
        data=data,
        field_name="allowed_tools_raw",
        fields_set=fields_set,
        metadata_value=agentskills.get("allowed_tools"),
        current_value=skill.allowed_tools_raw,
    )
    next_spec_version = _resolve_spec_version_update(
        data=data,
        fields_set=fields_set,
        metadata_value=agentskills.get("spec_version"),
        current_value=skill.spec_version,
    )
    if next_name != skill.name:
        existing = await _find_existing_skill(
            repo,
            tenant_id=tenant_id,
            name=next_name,
            scope=skill.scope,
            project_id=skill.project_id,
        )
        if existing and existing.id != skill.id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=_("Skill already exists"),
            )

    updated_skill = Skill(
        id=skill.id,
        tenant_id=skill.tenant_id,
        project_id=skill.project_id,  # project_id cannot be changed
        name=next_name,
        description=description or data.description or skill.description,
        tools=tools or data.tools or skill.tools,
        status=SkillStatus(data.status) if data.status else skill.status,
        created_at=skill.created_at,
        updated_at=datetime.now(UTC),
        metadata=metadata,
        source=skill.source,
        file_path=skill.file_path,
        full_content=full_content if full_content is not None else skill.full_content,
        resource_files=skill.resource_files,
        agent_modes=skill.agent_modes,
        scope=skill.scope,
        is_system_skill=skill.is_system_skill,
        license=next_license,
        compatibility=next_compatibility,
        allowed_tools_raw=next_allowed_tools_raw,
        allowed_tools_parsed=skill.allowed_tools_parsed,
        spec_version=next_spec_version,
        current_version=skill.current_version,
        version_label=version_label or skill.version_label,
    )

    result = await repo.update(updated_skill)
    await db.commit()

    logger.info(f"Skill updated: {skill_id}")
    return skill_to_response(result)


@router.delete("/{skill_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_skill(
    request: Request,
    skill_id: str,
    tenant_id: str = Depends(_get_selected_skill_tenant_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """
    Delete a skill.
    """
    container = get_container_with_db(request, db)
    repo = container.skill_repository()
    skill = await repo.get_by_id(skill_id)

    if not skill:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_("Skill not found"),
        )

    # Verify tenant access
    if skill.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_("Skill not found"),
        )
    await _ensure_existing_skill_write_access(
        db,
        current_user=current_user,
        tenant_id=tenant_id,
        skill=skill,
    )

    await repo.delete(skill_id)
    await db.commit()

    logger.info(f"Skill deleted: {skill_id}")


@router.patch("/{skill_id}/status")
async def update_skill_status(
    request: Request,
    skill_id: str,
    status_value: str = Query(..., alias="status", description="New status"),
    tenant_id: str = Depends(_get_selected_skill_tenant_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SkillResponse:
    """
    Update skill status (active, disabled, deprecated).
    """
    container = get_container_with_db(request, db)
    repo = container.skill_repository()
    skill = await repo.get_by_id(skill_id)

    if not skill:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_("Skill not found"),
        )

    # Verify tenant access
    if skill.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_("Skill not found"),
        )
    await _ensure_existing_skill_write_access(
        db,
        current_user=current_user,
        tenant_id=tenant_id,
        skill=skill,
    )

    try:
        new_status = SkillStatus(status_value)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_("Invalid skill status"),
        ) from None

    from datetime import datetime

    updated_skill = Skill(
        id=skill.id,
        tenant_id=skill.tenant_id,
        project_id=skill.project_id,
        name=skill.name,
        description=skill.description,
        tools=skill.tools,
        full_content=skill.full_content,
        status=new_status,
        created_at=skill.created_at,
        updated_at=datetime.now(UTC),
        metadata=skill.metadata,
        source=skill.source,
        file_path=skill.file_path,
        agent_modes=skill.agent_modes,
        scope=skill.scope,
        is_system_skill=skill.is_system_skill,
        license=skill.license,
        compatibility=skill.compatibility,
        allowed_tools_raw=skill.allowed_tools_raw,
        allowed_tools_parsed=skill.allowed_tools_parsed,
        spec_version=skill.spec_version,
        current_version=skill.current_version,
        version_label=skill.version_label,
    )

    result = await repo.update(updated_skill)
    await db.commit()

    logger.info(f"Skill status updated: {skill_id} -> {status_value}")
    return skill_to_response(result)


# === System Skills Endpoints ===


@router.get("/system/list", response_model=SkillListResponse)
async def list_system_skills(
    request: Request,
    status_filter: str | None = Query(None, alias="status", description="Filter by status"),
    tenant_id: str = Depends(_get_selected_skill_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> SkillListResponse:
    """
    List all system-level skills.

    System skills are built-in skills loaded from the filesystem.
    They can be disabled or overridden per tenant.
    """
    from pathlib import Path

    from src.application.services.skill_service import SkillService

    container = get_container_with_db(request, db)
    skill_repo = container.skill_repository()

    # Get the SkillService to load system skills from filesystem
    skill_service = SkillService.create(
        skill_repository=skill_repo,
        base_path=Path.cwd(),
        tenant_id=tenant_id,
        include_system=True,
    )

    skill_status = SkillStatus(status_filter) if status_filter else None
    skills = await skill_service.list_system_skills(tenant_id=tenant_id, tier=2)

    # Apply status filter if provided
    if skill_status:
        skills = [s for s in skills if s.status == skill_status]

    return SkillListResponse(
        skills=[skill_to_response(s) for s in skills],
        total=len(skills),
    )


# === Content Endpoints ===


class SkillContentResponse(BaseModel):
    """Schema for skill content response."""

    skill_id: str
    name: str
    full_content: str | None
    scope: str
    is_system_skill: bool


class SkillContentUpdate(BaseModel):
    """Schema for updating skill content."""

    full_content: str = Field(..., min_length=1, description="Full SKILL.md content")


@router.get("/{skill_id}/content", response_model=SkillContentResponse)
async def get_skill_content(
    request: Request,
    skill_id: str,
    tenant_id: str = Depends(_get_selected_skill_tenant_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SkillContentResponse:
    """
    Get the full content of a skill.

    Returns the complete SKILL.md content for editing.
    """
    container = get_container_with_db(request, db)
    repo = container.skill_repository()
    skill = await repo.get_by_id(skill_id)

    if not skill:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_("Skill not found"),
        )

    # Verify tenant access (system skills are accessible to all tenants)
    if not skill.is_system_skill and skill.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_("Skill not found"),
        )
    await _ensure_existing_project_skill_access(
        db,
        current_user=current_user,
        tenant_id=tenant_id,
        skill=skill,
    )

    return SkillContentResponse(
        skill_id=skill.id,
        name=skill.name,
        full_content=skill.full_content,
        scope=skill.scope.value,
        is_system_skill=skill.is_system_skill,
    )


@router.put("/{skill_id}/content", response_model=SkillResponse)
async def update_skill_content(
    request: Request,
    skill_id: str,
    data: SkillContentUpdate,
    tenant_id: str = Depends(_get_selected_skill_tenant_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SkillResponse:
    """
    Update the full content of a skill.

    System skills cannot be modified directly. Use tenant skill configs
    to override them instead.
    """
    container = get_container_with_db(request, db)
    repo = container.skill_repository()
    skill = await repo.get_by_id(skill_id)

    if not skill:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_("Skill not found"),
        )

    # Verify tenant access
    if skill.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_("Skill not found"),
        )
    await _ensure_existing_skill_write_access(
        db,
        current_user=current_user,
        tenant_id=tenant_id,
        skill=skill,
    )

    from datetime import datetime

    full_content, name, description, tools, package_metadata, version_label = _parsed_skill_payload(
        skill_md_content=data.full_content,
        name=None,
        description=None,
        tools=None,
    )
    assert full_content is not None
    metadata = _merge_agentskills_metadata(package_metadata)
    agentskills = metadata.get("agentskills", {}) if isinstance(metadata, dict) else {}
    if name != skill.name:
        existing = await _find_existing_skill(
            repo,
            tenant_id=tenant_id,
            name=name or skill.name,
            scope=skill.scope,
            project_id=skill.project_id,
        )
        if existing and existing.id != skill.id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=_("Skill already exists"),
            )

    # Update skill content
    updated_skill = Skill(
        id=skill.id,
        tenant_id=skill.tenant_id,
        project_id=skill.project_id,
        name=name or skill.name,
        description=description or skill.description,
        tools=tools or skill.tools,
        full_content=full_content,
        resource_files=skill.resource_files,
        status=skill.status,
        created_at=skill.created_at,
        updated_at=datetime.now(UTC),
        metadata=metadata or skill.metadata,
        source=skill.source,
        file_path=skill.file_path,
        agent_modes=skill.agent_modes,
        scope=skill.scope,
        is_system_skill=skill.is_system_skill,
        license=agentskills.get("license") or skill.license,
        compatibility=agentskills.get("compatibility") or skill.compatibility,
        allowed_tools_raw=agentskills.get("allowed_tools") or skill.allowed_tools_raw,
        allowed_tools_parsed=skill.allowed_tools_parsed,
        spec_version=agentskills.get("spec_version") or skill.spec_version,
        current_version=skill.current_version,
        version_label=version_label or skill.version_label,
    )

    result = await repo.update(updated_skill)
    result = await repo.get_by_id(result.id) or result
    await _create_skill_version_snapshot(
        db,
        repo,
        result,
        skill_md_content=full_content,
        resource_files=result.resource_files,
        change_summary="Manual content update",
        created_by="agent",
    )
    await db.commit()

    logger.info(f"Skill content updated: {skill_id}")
    updated_result = await repo.get_by_id(skill_id)
    return skill_to_response(updated_result or result)


# === Import / Export / Install / Upgrade Endpoints ===


@router.post(
    "/import",
    response_model=SkillLifecycleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Import an AgentSkills.io package",
)
async def import_skill_package(
    request: Request,
    data: SkillImportRequest,
    tenant_id: str = Depends(_get_selected_skill_tenant_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SkillLifecycleResponse:
    """Import SKILL.md plus resources into the tenant or project skill library."""
    scope = _validate_skill_scope(data.scope, data.project_id)
    parsed, metadata, tools = _parse_skill_package(data.skill_md_content)
    await _ensure_skill_scope_write_access(
        db,
        current_user=current_user,
        tenant_id=tenant_id,
        scope=scope,
        project_id=data.project_id,
    )

    container = get_container_with_db(request, db)
    repo = container.skill_repository()
    existing = await _find_existing_skill(
        repo,
        tenant_id=tenant_id,
        name=parsed.name,
        scope=scope,
        project_id=data.project_id,
    )
    if existing and not data.overwrite:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_("Skill already exists"),
        )

    version_label = _extract_version_label_from_parsed(parsed)
    if existing:
        existing.description = parsed.description
        existing.tools = tools
        existing.full_content = data.skill_md_content
        existing.resource_files = dict(data.resource_files)
        existing.metadata = metadata
        existing.license = parsed.license
        existing.compatibility = parsed.compatibility
        existing.allowed_tools_raw = parsed.allowed_tools_raw
        existing.updated_at = datetime.now(UTC)
        existing.version_label = version_label
        skill = await repo.update(existing)
        action = "update"
    else:
        skill = Skill.create(
            tenant_id=tenant_id,
            name=parsed.name,
            description=parsed.description,
            tools=tools,
            project_id=data.project_id,
            full_content=data.skill_md_content,
            resource_files=data.resource_files,
            metadata=metadata,
            scope=scope,
            is_system_skill=False,
            license=parsed.license,
            compatibility=parsed.compatibility,
            allowed_tools_raw=parsed.allowed_tools_raw,
        )
        skill.version_label = version_label
        skill = await repo.create(skill)
        action = "import"

    version = await _create_skill_version_snapshot(
        db,
        repo,
        skill,
        skill_md_content=data.skill_md_content,
        resource_files=data.resource_files,
        change_summary=data.change_summary,
        created_by="import",
    )
    await db.commit()

    return SkillLifecycleResponse(
        action=action,
        skill=skill_to_response(skill),
        version_number=version.version_number,
        version_label=version.version_label,
    )


@router.post(
    "/import/zip",
    response_model=SkillLifecycleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Import an AgentSkills.io zip package",
)
async def import_skill_zip_package(
    request: Request,
    archive: UploadFile = File(...),
    scope: str = Form("tenant"),
    project_id: str | None = Form(None),
    overwrite: bool = Form(False),
    change_summary: str | None = Form(None),
    tenant_id: str = Depends(_get_selected_skill_tenant_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SkillLifecycleResponse:
    """Import a zipped skill directory containing one SKILL.md plus bundled files."""
    if archive.filename and not archive.filename.lower().endswith(".zip"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_("Skill import file must be a .zip archive"),
        )

    skill_md_content, resource_files = _parse_skill_zip_package(await archive.read())
    return await import_skill_package(
        request=request,
        data=SkillImportRequest(
            skill_md_content=skill_md_content,
            resource_files=resource_files,
            scope=scope,
            project_id=project_id,
            overwrite=overwrite,
            change_summary=change_summary,
        ),
        tenant_id=tenant_id,
        current_user=current_user,
        db=db,
    )


@router.get(
    "/{skill_id}/export",
    response_model=SkillPackageResponse,
    summary="Export a skill as an AgentSkills.io package",
)
async def export_skill_package(
    request: Request,
    skill_id: str,
    tenant_id: str = Depends(_get_selected_skill_tenant_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SkillPackageResponse:
    """Export a skill's latest SKILL.md snapshot and bundled resource files."""
    from src.infrastructure.adapters.secondary.persistence.sql_skill_version_repository import (
        SqlSkillVersionRepository,
    )

    container = get_container_with_db(request, db)
    repo = container.skill_repository()
    skill = await _get_readable_skill_or_404(
        db=db,
        repo=repo,
        skill_id=skill_id,
        tenant_id=tenant_id,
        allow_system=True,
    )
    await _ensure_existing_project_skill_access(
        db,
        current_user=current_user,
        tenant_id=tenant_id,
        skill=skill,
    )

    version_repo = SqlSkillVersionRepository(db)
    version = await version_repo.get_latest(skill.id) if _is_database_backed(skill) else None
    skill_md_content = (
        version.skill_md_content
        if version is not None
        else skill.full_content
        or _build_skill_md_from_payload(skill.to_dict(), skill.version_label)
    )
    resource_files = (
        version.resource_files if version is not None else _filesystem_skill_resource_files(skill)
    )

    return SkillPackageResponse(
        skill=skill_to_response(skill),
        skill_md_content=skill_md_content,
        resource_files=resource_files,
        version_number=version.version_number if version is not None else None,
        version_label=version.version_label if version is not None else skill.version_label,
    )


# === Version History Endpoints ===


class SkillVersionResponse(BaseModel):
    """Schema for skill version response."""

    id: str
    skill_id: str
    version_number: int
    version_label: str | None
    change_summary: str | None
    created_by: str
    created_at: str


class SkillVersionDetailResponse(SkillVersionResponse):
    """Schema for skill version detail (includes content)."""

    skill_md_content: str
    resource_files: dict[str, Any] | None = None


class SkillVersionListResponse(BaseModel):
    """Schema for skill version list response."""

    versions: list[SkillVersionResponse]
    total: int


class SkillEvolutionJobResponse(BaseModel):
    """Schema for skill evolution job response."""

    id: str
    project_id: str | None = None
    skill_name: str
    action: str
    status: str
    rationale: str | None
    candidate_preview: str | None = None
    candidate_content: str | None = None
    blocked_by_review: bool = False
    session_ids: list[str]
    skill_version_id: str | None
    created_at: str
    applied_at: str | None


class SkillEvolutionRouteEntry(BaseModel):
    """A version or evolution job shown in the skill's evolution route."""

    kind: str
    id: str
    label: str
    project_id: str | None = None
    status: str | None = None
    action: str | None = None
    version_number: int | None = None
    version_label: str | None = None
    skill_version_id: str | None = None
    change_summary: str | None = None
    rationale: str | None = None
    candidate_preview: str | None = None
    created_by: str | None = None
    created_at: str


class SkillEvolutionTriggerResponse(BaseModel):
    """Describes when and how skill evolution runs."""

    capture_hook: str
    capture_timing: str
    scheduled_timing: str
    manual_trigger: str
    min_sessions_per_skill: int
    scoring_min_sessions_per_skill: int
    min_avg_score: float
    max_sessions_per_batch: int
    publish_mode: str
    auto_apply: bool
    enabled: bool


class SkillEvolutionConfigResponse(BaseModel):
    """Tenant skill evolution strategy config."""

    enabled: bool
    min_sessions_per_skill: int
    scoring_min_sessions_per_skill: int
    min_avg_score: float
    max_sessions_per_batch: int
    evolution_interval_minutes: int
    publish_mode: str
    auto_apply: bool


class SkillEvolutionConfigUpdateRequest(BaseModel):
    """Request schema for updating tenant skill evolution strategy config."""

    enabled: bool | None = None
    min_sessions_per_skill: int | None = Field(default=None, ge=1, le=100)
    scoring_min_sessions_per_skill: int | None = Field(default=None, ge=1, le=100)
    min_avg_score: float | None = Field(default=None, ge=0.0, le=1.0)
    max_sessions_per_batch: int | None = Field(default=None, ge=1, le=100)
    evolution_interval_minutes: int | None = Field(default=None, ge=1, le=10080)
    publish_mode: str | None = None
    auto_apply: bool | None = None


class SkillEvolutionMonitorResponse(BaseModel):
    """Operational status for the tenant-wide skill evolution loop."""

    refresh_interval_seconds: int
    latest_session_at: str | None
    latest_job_at: str | None
    backlog_count: int
    unscored_count: int
    blocked_by_review_count: int
    eligible_skill_count: int
    needs_attention: bool


class SkillEvolutionStageResponse(BaseModel):
    """One visible stage in the skill evolution pipeline."""

    id: str
    label: str
    status: str
    count: int
    backlog_count: int = 0
    detail: str


class SkillEvolutionOverviewResponse(BaseModel):
    """Global tenant overview for the skill evolution UI."""

    stats: SkillEvolutionOverviewStatsResponse
    monitor: SkillEvolutionMonitorResponse
    stages: list[SkillEvolutionStageResponse]
    skills: list[SkillEvolutionSkillSummaryResponse]
    recent_sessions: list[SkillEvolutionSessionResponse]
    recent_jobs: list[SkillEvolutionJobResponse]
    trigger: SkillEvolutionTriggerResponse


class SkillEvolutionDetailResponse(BaseModel):
    """Schema for skill evolution route and trigger details."""

    skill_id: str
    skill_name: str
    captured_session_count: int
    jobs: list[SkillEvolutionJobResponse]
    route: list[SkillEvolutionRouteEntry]
    trigger: SkillEvolutionTriggerResponse


class SkillEvolutionRunResponse(BaseModel):
    """Schema for manual evolution run result."""

    skill_id: str
    skill_name: str
    result: dict[str, Any]


class SkillEvolutionTenantRunResponse(BaseModel):
    """Schema for a tenant-wide manual evolution run result."""

    tenant_id: str
    result: dict[str, Any]


class SkillRollbackRequest(BaseModel):
    """Schema for skill rollback request."""

    version_number: int = Field(..., ge=1, description="Version number to rollback to")


def _evolution_job_to_response(job: Any) -> SkillEvolutionJobResponse:  # noqa: ANN401
    session_ids = job.session_ids if isinstance(job.session_ids, list) else []
    candidate_content = getattr(job, "candidate_content", None)
    candidate_text = candidate_content if isinstance(candidate_content, str) else None
    return SkillEvolutionJobResponse(
        id=job.id,
        project_id=getattr(job, "project_id", None),
        skill_name=job.skill_name,
        action=job.action,
        status=job.status,
        rationale=job.rationale,
        candidate_preview=(
            candidate_text[:500] if candidate_text is not None and candidate_text else None
        ),
        candidate_content=candidate_text,
        blocked_by_review=job.status == "pending_review",
        session_ids=[str(value) for value in session_ids],
        skill_version_id=job.skill_version_id,
        created_at=job.created_at.isoformat(),
        applied_at=job.applied_at.isoformat() if job.applied_at else None,
    )


def _evolution_session_to_response(session: Any) -> SkillEvolutionSessionResponse:  # noqa: ANN401
    return SkillEvolutionSessionResponse(
        id=session.id,
        skill_name=session.skill_name,
        conversation_id=session.conversation_id,
        project_id=session.project_id,
        user_query=session.user_query,
        summary=session.summary,
        judge_scores=session.judge_scores,
        overall_score=session.overall_score,
        success=session.success,
        execution_time_ms=session.execution_time_ms,
        tool_call_count=session.tool_call_count,
        processed=session.processed,
        created_at=session.created_at.isoformat(),
    )


def _int_response_field(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float, str)):
        return int(value)
    return 0


def _float_response_field(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float, str)):
        return float(value)
    return None


def _overview_stats_to_response(
    stats: Mapping[str, object],
) -> SkillEvolutionOverviewStatsResponse:
    return SkillEvolutionOverviewStatsResponse(
        total_sessions=_int_response_field(stats.get("total_sessions")),
        skill_sessions=_int_response_field(stats.get("skill_sessions")),
        no_skill_sessions=_int_response_field(stats.get("no_skill_sessions")),
        unprocessed_sessions=_int_response_field(stats.get("unprocessed_sessions")),
        processed_sessions=_int_response_field(stats.get("processed_sessions")),
        scored_sessions=_int_response_field(stats.get("scored_sessions")),
        successful_sessions=_int_response_field(stats.get("successful_sessions")),
        avg_score=_float_response_field(stats.get("avg_score")),
        total_jobs=_int_response_field(stats.get("total_jobs")),
        pending_jobs=_int_response_field(stats.get("pending_jobs")),
        applied_jobs=_int_response_field(stats.get("applied_jobs")),
        skipped_jobs=_int_response_field(stats.get("skipped_jobs")),
        rejected_jobs=_int_response_field(stats.get("rejected_jobs")),
    )


def _skill_summary_to_response(
    summary: Mapping[str, object],
) -> SkillEvolutionSkillSummaryResponse:
    latest_session_at = summary.get("latest_session_at")
    latest_job_at = summary.get("latest_job_at")
    return SkillEvolutionSkillSummaryResponse(
        skill_id=str(summary["skill_id"]) if summary.get("skill_id") else None,
        project_id=str(summary["project_id"]) if summary.get("project_id") else None,
        skill_name=str(summary.get("skill_name", "")),
        session_count=_int_response_field(summary.get("session_count")),
        success_count=_int_response_field(summary.get("success_count")),
        unprocessed_count=_int_response_field(summary.get("unprocessed_count")),
        scored_count=_int_response_field(summary.get("scored_count")),
        avg_score=_float_response_field(summary.get("avg_score")),
        latest_session_at=(
            latest_session_at.isoformat() if isinstance(latest_session_at, datetime) else None
        ),
        job_count=_int_response_field(summary.get("job_count")),
        pending_job_count=_int_response_field(summary.get("pending_job_count")),
        latest_job_at=(latest_job_at.isoformat() if isinstance(latest_job_at, datetime) else None),
    )


def _build_evolution_route(
    *,
    versions: list[SkillVersion],
    jobs: list[Any],
) -> list[SkillEvolutionRouteEntry]:
    entries: list[SkillEvolutionRouteEntry] = []
    for version in versions:
        entries.append(
            SkillEvolutionRouteEntry(
                kind="version",
                id=version.id,
                label=version.version_label or f"v{version.version_number}",
                version_number=version.version_number,
                version_label=version.version_label,
                change_summary=version.change_summary,
                created_by=version.created_by,
                created_at=version.created_at.isoformat(),
            )
        )
    for job in jobs:
        entries.append(
            SkillEvolutionRouteEntry(
                kind="evolution_job",
                id=job.id,
                label=f"{job.action}:{job.status}",
                project_id=getattr(job, "project_id", None),
                status=job.status,
                action=job.action,
                skill_version_id=job.skill_version_id,
                rationale=job.rationale,
                candidate_preview=(
                    job.candidate_content[:500]
                    if isinstance(job.candidate_content, str) and job.candidate_content
                    else None
                ),
                created_by="skill-evolution",
                created_at=job.created_at.isoformat(),
            )
        )
    return sorted(entries, key=lambda entry: entry.created_at, reverse=True)


def _skill_evolution_config_response(config: Any) -> SkillEvolutionConfigResponse:  # noqa: ANN401
    return SkillEvolutionConfigResponse(
        enabled=config.enabled,
        min_sessions_per_skill=config.min_sessions_per_skill,
        scoring_min_sessions_per_skill=config.scoring_min_sessions_per_skill,
        min_avg_score=config.min_avg_score,
        max_sessions_per_batch=config.max_sessions_per_batch,
        evolution_interval_minutes=config.evolution_interval_minutes,
        publish_mode=config.publish_mode,
        auto_apply=config.auto_apply,
    )


def _skill_evolution_trigger_response(
    skill_id: str,
    config: Any | None = None,  # noqa: ANN401
) -> SkillEvolutionTriggerResponse:
    from src.infrastructure.agent.plugins.skill_evolution.config import (
        SkillEvolutionConfig,
    )

    config = config or SkillEvolutionConfig.from_env()
    return SkillEvolutionTriggerResponse(
        capture_hook="after_turn_complete",
        capture_timing=(
            "After every agent turn completes, the plugin records matched skills, "
            "dynamically loaded skill_loader usage, conversation trajectory, tool calls, "
            "success, and latency."
        ),
        scheduled_timing=(
            f"Every {config.evolution_interval_minutes} minute(s), the scheduler "
            "summarizes, judges, aggregates, and evolves qualifying skill sessions."
        ),
        manual_trigger=(
            f"/api/v1/skills/{skill_id}/evolution/run"
            if skill_id
            else "/api/v1/skills/{skill_id}/evolution/run"
        ),
        min_sessions_per_skill=config.min_sessions_per_skill,
        scoring_min_sessions_per_skill=config.scoring_min_sessions_per_skill,
        min_avg_score=config.min_avg_score,
        max_sessions_per_batch=config.max_sessions_per_batch,
        publish_mode=config.publish_mode,
        auto_apply=config.auto_apply,
        enabled=config.enabled,
    )


async def _load_skill_evolution_config(db: AsyncSession, tenant_id: str) -> Any:  # noqa: ANN401
    from sqlalchemy.exc import SQLAlchemyError

    from src.infrastructure.adapters.secondary.persistence.plugin_config_repository import (
        PluginConfigRepository,
    )
    from src.infrastructure.agent.plugins.skill_evolution.config import (
        SkillEvolutionConfig,
    )

    base_config = SkillEvolutionConfig.from_env()
    try:
        row = await PluginConfigRepository(db).get_by_tenant_and_plugin(
            tenant_id=tenant_id,
            plugin_name="skill_evolution",
        )
    except (AttributeError, SQLAlchemyError):
        return base_config
    overrides = row.config if row is not None and isinstance(row.config, dict) else {}
    return base_config.with_overrides(overrides)


def _skill_evolution_config_payload(config: SkillEvolutionConfigUpdateRequest) -> dict[str, object]:
    payload = config.model_dump(exclude_unset=True)
    publish_mode = payload.get("publish_mode")
    if publish_mode is not None and publish_mode not in {"review", "direct"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_("Invalid skill evolution publish mode"),
        )
    return payload


def _skill_evolution_monitor_response(
    *,
    stats: SkillEvolutionOverviewStatsResponse,
    skill_summaries: list[SkillEvolutionSkillSummaryResponse],
    recent_sessions: list[Any],
    recent_jobs: list[Any],
    trigger: SkillEvolutionTriggerResponse,
) -> SkillEvolutionMonitorResponse:
    latest_session_at = recent_sessions[0].created_at.isoformat() if recent_sessions else None
    latest_job_at = recent_jobs[0].created_at.isoformat() if recent_jobs else None
    scorable_backlog_count = sum(
        summary.unprocessed_count
        for summary in skill_summaries
        if summary.skill_name != "__no_skill__"
        and summary.session_count >= trigger.scoring_min_sessions_per_skill
    )
    unscored_count = max(stats.processed_sessions - stats.scored_sessions, 0)
    eligible_skill_count = sum(
        1
        for summary in skill_summaries
        if summary.skill_name != "__no_skill__"
        and summary.session_count >= trigger.min_sessions_per_skill
        and summary.avg_score is not None
        and summary.avg_score >= trigger.min_avg_score
    )
    blocked_by_review_count = stats.pending_jobs
    return SkillEvolutionMonitorResponse(
        refresh_interval_seconds=15,
        latest_session_at=latest_session_at,
        latest_job_at=latest_job_at,
        backlog_count=scorable_backlog_count,
        unscored_count=unscored_count,
        blocked_by_review_count=blocked_by_review_count,
        eligible_skill_count=eligible_skill_count,
        needs_attention=scorable_backlog_count > 0
        or unscored_count > 0
        or blocked_by_review_count > 0,
    )


def _skill_evolution_stage_responses(
    *,
    stats: SkillEvolutionOverviewStatsResponse,
    monitor: SkillEvolutionMonitorResponse,
) -> list[SkillEvolutionStageResponse]:
    return [
        SkillEvolutionStageResponse(
            id="capture",
            label="capture",
            status="active" if stats.total_sessions else "waiting",
            count=stats.total_sessions,
            detail="Captured agent turns available for evolution.",
        ),
        SkillEvolutionStageResponse(
            id="summarize",
            label="summarize",
            status="waiting" if monitor.backlog_count else "complete",
            count=stats.processed_sessions,
            backlog_count=monitor.backlog_count,
            detail="Captured turns are summarized into comparable trajectories.",
        ),
        SkillEvolutionStageResponse(
            id="judge",
            label="judge",
            status="waiting" if monitor.unscored_count else "complete",
            count=stats.scored_sessions,
            backlog_count=monitor.unscored_count,
            detail="Summaries are judged and scored for evolution readiness.",
        ),
        SkillEvolutionStageResponse(
            id="review",
            label="review",
            status="blocked" if stats.pending_jobs else "complete",
            count=stats.pending_jobs,
            backlog_count=stats.pending_jobs,
            detail="Pending jobs require apply or reject before duplicate batches advance.",
        ),
        SkillEvolutionStageResponse(
            id="apply",
            label="apply",
            status="active" if stats.applied_jobs else "waiting",
            count=stats.applied_jobs,
            detail="Applied jobs create skill versions attributed to evolution.",
        ),
    ]


@router.get(
    "/evolution/config",
    response_model=SkillEvolutionConfigResponse,
    summary="Get skill evolution strategy config",
)
async def get_skill_evolution_config(
    db: AsyncSession = Depends(get_db),
    tenant: str | dict[str, Any] = Depends(_get_selected_skill_tenant_id),
) -> SkillEvolutionConfigResponse:
    """Return tenant skill evolution strategy config."""
    tenant_id = _normalize_tenant_id(tenant)
    config = await _load_skill_evolution_config(db, tenant_id)
    return _skill_evolution_config_response(config)


@router.put(
    "/evolution/config",
    response_model=SkillEvolutionConfigResponse,
    summary="Update skill evolution strategy config",
)
async def update_skill_evolution_config(
    payload: SkillEvolutionConfigUpdateRequest,
    db: AsyncSession = Depends(get_db),
    tenant: str | dict[str, Any] = Depends(_get_selected_skill_tenant_id),
    current_user: User = Depends(get_current_user),
) -> SkillEvolutionConfigResponse:
    """Persist tenant skill evolution strategy config."""
    from src.infrastructure.adapters.secondary.persistence.plugin_config_repository import (
        PluginConfigRepository,
    )

    tenant_id = _normalize_tenant_id(tenant)
    await _ensure_tenant_skill_write_access(
        db,
        current_user=current_user,
        tenant_id=tenant_id,
    )
    current = await _load_skill_evolution_config(db, tenant_id)
    next_config = current.with_overrides(_skill_evolution_config_payload(payload))
    await PluginConfigRepository(db).upsert(
        tenant_id=tenant_id,
        plugin_name="skill_evolution",
        config=_skill_evolution_config_response(next_config).model_dump(),
    )
    await db.commit()
    return _skill_evolution_config_response(next_config)


@router.get(
    "/evolution/overview",
    response_model=SkillEvolutionOverviewResponse,
    summary="Get skill evolution overview",
)
async def get_skill_evolution_overview(
    skill_limit: int = Query(50, ge=1, le=200),
    session_limit: int = Query(50, ge=1, le=200),
    job_limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    tenant: str | dict[str, Any] = Depends(_get_selected_skill_tenant_id),
    current_user: User = Depends(get_current_user),
) -> SkillEvolutionOverviewResponse:
    """Return tenant-wide evolution capture, scoring, and job state."""
    from src.infrastructure.agent.plugins.skill_evolution.repository import (
        SkillEvolutionRepository,
    )

    tenant_id = _normalize_tenant_id(tenant)
    repo = SkillEvolutionRepository(db)
    config = await _load_skill_evolution_config(db, tenant_id)
    accessible_project_ids = await _accessible_skill_project_ids(
        db,
        current_user=current_user,
        tenant_id=tenant_id,
    )
    stats = await repo.get_overview_stats(
        tenant_id=tenant_id,
        project_ids=accessible_project_ids,
    )
    skill_summaries = await repo.get_skill_session_summaries(
        tenant_id=tenant_id,
        project_ids=accessible_project_ids,
        limit=skill_limit,
    )
    recent_sessions = await repo.list_recent_sessions(
        tenant_id=tenant_id,
        project_ids=accessible_project_ids,
        limit=session_limit,
    )
    recent_jobs = await repo.list_jobs(
        tenant_id=tenant_id,
        project_ids=accessible_project_ids,
        limit=job_limit,
    )

    stats_response = _overview_stats_to_response(stats)
    skill_responses = [_skill_summary_to_response(summary) for summary in skill_summaries]
    trigger_response = _skill_evolution_trigger_response("", config=config)
    monitor_response = _skill_evolution_monitor_response(
        stats=stats_response,
        skill_summaries=skill_responses,
        recent_sessions=recent_sessions,
        recent_jobs=recent_jobs,
        trigger=trigger_response,
    )

    return SkillEvolutionOverviewResponse(
        stats=stats_response,
        monitor=monitor_response,
        stages=_skill_evolution_stage_responses(stats=stats_response, monitor=monitor_response),
        skills=skill_responses,
        recent_sessions=[_evolution_session_to_response(session) for session in recent_sessions],
        recent_jobs=[_evolution_job_to_response(job) for job in recent_jobs],
        trigger=trigger_response,
    )


@router.post(
    "/evolution/jobs/{job_id}/apply",
    response_model=SkillEvolutionJobResponse,
    summary="Apply a pending skill evolution job",
)
async def apply_skill_evolution_job(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    tenant: str | dict[str, Any] = Depends(_get_selected_skill_tenant_id),
    current_user: User = Depends(get_current_user),
) -> SkillEvolutionJobResponse:
    """Apply a pending evolution job and create a new SkillVersion."""
    from pathlib import Path

    from src.application.services.skill_service import SkillService
    from src.infrastructure.adapters.secondary.persistence.sql_skill_repository import (
        SqlSkillRepository,
    )
    from src.infrastructure.adapters.secondary.persistence.sql_skill_version_repository import (
        SqlSkillVersionRepository,
    )
    from src.infrastructure.agent.plugins.skill_evolution.repository import (
        SkillEvolutionRepository,
    )
    from src.infrastructure.agent.plugins.skill_evolution.skill_merger import (
        SkillMerger,
    )

    tenant_id = _normalize_tenant_id(tenant)
    evolution_repo = SkillEvolutionRepository(db)
    job = await evolution_repo.get_job(job_id)
    _validate_pending_evolution_job(job, tenant_id=tenant_id)
    assert job is not None

    skill_repo = SqlSkillRepository(db)
    await _ensure_evolution_job_write_access(
        db,
        job=job,
        current_user=current_user,
        tenant_id=tenant_id,
    )
    skill_version_repo = SqlSkillVersionRepository(db)
    skill_service = SkillService.create(
        skill_repository=skill_repo,
        base_path=Path.cwd(),
        tenant_id=tenant_id,
        include_system=True,
    )
    version_id = await SkillMerger(skill_service=skill_service).apply_evolution(
        job,
        tenant_id=tenant_id,
        project_id=getattr(job, "project_id", None),
        skill_repository=skill_repo,
        skill_version_repository=skill_version_repo,
    )
    if version_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_("Skill evolution job cannot be applied"),
        )

    await evolution_repo.update_job_status(
        job.id,
        status="applied",
        skill_version_id=version_id,
    )
    await db.commit()
    refreshed = await evolution_repo.get_job(job.id)
    return _evolution_job_to_response(refreshed or job)


@router.post(
    "/evolution/jobs/{job_id}/reject",
    response_model=SkillEvolutionJobResponse,
    summary="Reject a pending skill evolution job",
)
async def reject_skill_evolution_job(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    tenant: str | dict[str, Any] = Depends(_get_selected_skill_tenant_id),
    current_user: User = Depends(get_current_user),
) -> SkillEvolutionJobResponse:
    """Reject a pending evolution job without changing the target skill."""
    from src.infrastructure.agent.plugins.skill_evolution.repository import (
        SkillEvolutionRepository,
    )

    tenant_id = _normalize_tenant_id(tenant)
    evolution_repo = SkillEvolutionRepository(db)
    job = await evolution_repo.get_job(job_id)
    _validate_pending_evolution_job(job, tenant_id=tenant_id)
    assert job is not None
    await _ensure_evolution_job_write_access(
        db,
        job=job,
        current_user=current_user,
        tenant_id=tenant_id,
    )

    await evolution_repo.update_job_status(job.id, status="rejected")
    await db.commit()
    refreshed = await evolution_repo.get_job(job.id)
    return _evolution_job_to_response(refreshed or job)


def _validate_pending_evolution_job(job: Any, *, tenant_id: str) -> None:  # noqa: ANN401
    if job is None or job.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_("Skill evolution job not found"),
        )
    if job.status != "pending_review":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_("Skill evolution job is not pending review"),
        )


async def _ensure_evolution_job_write_access(
    db: AsyncSession,
    *,
    job: Any,  # noqa: ANN401
    current_user: User,
    tenant_id: str,
) -> None:
    project_id = getattr(job, "project_id", None)
    if project_id is None:
        await _ensure_tenant_skill_write_access(
            db,
            current_user=current_user,
            tenant_id=tenant_id,
        )
        return
    await _ensure_project_skill_access(
        db,
        current_user=current_user,
        tenant_id=tenant_id,
        project_id=str(project_id),
        required_roles=_PROJECT_SKILL_WRITE_ROLES,
    )


@router.post(
    "/evolution/run",
    response_model=SkillEvolutionTenantRunResponse,
    summary="Run tenant skill evolution now",
)
async def run_tenant_skill_evolution(
    request: Request,
    db: AsyncSession = Depends(get_db),
    tenant: str | dict[str, Any] = Depends(_get_selected_skill_tenant_id),
    current_user: User = Depends(get_current_user),
) -> SkillEvolutionTenantRunResponse:
    """Manually trigger one evolution cycle for the current tenant."""
    tenant_id = _normalize_tenant_id(tenant)
    await _ensure_tenant_skill_write_access(
        db,
        current_user=current_user,
        tenant_id=tenant_id,
    )
    container = get_container_with_db(request, db)
    plugin = container.skill_evolution_plugin()
    if plugin is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_("Skill evolution plugin is not available"),
        )

    result = plugin.schedule_evolution(
        tenant_id=tenant_id,
        project_id=None,
        skill_name=None,
    )
    return SkillEvolutionTenantRunResponse(
        tenant_id=tenant_id,
        result=result,
    )


@router.get(
    "/{skill_id}/evolution",
    response_model=SkillEvolutionDetailResponse,
    summary="Get skill evolution route",
)
async def get_skill_evolution(
    skill_id: str,
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    tenant: str | dict[str, Any] = Depends(_get_selected_skill_tenant_id),
    current_user: User = Depends(get_current_user),
) -> SkillEvolutionDetailResponse:
    """Return trigger metadata, evolution jobs, and version route for a skill."""
    from src.infrastructure.adapters.secondary.persistence.sql_skill_repository import (
        SqlSkillRepository,
    )
    from src.infrastructure.adapters.secondary.persistence.sql_skill_version_repository import (
        SqlSkillVersionRepository,
    )
    from src.infrastructure.agent.plugins.skill_evolution.repository import (
        SkillEvolutionRepository,
    )

    tenant_id = _normalize_tenant_id(tenant)
    config = await _load_skill_evolution_config(db, tenant_id)
    skill_repo = SqlSkillRepository(db)
    skill = await _get_tenant_skill_or_404(skill_repo, skill_id, tenant_id)
    await _ensure_existing_project_skill_access(
        db,
        current_user=current_user,
        tenant_id=tenant_id,
        skill=skill,
    )

    version_repo = SqlSkillVersionRepository(db)
    versions = await version_repo.list_by_skill(skill_id, limit=limit, offset=0)

    evolution_repo = SkillEvolutionRepository(db)
    jobs = await evolution_repo.list_jobs(
        tenant_id=tenant_id,
        skill_name=skill.name,
        project_id=skill.project_id,
        filter_project_id=True,
        limit=limit,
    )
    captured_session_count = await evolution_repo.count_sessions_by_skill(
        tenant_id=tenant_id,
        skill_name=skill.name,
        project_id=skill.project_id,
        filter_project_id=True,
    )

    return SkillEvolutionDetailResponse(
        skill_id=skill.id,
        skill_name=skill.name,
        captured_session_count=captured_session_count,
        jobs=[_evolution_job_to_response(job) for job in jobs],
        route=_build_evolution_route(versions=versions, jobs=jobs),
        trigger=_skill_evolution_trigger_response(skill_id, config=config),
    )


@router.post(
    "/{skill_id}/evolution/run",
    response_model=SkillEvolutionRunResponse,
    summary="Run skill evolution now",
)
async def run_skill_evolution(
    request: Request,
    skill_id: str,
    db: AsyncSession = Depends(get_db),
    tenant: str | dict[str, Any] = Depends(_get_selected_skill_tenant_id),
    current_user: User = Depends(get_current_user),
) -> SkillEvolutionRunResponse:
    """Manually trigger one evolution cycle scoped to a single skill."""
    from src.infrastructure.adapters.secondary.persistence.sql_skill_repository import (
        SqlSkillRepository,
    )

    tenant_id = _normalize_tenant_id(tenant)
    skill_repo = SqlSkillRepository(db)
    skill = await _get_tenant_skill_or_404(skill_repo, skill_id, tenant_id)
    if skill.is_system_skill or skill.scope == SkillScope.SYSTEM:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_("Skill evolution is only available for managed skills"),
        )
    await _ensure_existing_skill_write_access(
        db,
        current_user=current_user,
        tenant_id=tenant_id,
        skill=skill,
    )

    container = get_container_with_db(request, db)
    plugin = container.skill_evolution_plugin()
    if plugin is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_("Skill evolution plugin is not available"),
        )

    result = plugin.schedule_evolution(
        tenant_id=tenant_id,
        project_id=skill.project_id,
        skill_name=skill.name,
    )
    return SkillEvolutionRunResponse(
        skill_id=skill.id,
        skill_name=skill.name,
        result=result,
    )


@router.get(
    "/{skill_id}/versions",
    response_model=SkillVersionListResponse,
    summary="List skill versions",
)
async def list_skill_versions(
    skill_id: str,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    tenant: str | dict[str, Any] = Depends(_get_selected_skill_tenant_id),
    current_user: User = Depends(get_current_user),
) -> SkillVersionListResponse:
    """List all versions of a skill, ordered by version_number DESC."""
    from src.infrastructure.adapters.secondary.persistence.sql_skill_repository import (
        SqlSkillRepository,
    )
    from src.infrastructure.adapters.secondary.persistence.sql_skill_version_repository import (
        SqlSkillVersionRepository,
    )

    skill_repo = SqlSkillRepository(db)
    tenant_id = _normalize_tenant_id(tenant)
    skill = await _get_tenant_skill_or_404(skill_repo, skill_id, tenant_id)
    await _ensure_existing_project_skill_access(
        db,
        current_user=current_user,
        tenant_id=tenant_id,
        skill=skill,
    )

    version_repo = SqlSkillVersionRepository(db)
    versions = await version_repo.list_by_skill(skill_id, limit=limit, offset=offset)
    total = await version_repo.count_by_skill(skill_id)

    return SkillVersionListResponse(
        versions=[
            SkillVersionResponse(
                id=v.id,
                skill_id=v.skill_id,
                version_number=v.version_number,
                version_label=v.version_label,
                change_summary=v.change_summary,
                created_by=v.created_by,
                created_at=v.created_at.isoformat(),
            )
            for v in versions
        ],
        total=total,
    )


@router.get(
    "/{skill_id}/versions/{version_number}",
    response_model=SkillVersionDetailResponse,
    summary="Get skill version detail",
)
async def get_skill_version(
    skill_id: str,
    version_number: int,
    db: AsyncSession = Depends(get_db),
    tenant: str | dict[str, Any] = Depends(_get_selected_skill_tenant_id),
    current_user: User = Depends(get_current_user),
) -> SkillVersionDetailResponse:
    """Get a specific version of a skill including content and resource files."""
    from src.infrastructure.adapters.secondary.persistence.sql_skill_repository import (
        SqlSkillRepository,
    )
    from src.infrastructure.adapters.secondary.persistence.sql_skill_version_repository import (
        SqlSkillVersionRepository,
    )

    skill_repo = SqlSkillRepository(db)
    tenant_id = _normalize_tenant_id(tenant)
    skill = await _get_tenant_skill_or_404(skill_repo, skill_id, tenant_id)
    await _ensure_existing_project_skill_access(
        db,
        current_user=current_user,
        tenant_id=tenant_id,
        skill=skill,
    )

    version_repo = SqlSkillVersionRepository(db)
    version = await version_repo.get_by_version(skill_id, version_number)

    if not version:
        raise _skill_version_not_found_error()

    return SkillVersionDetailResponse(
        id=version.id,
        skill_id=version.skill_id,
        version_number=version.version_number,
        version_label=version.version_label,
        skill_md_content=version.skill_md_content,
        resource_files=version.resource_files,
        change_summary=version.change_summary,
        created_by=version.created_by,
        created_at=version.created_at.isoformat(),
    )


@router.post(
    "/{skill_id}/rollback",
    response_model=SkillResponse,
    summary="Rollback skill to a previous version",
)
async def rollback_skill(
    skill_id: str,
    request_body: SkillRollbackRequest,
    db: AsyncSession = Depends(get_db),
    tenant: str | dict[str, Any] = Depends(_get_selected_skill_tenant_id),
    current_user: User = Depends(get_current_user),
) -> SkillResponse:
    """Rollback a skill to a specific version. Creates a new version entry."""
    from pathlib import Path

    from src.application.services.skill_reverse_sync import SkillReverseSync
    from src.infrastructure.adapters.secondary.persistence.sql_skill_repository import (
        SqlSkillRepository,
    )
    from src.infrastructure.adapters.secondary.persistence.sql_skill_version_repository import (
        SqlSkillVersionRepository,
    )

    skill_repo = SqlSkillRepository(db)
    version_repo = SqlSkillVersionRepository(db)

    # Verify skill exists and belongs to tenant
    skill = await skill_repo.get_by_id(skill_id)
    if not skill:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_("Skill not found"),
        )

    tenant_id = _normalize_tenant_id(tenant)
    if skill.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_("Access denied"),
        )
    await _ensure_existing_skill_write_access(
        db,
        current_user=current_user,
        tenant_id=tenant_id,
        skill=skill,
    )

    reverse_sync = SkillReverseSync(
        skill_repository=skill_repo,
        skill_version_repository=version_repo,
        host_project_path=Path.cwd(),
    )

    result = await reverse_sync.rollback_to_version(
        skill_id=skill_id,
        version_number=request_body.version_number,
    )

    if "error" in result:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result["error"] or _("Skill rollback failed"),
        )

    await db.commit()

    # Return updated skill
    updated_skill = await skill_repo.get_by_id(skill_id)
    assert updated_skill is not None
    return skill_to_response(updated_skill)
