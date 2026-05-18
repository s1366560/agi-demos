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
from collections.abc import Mapping
from datetime import UTC, datetime
from io import BytesIO
from pathlib import PurePosixPath
from typing import Any

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
from sqlalchemy.ext.asyncio import AsyncSession

from src.configuration.di_container import DIContainer
from src.domain.model.agent.skill import Skill, SkillScope, SkillStatus
from src.domain.model.agent.skill.skill_version import SkillVersion
from src.domain.model.agent.skill_source import SkillSource
from src.domain.ports.repositories.skill_repository import SkillRepositoryPort
from src.infrastructure.adapters.primary.web.dependencies import get_current_user_tenant
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import CuratedSkill
from src.infrastructure.i18n import gettext as _
from src.infrastructure.skill.markdown_parser import MarkdownParser, SkillMarkdown
from src.infrastructure.skill.validator import AgentSkillsValidator


def get_container_with_db(request: Request, db: AsyncSession) -> DIContainer:
    """
    Get DI container with database session for the current request.
    """
    app_container = request.app.state.container
    return DIContainer(
        db=db,
        graph_service=app_container.graph_service,
        redis_client=app_container.redis_client,
    )


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/skills", tags=["Skills"])


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
    agent_modes: list[str] = Field(default_factory=lambda: ["*"])
    license: str | None = None
    compatibility: str | None = None
    allowed_tools_raw: str | None = None
    spec_version: str = "1.0"
    current_version: int = 0
    version_label: str | None = None
    # P2-4 curated lineage
    parent_curated_id: str | None = None
    semver: str | None = None
    revision_hash: str | None = None


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


class SkillInstallRequest(BaseModel):
    """Schema for installing an approved curated skill."""

    curated_id: str = Field(..., min_length=1)
    project_id: str | None = None
    overwrite: bool = Field(False, description="Update an existing skill with the same name")


class SkillUpgradeRequest(BaseModel):
    """Schema for upgrading an installed skill to a curated revision."""

    curated_id: str | None = Field(None, description="Specific curated revision to upgrade to")
    change_summary: str | None = Field(None, max_length=2000)


class SkillLifecycleResponse(BaseModel):
    """Schema for install/import/upgrade responses."""

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
        parent_curated_id=getattr(skill, "parent_curated_id", None),
        semver=getattr(skill, "semver", None),
        revision_hash=getattr(skill, "revision_hash", None),
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


def _coerce_string_dict(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): str(item) for key, item in value.items() if item is not None}


