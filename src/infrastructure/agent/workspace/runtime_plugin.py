"""Built-in workspace execution runtime hooks."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar

from src.infrastructure.agent.plugins.registry import AgentPluginRegistry, PluginSkillBuildContext
from src.infrastructure.agent.plugins.runtime_api import PluginRuntimeApi
from src.infrastructure.agent.workspace.runtime_role_contract import (
    WORKSPACE_ROLE_WORKER,
    WORKSPACE_SESSION_ROLE_KEY,
    is_workspace_conversation,
)

from .skill_provider import (
    WORKSPACE_TASK_HARNESS_SKILL_NAME as WORKSPACE_TASK_HARNESS_SKILL_NAME,
    workspace_task_harness_skill_payload,
)

PLUGIN_NAME = "workspace-runtime"

_SESSION_INSTRUCTION = (
    "Workspace runtime is active. Treat this turn as part of a durable task attempt: "
    "use real tools for inspection, edits, and verification; keep the workspace task "
    "identity stable; and report durable progress through workspace reporting tools."
)
_RESPONSE_INSTRUCTION = (
    "Before ending a workspace turn, check whether the task still needs a real tool call. "
    "Do not print pseudo tool-call markup such as [TOOL_CALL], <minimax:tool_call>, or "
    "<invoke name=...>. When finished, call workspace_report_complete with artifacts and "
    "verification evidence; when blocked, call workspace_report_blocked with the blocker."
)
_TOOL_FOLLOWUP_INSTRUCTION = (
    "After this workspace tool result, either continue with the next concrete tool call or "
    "close the attempt using workspace_report_complete/workspace_report_blocked."
)
_WORKER_TASK_TREE_INSTRUCTION = (
    "This is a workspace worker session. Do not use todowrite add/replace to split or "
    "dispatch global workspace tasks; keep any private checklist in your reasoning and use "
    "workspace_report_progress/complete/blocked for the bound task. Do not use "
    "delegate_to_subagent or parallel_delegate_subagents from a worker session; helper "
    "subagents do not own this attempt's durable terminal report or worktree guard."
)


def _build_workspace_task_harness_skills(
    context: PluginSkillBuildContext,
) -> list[dict[str, Any]]:
    """Expose the workspace harness as a built-in plugin skill."""
    _ = context
    return [workspace_task_harness_skill_payload()]


def _workspace_session_role(payload: Mapping[str, Any]) -> str:
    runtime_context = payload.get("runtime_context")
    if isinstance(runtime_context, Mapping):
        role = runtime_context.get(WORKSPACE_SESSION_ROLE_KEY)
        if isinstance(role, str):
            return role
    role = payload.get(WORKSPACE_SESSION_ROLE_KEY)
    return role if isinstance(role, str) else ""


def _is_workspace_worker_runtime(payload: Mapping[str, Any]) -> bool:
    return _workspace_session_role(payload) == WORKSPACE_ROLE_WORKER


def _append_instruction(
    payload: Mapping[str, Any],
    field_name: str,
    instruction: str,
) -> dict[str, Any]:
    updated = dict(payload)
    current = payload.get(field_name)
    items = list(current) if isinstance(current, list) else []
    if instruction not in items:
        items.append(instruction)
    updated[field_name] = items
    return updated


def _on_session_start(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not is_workspace_conversation(payload):
        return dict(payload)
    updated = _append_instruction(payload, "session_instructions", _SESSION_INSTRUCTION)
    if _is_workspace_worker_runtime(payload):
        updated = _append_instruction(
            updated,
            "session_instructions",
            _WORKER_TASK_TREE_INSTRUCTION,
        )
    return updated


def _before_response(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not is_workspace_conversation(payload) or not _is_workspace_worker_runtime(payload):
        return dict(payload)
    return _append_instruction(payload, "response_instructions", _RESPONSE_INSTRUCTION)


def _after_tool_execution(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not is_workspace_conversation(payload) or not _is_workspace_worker_runtime(payload):
        return dict(payload)
    tool_name = str(payload.get("tool_name", "")).strip()
    if not tool_name:
        return dict(payload)
    return _append_instruction(payload, "response_instructions", _TOOL_FOLLOWUP_INSTRUCTION)


def register_builtin_workspace_plugin(registry: AgentPluginRegistry) -> None:
    """Register built-in workspace runtime hooks."""

    api = PluginRuntimeApi(PLUGIN_NAME, registry=registry)
    _register_workspace_plugin(api)


def _register_workspace_plugin(api: PluginRuntimeApi) -> None:
    api.register_skill_factory(
        _build_workspace_task_harness_skills,
        overwrite=True,
    )
    api.register_hook(
        "on_session_start",
        _on_session_start,
        hook_family="mutating",
        priority=15,
        display_name="Workspace session harness",
        description="Activates durable workspace task execution guidance.",
        overwrite=True,
    )
    api.register_hook(
        "before_response",
        _before_response,
        hook_family="mutating",
        priority=15,
        display_name="Workspace response continuation",
        description="Keeps workspace workers on real tools and explicit terminal reports.",
        overwrite=True,
    )
    api.register_hook(
        "after_tool_execution",
        _after_tool_execution,
        hook_family="mutating",
        priority=15,
        display_name="Workspace tool follow-up",
        description="Prompts the next workspace action after tool execution.",
        overwrite=True,
    )


class BuiltinWorkspaceRuntimePlugin:
    """Builtin plugin wrapper so runtime manager can inventory workspace-runtime."""

    name = PLUGIN_NAME
    plugin_manifest: ClassVar[dict[str, str]] = {
        "id": PLUGIN_NAME,
        "kind": "runtime",
        "version": "builtin",
    }

    def setup(self, api: PluginRuntimeApi) -> None:
        _register_workspace_plugin(api)
