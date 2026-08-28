"""Generation-owned Sisyphus instruction contributions for plugin runtime v2."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from .agent_events import (
    AGENT_BEFORE_REQUEST_EVENT_V2,
    AGENT_SESSION_START_EVENT_V2,
    TOOLS_AFTER_EXECUTE_EVENT_V2,
)
from .runtime import ContextV2, PluginDefinitionV2, generated_contract_digest_v2

SISYPHUS_SESSION_START_MODULE_V2: Final[str] = "builtin://memstack/agent/sisyphus/session-start"
SISYPHUS_BEFORE_REQUEST_MODULE_V2: Final[str] = "builtin://memstack/agent/sisyphus/before-request"
SISYPHUS_AFTER_TOOL_EXECUTE_MODULE_V2: Final[str] = (
    "builtin://memstack/agent/sisyphus/after-tool-execute"
)
SISYPHUS_RUNTIME_MODULES_V2: Final[tuple[str, ...]] = (
    SISYPHUS_SESSION_START_MODULE_V2,
    SISYPHUS_BEFORE_REQUEST_MODULE_V2,
    SISYPHUS_AFTER_TOOL_EXECUTE_MODULE_V2,
)

_FOLLOWUP_TOOLS = frozenset(
    {
        "delegate_to_subagent",
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


def _string_setting(config: Mapping[str, Any], key: str) -> str:
    value = config.get(key)
    if not isinstance(value, str):
        raise ValueError(f"sisyphus {key} must be a string")
    return value


def _boolean_setting(config: Mapping[str, Any], key: str) -> bool:
    value = config.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"sisyphus {key} must be a boolean")
    return value


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


def _apply_sisyphus_session_start_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    startup_reminder = _string_setting(config, "startup_reminder")

    def on_session_start(_payload: Mapping[str, object]) -> dict[str, object]:
        return _contribution(context.entry_id, session=(startup_reminder,))

    _ = context.on(AGENT_SESSION_START_EVENT_V2, on_session_start)


def _apply_sisyphus_before_request_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    response_reminder = _string_setting(config, "response_reminder")
    require_direct_outcome = _boolean_setting(config, "require_direct_outcome")

    def before_request(_payload: Mapping[str, object]) -> dict[str, object]:
        reminders = [response_reminder]
        if require_direct_outcome:
            reminders.append(_DIRECT_OUTCOME_REMINDER)
        return _contribution(context.entry_id, response=tuple(reminders))

    _ = context.on(AGENT_BEFORE_REQUEST_EVENT_V2, before_request)


def _apply_sisyphus_after_tool_execute_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    tool_followup_reminder = _string_setting(config, "tool_followup_reminder")

    def after_tool_execute(
        payload: Mapping[str, object],
    ) -> dict[str, object] | None:
        tool_name = payload.get("tool_name")
        if not isinstance(tool_name, str) or tool_name.lower() not in _FOLLOWUP_TOOLS:
            return None
        reminder = tool_followup_reminder
        if tool_name.lower() == "delegate_to_subagent":
            reminder = f"{reminder} {_DELEGATION_FOLLOWUP}"
        return _contribution(context.entry_id, response=(reminder,))

    _ = context.on(TOOLS_AFTER_EXECUTE_EVENT_V2, after_tool_execute)


def sisyphus_runtime_definitions_v2() -> tuple[PluginDefinitionV2, ...]:
    """Return one trusted definition for each independently ordered Sisyphus hook."""
    return (
        PluginDefinitionV2(
            module_ref=SISYPHUS_SESSION_START_MODULE_V2,
            contract_digest=generated_contract_digest_v2(SISYPHUS_SESSION_START_MODULE_V2),
            apply=_apply_sisyphus_session_start_v2,
        ),
        PluginDefinitionV2(
            module_ref=SISYPHUS_BEFORE_REQUEST_MODULE_V2,
            contract_digest=generated_contract_digest_v2(SISYPHUS_BEFORE_REQUEST_MODULE_V2),
            apply=_apply_sisyphus_before_request_v2,
        ),
        PluginDefinitionV2(
            module_ref=SISYPHUS_AFTER_TOOL_EXECUTE_MODULE_V2,
            contract_digest=generated_contract_digest_v2(SISYPHUS_AFTER_TOOL_EXECUTE_MODULE_V2),
            apply=_apply_sisyphus_after_tool_execute_v2,
        ),
    )


__all__ = [
    "SISYPHUS_AFTER_TOOL_EXECUTE_MODULE_V2",
    "SISYPHUS_BEFORE_REQUEST_MODULE_V2",
    "SISYPHUS_RUNTIME_MODULES_V2",
    "SISYPHUS_SESSION_START_MODULE_V2",
    "sisyphus_runtime_definitions_v2",
]
