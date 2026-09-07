"""Generation-owned Workspace instruction contributions for plugin runtime v2."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from src.infrastructure.agent.workspace.runtime_role_contract import (
    WORKSPACE_ROLE_WORKER,
    WORKSPACE_SESSION_ROLE_KEY,
)

from .agent_events import (
    AGENT_BEFORE_REQUEST_EVENT_V2,
    AGENT_SESSION_START_EVENT_V2,
    TOOLS_AFTER_EXECUTE_EVENT_V2,
)
from .runtime import ContextV2, PluginDefinitionV2, generated_contract_digest_v2

WORKSPACE_SESSION_START_MODULE_V2: Final[str] = "builtin://memstack/agent/workspace/session-start"
WORKSPACE_BEFORE_REQUEST_MODULE_V2: Final[str] = "builtin://memstack/agent/workspace/before-request"
WORKSPACE_AFTER_TOOL_EXECUTE_MODULE_V2: Final[str] = (
    "builtin://memstack/agent/workspace/after-tool-execute"
)
WORKSPACE_RUNTIME_MODULES_V2: Final[tuple[str, ...]] = (
    WORKSPACE_SESSION_START_MODULE_V2,
    WORKSPACE_BEFORE_REQUEST_MODULE_V2,
    WORKSPACE_AFTER_TOOL_EXECUTE_MODULE_V2,
)

_SESSION_INSTRUCTION = (
    "Workspace runtime is active. Treat this turn as part of a durable task attempt: use real "
    "tools for inspection, edits, and verification; keep the workspace task identity stable; "
    "and report durable progress through workspace reporting tools."
)
_RESPONSE_INSTRUCTION = (
    "Before ending a workspace turn, check whether the task still needs a real tool call. Do not "
    "print pseudo tool-call markup such as [TOOL_CALL], <minimax:tool_call>, or "
    "<invoke name=...>. When finished, call workspace_report_complete with artifacts and "
    "verification evidence; when blocked, call workspace_report_blocked with the blocker."
)
_TOOL_FOLLOWUP_INSTRUCTION = (
    "After this workspace tool result, either continue with the next concrete tool call or close "
    "the attempt using workspace_report_complete/workspace_report_blocked."
)
_WORKER_TASK_TREE_INSTRUCTION = (
    "This is a workspace worker session. Do not use todowrite add/replace to split or dispatch "
    "global workspace tasks; keep any private checklist in your reasoning and use "
    "workspace_report_progress/complete/blocked for the bound task. Do not use "
    "delegate_to_subagent or parallel_delegate_subagents from a worker session; helper subagents "
    "do not own this attempt's durable terminal report or worktree guard."
)


def _is_workspace(payload: Mapping[str, object]) -> bool:
    if payload.get("task_authority") == "workspace":
        return True
    workspace_id = payload.get("workspace_id")
    workspace_role = payload.get(WORKSPACE_SESSION_ROLE_KEY)
    return isinstance(workspace_id, str) and bool(workspace_id) and isinstance(workspace_role, str)


def _is_worker(payload: Mapping[str, object]) -> bool:
    return payload.get(WORKSPACE_SESSION_ROLE_KEY) == WORKSPACE_ROLE_WORKER


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


def _apply_workspace_session_start_v2(
    context: ContextV2,
    _config: Mapping[str, Any],
) -> None:
    def on_session_start(
        payload: Mapping[str, object],
    ) -> dict[str, object] | None:
        if not _is_workspace(payload):
            return None
        instructions = [_SESSION_INSTRUCTION]
        if _is_worker(payload):
            instructions.append(_WORKER_TASK_TREE_INSTRUCTION)
        return _contribution(context.entry_id, session=tuple(instructions))

    _ = context.on(AGENT_SESSION_START_EVENT_V2, on_session_start)


def _apply_workspace_before_request_v2(
    context: ContextV2,
    _config: Mapping[str, Any],
) -> None:
    def before_request(
        payload: Mapping[str, object],
    ) -> dict[str, object] | None:
        if not _is_workspace(payload) or not _is_worker(payload):
            return None
        return _contribution(context.entry_id, response=(_RESPONSE_INSTRUCTION,))

    _ = context.on(AGENT_BEFORE_REQUEST_EVENT_V2, before_request)


def _apply_workspace_after_tool_execute_v2(
    context: ContextV2,
    _config: Mapping[str, Any],
) -> None:
    def after_tool_execute(
        payload: Mapping[str, object],
    ) -> dict[str, object] | None:
        if not _is_workspace(payload) or not _is_worker(payload):
            return None
        tool_name = payload.get("tool_name")
        if not isinstance(tool_name, str) or not tool_name:
            return None
        return _contribution(context.entry_id, response=(_TOOL_FOLLOWUP_INSTRUCTION,))

    _ = context.on(TOOLS_AFTER_EXECUTE_EVENT_V2, after_tool_execute)


def workspace_runtime_definitions_v2() -> tuple[PluginDefinitionV2, ...]:
    """Return one trusted definition for each independently ordered Workspace hook."""
    return (
        PluginDefinitionV2(
            module_ref=WORKSPACE_SESSION_START_MODULE_V2,
            contract_digest=generated_contract_digest_v2(WORKSPACE_SESSION_START_MODULE_V2),
            apply=_apply_workspace_session_start_v2,
        ),
        PluginDefinitionV2(
            module_ref=WORKSPACE_BEFORE_REQUEST_MODULE_V2,
            contract_digest=generated_contract_digest_v2(WORKSPACE_BEFORE_REQUEST_MODULE_V2),
            apply=_apply_workspace_before_request_v2,
        ),
        PluginDefinitionV2(
            module_ref=WORKSPACE_AFTER_TOOL_EXECUTE_MODULE_V2,
            contract_digest=generated_contract_digest_v2(WORKSPACE_AFTER_TOOL_EXECUTE_MODULE_V2),
            apply=_apply_workspace_after_tool_execute_v2,
        ),
    )


__all__ = [
    "WORKSPACE_AFTER_TOOL_EXECUTE_MODULE_V2",
    "WORKSPACE_BEFORE_REQUEST_MODULE_V2",
    "WORKSPACE_RUNTIME_MODULES_V2",
    "WORKSPACE_SESSION_START_MODULE_V2",
    "workspace_runtime_definitions_v2",
]