def _merge_agentskills_metadata(
    metadata: dict[str, Any] | None,
    *,
    license_value: str | None = None,
    compatibility: str | None = None,
    allowed_tools_raw: str | None = None,
    spec_version: str | None = None,
) -> dict[str, Any] | None:
    merged = _coerce_any_dict(metadata)
    agentskills = _coerce_any_dict(merged.get("agentskills"))
    updates = {
        "license": license_value,
        "compatibility": compatibility,
        "allowed_tools": allowed_tools_raw,
        "spec_version": spec_version,
    }
    for key, value in updates.items():
        if value is not None and value != "":
            agentskills[key] = value
    if agentskills:
        merged["agentskills"] = agentskills
    return merged or None


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
            skill.semver or "",
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
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return "base64:" + b64encode(content).decode("ascii")


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
            if not info.is_dir() and not _is_ignored_zip_member(_safe_zip_member_path(info.filename))
        ]
        skill_md_infos = [
            info
            for info in file_infos
            if _safe_zip_member_path(info.filename).name == "SKILL.md"
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
        project_skills = await repo.list_by_project(project_id=project_id, scope=SkillScope.PROJECT)
        return next(
            (skill for skill in project_skills if skill.tenant_id == tenant_id and skill.name == name),
            None,
        )
    return await repo.get_by_name(tenant_id=tenant_id, name=name, scope=scope)


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


def _build_skill_md_from_payload(payload: dict[str, Any], semver: str | None = None) -> str:
    name = str(payload.get("name") or "skill")
    description = str(payload.get("description") or "")
    tools = payload.get("tools") if isinstance(payload.get("tools"), list) else []
    metadata = _coerce_any_dict(payload.get("metadata"))
    agentskills = _coerce_any_dict(metadata.get("agentskills"))
    if semver and "version" not in metadata:
        metadata["version"] = semver

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


def _semver_key(value: str | None) -> tuple[int, int, int]:
    if not value:
        return (0, 0, 0)
    parts = value.split(".")
    parsed = []
    for index in range(3):
        try:
            parsed.append(int(parts[index]))
        except (IndexError, ValueError):
            parsed.append(0)
    return (parsed[0], parsed[1], parsed[2])


async def _latest_curated_for_skill(db: AsyncSession, skill: Skill) -> CuratedSkill | None:
    from sqlalchemy import select

    from src.infrastructure.adapters.secondary.common.base_repository import (
        refresh_select_statement,
    )
    source_skill_id: str | None = None
    if skill.parent_curated_id:
        parent = await db.get(CuratedSkill, skill.parent_curated_id)
        if parent is not None:
            source_skill_id = parent.source_skill_id

    stmt = select(CuratedSkill).where(CuratedSkill.status == "active")
    if source_skill_id:
        stmt = stmt.where(CuratedSkill.source_skill_id == source_skill_id)
    stmt = stmt.order_by(CuratedSkill.created_at.desc())
    candidates = (await db.execute(refresh_select_statement(stmt))).scalars().all()

    if not source_skill_id:
        candidates = [
            row
            for row in candidates
            if isinstance(row.payload, dict) and row.payload.get("name") == skill.name
        ]

    candidates = sorted(candidates, key=lambda row: _semver_key(row.semver), reverse=True)
    for candidate in candidates:
        if candidate.revision_hash != skill.revision_hash:
            return candidate
    return candidates[0] if candidates else None


# === API Endpoints ===


@router.post("/", response_model=SkillResponse, status_code=status.HTTP_201_CREATED)
async def create_skill(
    request: Request,
    data: SkillCreate,
    tenant_id: str = Depends(get_current_user_tenant),
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

        if scope == SkillScope.PROJECT and not data.project_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=_("project_id is required for project-scoped skills"),
            )

        container = get_container_with_db(request, db)

        # Create skill
        metadata = _merge_agentskills_metadata(
            data.metadata,
            license_value=data.license,
            compatibility=data.compatibility,
            allowed_tools_raw=data.allowed_tools_raw,
            spec_version=data.spec_version,
        )
        skill = Skill.create(
            tenant_id=tenant_id,
            name=data.name,
            description=data.description,
            tools=data.tools,
            project_id=data.project_id,
            full_content=data.full_content,
            metadata=metadata,
            scope=scope,
            is_system_skill=False,
            license=data.license,
            compatibility=data.compatibility,
            allowed_tools_raw=data.allowed_tools_raw,
        )
        if data.spec_version:
            skill.spec_version = data.spec_version

        repo = container.skill_repository()
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
    search_query: str | None = Query(None, alias="search", description="Search by name/description"),
    q: str | None = Query(None, description="Alias for search"),
    status_filter: str | None = Query(None, alias="status", description="Filter by status"),
    scope_filter: str | None = Query(
        None, alias="scope", description="Filter by scope: system, tenant, project"
    ),
    project_id: str | None = Query(None, description="Filter project-scoped skills"),
    limit: int = Query(100, ge=1, le=500, description="Maximum results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    skip: int | None = Query(None, ge=0, description="Legacy offset alias"),
    tenant_id: str = Depends(get_current_user_tenant),
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
    tenant_id: str = Depends(get_current_user_tenant),
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

    return skill_to_response(skill)


@router.put("/{skill_id}", response_model=SkillResponse)
async def update_skill(
    request: Request,
    skill_id: str,
    data: SkillUpdate,
    tenant_id: str = Depends(get_current_user_tenant),
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

    # Update fields
    from datetime import datetime

    metadata = _merge_agentskills_metadata(
        data.metadata if data.metadata is not None else skill.metadata,
        license_value=data.license,
        compatibility=data.compatibility,
        allowed_tools_raw=data.allowed_tools_raw,
        spec_version=data.spec_version,
    )

    updated_skill = Skill(
        id=skill.id,
        tenant_id=skill.tenant_id,
        project_id=skill.project_id,  # project_id cannot be changed
        name=data.name if data.name else skill.name,
        description=data.description if data.description else skill.description,
        tools=data.tools if data.tools else skill.tools,
        status=SkillStatus(data.status) if data.status else skill.status,
        created_at=skill.created_at,
        updated_at=datetime.now(UTC),
        metadata=metadata,
        source=skill.source,
        file_path=skill.file_path,
        full_content=data.full_content if data.full_content is not None else skill.full_content,
        agent_modes=skill.agent_modes,
        scope=skill.scope,
        is_system_skill=skill.is_system_skill,
        license=data.license if data.license is not None else skill.license,
        compatibility=data.compatibility if data.compatibility is not None else skill.compatibility,
        allowed_tools_raw=data.allowed_tools_raw
        if data.allowed_tools_raw is not None
        else skill.allowed_tools_raw,
        allowed_tools_parsed=skill.allowed_tools_parsed,
        spec_version=data.spec_version if data.spec_version is not None else skill.spec_version,
        current_version=skill.current_version,
        version_label=skill.version_label,
        parent_curated_id=skill.parent_curated_id,
        semver=skill.semver,
        revision_hash=skill.revision_hash,
    )

    result = await repo.update(updated_skill)
    await db.commit()

    logger.info(f"Skill updated: {skill_id}")
    return skill_to_response(result)


@router.delete("/{skill_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_skill(
    request: Request,
    skill_id: str,
    tenant_id: str = Depends(get_current_user_tenant),
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

    await repo.delete(skill_id)
    await db.commit()

    logger.info(f"Skill deleted: {skill_id}")


@router.patch("/{skill_id}/status")
async def update_skill_status(
    request: Request,
    skill_id: str,
    status_value: str = Query(..., alias="status", description="New status"),
    tenant_id: str = Depends(get_current_user_tenant),
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
        parent_curated_id=skill.parent_curated_id,
        semver=skill.semver,
        revision_hash=skill.revision_hash,
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
    tenant_id: str = Depends(get_current_user_tenant),
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
    tenant_id: str = Depends(get_current_user_tenant),
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
    tenant_id: str = Depends(get_current_user_tenant),
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

    # System skills cannot be modified
    if skill.is_system_skill:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_("Cannot modify system skills. Use tenant skill config to override instead."),
        )

    from datetime import datetime

    # Update skill content
    updated_skill = Skill(
        id=skill.id,
        tenant_id=skill.tenant_id,
        project_id=skill.project_id,
        name=skill.name,
        description=skill.description,
        tools=skill.tools,
        full_content=data.full_content,
        status=skill.status,
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
        parent_curated_id=skill.parent_curated_id,
        semver=skill.semver,
        revision_hash=skill.revision_hash,
    )

    result = await repo.update(updated_skill)
    await db.commit()

    logger.info(f"Skill content updated: {skill_id}")
    return skill_to_response(result)


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
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> SkillLifecycleResponse:
    """Import SKILL.md plus resources into the tenant or project skill library."""
    scope = _validate_skill_scope(data.scope, data.project_id)
    parsed, metadata, tools = _parse_skill_package(data.skill_md_content)

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
        existing.metadata = metadata
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
            metadata=metadata,
            scope=scope,
            is_system_skill=False,
            license=parsed.license,
            compatibility=parsed.compatibility,
            allowed_tools_raw=parsed.allowed_tools_raw,
        )
        skill.version_label = version_label
        skill.semver = version_label
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
    tenant_id: str = Depends(get_current_user_tenant),
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
    tenant_id: str = Depends(get_current_user_tenant),
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

    version_repo = SqlSkillVersionRepository(db)
    version = await version_repo.get_latest(skill.id) if _is_database_backed(skill) else None
    skill_md_content = (
        version.skill_md_content
        if version is not None
        else skill.full_content or _build_skill_md_from_payload(skill.to_dict(), skill.semver)
    )
    resource_files = version.resource_files if version is not None else {}

    return SkillPackageResponse(
        skill=skill_to_response(skill),
        skill_md_content=skill_md_content,
        resource_files=resource_files,
        version_number=version.version_number if version is not None else None,
        version_label=version.version_label if version is not None else skill.version_label,
    )


@router.post(
    "/install",
    response_model=SkillLifecycleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Install a curated skill into the private library",
)
async def install_curated_skill(
    request: Request,
    data: SkillInstallRequest,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> SkillLifecycleResponse:
    """Install an approved curated skill as a tenant or project skill."""
    curated = await db.get(CuratedSkill, data.curated_id)
    if curated is None or curated.status != "active":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_("Curated skill not found"),
        )

    payload = _coerce_any_dict(curated.payload)
    name = str(payload.get("name") or "")
    description = str(payload.get("description") or "")
    if not name or not description:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_("Invalid curated skill package"),
        )
    raw_tools = payload.get("tools")
    tools = [str(tool) for tool in raw_tools] if isinstance(raw_tools, list) else ["*"]
    metadata = _coerce_any_dict(payload.get("metadata"))
    metadata.update(
        {
            "installed_from_curated_id": curated.id,
            "curated_revision_hash": curated.revision_hash,
        }
    )
    scope = SkillScope.PROJECT if data.project_id else SkillScope.TENANT
    skill_md_content = str(
        payload.get("full_content") or _build_skill_md_from_payload(payload, curated.semver)
    )
    resource_files = _coerce_string_dict(payload.get("resource_files"))

    container = get_container_with_db(request, db)
    repo = container.skill_repository()
    existing = await _find_existing_skill(
        repo,
        tenant_id=tenant_id,
        name=name,
        scope=scope,
        project_id=data.project_id,
    )
    if existing and not data.overwrite:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_("Skill already exists"),
        )

    if existing:
        existing.description = description
        existing.tools = tools or ["*"]
        existing.full_content = skill_md_content
        existing.metadata = metadata
        existing.parent_curated_id = curated.id
        existing.semver = curated.semver
        existing.revision_hash = curated.revision_hash
        existing.version_label = curated.semver
        existing.updated_at = datetime.now(UTC)
        skill = await repo.update(existing)
        action = "update"
    else:
        skill = Skill.create(
            tenant_id=tenant_id,
            name=name,
            description=description,
            tools=tools or ["*"],
            project_id=data.project_id,
            full_content=skill_md_content,
            metadata=metadata,
            scope=scope,
            is_system_skill=False,
        )
        skill.parent_curated_id = curated.id
        skill.semver = curated.semver
        skill.revision_hash = curated.revision_hash
        skill.version_label = curated.semver
        skill = await repo.create(skill)
        action = "install"

    version = await _create_skill_version_snapshot(
        db,
        repo,
        skill,
        skill_md_content=skill_md_content,
        resource_files=resource_files,
        change_summary=f"Installed curated skill {curated.id}",
        created_by="install",
    )
    await db.commit()

    return SkillLifecycleResponse(
        action=action,
        skill=skill_to_response(skill),
        version_number=version.version_number,
        version_label=version.version_label,
    )


@router.post(
    "/{skill_id}/upgrade",
    response_model=SkillLifecycleResponse,
    summary="Upgrade an installed skill to a curated revision",
)
async def upgrade_skill(
    request: Request,
    skill_id: str,
    data: SkillUpgradeRequest,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> SkillLifecycleResponse:
    """Upgrade an installed skill from a specified or latest curated revision."""
    container = get_container_with_db(request, db)
    repo = container.skill_repository()
    skill = await _get_tenant_skill_or_404(repo, skill_id, tenant_id)

    curated = (
        await db.get(CuratedSkill, data.curated_id)
        if data.curated_id
        else await _latest_curated_for_skill(db, skill)
    )
    if curated is None or curated.status != "active":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_("Curated skill not found"),
        )
    if curated.revision_hash == skill.revision_hash:
        return SkillLifecycleResponse(action="noop", skill=skill_to_response(skill))

    payload = _coerce_any_dict(curated.payload)
    skill.name = str(payload.get("name") or skill.name)
    skill.description = str(payload.get("description") or skill.description)
    raw_tools = payload.get("tools")
    if isinstance(raw_tools, list):
        skill.tools = [str(tool) for tool in raw_tools] or ["*"]
    skill.full_content = str(
        payload.get("full_content") or _build_skill_md_from_payload(payload, curated.semver)
    )
    metadata = _coerce_any_dict(payload.get("metadata"))
    metadata.update(
        {
            "installed_from_curated_id": curated.id,
            "curated_revision_hash": curated.revision_hash,
        }
    )
    skill.metadata = metadata
    skill.parent_curated_id = curated.id
    skill.semver = curated.semver
    skill.revision_hash = curated.revision_hash
    skill.version_label = curated.semver
    skill.updated_at = datetime.now(UTC)
    skill = await repo.update(skill)

    resource_files = _coerce_string_dict(payload.get("resource_files"))
    version = await _create_skill_version_snapshot(
        db,
        repo,
        skill,
        skill_md_content=skill.full_content or _build_skill_md_from_payload(payload, curated.semver),
        resource_files=resource_files,
        change_summary=data.change_summary or f"Upgraded from curated skill {curated.id}",
        created_by="upgrade",
    )
    await db.commit()

    return SkillLifecycleResponse(
        action="upgrade",
        skill=skill_to_response(skill),
        version_number=version.version_number,
        version_label=version.version_label,
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


class SkillRollbackRequest(BaseModel):
    """Schema for skill rollback request."""

    version_number: int = Field(..., ge=1, description="Version number to rollback to")


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
    tenant: str | dict[str, Any] = Depends(get_current_user_tenant),
) -> SkillVersionListResponse:
    """List all versions of a skill, ordered by version_number DESC."""
    from src.infrastructure.adapters.secondary.persistence.sql_skill_repository import (
        SqlSkillRepository,
    )
    from src.infrastructure.adapters.secondary.persistence.sql_skill_version_repository import (
        SqlSkillVersionRepository,
    )

    skill_repo = SqlSkillRepository(db)
    await _get_tenant_skill_or_404(skill_repo, skill_id, _normalize_tenant_id(tenant))

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
    tenant: str | dict[str, Any] = Depends(get_current_user_tenant),
) -> SkillVersionDetailResponse:
    """Get a specific version of a skill including content and resource files."""
    from src.infrastructure.adapters.secondary.persistence.sql_skill_repository import (
        SqlSkillRepository,
    )
    from src.infrastructure.adapters.secondary.persistence.sql_skill_version_repository import (
        SqlSkillVersionRepository,
    )

    version_repo = SqlSkillVersionRepository(db)
    version = await version_repo.get_by_version(skill_id, version_number)

    if not version:
        raise _skill_version_not_found_error()

    skill_repo = SqlSkillRepository(db)
    await _get_tenant_skill_or_404(skill_repo, skill_id, _normalize_tenant_id(tenant))

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
    tenant: str | dict[str, Any] = Depends(get_current_user_tenant),
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
            detail=_("Skill rollback failed"),
        )

    await db.commit()

    # Return updated skill
    updated_skill = await skill_repo.get_by_id(skill_id)
    assert updated_skill is not None
    return skill_to_response(updated_skill)
