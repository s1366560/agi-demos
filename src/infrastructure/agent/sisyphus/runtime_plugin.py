"""Built-in runtime hooks that reinforce Sisyphus behavior."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar

from src.infrastructure.agent.plugins.registry import AgentPluginRegistry
from src.infrastructure.agent.plugins.runtime_api import PluginRuntimeApi

PLUGIN_NAME = "sisyphus-runtime"

_STARTUP_REMINDER = (
    "Start doing the work immediately. Prefer concrete action over narrating intent, "
    "and only ask the user for input when a real decision or missing permission blocks progress."
)
_RESPONSE_REMINDER = (
    "Before responding, check whether there is another tool call, todo update, or delegation step "
    "you can perform yourself. Do not stop at analysis when execution is possible."
)
_TOOL_FOLLOWUP_REMINDER = (
    "After tool results arrive, synthesize the outcome, decide the next concrete action, and continue "
    "until the task reaches a stable handoff point."
)


def _read_setting(payload: Mapping[str, Any], key: str, default: str) -> str:
    """Read a string setting from the hook payload."""
    raw_settings = payload.get("hook_settings")
    if not isinstance(raw_settings, dict):
        return default
    value = raw_settings.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return default


def _read_bool_setting(payload: Mapping[str, Any], key: str, default: bool) -> bool:
    """Read a boolean setting from the hook payload."""
    raw_settings = payload.get("hook_settings")
    if not isinstance(raw_settings, dict):
        return default
    value = raw_settings.get(key)
    if isinstance(value, bool):
        return value
    return default


def _append_instruction(
    payload: Mapping[str, Any],
    field_name: str,
    instruction: str,
) -> dict[str, Any]:
    """Append a unique instruction to a list field in the payload."""
    if not instruction:
        return dict(payload)
    current = payload.get(field_name)
    items = list(current) if isinstance(current, list) else []
    if instruction not in items:
        items.append(instruction)
    updated_payload = dict(payload)
    updated_payload[field_name] = items
    return updated_payload


def _on_session_start(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Add a startup reminder for the first model turn."""
    reminder = _read_setting(payload, "startup_reminder", _STARTUP_REMINDER)
    return _append_instruction(payload, "session_instructions", reminder)


def _before_response(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Add a continuation reminder before every model response."""
    reminder = _read_setting(payload, "response_reminder", _RESPONSE_REMINDER)
    updated_payload = _append_instruction(payload, "response_instructions", reminder)
    if not _read_bool_setting(updated_payload, "require_direct_outcome", True):
        return updated_payload
    direct_outcome_reminder = (
        "If you can produce the requested change or result directly, do it instead of describing what "
        "you would do next."
    )
    return _append_instruction(updated_payload, "response_instructions", direct_outcome_reminder)


def _after_tool_execution(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Add a follow-up reminder after important tool activity."""
    tool_name = str(payload.get("tool_name", "")).strip().lower()
    if tool_name not in {"todowrite", "delegate_to_subagent", "skill", "skill_loader"}:
        return dict(payload)
    reminder = _read_setting(payload, "tool_followup_reminder", _TOOL_FOLLOWUP_REMINDER)
    if tool_name == "delegate_to_subagent":
        reminder = (
            f"{reminder} When a delegated worker returns, treat its result as candidate evidence only: "
            "review the task outcome and update workspace task status yourself via todoread/todowrite "
            "instead of assuming the worker already closed the task."
        )
    return _append_instruction(payload, "response_instructions", reminder)


def register_builtin_sisyphus_plugin(registry: AgentPluginRegistry) -> None:
    """Register built-in Sisyphus runtime hooks with metadata for the UI."""
    api = PluginRuntimeApi(PLUGIN_NAME, registry=registry)
    _register_sisyphus_plugin(api)


def _register_sisyphus_plugin(api: PluginRuntimeApi) -> None:
    """Register Sisyphus runtime hooks through the runtime API."""
    api.register_hook(
        "on_session_start",
        _on_session_start,
        hook_family="mutating",
        priority=20,
        display_name="Session start reminder",
        description="Reinforces Sisyphus' bias toward immediate execution.",
        default_settings={"startup_reminder": _STARTUP_REMINDER},
        settings_schema={
            "type": "object",
            "properties": {
                "startup_reminder": {
                    "type": "string",
                    "title": "Startup reminder",
                    "description": "Instruction appended at the start of each session.",
                    "maxLength": 2000,
                }
            },
            "additionalProperties": False,
        },
        overwrite=True,
    )
    api.register_hook(
        "before_response",
        _before_response,
        hook_family="mutating",
        priority=30,
        display_name="Response continuation reminder",
        description="Pushes the agent to keep working before concluding with prose.",
        default_settings={
            "response_reminder": _RESPONSE_REMINDER,
            "require_direct_outcome": True,
        },
        settings_schema={
            "type": "object",
            "properties": {
                "response_reminder": {
                    "type": "string",
                    "title": "Response reminder",
                    "description": "Instruction appended before the model drafts a response.",
                    "maxLength": 2000,
                },
                "require_direct_outcome": {
                    "type": "boolean",
                    "title": "Require direct outcome",
                    "description": "When enabled, remind the agent to act instead of merely describing.",
                },
            },
            "additionalProperties": False,
        },
        overwrite=True,
    )
    api.register_hook(
        "after_tool_execution",
        _after_tool_execution,
        hook_family="mutating",
        priority=40,
        display_name="Tool follow-up reminder",
        description="Encourages another concrete step after todo, skill, or delegation activity.",
        default_settings={"tool_followup_reminder": _TOOL_FOLLOWUP_REMINDER},
        settings_schema={
            "type": "object",
            "properties": {
                "tool_followup_reminder": {
                    "type": "string",
                    "title": "Tool follow-up reminder",
                    "description": "Instruction appended after key tool calls finish.",
                    "maxLength": 2000,
                }
            },
            "additionalProperties": False,
        },
        overwrite=True,
    )


class BuiltinSisyphusRuntimePlugin:
    """Builtin plugin wrapper so discovery/runtime manager can inventory sisyphus-runtime."""

    name = PLUGIN_NAME
    plugin_manifest: ClassVar[dict[str, str]] = {
        "id": PLUGIN_NAME,
        "kind": "runtime",
        "version": "builtin",
    }

    def setup(self, api: PluginRuntimeApi) -> None:
        _register_sisyphus_plugin(api)
