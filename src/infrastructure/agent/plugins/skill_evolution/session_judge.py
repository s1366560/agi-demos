"""LLM-driven session quality scoring.

Evaluates skill-execution sessions across four dimensions to produce
a weighted overall quality score used for filtering before evolution.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from src.domain.llm_providers.llm_types import LLMClient, Message
from src.infrastructure.agent.plugins.skill_evolution.config import SkillEvolutionConfig
from src.infrastructure.agent.plugins.skill_evolution.models import (
    SkillEvolutionSession,
)
from src.infrastructure.agent.plugins.skill_evolution.repository import (
    SkillEvolutionRepository,
)

logger = logging.getLogger(__name__)

_DIMENSION_WEIGHTS = {
    "task_completion": 0.55,
    "response_quality": 0.30,
    "efficiency": 0.05,
    "tool_usage": 0.10,
}

_JUDGE_SYSTEM_PROMPT = """You are a session quality judge. Evaluate the agent session and score it
on four dimensions (each 0.0-1.0):

1. task_completion (0.55): Did the agent complete the user's request?
2. response_quality (0.30): Was the final response helpful, accurate, and well-structured?
3. efficiency (0.05): Was the task completed with minimal unnecessary steps?
4. tool_usage (0.10): Were tools used appropriately and effectively?

Return ONLY valid JSON with no markdown fences:
{"task_completion": 0.8, "response_quality": 0.7, "efficiency": 0.9, "tool_usage": 0.85, "rationale": "Brief explanation"}"""


class SessionJudge:
    """Evaluates skill session quality using an LLM judge.

    Dimensions and weights follow the pattern established by SkillClaw's
    session_judge module, adapted for MemStack's LLM client.
    """

    def __init__(self, config: SkillEvolutionConfig) -> None:
        self._config = config
        self._model = config.llm_model or None

    async def judge_batch(
        self,
        sessions: list[SkillEvolutionSession],
        llm_client: LLMClient,
        repo: SkillEvolutionRepository,
    ) -> int:
        """Score a batch of sessions.

        Returns the number of sessions successfully scored.
        """
        count = 0
        for session in sessions:
            try:
                scores, overall = await self._judge_one(session, llm_client)
                await repo.update_scores(
                    session.id,
                    judge_scores=scores,
                    overall_score=overall,
                )
                count += 1
            except Exception:
                logger.exception(
                    "Failed to judge session %s", session.id
                )
        if count:
            logger.info("Judged %d skill evolution sessions", count)
        return count

    async def _judge_one(
        self,
        session: SkillEvolutionSession,
        llm_client: LLMClient,
    ) -> tuple[dict[str, Any], float]:
        summary_text = session.summary or ""
        trajectory = session.trajectory or {}

        user_prompt = (
            f"Skill: {session.skill_name}\n"
            f"User query: {session.user_query[:1000]}\n"
            f"Success: {session.success}\n"
            f"Tool calls: {session.tool_call_count}\n"
            f"Execution time: {session.execution_time_ms}ms\n\n"
            f"Summary: {summary_text}\n\n"
            f"Trajectory: {json.dumps(trajectory.get('steps', []), ensure_ascii=False)}"
        )

        messages: list[Message] = [
            Message(role="system", content=_JUDGE_SYSTEM_PROMPT),
            Message(role="user", content=user_prompt),
        ]

        response = await llm_client.generate(
            messages=messages,  # type: ignore[arg-type]
            max_tokens=1024,
        )

        content = _extract_content(response)
        parsed = json.loads(content)

        scores: dict[str, Any] = {
            "task_completion": float(parsed.get("task_completion", 0.5)),
            "response_quality": float(parsed.get("response_quality", 0.5)),
            "efficiency": float(parsed.get("efficiency", 0.5)),
            "tool_usage": float(parsed.get("tool_usage", 0.5)),
            "rationale": str(parsed.get("rationale", "")),
        }

        overall = sum(
            float(scores[dim]) * weight for dim, weight in _DIMENSION_WEIGHTS.items()
        )

        return scores, overall


def _extract_content(response: dict[str, Any]) -> str:
    choices = response.get("choices", [])
    if choices:
        msg = choices[0].get("message", {})
        return str(msg.get("content", ""))
    return str(response.get("content", ""))
