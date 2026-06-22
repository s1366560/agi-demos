"""Applies evolution results to existing skills via the Skill service layer."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

import yaml

from src.domain.model.agent.skill import Skill, SkillScope, SkillStatus
from src.domain.model.agent.skill.skill_version import SkillVersion
from src.infrastructure.skill.markdown_parser import MarkdownParseError, MarkdownParser
from src.infrastructure.skill.validator import AgentSkillsValidator, AllowedTool

if TYPE_CHECKING:
    from src.application.services.skill_service import SkillService
    from src.domain.ports.repositories.skill_repository import SkillRepositoryPort
    from src.domain.ports.repositories.skill_version_repository import SkillVersionRepositoryPort
    from src.infrastructure.agent.plugins.skill_evolution.models import (
        SkillEvolutionJob,
    )

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _ParsedSkillCandidate:
    name: str
    description: str
    tools: list[str]
    metadata: dict[str, Any]
    agent_modes: list[str]
    license: str | None
    compatibility: str | None
    allowed_tools_raw: str | None
    allowed_tools_parsed: list[AllowedTool]
    version_label: str | None


class SkillMerger:
    """Merges evolved skill content into an existing Skill.

    Creates a new SkillVersion to preserve history and updates the
    skill's content and trigger patterns in place.
    """

    def __init__(self, skill_service: SkillService) -> None:
        self._skill_service = skill_service

    async def apply_evolution(
        self,
        job: SkillEvolutionJob,
        *,
        tenant_id: str,
        project_id: str | None = None,
        skill_repository: SkillRepositoryPort | None = None,
        skill_version_repository: SkillVersionRepositoryPort | None = None,
    ) -> str | None:
        """Apply the evolution result from a job to the target skill.

        Returns the ID of the created SkillVersion, or None if the
        action is ``skip`` or the skill cannot be found.
        """
        if job.action == "skip":
            logger.info("Skipping evolution for skill '%s' (action=skip)", job.skill_name)
            return None

        if job.action == "create_skill" and job.candidate_content:
            try:
                return await self._persist_created_skill(
                    job,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    skill_repository=skill_repository,
                    skill_version_repository=skill_version_repository,
                )
            except Exception:
                logger.exception("Failed to create skill '%s' from evolution", job.skill_name)
                return None

        try:
            skill = await self._load_skill_for_apply(
                job.skill_name,
                tenant_id=tenant_id,
                project_id=project_id or getattr(job, "project_id", None),
                skill_repository=skill_repository,
            )
        except Exception:
            logger.exception("Failed to load skill '%s' for evolution", job.skill_name)
            return None

        if skill is None:
            logger.warning("Skill '%s' not found — cannot apply evolution", job.skill_name)
            return None

        return await self._apply_existing_skill_update(
            skill,
            job=job,
            tenant_id=tenant_id,
            project_id=project_id,
            skill_repository=skill_repository,
            skill_version_repository=skill_version_repository,
        )

    async def _apply_existing_skill_update(
        self,
        skill: Skill,
        *,
        job: SkillEvolutionJob,
        tenant_id: str,
        project_id: str | None,
        skill_repository: SkillRepositoryPort | None,
        skill_version_repository: SkillVersionRepositoryPort | None,
    ) -> str | None:
        if job.action == "optimize_description" and job.candidate_content:
            previous_version = skill.current_version
            updated_content = _replace_frontmatter_description(
                skill.full_content or "",
                job.candidate_content,
            )
            version_id = await self._persist_skill_update(
                skill,
                updated_content=updated_content,
                job=job,
                tenant_id=tenant_id,
                project_id=project_id,
                skill_repository=skill_repository,
                skill_version_repository=skill_version_repository,
            )
            logger.info(
                "Optimized description for skill '%s' (v%d -> v%d)",
                skill.name,
                previous_version,
                skill.current_version,
            )
            return version_id

        if job.action == "improve_skill" and job.candidate_content:
            previous_version = skill.current_version
            version_id = await self._persist_skill_update(
                skill,
                updated_content=job.candidate_content,
                job=job,
                tenant_id=tenant_id,
                project_id=project_id,
                skill_repository=skill_repository,
                skill_version_repository=skill_version_repository,
            )
            logger.info(
                "Improved skill '%s' (v%d -> v%d)",
                skill.name,
                previous_version,
                skill.current_version,
            )
            return version_id

        return None

    async def _persist_created_skill(
        self,
        job: SkillEvolutionJob,
        *,
        tenant_id: str,
        project_id: str | None,
        skill_repository: SkillRepositoryPort | None,
        skill_version_repository: SkillVersionRepositoryPort | None,
    ) -> str | None:
        if not job.candidate_content:
            return None

        parsed = _parse_skill_candidate(job.candidate_content)
        if parsed.name != job.skill_name:
            logger.warning(
                "Evolution create_skill candidate name '%s' does not match job skill '%s'",
                parsed.name,
                job.skill_name,
            )
            return None

        scope = SkillScope.PROJECT if project_id else SkillScope.TENANT
        if skill_repository is None or skill_version_repository is None:
            await self._skill_service.create_skill(
                tenant_id=tenant_id,
                name=parsed.name,
                description=parsed.description,
                tools=parsed.tools,
                project_id=project_id,
                full_content=job.candidate_content,
                scope=scope,
            )
            return None

        existing = await _find_database_skill(
            skill_repository,
            tenant_id=tenant_id,
            name=parsed.name,
            scope=scope,
            project_id=project_id,
        )
        if existing is not None:
            logger.warning(
                "Skill '%s' already exists in scope '%s' — cannot create from evolution",
                parsed.name,
                scope.value,
            )
            return None

        skill = Skill.create(
            tenant_id=tenant_id,
            name=parsed.name,
            description=parsed.description,
            tools=parsed.tools,
            project_id=project_id,
            full_content=job.candidate_content,
            metadata=parsed.metadata,
            agent_modes=parsed.agent_modes,
            scope=scope,
            is_system_skill=False,
            license=parsed.license,
            compatibility=parsed.compatibility,
            allowed_tools_raw=parsed.allowed_tools_raw,
            allowed_tools_parsed=list(parsed.allowed_tools_parsed),
        )
        skill.status = SkillStatus.ACTIVE
        skill.version_label = parsed.version_label
        created_skill = await skill_repository.create(skill)

        version = SkillVersion(
            id=str(uuid.uuid4()),
            skill_id=created_skill.id,
            version_number=1,
            version_label=parsed.version_label or "1",
            skill_md_content=job.candidate_content,
            resource_files={},
            change_summary=job.rationale or "Evolution create_skill",
            created_by="evolution",
        )
        await skill_version_repository.create(version)

        created_skill.current_version = version.version_number
        created_skill.version_label = version.version_label
        created_skill.updated_at = datetime.now(UTC)
        await skill_repository.update(created_skill)
        logger.info("Created skill '%s' from evolution job %s", parsed.name, job.id)
        return version.id

    async def _load_skill_for_apply(
        self,
        skill_name: str,
        *,
        tenant_id: str,
        project_id: str | None,
        skill_repository: SkillRepositoryPort | None,
    ) -> Skill | None:
        if skill_repository is not None:
            if project_id is not None:
                list_by_project = getattr(skill_repository, "list_by_project", None)
                if callable(list_by_project):
                    typed_list_by_project = cast(
                        Callable[..., Awaitable[list[Skill]]],
                        list_by_project,
                    )
                    skills = await typed_list_by_project(
                        project_id=project_id,
                        tenant_id=tenant_id,
                    )
                    for candidate in skills:
                        if candidate.name == skill_name:
                            return candidate
            repository_skill = await skill_repository.get_by_name(tenant_id, skill_name)
            if repository_skill is not None:
                return repository_skill
        return await self._skill_service.get_skill_by_name(
            tenant_id=tenant_id,
            skill_name=skill_name,
        )

    async def _persist_skill_update(
        self,
        skill: Skill,
        *,
        updated_content: str,
        job: SkillEvolutionJob,
        tenant_id: str,
        project_id: str | None,
        skill_repository: SkillRepositoryPort | None,
        skill_version_repository: SkillVersionRepositoryPort | None,
    ) -> str | None:
        if skill_repository is None or skill_version_repository is None:
            await self._skill_service.update_skill_content(
                skill.id,
                full_content=updated_content,
            )
            return None

        skill = await self._ensure_database_skill(
            skill,
            updated_content=updated_content,
            tenant_id=tenant_id,
            project_id=project_id,
            skill_repository=skill_repository,
        )

        max_version = await skill_version_repository.get_max_version_number(skill.id)
        next_version = max_version + 1
        version_label = str(next_version)
        version = SkillVersion(
            id=str(uuid.uuid4()),
            skill_id=skill.id,
            version_number=next_version,
            version_label=version_label,
            skill_md_content=updated_content,
            resource_files={},
            change_summary=job.rationale or f"Evolution {job.action}",
            created_by="evolution",
        )
        await skill_version_repository.create(version)

        skill.full_content = updated_content
        skill.current_version = version.version_number
        skill.version_label = version.version_label
        skill.updated_at = datetime.now(UTC)
        await skill_repository.update(skill)
        return version.id

    async def _ensure_database_skill(
        self,
        skill: Skill,
        *,
        updated_content: str,
        tenant_id: str,
        project_id: str | None,
        skill_repository: SkillRepositoryPort,
    ) -> Skill:
        existing: Skill | None = None
        if project_id is not None:
            list_by_project = getattr(skill_repository, "list_by_project", None)
            if callable(list_by_project):
                typed_list_by_project = cast(
                    Callable[..., Awaitable[list[Skill]]],
                    list_by_project,
                )
                skills = await typed_list_by_project(project_id=project_id, tenant_id=tenant_id)
                existing = next(
                    (candidate for candidate in skills if candidate.name == skill.name),
                    None,
                )
        if existing is None:
            existing = await skill_repository.get_by_name(tenant_id, skill.name)
        if existing is not None:
            return existing

        scope = SkillScope.PROJECT if project_id else SkillScope.TENANT
        metadata = {
            **(skill.metadata or {}),
            "evolution_imported_from": "filesystem",
            "source_skill_id": skill.id,
            "source_file_path": skill.file_path,
            "source_scope": skill.scope.value,
            "source_is_system_skill": skill.is_system_skill,
        }
        imported = Skill(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            project_id=project_id,
            name=skill.name,
            description=skill.description,
            tools=list(skill.tools),
            status=skill.status,
            metadata=metadata,
            source=skill.source,
            file_path=skill.file_path,
            full_content=skill.full_content or updated_content,
            agent_modes=list(skill.agent_modes),
            scope=scope,
            is_system_skill=False,
            license=skill.license,
            compatibility=skill.compatibility,
            allowed_tools_raw=skill.allowed_tools_raw,
            allowed_tools_parsed=list(skill.allowed_tools_parsed),
            spec_version=skill.spec_version,
            current_version=0,
        )
        await skill_repository.create(imported)
        return imported


def _replace_frontmatter_description(content: str, description: str) -> str:
    """Update only frontmatter description when a skill has YAML frontmatter."""
    if not content.startswith("---\n"):
        return content or description

    end = content.find("\n---", 4)
    if end == -1:
        return content or description

    frontmatter_text = content[4:end].strip()
    body = content[end + 4 :]
    try:
        frontmatter = yaml.safe_load(frontmatter_text) or {}
    except yaml.YAMLError:
        return content

    if not isinstance(frontmatter, dict):
        return content

    frontmatter["description"] = description
    yaml_text = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True).strip()
    return f"---\n{yaml_text}\n---{body}"


def _parse_skill_candidate(content: str) -> _ParsedSkillCandidate:
    validation = AgentSkillsValidator(strict=False).validate_content(content)
    if not validation.is_valid:
        raise ValueError("Invalid Agent Skill package")

    try:
        parsed = MarkdownParser().parse(content)
    except MarkdownParseError as exc:
        raise ValueError("Invalid SKILL.md candidate") from exc

    tools = parsed.tools or parsed.allowed_tools or ["*"]
    metadata = dict(parsed.metadata or {})
    metadata["agentskills"] = {
        "license": parsed.license,
        "compatibility": parsed.compatibility,
        "allowed_tools": parsed.allowed_tools_raw,
        "validation": validation.to_dict(),
    }
    allowed_tools_parsed = (
        AllowedTool.parse_many(parsed.allowed_tools_raw) if parsed.allowed_tools_raw else []
    )
    version_label = _extract_version_label(parsed.version, metadata)
    return _ParsedSkillCandidate(
        name=parsed.name,
        description=parsed.description,
        tools=tools,
        metadata=metadata,
        agent_modes=parsed.agent,
        license=parsed.license,
        compatibility=parsed.compatibility,
        allowed_tools_raw=parsed.allowed_tools_raw,
        allowed_tools_parsed=allowed_tools_parsed,
        version_label=version_label,
    )


def _extract_version_label(version: str | None, metadata: dict[str, Any]) -> str | None:
    if version:
        return str(version)
    metadata_version = metadata.get("version")
    return str(metadata_version) if metadata_version is not None else None


async def _find_database_skill(
    skill_repository: SkillRepositoryPort,
    *,
    tenant_id: str,
    name: str,
    scope: SkillScope,
    project_id: str | None,
) -> Skill | None:
    if scope == SkillScope.PROJECT and project_id:
        list_by_project = getattr(skill_repository, "list_by_project", None)
        if callable(list_by_project):
            typed_list_by_project = cast(
                Callable[..., Awaitable[list[Skill]]],
                list_by_project,
            )
            project_skills = await typed_list_by_project(
                project_id=project_id,
                tenant_id=tenant_id,
                scope=SkillScope.PROJECT,
            )
            return next((skill for skill in project_skills if skill.name == name), None)
    return await skill_repository.get_by_name(tenant_id, name, scope)
