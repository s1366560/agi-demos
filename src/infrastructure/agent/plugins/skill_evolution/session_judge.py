"""LLM-driven session quality scoring.

Evaluates skill-execution sessions across four dimensions to produce
a weighted overall quality score used for filtering before evolution.
"""

from __future__ import annotations

import asyncio
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
        async def judge_one(session: SkillEvolutionSession) -> tuple[str, dict[str, Any], float] | None:
            try:
                scores, overall = await self._judge_one(session, llm_client)
                return session.id, scores, overall
            except Exception:
                logger.exception("Failed to judge session %s", session.id)
                return None

        results = await _run_with_concurrency(
            [judge_one(session) for session in sessions],
            limit=self._config.llm_concurrency,
            timeout_seconds=self._config.llm_timeout_seconds,
        )

        count = 0
        for result in results:
            if result is None:
                continue
            session_id, scores, overall = result
            try:
                await repo.update_scores(
                    session_id,
                    judge_scores=scores,
                    overall_score=overall,
                )
                count += 1
            except Exception:
                logger.exception("Failed to persist score for session %s", session_id)
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
        final_response = str(trajectory.get("final_response", "")).strip()

        user_prompt = (
            f"Skill: {session.skill_name}\n"
            f"User query: {session.user_query[:1000]}\n"
            f"Success: {session.success}\n"
            f"Tool calls: {session.tool_call_count}\n"
            f"Execution time: {session.execution_time_ms}ms\n\n"
            f"Summary: {summary_text}\n\n"
            f"Final response:\n{final_response[:2000]}\n\n"
            f"Trajectory: {json.dumps(trajectory.get('steps', []), ensure_ascii=False)}"
        )

        messages: list[Message] = [
            Message(role="system", content=_JUDGE_SYSTEM_PROMPT),
            Message(role="user", content=user_prompt),
        ]

        response = await llm_client.generate(
            messages=messages,
            max_tokens=1024,
        )

        content = _extract_content(response)
        try:
            parsed = json.loads(_strip_json_payload(content))
        except json.JSONDecodeError:
            logger.warning(
                "Skill evolution judge received non-JSON response for session %s",
                session.id,
            )
            return _fallback_scores(session, content)

        scores: dict[str, Any] = {
            "task_completion": float(parsed.get("task_completion", 0.5)),
            "response_quality": float(parsed.get("response_quality", 0.5)),
            "efficiency": float(parsed.get("efficiency", 0.5)),
            "tool_usage": float(parsed.get("tool_usage", 0.5)),
            "rationale": str(parsed.get("rationale", "")),
        }

        overall = sum(float(scores[dim]) * weight for dim, weight in _DIMENSION_WEIGHTS.items())

        return scores, overall


def _fallback_scores(
    session: SkillEvolutionSession,
    content: str,
) -> tuple[dict[str, Any], float]:
    if session.success:
        scores: dict[str, Any] = {
            "task_completion": 0.65,
            "response_quality": 0.55,
            "efficiency": 0.50,
            "tool_usage": 0.55 if session.tool_call_count > 0 else 0.40,
            "rationale": (
                "Automatic fallback score: judge model did not return valid JSON; "
                "score derived conservatively from recorded success/tool metadata. "
                f"Raw model response: {content[:300]}"
            ),
        }
    else:
        scores = {
            "task_completion": 0.25,
            "response_quality": 0.25,
            "efficiency": 0.35,
            "tool_usage": 0.35 if session.tool_call_count > 0 else 0.20,
            "rationale": (
                "Automatic fallback score: judge model did not return valid JSON and "
                "the session was recorded as unsuccessful. "
                f"Raw model response: {content[:300]}"
            ),
        }

    overall = sum(float(scores[dim]) * weight for dim, weight in _DIMENSION_WEIGHTS.items())
    return scores, overall


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


async def _run_with_concurrency(
    coros: list[Any],
    *,
    limit: int,
    timeout_seconds: int,
) -> list[Any]:
    semaphore = asyncio.Semaphore(max(1, limit))

    async def run_one(coro: Any) -> Any:  # noqa: ANN401
        async with semaphore:
            try:
                return await asyncio.wait_for(coro, timeout=max(1, timeout_seconds))
            except TimeoutError:
                logger.warning("Skill evolution judging timed out")
                return None

    return await asyncio.gather(*(run_one(coro) for coro in coros))
