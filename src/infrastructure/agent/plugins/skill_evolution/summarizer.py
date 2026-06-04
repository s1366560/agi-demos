"""LLM-driven session summarization.

Compresses raw skill-evolution sessions into compact trajectories
and analytical summaries suitable for the evolution engine.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any, cast

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
        for session in sessions:
            try:
                await _enrich_sparse_trajectory_from_events(session, repo)
            except Exception:
                logger.exception(
                    "Failed to enrich skill evolution session %s before summarization",
                    session.id,
                )

        async def summarize_one(session: SkillEvolutionSession) -> tuple[str, dict[str, Any], str] | None:
            try:
                trajectory, summary_text = await self._summarize_one(session, llm_client)
                return session.id, trajectory, summary_text
            except Exception:
                logger.exception("Failed to summarize session %s", session.id)
                return None

        results = await _run_with_concurrency(
            [summarize_one(session) for session in sessions],
            limit=self._config.llm_concurrency,
            timeout_seconds=self._config.llm_timeout_seconds,
        )

        count = 0
        for result in results:
            if result is None:
                continue
            session_id, trajectory, summary_text = result
            try:
                await repo.update_summary(
                    session_id,
                    trajectory=trajectory,
                    summary=summary_text,
                )
                count += 1
            except Exception:
                logger.exception("Failed to persist summary for session %s", session_id)
        if count:
            logger.info("Summarized %d skill evolution sessions", count)
        return count

    async def _summarize_one(
        self,
        session: SkillEvolutionSession,
        llm_client: LLMClient,
    ) -> tuple[dict[str, Any], str]:
        raw_trajectory = session.trajectory or {}
        steps_json = json.dumps(raw_trajectory.get("steps", []), ensure_ascii=False)
        final_response = str(raw_trajectory.get("final_response", "")).strip()

        user_prompt = (
            f"Skill: {session.skill_name}\n"
            f"User query: {session.user_query[:1000]}\n"
            f"Success: {session.success}\n"
            f"Tool calls: {session.tool_call_count}\n"
            f"Execution time: {session.execution_time_ms}ms\n\n"
            f"Final response:\n{final_response[:2000]}\n\n"
            f"Raw trace steps:\n{steps_json}"
        )

        messages: list[Message] = [
            Message(role="system", content=_SUMMARIZE_SYSTEM_PROMPT),
            Message(role="user", content=user_prompt),
        ]

        response = await llm_client.generate(
            messages=messages,
            max_tokens=2048,
        )

        content = _extract_content(response)
        try:
            parsed = json.loads(_strip_json_payload(content))
        except json.JSONDecodeError:
            logger.warning(
                "Skill evolution summarizer received non-JSON response for session %s",
                session.id,
            )
            return _fallback_summary(session, raw_trajectory, content)

        parsed_trajectory = parsed.get("trajectory", raw_trajectory)
        if isinstance(parsed_trajectory, list):
            trajectory: dict[str, Any] = {"steps": parsed_trajectory}
        elif isinstance(parsed_trajectory, dict):
            trajectory = dict(parsed_trajectory)
        else:
            trajectory = dict(raw_trajectory)
        summary = parsed.get("summary", "")
        if final_response and not str(trajectory.get("final_response", "")).strip():
            trajectory["final_response"] = final_response[:2000]
        if raw_trajectory.get("trajectory_source") and not trajectory.get("trajectory_source"):
            trajectory["trajectory_source"] = raw_trajectory.get("trajectory_source")

        return trajectory, summary


async def _enrich_sparse_trajectory_from_events(
    session: SkillEvolutionSession,
    repo: SkillEvolutionRepository,
) -> None:
    raw_trajectory = session.trajectory if isinstance(session.trajectory, dict) else {}
    if not _needs_event_enrichment(raw_trajectory):
        return

    event_getter = getattr(repo, "get_conversation_trace_events", None)
    if not callable(event_getter):
        return
    typed_event_getter = cast(
        Callable[..., Awaitable[list[dict[str, object]]]],
        event_getter,
    )

    try:
        events = await typed_event_getter(conversation_id=session.conversation_id)
    except Exception:
        logger.exception(
            "Failed to enrich sparse skill evolution trajectory for session %s",
            session.id,
        )
        return

    steps, final_response, tool_call_count = _trajectory_from_events(events)
    if not steps and not final_response:
        return

    existing_steps = raw_trajectory.get("steps", [])
    should_replace_steps = not isinstance(existing_steps, list) or len(steps) > len(existing_steps)
    should_add_final_response = final_response and not str(
        raw_trajectory.get("final_response", "")
    ).strip()
    if not should_replace_steps and not should_add_final_response:
        return

    enriched = dict(raw_trajectory)
    if should_replace_steps:
        enriched["steps"] = steps
    if should_add_final_response:
        enriched["final_response"] = final_response[:2000]
    enriched["trajectory_source"] = "agent_execution_events"
    session.trajectory = enriched
    if tool_call_count > session.tool_call_count:
        session.tool_call_count = tool_call_count


def _is_sparse_trajectory(trajectory: dict[str, Any]) -> bool:
    steps = trajectory.get("steps", [])
    if not isinstance(steps, list) or len(steps) <= 1:
        return True
    tool_names = [
        str(step.get("tool") or step.get("name") or "")
        for step in steps
        if isinstance(step, dict)
    ]
    return bool(tool_names) and all(name == "skill_loader" for name in tool_names)


def _needs_event_enrichment(trajectory: dict[str, Any]) -> bool:
    return _is_sparse_trajectory(trajectory) or not str(
        trajectory.get("final_response", "")
    ).strip()


def _trajectory_from_events(
    events: list[dict[str, object]],
) -> tuple[list[dict[str, Any]], str, int]:
    steps: list[dict[str, Any]] = []
    final_response = ""
    tool_call_count = 0

    for event in events:
        event_type = str(event.get("event_type", ""))
        data = event.get("event_data")
        if not isinstance(data, dict):
            continue

        if event_type == "assistant_message":
            content = str(data.get("content") or "").strip()
            if content:
                steps.append({"type": "assistant", "content": content[:2000]})
                final_response = content
        elif event_type == "act":
            tool_name = str(data.get("tool_name") or "")
            if tool_name:
                steps.append(
                    {
                        "type": "tool_call",
                        "name": tool_name,
                        "status": data.get("status"),
                        "input": _short_json(data.get("tool_input")),
                    }
                )
                tool_call_count += 1
        elif event_type == "observe":
            tool_name = str(data.get("tool_name") or "")
            content = data.get("result", data.get("observation", ""))
            status = str(data.get("status") or "")
            steps.append(
                {
                    "type": "tool_result",
                    "name": tool_name,
                    "success": not bool(data.get("error")) and status != "failed",
                    "content": str(content)[:2000],
                    "error": data.get("error"),
                }
            )
        elif event_type == "complete":
            content = str(data.get("content") or data.get("result") or "").strip()
            if content:
                final_response = content
                steps.append({"type": "complete", "content": content[:2000]})
        elif event_type == "error":
            message = str(data.get("message") or data.get("error") or "").strip()
            steps.append({"type": "error", "content": message[:2000]})

    return steps[:80], final_response, tool_call_count


def _short_json(value: object) -> str:
    if value is None:
        return ""
    try:
        return json.dumps(value, ensure_ascii=False)[:1000]
    except TypeError:
        return str(value)[:1000]


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
                logger.warning("Skill evolution summarization timed out")
                return None

    return await asyncio.gather(*(run_one(coro) for coro in coros))


def _fallback_summary(
    session: SkillEvolutionSession,
    raw_trajectory: dict[str, Any],
    content: str,
) -> tuple[dict[str, Any], str]:
    trajectory = raw_trajectory if isinstance(raw_trajectory, dict) else {}
    final_response = str(trajectory.get("final_response", "")).strip()
    response_note = f" Final response: {final_response[:500]}" if final_response else ""
    content_note = f" Raw model response: {content[:300]}" if content else ""
    summary = (
        "Automatic fallback summary: the summarizer model did not return valid JSON. "
        f"User query: {session.user_query[:500]}.{response_note}{content_note}"
    )
    return trajectory, summary


def _extract_content(response: dict[str, Any]) -> str:
    """Extract text content from an LLM response dict."""
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
