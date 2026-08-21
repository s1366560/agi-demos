"""Generation-owned Sisyphus instruction contributions for plugin runtime v2."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from .agent_events import (
    AGENT_BEFORE_REQUEST_EVENT_V2,
    AGENT_SESSION_START_EVENT_V2,
    TOOLS_AFTER_EXECUTE_EVENT_V2,
)
from .runtime import ContextV2, PluginDefinitionV2, generated_contract_digest_v2

SISYPHUS_RUNTIME_MODULE_V2: Final[str] = "builtin://memstack/agent/sisyphus-runtime"

_FOLLOWUP_TOOLS = frozenset(
    {
        "delegate_to_subagent",
        "skill",
        "skill_loader",
        "todowrite",
    }
)
_DIRECT_OUTCOME_REMINDER = (
    "If you can produce the requested change or result directly, do it instead of describing "
    "what you would do next."
)
_DELEGATION_FOLLOWUP = (
    "When a delegated worker returns, treat its result as candidate evidence only: review the "
    "task outcome and update workspace task status yourself via todoread/todowrite instead of "
    "assuming the worker already closed the task."
)


@dataclass(frozen=True, kw_only=True)
class _SisyphusSettingsV2:
    startup_reminder: str
    response_reminder: str
    tool_followup_reminder: str
    require_direct_outcome: bool


def _settings(config: Mapping[str, Any]) -> _SisyphusSettingsV2:
    startup_reminder = config.get("startup_reminder")
    response_reminder = config.get("response_reminder")
    tool_followup_reminder = config.get("tool_followup_reminder")
    require_direct_outcome = config.get("require_direct_outcome")
    if not isinstance(startup_reminder, str):
        raise ValueError("sisyphus startup_reminder must be a string")
    if not isinstance(response_reminder, str):
        raise ValueError("sisyphus response_reminder must be a string")
    if not isinstance(tool_followup_reminder, str):
        raise ValueError("sisyphus tool_followup_reminder must be a string")
    if not isinstance(require_direct_outcome, bool):
        raise ValueError("sisyphus require_direct_outcome must be a boolean")
    return _SisyphusSettingsV2(
        startup_reminder=startup_reminder,
        response_reminder=response_reminder,
        tool_followup_reminder=tool_followup_reminder,
        require_direct_outcome=require_direct_outcome,
    )


def _contribution(
    entry_id: str,
    *,
    session: tuple[str, ...] = (),
    response: tuple[str, ...] = (),
) -> dict[str, object]:
    return {
        "source_entry_id": entry_id,
        "session_instructions": list(session),
        "response_instructions": list(response),
    }


def _apply_sisyphus_runtime_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    settings = _settings(config)

    def on_session_start(_payload: Mapping[str, object]) -> dict[str, object]:
        return _contribution(context.entry_id, session=(settings.startup_reminder,))

    def before_request(_payload: Mapping[str, object]) -> dict[str, object]:
        reminders = [settings.response_reminder]
        if settings.require_direct_outcome:
            reminders.append(_DIRECT_OUTCOME_REMINDER)
        return _contribution(context.entry_id, response=tuple(reminders))

    def after_tool_execute(
        payload: Mapping[str, object],
    ) -> dict[str, object] | None:
        tool_name = payload.get("tool_name")
        if not isinstance(tool_name, str) or tool_name.lower() not in _FOLLOWUP_TOOLS:
            return None
        reminder = settings.tool_followup_reminder
        if tool_name.lower() == "delegate_to_subagent":
            reminder = f"{reminder} {_DELEGATION_FOLLOWUP}"
        return _contribution(context.entry_id, response=(reminder,))

    _ = context.on(AGENT_SESSION_START_EVENT_V2, on_session_start)
    _ = context.on(AGENT_BEFORE_REQUEST_EVENT_V2, before_request)
    _ = context.on(TOOLS_AFTER_EXECUTE_EVENT_V2, after_tool_execute)


def sisyphus_runtime_definition_v2() -> PluginDefinitionV2:
    """Return the trusted Sisyphus module bound to its generated contract."""
    return PluginDefinitionV2(
        module_ref=SISYPHUS_RUNTIME_MODULE_V2,
        contract_digest=generated_contract_digest_v2(SISYPHUS_RUNTIME_MODULE_V2),
        apply=_apply_sisyphus_runtime_v2,
    )


__all__ = ["SISYPHUS_RUNTIME_MODULE_V2", "sisyphus_runtime_definition_v2"]
