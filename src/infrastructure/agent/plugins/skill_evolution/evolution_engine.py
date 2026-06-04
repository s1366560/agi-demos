"""Core evolution decision engine.

For each skill group with sufficient session evidence, this engine
calls an LLM to decide one of four actions and, when appropriate,
produces improved SKILL.md content.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, cast

from src.domain.llm_providers.llm_types import LLMClient, Message
from src.infrastructure.agent.plugins.skill_evolution.models import SkillEvolutionJob

if TYPE_CHECKING:
    from src.application.services.skill_service import SkillService
    from src.domain.ports.repositories.skill_repository import SkillRepositoryPort
    from src.domain.ports.repositories.skill_version_repository import SkillVersionRepositoryPort
    from src.infrastructure.agent.plugins.skill_evolution.aggregation import (
        SkillSessionGroup,
    )
    from src.infrastructure.agent.plugins.skill_evolution.config import (
        SkillEvolutionConfig,
    )
    from src.infrastructure.agent.plugins.skill_evolution.repository import (
        SkillEvolutionRepository,
    )
    from src.infrastructure.agent.plugins.skill_evolution.skill_merger import (
        SkillMerger,
    )

logger = logging.getLogger(__name__)

_EVOLVE_SYSTEM_PROMPT = """You are a skill evolution specialist. Your job is to analyze real agent usage data
and improve SKILL.md files to make them more effective.

You will receive:
1. The current SKILL.md content for a skill, or a note that no managed skill exists yet
2. Session evidence: summaries of real agent sessions that used this skill, with quality scores

Based on the evidence, decide ONE of these actions:

- "create_skill": No managed skill exists yet, but the session evidence shows a reusable
  workflow worth preserving. Write a complete new SKILL.md.
- "improve_skill": The skill has issues (unclear instructions, missing edge cases, wrong tool choices).
  Rewrite the FULL SKILL.md to address the problems while preserving what works.
- "optimize_description": The skill content is good but the description/trigger patterns
  don't match what users actually need. Only update the description and trigger_patterns.
- "skip": The skill is working well and no changes are needed. This is the DEFAULT —
  only suggest changes when there is CLEAR evidence of problems.

Rules:
1. Be conservative. Only change what needs changing.
2. Preserve the original voice, structure, and formatting conventions.
3. If the evidence shows the skill works well, choose "skip".
4. Keep SKILL.md frontmatter (--- ... ---) intact unless changing description/triggers.
5. Never remove working instructions — only add or refine.
6. If no managed skill exists, choose either "create_skill" or "skip"; do not choose
   "improve_skill" or "optimize_description".

