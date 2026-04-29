"""LLM-driven session summarization.

Compresses raw skill-evolution sessions into compact trajectories
and analytical summaries suitable for the evolution engine.
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

_SUMMARIZE_SYSTEM_PROMPT = """You are a session analyst. Given an agent session trace for a skill execution,
produce a compact JSON summary with two fields:

1. "trajectory": A concise step-by-step trace of what the agent did. Each step is
   { "step": N, "action": "...", "tool": "tool_name or null", "outcome": "success|error|partial" }.
   Include only significant actions (max 15 steps).

2. "summary": A 3-5 sentence analytical summary covering:
   - What was the user's goal?
   - How did the skill help or hinder?
   - What went well and what went wrong?
   - The final outcome.

Return ONLY valid JSON, no markdown fences or extra text.

Example output:
{"trajectory": [{"step": 1, "action": "Read the target file", "tool": "read_file", "outcome": "success"}], "summary": "The user wanted to..."}"""


class SessionSummarizer:
    """Summarizes raw session data using an LLM.

    Each session's conversation context is sent to the LLM to produce
    a structured trajectory and a narrative summary.
    """

    def __init__(self, config: SkillEvolutionConfig) -> None:
        self._config = config
        self._model = config.llm_model or None

    async def summarize_batch(
        self,
        sessions: list[SkillEvolutionSession],
        llm_client: LLMClient,
        repo: SkillEvolutionRepository,
    ) -> int:
        """Summarize a batch of sessions.

        Returns the number of sessions successfully summarized.
        """
        count = 0
        for session in sessions:
            try:
                trajectory, summary_text = await self._summarize_one(
                    session, llm_client
                )
                await repo.update_summary(
                    session.id,
                    trajectory=trajectory,
                    summary=summary_text,
                )
                count += 1
            except Exception:
                logger.exception(
                    "Failed to summarize session %s", session.id
                )
        if count:
            logger.info("Summarized %d skill evolution sessions", count)
        return count

    async def _summarize_one(
        self,
        session: SkillEvolutionSession,
        llm_client: LLMClient,
    ) -> tuple[dict[str, Any], str]:
        raw_trajectory = session.trajectory or {}
        steps_json = json.dumps(
            raw_trajectory.get("steps", []), ensure_ascii=False
        )

        user_prompt = (
            f"Skill: {session.skill_name}\n"
            f"User query: {session.user_query[:1000]}\n"
            f"Success: {session.success}\n"
            f"Tool calls: {session.tool_call_count}\n"
            f"Execution time: {session.execution_time_ms}ms\n\n"
            f"Raw trace steps:\n{steps_json}"
        )

        messages: list[Message] = [
            Message(role="system", content=_SUMMARIZE_SYSTEM_PROMPT),
            Message(role="user", content=user_prompt),
        ]

        response = await llm_client.generate(
            messages=messages,  # type: ignore[arg-type]
            max_tokens=2048,
        )

        content = _extract_content(response)
        parsed = json.loads(content)

        trajectory = parsed.get("trajectory", raw_trajectory)
        summary = parsed.get("summary", "")

        return trajectory, summary


def _extract_content(response: dict[str, Any]) -> str:
    """Extract text content from an LLM response dict."""
    choices = response.get("choices", [])
    if choices:
        msg = choices[0].get("message", {})
        return str(msg.get("content", ""))
    return str(response.get("content", ""))
