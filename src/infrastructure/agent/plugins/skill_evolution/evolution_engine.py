"""Core evolution decision engine.

For each skill group with sufficient session evidence, this engine
calls an LLM to decide one of four actions and, when appropriate,
produces improved SKILL.md content.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import TYPE_CHECKING, Any

from src.domain.llm_providers.llm_types import LLMClient, Message

if TYPE_CHECKING:
    from src.application.services.skill_service import SkillService
    from src.infrastructure.agent.plugins.skill_evolution.aggregation import (
        SkillSessionGroup,
    )
    from src.infrastructure.agent.plugins.skill_evolution.config import (
        SkillEvolutionConfig,
    )
    from src.infrastructure.agent.plugins.skill_evolution.models import (
        SkillEvolutionJob,
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
1. The current SKILL.md content for a skill
2. Session evidence: summaries of real agent sessions that used this skill, with quality scores

Based on the evidence, decide ONE of these actions:

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

Return ONLY valid JSON (no markdown fences):
{
  "action": "improve_skill" | "optimize_description" | "skip",
  "rationale": "Why this decision — cite specific session evidence",
  "skill_content": "Full improved SKILL.md (only for improve_skill)",
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

    async def evolve_all(
        self,
        groups: dict[str, SkillSessionGroup],
        llm_client: LLMClient,
        repo: SkillEvolutionRepository,
        *,
        tenant_id: str,
        project_id: str | None = None,
    ) -> list[SkillEvolutionJob]:
        """Run evolution for every skill group.

        Returns the list of created evolution jobs.
        """
        jobs: list[SkillEvolutionJob] = []
        existing_names = set(groups.keys())

        for group in groups.values():
            try:
                job = await self._evolve_one(
                    group, llm_client, existing_names, tenant_id=tenant_id
                )
                if job is not None:
                    await repo.save_job(job)
                    jobs.append(job)

                    if self._config.publish_mode == "direct" and self._config.auto_apply:
                        await self._apply_job(job, repo, tenant_id=tenant_id, project_id=project_id)
            except Exception:
                logger.exception(
                    "Evolution failed for skill '%s'", group.skill_name
                )

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
    ) -> SkillEvolutionJob | None:
        skill = await self._load_skill(group.skill_name, tenant_id=tenant_id)
        current_content = skill.full_content or skill.prompt_template or ""

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
            messages=messages,  # type: ignore[arg-type]
            max_tokens=4096,
        )

        content = _extract_content(response)
        parsed = json.loads(content)

        action = parsed.get("action", "skip")
        rationale = parsed.get("rationale", "")
        candidate_content = parsed.get("skill_content")
        description = parsed.get("description")

        if action == "optimize_description" and description:
            candidate_content = description

        session_ids = [s.id for s in group.sessions]

        job = SkillEvolutionJob(
            id=f"evj-{uuid.uuid4().hex[:16]}",
            skill_name=group.skill_name,
            tenant_id=tenant_id,
            action=action,
            candidate_content=candidate_content,
            rationale=rationale,
            session_ids=session_ids,
            status="pending_review",
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
    ) -> None:
        try:
            version_id = await self._merger.apply_evolution(
                job, tenant_id=tenant_id, project_id=project_id
            )
            await repo.update_job_status(
                job.id, status="applied", skill_version_id=version_id
            )
        except Exception:
            logger.exception("Failed to apply evolution job %s", job.id)
            await repo.update_job_status(job.id, status="pending_review")

    async def _load_skill(self, skill_name: str, *, tenant_id: str) -> Any:  # noqa: ANN401
        return await self._skill_service.get_skill_by_name(
            tenant_id=tenant_id, skill_name=skill_name
        )

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