Return ONLY valid JSON (no markdown fences):
{
  "action": "create_skill" | "improve_skill" | "optimize_description" | "skip",
  "rationale": "Why this decision — cite specific session evidence",
  "skill_content": "Full SKILL.md content (for create_skill or improve_skill)",
  "description": "Updated description line (only for optimize_description)"
}"""


class EvolutionEngine:
    """Decides and executes skill evolution actions.

    For each skill group with sufficient evidence, calls an LLM to
    produce an evolution decision and candidate content, records the
    result as a ``SkillEvolutionJob``, and optionally applies it.
    """

    def __init__(
        self,
        config: SkillEvolutionConfig,
        skill_service: SkillService,
        merger: SkillMerger,
    ) -> None:
        self._config = config
        self._skill_service = skill_service
        self._merger = merger
        self.last_blocked_by_review_count = 0

    async def evolve_all(
        self,
        groups: dict[str, SkillSessionGroup],
        llm_client: LLMClient,
        repo: SkillEvolutionRepository,
        *,
        tenant_id: str,
        project_id: str | None = None,
        skill_repository: SkillRepositoryPort | None = None,
        skill_version_repository: SkillVersionRepositoryPort | None = None,
    ) -> list[SkillEvolutionJob]:
        """Run evolution for every skill group.

        Returns the list of created evolution jobs.
        """
        jobs: list[SkillEvolutionJob] = []
        self.last_blocked_by_review_count = 0
        existing_names = await self._existing_skill_names(
            tenant_id=tenant_id,
            skill_repository=skill_repository,
            fallback_names=set(groups.keys()),
        )

        for group in groups.values():
            try:
                session_ids = [s.id for s in group.sessions]
                existing_job = await _get_existing_job_for_sessions(
                    repo,
                    tenant_id=tenant_id,
                    skill_name=group.skill_name,
                    session_ids=session_ids,
                )
                if existing_job is not None:
                    if existing_job.status == "pending_review":
                        self.last_blocked_by_review_count += 1
                    logger.info(
                        "Skipping duplicate evolution job for '%s' (%d sessions, status=%s)",
                        group.skill_name,
                        len(session_ids),
                        existing_job.status,
                    )
                    continue

                job = await self._evolve_one(
                    group,
                    llm_client,
                    existing_names,
                    tenant_id=tenant_id,
                    skill_repository=skill_repository,
                )
                if job is not None:
                    await repo.save_job(job)
                    jobs.append(job)

                    if self._config.publish_mode == "direct" and self._config.auto_apply:
                        await self._apply_job(
                            job,
                            repo,
                            tenant_id=tenant_id,
                            project_id=project_id,
                            skill_repository=skill_repository,
                            skill_version_repository=skill_version_repository,
                        )
            except Exception:
                logger.exception("Evolution failed for skill '%s'", group.skill_name)

        if jobs:
            logger.info("Created %d evolution jobs", len(jobs))
        return jobs

    async def _evolve_one(
        self,
        group: SkillSessionGroup,
        llm_client: LLMClient,
        existing_skill_names: set[str],
        *,
        tenant_id: str,
        skill_repository: SkillRepositoryPort | None = None,
    ) -> SkillEvolutionJob | None:
        skill = await self._load_skill(
            group.skill_name, tenant_id=tenant_id, skill_repository=skill_repository
        )
        current_content = (
            skill.full_content
            if skill is not None
            else (
                "No managed or file-system SKILL.md exists for this skill name yet. "
                "Use action=create_skill only if the evidence supports a reusable workflow."
            )
        )

        evidence = self._build_evidence_text(group)
        existing_list = "\n".join(
            f"- {n}" for n in sorted(existing_skill_names) if n != group.skill_name
        )

        user_prompt = (
            f"Current SKILL.md for '{group.skill_name}':\n```markdown\n{current_content[:6000]}\n```\n\n"
            f"Session evidence ({group.session_count} sessions, "
            f"avg score {group.avg_score:.2f}, "
            f"success rate {group.success_rate:.1%}):\n{evidence}\n\n"
            f"Existing skill names (avoid conflicts):\n{existing_list}"
        )

        messages: list[Message] = [
            Message(role="system", content=_EVOLVE_SYSTEM_PROMPT),
            Message(role="user", content=user_prompt),
        ]

        response = await llm_client.generate(
            messages=messages,
            max_tokens=4096,
        )

        content = _extract_content(response)
        parsed = json.loads(_strip_json_payload(content))

        action = parsed.get("action", "skip")
        rationale = parsed.get("rationale", "")
        candidate_content = parsed.get("skill_content")
        description = parsed.get("description")

        if action == "optimize_description" and description:
            candidate_content = description

        session_ids = [s.id for s in group.sessions]
        job_status = "skipped" if action == "skip" else "pending_review"

        job = SkillEvolutionJob(
            id=f"evj-{uuid.uuid4().hex[:16]}",
            skill_name=group.skill_name,
            tenant_id=tenant_id,
            action=action,
            candidate_content=candidate_content,
            rationale=rationale,
            session_ids=session_ids,
            status=job_status,
        )

        logger.info(
            "Evolution decision for '%s': %s (rationale=%s)",
            group.skill_name,
            action,
            rationale[:120] if rationale else "",
        )
        return job

    async def _apply_job(
        self,
        job: SkillEvolutionJob,
        repo: SkillEvolutionRepository,
        *,
        tenant_id: str,
        project_id: str | None = None,
        skill_repository: SkillRepositoryPort | None = None,
        skill_version_repository: SkillVersionRepositoryPort | None = None,
    ) -> None:
        try:
            version_id = await self._merger.apply_evolution(
                job,
                tenant_id=tenant_id,
                project_id=project_id,
                skill_repository=skill_repository,
                skill_version_repository=skill_version_repository,
            )
            await repo.update_job_status(job.id, status="applied", skill_version_id=version_id)
        except Exception:
            logger.exception("Failed to apply evolution job %s", job.id)
            await repo.update_job_status(job.id, status="pending_review")

    async def _load_skill(
        self,
        skill_name: str,
        *,
        tenant_id: str,
        skill_repository: SkillRepositoryPort | None = None,
    ) -> Any:  # noqa: ANN401
        if skill_repository is not None:
            skill = await skill_repository.get_by_name(tenant_id, skill_name)
            if skill is not None:
                return skill
        return await self._skill_service.get_skill_by_name(
            tenant_id=tenant_id, skill_name=skill_name
        )

    async def _existing_skill_names(
        self,
        *,
        tenant_id: str,
        skill_repository: SkillRepositoryPort | None,
        fallback_names: set[str],
    ) -> set[str]:
        if skill_repository is None:
            return fallback_names
        try:
            skills = await skill_repository.list_by_tenant(tenant_id, limit=500)
        except Exception:
            logger.exception("Failed to list existing skill names for evolution")
            return fallback_names
        return {skill.name for skill in skills}

    @staticmethod
    def _build_evidence_text(group: SkillSessionGroup) -> str:
        parts: list[str] = []
        for i, s in enumerate(group.sessions[:20], 1):
            score = s.overall_score or 0.0
            status = "SUCCESS" if s.success else "FAILURE"
            parts.append(
                f"  [{i}] score={score:.2f} {status} | {s.user_query[:200]}\n"
                f"      summary: {(s.summary or 'N/A')[:300]}"
            )
        return "\n".join(parts)


def _extract_content(response: dict[str, Any]) -> str:
    choices = response.get("choices", [])
    if choices:
        msg = choices[0].get("message", {})
        return str(msg.get("content", ""))
    return str(response.get("content", ""))


def _strip_json_payload(content: str) -> str:
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    return text


async def _get_existing_job_for_sessions(
    repo: SkillEvolutionRepository,
    *,
    tenant_id: str,
    skill_name: str,
    session_ids: list[str],
) -> SkillEvolutionJob | None:
    method = getattr(repo, "get_job_for_sessions", None)
    if callable(method):
        typed_method = cast(
            Callable[..., Awaitable[SkillEvolutionJob | None]],
            method,
        )
        try:
            return await typed_method(
                tenant_id=tenant_id,
                skill_name=skill_name,
                session_ids=session_ids,
                excluded_statuses={"rejected"},
            )
        except TypeError:
            pass

    if await repo.has_job_for_sessions(
        tenant_id=tenant_id,
        skill_name=skill_name,
        session_ids=session_ids,
    ):
        return SkillEvolutionJob(
            id="existing",
            skill_name=skill_name,
            tenant_id=tenant_id,
            action="unknown",
            status="pending_review",
            session_ids=session_ids,
        )
    return None
