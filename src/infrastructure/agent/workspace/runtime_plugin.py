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
_WORKER_TASK_TREE_INSTRUCTION = (
    "This is a workspace worker session. Do not use todowrite add/replace to split or "
    "dispatch global workspace tasks; keep any private checklist in your reasoning and use "
    "workspace_report_progress/complete/blocked for the bound task. Do not use "
    "delegate_to_subagent or parallel_delegate_subagents from a worker session; helper "
    "subagents do not own this attempt's durable terminal report or worktree guard."
)
_WORKSPACE_TASK_HARNESS_FULL_CONTENT = """# Workspace Task Harness

Use this skill when a workspace task needs durable decomposition, delegated execution,
collaboration tracking, or verification evidence.

## Workflow

1. Rehydrate the active workspace/task/attempt context before changing files.
2. Decompose the request into feature-sized checklist items with explicit acceptance criteria.
3. Execute each item with real tools, durable progress reports, and workspace chat updates when
   coordination matters.
4. Before editing, read the applicable AGENTS.md or project guidance, inspect existing patterns,
   and keep the implementation plan local to the bound task.
5. Apply a code-quality gate before reporting completion: preserve existing architecture,
   avoid duplicate business logic or duplicate type/schema definitions, commit migrations with
   schema changes, keep dependency lockfiles in sync, protect secrets and tokens, avoid silent
   mock-data fallbacks in production paths, and verify frontend/backend contracts when both sides
   change. Treat explicit AGENTS.md/project guidance as hard acceptance criteria for code, docs,
   tests, generated artifacts, and reports; include project_guidance:checked evidence when such
   guidance exists. In shared worktrees, isolate commits to this task's intended files: inspect
   git status/diff, stage explicit owned paths only, and do not use broad staging such as
   git add -A, git add ., or git commit -a when unrelated dirty files exist.
6. Persist artifacts, changed files, test commands, verification evidence, and remaining risk.
7. Finish by calling `workspace_report_complete`, or `workspace_report_blocked` with a concrete
   blocker and next recovery action.

## Evidence Standard

- Every code change needs a diff summary and at least one targeted verification command.
- Every handoff needs completed steps, next steps, changed files, test results, and known gaps.
- Every collaboration blocker needs the blocked task, owner, missing input, and recommended action.
- Quality-sensitive changes need focused evidence: migration or rollback proof for schema changes,
  lockfile evidence for dependency changes, contract tests for API/UI boundary changes, and security
  notes for authentication, authorization, secrets, or token handling.
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
