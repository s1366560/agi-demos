"""LLM-backed Reflector adapter implementing ``ReflectorPort``.

Distilled from routa's `flow-analyst.yaml` specialist prompt. Wraps an
arbitrary LLM completion callable, sends a structured friction +
playbooks payload, and parses the JSON response into
``ReflectionVerdict`` values.

Per Agent-First: the verdict (CREATE / REINFORCE / DEPRECATE / NOOP) comes
from the LLM call. We only do *parsing* and *structural validation* in
this adapter — we never invent verdicts ourselves.

The adapter accepts a minimal ``LLMCompletion`` protocol rather than the
full ``LiteLLMClient`` so it stays unit-testable without a network.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Protocol

from src.domain.model.flow.friction_signal import FrictionSignal
from src.domain.model.flow.playbook import Playbook
from src.domain.model.flow.reflection_verdict import ReflectionAction, ReflectionVerdict
from src.domain.ports.services.reflector_port import ReflectorPort

logger = logging.getLogger(__name__)


class LLMCompletion(Protocol):
    """Minimal interface required by ``LLMReflector``.

    Any client that takes a list of OpenAI-style messages and returns a
    dict with a ``content`` string can be supplied. ``LiteLLMClient.generate``
    matches this signature.
    """

    async def __call__(
        self, *, messages: list[dict[str, str]], response_format: dict[str, str] | None = None
    ) -> dict[str, Any]: ...


_SYSTEM_PROMPT = """You are the Flow Reflector for an AI agent platform.

You analyze a window of friction signals (bounces, retries, aborts, timeouts,
gate blocks) and the project's existing playbooks. You then emit a JSON
array of verdicts describing what the playbook library should do next.

# Verdict actions
- "create": propose a new playbook. Required fields: name, trigger.description,
  steps (each with order + instruction).
- "reinforce": one of the existing playbooks helped — bump its hit_count
  and re-activate it. Required: playbook_id.
- "deprecate": one of the existing playbooks is now harmful or obsolete.
  Required: playbook_id.
- "noop": you have no actionable verdict. Return an empty array instead.

# Output contract
Return ONLY a JSON object of the shape:
{
  "verdicts": [
    {
      "action": "create" | "reinforce" | "deprecate",
      "playbook_id": "..." | null,
      "rationale": "...",
      "proposed_playbook": {                  // CREATE only
        "name": "...",
        "trigger": { "description": "..." },
        "steps": [ { "order": 1, "instruction": "..." }, ... ]
      }
    }
  ]
}

# Constraints
- Maximum 5 verdicts.
- Do not include free-text outside the JSON.
- Skip any verdict you cannot justify with concrete evidence from the signals.
"""


class LLMReflector(ReflectorPort):
    """Default ``ReflectorPort`` adapter — calls an LLM with a JSON contract."""

    def __init__(
        self,
        *,
        completion: LLMCompletion,
        max_signals: int = 200,
        max_playbooks: int = 50,
    ) -> None:
        self._completion = completion
        self._max_signals = max_signals
        self._max_playbooks = max_playbooks

    async def reflect(
        self,
        *,
        project_id: str,
        signals: list[FrictionSignal],
        existing_playbooks: list[Playbook],
    ) -> list[ReflectionVerdict]:
        if not signals:
            return []

        payload = {
            "project_id": project_id,
            "signals": [_signal_to_dict(s) for s in signals[: self._max_signals]],
            "existing_playbooks": [
                _playbook_to_dict(p) for p in existing_playbooks[: self._max_playbooks]
            ],
        }
        user_message = json.dumps(payload, ensure_ascii=False)

        try:
            result = await self._completion(
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                response_format={"type": "json_object"},
            )
        except Exception:
            logger.exception(
                "Reflector LLM call failed", extra={"project_id": project_id}
            )
            return []

        content = (result or {}).get("content") or ""
        return _parse_verdicts(content, project_id=project_id)


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------


def _signal_to_dict(signal: FrictionSignal) -> dict[str, Any]:
    return {
        "task_id": signal.task_id,
        "kind": signal.kind.value,
        "source_lane": signal.source_lane,
        "target_lane": signal.target_lane,
        "metadata": signal.metadata,
        "observed_at": signal.observed_at.isoformat(),
    }


def _playbook_to_dict(playbook: Playbook) -> dict[str, Any]:
    return {
        "id": playbook.id,
        "name": playbook.name,
        "status": playbook.status.value,
        "hit_count": playbook.hit_count,
        "trigger": {
            "description": playbook.trigger.description,
            "friction_kinds": list(playbook.trigger.friction_kinds),
            "lane_transitions": [
                list(pair) for pair in playbook.trigger.lane_transitions
            ],
        },
        "steps": [
            {"order": s.order, "instruction": s.instruction}
            for s in playbook.steps
        ],
    }


def _parse_verdicts(
    content: str, *, project_id: str
) -> list[ReflectionVerdict]:
    """Parse the LLM JSON response into verdicts. Skip malformed entries."""
    try:
        loaded = json.loads(content)
    except json.JSONDecodeError:
        logger.warning(
            "Reflector returned non-JSON content", extra={"project_id": project_id}
        )
        return []

    if not isinstance(loaded, dict):
        return []
    raw_verdicts = loaded.get("verdicts")
    if not isinstance(raw_verdicts, list):
        return []

    verdicts: list[ReflectionVerdict] = []
    for entry in raw_verdicts:
        verdict = _build_verdict(entry)
        if verdict is not None:
            verdicts.append(verdict)
    return verdicts


def _build_verdict(entry: object) -> ReflectionVerdict | None:
    if not isinstance(entry, dict):
        return None
    raw_action = str(entry.get("action") or "").lower()
    try:
        action = ReflectionAction(raw_action)
    except ValueError:
        return None
    rationale = str(entry.get("rationale") or "").strip()
    if action in (ReflectionAction.REINFORCE, ReflectionAction.DEPRECATE):
        return _build_existing_playbook_verdict(action, rationale, entry.get("playbook_id"))
    if action is ReflectionAction.CREATE:
        return _build_create_verdict(rationale, entry.get("proposed_playbook"))
    return ReflectionVerdict(
        action=ReflectionAction.NOOP,
        playbook_id=None,
        rationale=rationale,
        proposed_playbook=None,
    )


def _build_existing_playbook_verdict(
    action: ReflectionAction, rationale: str, playbook_id: object
) -> ReflectionVerdict | None:
    if not isinstance(playbook_id, str) or not playbook_id.strip():
        return None
    return ReflectionVerdict(
        action=action,
        playbook_id=playbook_id.strip(),
        rationale=rationale,
        proposed_playbook=None,
    )


def _build_create_verdict(rationale: str, proposed: object) -> ReflectionVerdict | None:
    if not isinstance(proposed, dict) or not proposed.get("name"):
        return None
    return ReflectionVerdict(
        action=ReflectionAction.CREATE,
        playbook_id=None,
        rationale=rationale,
        proposed_playbook=proposed,
    )


__all__ = ["LLMCompletion", "LLMReflector"]
