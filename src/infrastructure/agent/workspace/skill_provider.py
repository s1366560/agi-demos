"""Builtin workspace Skill source independent of the retired V1 plugin registry."""

from __future__ import annotations

from typing import Any

from src.domain.model.agent.skill import Skill, SkillScope
from src.domain.model.agent.skill.skill_source import SkillSource

WORKSPACE_TASK_HARNESS_SKILL_NAME = "workspace-task-harness"

_WORKSPACE_TASK_HARNESS_DESCRIPTION = (
    "Run long workspace tasks through durable decomposition, collaboration tracking, "
    "handoff, and verification evidence."
)
_WORKSPACE_TASK_HARNESS_TOOLS = (
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


def workspace_task_harness_skill_payload() -> dict[str, Any]:
    """Return the legacy-neutral declarative payload for compatibility callers."""
    return {
        "name": WORKSPACE_TASK_HARNESS_SKILL_NAME,
        "description": _WORKSPACE_TASK_HARNESS_DESCRIPTION,
        "tools": list(_WORKSPACE_TASK_HARNESS_TOOLS),
        "full_content": _WORKSPACE_TASK_HARNESS_FULL_CONTENT,
        "agent_modes": ["*"],
        "scope": "tenant",
        "metadata": {
            "plugin": "workspace-runtime",
            "capabilities": [
                "feature_checklist",
                "handoff_package",
                "collaboration_tracking",
                "verification_evidence",
            ],
        },
    }


def build_workspace_task_harness_skill(
    *,
    tenant_id: str,
    project_id: str | None,
) -> Skill:
    """Build the stable builtin workspace harness Skill for one worker scope."""
    normalized_tenant_id = tenant_id.strip()
    if not normalized_tenant_id:
        raise ValueError("workspace task harness requires tenant_id")
    normalized_project_id = project_id.strip() if project_id else None
    return Skill(
        id=(
            f"builtin:{WORKSPACE_TASK_HARNESS_SKILL_NAME}:"
            f"{normalized_tenant_id}:{normalized_project_id or 'global'}"
        ),
        tenant_id=normalized_tenant_id,
        project_id=normalized_project_id,
        name=WORKSPACE_TASK_HARNESS_SKILL_NAME,
        description=_WORKSPACE_TASK_HARNESS_DESCRIPTION,
        tools=list(_WORKSPACE_TASK_HARNESS_TOOLS),
        metadata=workspace_task_harness_skill_payload()["metadata"],
        source=SkillSource.PLUGIN,
        full_content=_WORKSPACE_TASK_HARNESS_FULL_CONTENT,
        agent_modes=["*"],
        scope=SkillScope.TENANT,
    )


__all__ = [
    "WORKSPACE_TASK_HARNESS_SKILL_NAME",
    "build_workspace_task_harness_skill",
    "workspace_task_harness_skill_payload",
]
