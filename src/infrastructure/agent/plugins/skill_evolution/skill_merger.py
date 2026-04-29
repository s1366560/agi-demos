"""Applies evolution results to existing skills via the Skill service layer."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.application.services.skill_service import SkillService
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
    ) -> str | None:
        """Apply the evolution result from a job to the target skill.

        Returns the ID of the created SkillVersion, or None if the
        action is ``skip`` or the skill cannot be found.
        """
        if job.action == "skip":
            logger.info("Skipping evolution for skill '%s' (action=skip)", job.skill_name)
            return None

        try:
            skill = await self._skill_service.get_skill_by_name(
                tenant_id=tenant_id, skill_name=job.skill_name
            )
        except Exception:
            logger.exception(
                "Failed to load skill '%s' for evolution", job.skill_name
            )
            return None

        if skill is None:
            logger.warning(
                "Skill '%s' not found — cannot apply evolution", job.skill_name
            )
            return None

        if job.action == "optimize_description" and job.candidate_content:
            await self._skill_service.update_skill_content(
                skill.id,
                full_content=job.candidate_content,
            )
            logger.info(
                "Optimized description for skill '%s' (v%d -> v%d)",
                skill.name,
                skill.current_version,
                skill.current_version + 1,
            )
            return None

        if job.action == "improve_skill" and job.candidate_content:
            await self._skill_service.update_skill_content(
                skill.id,
                full_content=job.candidate_content,
            )
            logger.info(
                "Improved skill '%s' (v%d -> v%d)",
                skill.name,
                skill.current_version,
                skill.current_version + 1,
            )
            return None

        if job.action == "create_skill" and job.candidate_content:
            logger.info(
                "Skill creation requested for '%s' — manual review needed",
                job.skill_name,
            )

        return None
