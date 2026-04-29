"""Captures skill-execution session data from agent pipeline events."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping
from typing import Any

from src.infrastructure.agent.plugins.skill_evolution.config import SkillEvolutionConfig
from src.infrastructure.agent.plugins.skill_evolution.models import (
    SkillEvolutionSession,
)

logger = logging.getLogger(__name__)

_NO_SKILL_KEY = "__no_skill__"


def _build_trajectory(
    conversation_context: list[dict[str, str]],
    user_message: str,
    final_content: str,
) -> dict[str, Any]:
    """Extract a lightweight tool-call trajectory from the conversation context.

    The trajectory includes user message, assistant responses, and any
    tool-call / tool-result pairs found in the context.
    """
    steps: list[dict[str, Any]] = []
    tool_call_count = 0

    for msg in conversation_context:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if role == "assistant" and content:
            steps.append({"type": "assistant", "content": str(content)[:2000]})
        elif role == "tool" or role == "function":
            steps.append(
                {
                    "type": "tool_result",
                    "name": msg.get("name", msg.get("tool_call_id", "")),
                    "content": str(content)[:2000],
                }
            )
            tool_call_count += 1

    return {
        "user_query": user_message[:2000],
        "final_response": final_content[:2000],
        "steps": steps,
        "tool_call_count": tool_call_count,
    }


class SessionCollector:
    """Collects skill session data when skills are executed.

    Designed to be called from the ``after_turn_complete`` plugin hook.
    Performs fire-and-forget persistence so it never blocks the main
    agent loop.
    """

    def __init__(self, config: SkillEvolutionConfig) -> None:
        self._config = config

    def build_session(
        self,
        *,
        tenant_id: str,
        project_id: str | None,
        conversation_id: str,
        user_message: str,
        final_content: str,
        matched_skill_name: str | None,
        conversation_context: list[dict[str, str]],
        success: bool,
        execution_time_ms: int = 0,
    ) -> SkillEvolutionSession | None:
        """Build a session entity from hook payload data.

        Returns ``None`` when there is nothing to record (no skill
        matched and config says to skip no-skill sessions).
        """
        skill_name = matched_skill_name or _NO_SKILL_KEY

        trajectory = _build_trajectory(
            conversation_context, user_message, final_content
        )

        return SkillEvolutionSession(
            id=f"evs-{uuid.uuid4().hex[:16]}",
            skill_name=skill_name,
            tenant_id=tenant_id,
            project_id=project_id,
            conversation_id=conversation_id,
            user_query=user_message[:2000],
            trajectory=trajectory,
            success=success,
            execution_time_ms=execution_time_ms,
            tool_call_count=trajectory["tool_call_count"],
            processed=False,
        )

    async def capture_from_hook(
        self,
        payload: Mapping[str, Any],
        *,
        session_factory: Any = None,  # noqa: ANN401
    ) -> None:
        """Extract skill session data from hook payload and persist.

        Called synchronously inside the hook handler; async DB write
        is spawned as a background task via ``session_factory``.
        """
        if not self._config.enabled:
            return

        matched_skill_name = payload.get("matched_skill_name")
        if isinstance(matched_skill_name, str):
            matched_skill_name = matched_skill_name.strip() or None

        session = self.build_session(
            tenant_id=str(payload.get("tenant_id", "")),
            project_id=_str_or_none(payload.get("project_id")),
            conversation_id=str(payload.get("conversation_id", "")),
            user_message=str(payload.get("user_message", "")),
            final_content=str(payload.get("final_content", "")),
            matched_skill_name=matched_skill_name,
            conversation_context=list(payload.get("conversation_context", [])),
            success=bool(payload.get("success", False)),
            execution_time_ms=int(payload.get("execution_time_ms", 0)),
        )

        if session is None:
            return

        if session_factory is not None:
            try:
                async with session_factory() as db:
                    repo = _get_repo(db)
                    await repo.save_session(session)
                    await db.commit()
            except Exception:
                logger.exception(
                    "Failed to persist skill evolution session %s", session.id
                )
        else:
            logger.debug(
                "Skill evolution session %s not persisted (no session_factory)",
                session.id,
            )


def _str_or_none(value: object) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def _get_repo(db: Any) -> Any:  # noqa: ANN401
    from src.infrastructure.agent.plugins.skill_evolution.repository import (
        SkillEvolutionRepository,
    )

    return SkillEvolutionRepository(db)
