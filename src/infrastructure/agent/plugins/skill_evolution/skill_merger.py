"""Applies evolution results to existing skills via the Skill service layer."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

import yaml

from src.domain.model.agent.skill import Skill, SkillScope
from src.domain.model.agent.skill.skill_version import SkillVersion

if TYPE_CHECKING:
    from src.application.services.skill_service import SkillService
    from src.domain.ports.repositories.skill_repository import SkillRepositoryPort
    from src.domain.ports.repositories.skill_version_repository import SkillVersionRepositoryPort
    from src.infrastructure.agent.plugins.skill_evolution.models import (
        SkillEvolutionJob,
    )

logger = logging.getLogger(__name__)


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
            logger.warning(
                "Skill '%s' not found — cannot apply evolution", job.skill_name
            )
            return None

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

        if job.action == "create_skill" and job.candidate_content:
            logger.info(
                "Skill creation requested for '%s' — manual review needed",
                job.skill_name,
            )

        return None

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
                    for skill in skills:
                        if skill.name == skill_name:
                            return skill
            skill = await skill_repository.get_by_name(tenant_id, skill_name)
            if skill is not None:
                return skill
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
