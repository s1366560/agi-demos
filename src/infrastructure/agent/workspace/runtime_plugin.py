"""Built-in workspace execution runtime hooks."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar

from src.domain.model.agent.skill.skill import TriggerPattern
from src.infrastructure.agent.plugins.registry import AgentPluginRegistry, PluginSkillBuildContext
from src.infrastructure.agent.plugins.runtime_api import PluginRuntimeApi

PLUGIN_NAME = "workspace-runtime"
WORKSPACE_TASK_HARNESS_SKILL_NAME = "workspace-task-harness"

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
_WORKSPACE_TASK_HARNESS_FULL_CONTENT = """# Workspace Task Harness

Use this skill when a workspace task needs durable decomposition, delegated execution,
collaboration tracking, or verification evidence.

## Workflow

1. Rehydrate the active workspace/task/attempt context before changing files.
2. Decompose the request into feature-sized checklist items with explicit acceptance criteria.
3. Execute each item with real tools, durable progress reports, and workspace chat updates when
   coordination matters.
4. Persist artifacts, changed files, test commands, verification evidence, and remaining risk.
5. Finish by calling `workspace_report_complete`, or `workspace_report_blocked` with a concrete
   blocker and next recovery action.

## Evidence Standard

- Every code change needs a diff summary and at least one targeted verification command.
- Every handoff needs completed steps, next steps, changed files, test results, and known gaps.
- Every collaboration blocker needs the blocked task, owner, missing input, and recommended action.
"""


def _build_workspace_task_harness_skills(
    context: PluginSkillBuildContext,
) -> list[dict[str, Any]]:
    """Expose the workspace harness as a built-in plugin skill."""
    _ = context
    return [
        {
            "name": WORKSPACE_TASK_HARNESS_SKILL_NAME,
            "description": (
                "Run long workspace tasks through durable decomposition, collaboration tracking, "
                "handoff, and verification evidence."
            ),
            "tools": [
                "read",
                "write",
                "edit",
                "bash",
                "glob",
                "grep",
                "workspace_chat_read",
                "workspace_chat_send",
                "workspace_report_progress",
                "workspace_report_complete",
                "workspace_report_blocked",
                "workspace_request_clarification",
            ],
            "trigger_type": "hybrid",
            "trigger_patterns": [
                TriggerPattern("workspace task", weight=0.9),
                TriggerPattern("durable handoff", weight=0.9),
                TriggerPattern("collaboration tracking", weight=0.85),
                TriggerPattern("任务分解", weight=0.85),
                TriggerPattern("协作跟踪", weight=0.85),
                TriggerPattern("验收证据", weight=0.8),
            ],
            "prompt_template": _WORKSPACE_TASK_HARNESS_FULL_CONTENT,
            "full_content": _WORKSPACE_TASK_HARNESS_FULL_CONTENT,
            "agent_modes": ["*"],
            "scope": "tenant",
            "metadata": {
                "plugin": PLUGIN_NAME,
                "capabilities": [
                    "feature_checklist",
                    "handoff_package",
                    "collaboration_tracking",
                    "verification_evidence",
                ],
            },
        }
    ]


def _is_workspace_runtime(payload: Mapping[str, Any]) -> bool:
    runtime_context = payload.get("runtime_context")
    if isinstance(runtime_context, Mapping):
        if runtime_context.get("task_authority") == "workspace":
            return True
        if runtime_context.get("workspace_id") and runtime_context.get("workspace_session_role"):
            return True
    return payload.get("task_authority") == "workspace"


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
    if not _is_workspace_runtime(payload):
        return dict(payload)
    return _append_instruction(payload, "session_instructions", _SESSION_INSTRUCTION)


def _before_response(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not _is_workspace_runtime(payload):
        return dict(payload)
    return _append_instruction(payload, "response_instructions", _RESPONSE_INSTRUCTION)


def _after_tool_execution(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not _is_workspace_runtime(payload):
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
