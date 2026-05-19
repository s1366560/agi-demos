"""Auto-launch a worker agent conversation when a workspace task is assigned.

This is the missing piece in the autonomy loop: previously, calling
``WorkspaceTaskCommandService.assign_task_to_agent`` only persisted the
assignment + emitted ``WORKSPACE_TASK_ASSIGNED`` — no listener actually
started a conversation with the worker agent definition. Worker
``report_workspace_task`` calls (consumed by ``apply_workspace_worker_report``)
were therefore never reached unless the leader manually @-mentioned the
worker in chat.

This module closes the loop: ``schedule_worker_session`` is invoked right
after assignment to fire-and-forget a coroutine that:

1. Resolves the workspace (tenant_id, project_id).
2. Generates a deterministic conversation id keyed by
   ``workspace + worker_agent_id + scope("task:{task_id}")``.
3. Creates the ``Conversation`` row if missing, stamping
   ``agent_config={"selected_agent_id": worker_agent_id}`` so the UI badge
   knows which agent definition owns this conversation.
4. Posts a concise task brief, injects operational workspace context as
   system model context, and streams it through ``stream_chat_v2(agent_id=...)``.

Safety:
- Redis ``SETNX`` cooldown (default 5 min) keyed on the conversation id
  prevents duplicate launches for the same task within a short window.
- Per-launch failures are logged but never raised — assignment workflow
  must remain unaffected.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import posixpath
import re
import time
from collections.abc import Awaitable, Callable, Iterable, Mapping
from datetime import UTC, datetime
from typing import Any, Protocol, cast

from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.workspace_autonomy_profiles import evaluate_workspace_code_context
from src.domain.model.workspace.workspace_task import WorkspaceTask
from src.infrastructure.agent.workspace.code_context import (
    WorkspaceCodeContext,
    load_workspace_code_context,
)
from src.infrastructure.agent.workspace.workspace_metadata_keys import (
    ACTIVE_EXECUTION_ROOT,
    ATTEMPT_WORKTREE,
    CURRENT_ATTEMPT_ID,
    CURRENT_ATTEMPT_WORKER_BINDING_ID,
    PREFERRED_LANGUAGE,
    ROOT_GOAL_TASK_ID,
    WORKTREE_SETUP,
)
from src.infrastructure.agent.workspace_plan.pipeline import (
    DRONE_PROVIDER,
    build_pipeline_contract_from_metadata,
)
from src.infrastructure.agent.workspace_plan.system_actor import WORKSPACE_PLAN_SYSTEM_ACTOR_ID

logger = logging.getLogger(__name__)

_background_tasks: set[asyncio.Task[Any]] = set()

# Cooldown TTL — long enough to avoid double-launch on transient retries
# but short enough that a genuine re-assignment after rework can re-fire.
WORKER_LAUNCH_COOLDOWN_SECONDS = 300
WORKER_LAUNCH_HEARTBEAT_SECONDS = int(os.getenv("WORKSPACE_WORKER_LAUNCH_HEARTBEAT_SECONDS", "45"))
WORKER_STREAM_FINISH_POLL_SECONDS = int(
    os.getenv("WORKSPACE_WORKER_STREAM_FINISH_POLL_SECONDS", "15")
)
WORKER_STREAM_ORPHAN_GRACE_SECONDS = int(
    os.getenv("WORKSPACE_WORKER_STREAM_ORPHAN_GRACE_SECONDS", "900")
)
WORKER_MAX_SINGLE_WRITE_CHARS = 64_000
WORKER_RECOMMENDED_WRITE_CHUNK_CHARS = 4_000
WORKER_MAX_SINGLE_BASH_COMMAND_CHARS = 6_000
WORKER_REPAIR_SOURCE_METADATA_MAX_DEPTH = 12
WORKER_COMPLETION_REQUIRED_PREFLIGHT_REFS = (
    "preflight:read-progress",
    "preflight:git-status",
)
_VERIFICATION_SCRIPT_SCOPE_PATH_PATTERN = re.compile(
    r"(?P<path>[A-Za-z0-9_./-]*(?:test|spec|e2e|integration|audit|benchmark)"
    + r"[A-Za-z0-9_./-]*\.(?:js|jsx|ts|tsx|mjs|cjs|py|sh))",
    re.I,
)

_WORKSPACE_APP_CONTEXT_TYPE = "workspace_worker_runtime"
_WORKSPACE_ROOT_OVERRIDE_MARKERS = ("worktree_path", "[feature-checkpoint]", "[worktree-setup]")
_WORKER_VERIFICATION_INTEGRITY_PHASES = frozenset({"test", "review"})
_TERMINAL_REPORT_TOOLS = frozenset({"workspace_report_complete", "workspace_report_blocked"})
_NATIVE_TOOL_PROTOCOL_GUARD = (
    "Use only the platform's native tool-call channel for tools. Do not print "
    "tool-call markup, JSON/function-call stubs, or shell command code blocks as "
    "a substitute for a tool call. In particular, never emit [TOOL_CALL], "
    "[/TOOL_CALL], {tool => ...}, <minimax:tool_call>, or <invoke name=...> text."
)
_WORKER_CODE_QUALITY_INSTRUCTIONS = (
    "Before implementation, read the applicable AGENTS.md/project guidance and inspect "
    "nearby code patterns. Keep the task plan bounded to the assigned workspace task; "
    "do not broaden scope just because a related feature exists.",
    (
        "Treat explicit repository guidance as hard acceptance criteria for the diff. "
        "Extract concrete style, safety, testing, migration, artifact, and prohibited-pattern "
        "requirements before editing; if the guidance forbids a pattern or content form, do "
        "not introduce it in code, docs, tests, generated assets, or reports."
    ),
    (
        "Prefer existing architecture, shared modules, shared types, and repository "
        "utilities. Do not duplicate business logic across frontend/backend, duplicate "
        "schema/type definitions, or create temporary parallel implementations when a "
        "shared contract should own the behavior."
    ),
    (
        "For database schema changes, commit a reproducible migration or documented "
        "rollback path; do not rely on local db push/dev database mutation as the only "
        "state change."
    ),
    (
        "For dependency changes, update the matching lockfile and verify imports/builds "
        "against the changed dependency graph."
    ),
    (
        "For authentication, authorization, API keys, tokens, secrets, or credentials, "
        "store only safe representations such as hashes or prefixes when possible, avoid "
        "logging sensitive values, and include focused security verification."
    ),
    (
        "For frontend/backend contract changes, update both sides deliberately and add "
        "contract or integration evidence proving they agree on request shape, response "
        "shape, error states, and shared calculations."
    ),
    (
        "In shared workspace worktrees, isolate commits to this task's intended files. "
        "Inspect git status and git diff before staging, use explicit git add <path> for "
        "only the files you own, and never use broad staging such as git add -A, git add ., "
        "or git commit -a when unrelated dirty files exist. Leave unrelated changes "
        "unstaged and mention them as external workspace activity."
    ),
    (
        "Do not silently show mock or fake data in production paths. If real data is "
        "unavailable, implement an explicit empty/loading/error state or label demo data "
        "as demo data."
    ),
    (
        "For test, review, audit, benchmark, and E2E nodes, do not weaken, replace, "
        "delete, or bypass verification scripts just to make evidence pass. Fix product "
        "behavior, preserve assertion strength, or report remaining failures honestly."
    ),
    (
        "Before workspace_report_complete, review git diff for accidental breadth, run "
        "targeted tests/build/type checks, include project_guidance:checked evidence when "
        "AGENTS.md/project guidance exists, and report unresolved risks honestly."
    ),
)


class _WorkspaceProjection(Protocol):
    project_id: str
    tenant_id: str


class _WorkerConversationProjection(Protocol):
    workspace_id: str | None
    linked_workspace_task_id: str | None
    metadata: dict[str, object]
    updated_at: datetime | None


def _conversation_scope_for_task(task_id: str, attempt_id: str | None = None) -> str:
    """Stable scope string for a worker session bound to a task."""
    if attempt_id:
        return f"task:{task_id}:attempt:{attempt_id}"
    return f"task:{task_id}"


def _conversation_id_for_worker(
    *,
    workspace_id: str,
    worker_agent_id: str,
    task_id: str,
    attempt_id: str | None = None,
) -> str:
    """Generate the conversation id a worker session should reuse.

    Delegates to :py:meth:`WorkspaceMentionRouter.workspace_conversation_id`
    so that mention-routed and dispatch-launched conversations converge to the
    same id when the scope matches.
    """
    from src.application.services.workspace_mention_router import (
        WorkspaceMentionRouter,
    )

    return WorkspaceMentionRouter.workspace_conversation_id(
        workspace_id,
        worker_agent_id,
        conversation_scope=_conversation_scope_for_task(task_id, attempt_id),
    )


def _worker_conversation_kwargs(
    *,
    conversation_id: str,
    workspace_id: str,
    workspace: _WorkspaceProjection,
    task: WorkspaceTask,
    actor_user_id: str,
    worker_agent_id: str,
    worker_binding_id: str,
    root_goal_task_id: str,
    attempt_id: str,
    active_status: object,
) -> dict[str, Any]:
    created_at = datetime.now(UTC)
    preferred_language = _preferred_language_from_metadata(task.metadata)
    metadata = {
        "workspace_id": workspace_id,
        "agent_id": worker_agent_id,
        "workspace_agent_binding_id": worker_binding_id,
        "workspace_task_id": task.id,
        ROOT_GOAL_TASK_ID: root_goal_task_id,
        "attempt_id": attempt_id,
        "conversation_scope": _conversation_scope_for_task(task.id, attempt_id),
        "source": "workspace_worker_launch",
        "created_at": created_at.isoformat(),
    }
    if preferred_language:
        metadata[PREFERRED_LANGUAGE] = preferred_language
    return {
        "id": conversation_id,
        "project_id": workspace.project_id,
        "tenant_id": workspace.tenant_id,
        "user_id": actor_user_id,
        "title": f"Workspace Worker - {task.title[:80]}",
        "status": active_status,
        "agent_config": {"selected_agent_id": worker_agent_id},
        "metadata": metadata,
        "message_count": 0,
        "created_at": created_at,
        "workspace_id": workspace_id,
        "linked_workspace_task_id": task.id,
    }


def _worker_conversation_linkage_conflict(
    conversation: _WorkerConversationProjection,
    *,
    workspace_id: str,
    task_id: str,
) -> dict[str, str] | None:
    conversation_workspace_id = _non_empty_text(conversation.workspace_id)
    linked_workspace_task_id = _non_empty_text(conversation.linked_workspace_task_id)
    has_workspace_conflict = (
        conversation_workspace_id is not None and conversation_workspace_id != workspace_id
    )
    has_task_conflict = linked_workspace_task_id is not None and linked_workspace_task_id != task_id
    if has_workspace_conflict or has_task_conflict:
        return {
            "conversation_workspace_id": conversation_workspace_id or "",
            "linked_workspace_task_id": linked_workspace_task_id or "",
            "expected_workspace_id": workspace_id,
            "expected_workspace_task_id": task_id,
        }
    return None


def _patch_worker_conversation_linkage(
    conversation: _WorkerConversationProjection,
    *,
    workspace_id: str,
    task_id: str,
) -> bool:
    changed = False
    if _non_empty_text(conversation.workspace_id) != workspace_id:
        conversation.workspace_id = workspace_id
        changed = True
    if _non_empty_text(conversation.linked_workspace_task_id) != task_id:
        conversation.linked_workspace_task_id = task_id
        changed = True
    metadata = dict(conversation.metadata or {})
    metadata_changed = False
    if not metadata.get("workspace_id"):
        metadata["workspace_id"] = workspace_id
        metadata_changed = True
    if not metadata.get("workspace_task_id"):
        metadata["workspace_task_id"] = task_id
        metadata_changed = True
    if metadata_changed:
        conversation.metadata = metadata
        changed = True
    if changed:
        conversation.updated_at = datetime.now(UTC)
    return changed


def _non_empty_text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _preferred_language_from_metadata(metadata: Mapping[str, Any] | None) -> str | None:
    if not isinstance(metadata, Mapping):
        return None
    value = metadata.get(PREFERRED_LANGUAGE)
    return value if isinstance(value, str) and value in {"en-US", "zh-CN"} else None


async def _user_preferred_language(db: AsyncSession, user_id: str | None) -> str | None:
    """Look up the stored preferred_language for a user. Returns None on any failure."""
    if not isinstance(user_id, str) or not user_id:
        return None
    try:
        from sqlalchemy import select

        from src.infrastructure.adapters.secondary.common.base_repository import (
            refresh_select_statement,
        )
        from src.infrastructure.adapters.secondary.persistence.models import User as DBUser

        result = await db.execute(
            refresh_select_statement(select(DBUser.preferred_language).where(DBUser.id == user_id))
        )
        value = result.scalar_one_or_none()
        if isinstance(value, str) and value in {"en-US", "zh-CN"}:
            return value
    except Exception:
        logger.debug("workspace_worker_launch._user_preferred_language_failed", exc_info=True)
    return None


def _metadata_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped if stripped else None


def _iter_verification_script_scope_paths(value: object) -> list[str]:
    paths: list[str] = []
    if isinstance(value, str):
        for match in _VERIFICATION_SCRIPT_SCOPE_PATH_PATTERN.finditer(value):
            path = posixpath.normpath(match.group("path").strip().lstrip("./"))
            if path and path != "." and path not in paths:
                paths.append(path)
        return paths
    if isinstance(value, Mapping):
        mapped = cast(Mapping[str, object], value)
        for key in (
            "allowed_write_scope",
            "allowed_verification_script_paths",
            "verification_script_paths",
        ):
            paths.extend(_iter_verification_script_scope_paths(mapped.get(key)))
        return list(dict.fromkeys(paths))
    if isinstance(value, (list, tuple, set)):
        for item in cast(Iterable[object], value):
            paths.extend(_iter_verification_script_scope_paths(item))
        return list(dict.fromkeys(paths))
    return paths


def _verification_script_change_allowlist(
    task_meta: Mapping[str, Any],
    node_meta: Mapping[str, Any],
) -> list[str]:
    paths: list[str] = []
    for metadata in (task_meta, node_meta):
        paths.extend(
            _iter_verification_script_scope_paths(metadata.get("allowed_verification_script_paths"))
        )
        for repair_key in (
            "current_repair_turn",
            "last_verification_judge_repair_brief",
        ):
            repair = metadata.get(repair_key)
            if not isinstance(repair, Mapping):
                continue
            mapped_repair = cast(Mapping[str, object], repair)
            brief: object = (
                mapped_repair.get("repair_brief")
                if repair_key == "current_repair_turn"
                else mapped_repair
            )
            paths.extend(_iter_verification_script_scope_paths(brief))
    return list(dict.fromkeys(paths))


def _workspace_verification_integrity_context(
    task_metadata: Mapping[str, Any] | None,
    plan_node_metadata: Mapping[str, Any] | None = None,
    *,
    task_title: str | None = None,
    task_description: str | None = None,
) -> dict[str, Any] | None:
    task_meta: Mapping[str, Any] = task_metadata if isinstance(task_metadata, Mapping) else {}
    node_meta: Mapping[str, Any] = (
        plan_node_metadata if isinstance(plan_node_metadata, Mapping) else {}
    )
    node_phase = _metadata_text(node_meta.get("iteration_phase"))
    task_phase = _metadata_text(task_meta.get("iteration_phase"))
    phase = node_phase or task_phase
    if phase is None or phase.lower() not in _WORKER_VERIFICATION_INTEGRITY_PHASES:
        return None
    allow_script_changes = (
        task_meta.get("allow_verification_script_changes") is True
        or node_meta.get("allow_verification_script_changes") is True
    )
    allow_failed_tests = (
        task_meta.get("allow_failed_tests") is True or node_meta.get("allow_failed_tests") is True
    )
    allowed_script_paths = _verification_script_change_allowlist(task_meta, node_meta)
    source = "workspace_plan_node_metadata" if node_phase else "workspace_task_metadata"
    contract_hints = [
        text[:1200]
        for text in (
            _metadata_text(task_title),
            _metadata_text(task_description),
        )
        if text
    ]
    return {
        "source": source,
        "iteration_phase": phase.lower(),
        "allow_failed_tests": allow_failed_tests,
        "allow_verification_script_changes": allow_script_changes,
        "allowed_verification_script_paths": allowed_script_paths,
        "protected_script_changes": not allow_script_changes,
        "test_contract_hints": contract_hints,
        "rule": (
            "For test/review workspace nodes, sandbox write tools must not modify "
            "test, spec, E2E, integration, audit, or benchmark scripts unless the "
            "plan node explicitly sets allow_verification_script_changes=true or a "
            "repair brief allowlists the exact verification script path."
        ),
    }


def _render_visible_verification_integrity_gate(policy: Mapping[str, Any] | None) -> str | None:
    if not policy:
        return None
    phase = _metadata_text(policy.get("iteration_phase")) or "test"
    if policy.get("allow_verification_script_changes") is True:
        return (
            "## Test/review integrity gate\n"
            f"This `{phase}` node has an explicit allow_verification_script_changes "
            "contract, but you still must preserve assertion strength and explain why "
            "each verification script change is necessary. Do not loosen checks, skip "
            "failed cases, or report success with known failed tests."
        )
    allowed_paths = policy.get("allowed_verification_script_paths")
    if isinstance(allowed_paths, list) and allowed_paths:
        rendered_paths = ", ".join(f"`{path}`" for path in cast(list[str], allowed_paths[:8]))
        return (
            "## Test/review integrity gate\n"
            f"This is a protected `{phase}` workspace node. The current repair brief "
            f"explicitly permits changing only these verification scripts: {rendered_paths}. "
            "Use that exception only to fix the listed failure; do not edit, replace, "
            "regenerate, or loosen other test, spec, E2E, integration, audit, or "
            "benchmark scripts. If the required verification still cannot run with "
            "0 failed tests, call workspace_report_blocked with the failing command "
            "and exact evidence instead of workspace_report_complete."
        )
    return (
        "## Test/review integrity gate\n"
        f"This is a protected `{phase}` workspace node. Treat any failed, failing, or "
        "non-zero test evidence as incomplete; do not call workspace_report_complete "
        "until required tests report 0 failed, unless the plan explicitly allows failed "
        "tests. Do not edit, replace, regenerate, or loosen test, spec, E2E, "
        "integration, audit, or benchmark scripts to make this node pass; tool guards "
        "will reject it and the verifier will reject the attempt. If a test appears "
        "wrong, verify product behavior from source/runtime evidence, fix product code "
        "when product behavior is wrong, or call workspace_report_blocked with the "
        "failing command and the exact contract needed. When retrying after verifier "
        "feedback about script mutation or a dirty worktree, first restore or isolate "
        "those files, rerun from clean git status, and never summarize partial results "
        "such as 13/14 or 85/86 as complete. If the node contract itself explicitly "
        "requires a partial result such as 202/203, include a structured "
        "contract_disposition:<reason> verification ref in workspace_report_complete so "
        "the verifier can judge that exception from fresh current-attempt evidence."
    )


def _render_visible_handoff_interpretation_gate(
    *,
    rendered_extra: str,
    verification_integrity: Mapping[str, Any] | None,
) -> str | None:
    if not verification_integrity or "[handoff-package]" not in rendered_extra:
        return None
    return (
        "## Handoff package interpretation\n"
        "The handoff package is historical context from previous attempts, not current "
        "acceptance evidence. Do not inherit `completed_step`, `last_report=completed`, "
        "candidate summaries, old commit_ref values, or phrases such as known test design "
        "limitation as proof that this attempt is complete. For protected test/review "
        "nodes, any handoff `test_command` or `verification_notes` containing failed, "
        "failing, non-zero, or partial results remains unresolved until this attempt "
        "produces fresh 0-failed evidence. If the current run still has a failing test, "
        "call workspace_report_blocked with the failing command and exact evidence instead "
        "of workspace_report_complete."
    )


def _workspace_delivery_cicd_context(
    workspace_metadata: Mapping[str, Any] | None,
    plan_node_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Render workspace-owned CI/CD settings into safe worker-facing context."""
    if not isinstance(workspace_metadata, Mapping):
        return None
    raw_delivery = workspace_metadata.get("delivery_cicd")
    if not isinstance(raw_delivery, Mapping):
        return None

    try:
        contract = build_pipeline_contract_from_metadata(
            workspace_metadata=dict(workspace_metadata),
            fallback_code_root=_metadata_text(workspace_metadata.get("sandbox_code_root")),
        )
    except Exception:
        logger.debug("workspace_worker_launch.delivery_cicd_context_failed", exc_info=True)
        return None

    phase = None
    if isinstance(plan_node_metadata, Mapping):
        phase = _metadata_text(plan_node_metadata.get("iteration_phase"))
    deploy = contract.deploy.to_json() if contract.deploy is not None else None
    if isinstance(deploy, dict):
        deploy = _deploy_context_with_runner_hints(deploy)
    context: dict[str, Any] = {
        "source": "workspace.metadata.delivery_cicd",
        "provider": contract.provider,
        "code_root": contract.code_root,
        "auto_deploy": contract.auto_deploy,
        "contract_source": contract.contract_source,
        "node_phase": phase.lower() if phase else None,
        "deploy": deploy,
        "instructions": [
            (
                "Treat this workspace delivery contract as the source of truth for CI/CD "
                "and deployment work."
            ),
            (
                "Do not replace the configured deployment mode with a CLI smoke check unless "
                "the contract itself says deploy.mode=cli."
            ),
        ],
    }

    if contract.provider == DRONE_PROVIDER:
        provider_config = dict(contract.provider_config)
        drone_context: dict[str, Any] = {
            "repo": _metadata_text(provider_config.get("repo") or provider_config.get("repository")),
            "branch": _metadata_text(provider_config.get("branch")),
            "target": _metadata_text(provider_config.get("target")),
            "server_url_env": _metadata_text(provider_config.get("server_url_env")),
            "token_env": _metadata_text(provider_config.get("token_env")) or "DRONE_TOKEN",
        }
        poll_interval = provider_config.get("poll_interval_seconds")
        if poll_interval is not None:
            drone_context["poll_interval_seconds"] = poll_interval
        source_control = provider_config.get("source_control")
        if isinstance(source_control, Mapping):
            drone_context["source_control"] = {
                key: value
                for key, value in {
                    "provider": _metadata_text(source_control.get("provider")),
                    "repo": _metadata_text(source_control.get("repo")),
                    "default_branch": _metadata_text(source_control.get("default_branch")),
                    "clone_url": _metadata_text(source_control.get("clone_url")),
                    "auth_token_env": _metadata_text(source_control.get("auth_token_env")),
                }.items()
                if value
            }
        context["drone"] = {key: value for key, value in drone_context.items() if value}
        context["instructions"].extend(
            [
                "Use Drone as the workspace-selected CI/CD provider.",
                (
                    "For deploy/review phases, .drone.yml must implement the configured "
                    "deploy contract and the Drone run must produce matching deployment "
                    "evidence."
                ),
                (
                    "Drone/GitHub tokens and the Drone API are host-side harness concerns. "
                    "A sandbox worker may not have DRONE_TOKEN, GITHUB_TOKEN, docker, or the "
                    "drone CLI in its environment; do not treat those sandbox-local absences "
                    "as a hard blocker. Commit or report the required .drone.yml/config state "
                    "so the platform harness can trigger and verify Drone."
                ),
                (
                    "If there are no deploy-code changes to commit, report the clean worktree "
                    "and current commit instead of fabricating a no-op change just to trigger CI."
                ),
                (
                    "For implement/test phases, the harness may trigger Drone for CI evidence; "
                    "do not treat a suppressed or fallback CLI deploy step as proof of the "
                    "configured deployment mode."
                ),
            ]
        )

    if deploy and deploy.get("enabled") is True:
        mode = str(deploy.get("mode") or "")
        if mode == "docker":
            context["instructions"].append(
                "Docker deploy mode requires Docker image build/publish semantics such as "
                "plugins/docker or explicit docker build and docker push commands. A step "
                "that only checks MEMSTACK_DEPLOY_MODE=cli is not valid docker deploy evidence."
            )
            context["instructions"].append(
                "Drone Docker steps run inside runner/plugin containers; do not use localhost "
                "or 127.0.0.1 for a registry on the host. When the configured registry is local, "
                "use the Docker runner reachable registry/image values in this brief, such as "
                "host.docker.internal:<port>, for plugins/docker repo and registry settings."
            )
            context["instructions"].append(
                "Before reporting deploy completion, inspect .drone.yml. If docker mode still "
                "uses localhost/127.0.0.1 for the registry or image, update it to the runner "
                "reachable registry/image and commit that pipeline fix."
            )
        elif mode == "kubernetes":
            context["instructions"].append(
                "Kubernetes deploy mode requires applying the configured manifests with the "
                "configured kubeconfig secret name; CLI-only smoke output is not enough."
            )

    return context


def _deploy_context_with_runner_hints(deploy: dict[str, Any]) -> dict[str, Any]:
    if str(deploy.get("mode") or "") != "docker":
        return deploy
    docker = deploy.get("docker")
    if not isinstance(docker, Mapping):
        return deploy

    docker_context = dict(docker)
    registry = _metadata_text(docker_context.get("registry"))
    registry_internal = _drone_runner_localhost_alias(registry)
    if registry_internal:
        docker_context.setdefault("registry_internal", registry_internal)

    image = _metadata_text(docker_context.get("image"))
    if image and registry and registry_internal and image.startswith(f"{registry}/"):
        docker_context.setdefault(
            "image_internal",
            f"{registry_internal}/{image.removeprefix(f'{registry}/')}",
        )

    output = dict(deploy)
    output["docker"] = docker_context
    return output


def _drone_runner_localhost_alias(value: str | None) -> str | None:
    if not value:
        return None
    prefix = ""
    rest = value
    if "://" in value:
        scheme, rest = value.split("://", 1)
        prefix = f"{scheme}://"
    for host in ("localhost", "127.0.0.1", "::1"):
        if rest == host:
            return f"{prefix}host.docker.internal"
        if rest.startswith(f"{host}:"):
            return f"{prefix}host.docker.internal:{rest.split(':', 1)[1]}"
    return None


def _render_delivery_cicd_brief(context: Mapping[str, Any]) -> str:
    provider = _metadata_text(context.get("provider")) or "unknown"
    code_root = _metadata_text(context.get("code_root"))
    phase = _metadata_text(context.get("node_phase"))
    lines = ["## Workspace delivery CI/CD contract", f"Provider: {provider}"]
    if phase:
        lines.append(f"Current node phase: {phase}")
    if code_root:
        lines.append(f"Code root: `{code_root}`")

    _append_delivery_drone_lines(lines, context.get("drone"))
    _append_delivery_deploy_lines(lines, context.get("deploy"))
    _append_delivery_instruction_lines(lines, context.get("instructions"))
    return "\n".join(lines)


def _append_delivery_drone_lines(lines: list[str], drone: object) -> None:
    if not isinstance(drone, Mapping):
        return
    repo = _metadata_text(drone.get("repo"))
    branch = _metadata_text(drone.get("branch"))
    if repo:
        lines.append(f"Drone repo: `{repo}`")
    if branch:
        lines.append(f"Drone branch: `{branch}`")


def _append_delivery_deploy_lines(lines: list[str], deploy: object) -> None:
    if not isinstance(deploy, Mapping) or deploy.get("enabled") is not True:
        return
    mode = _metadata_text(deploy.get("mode")) or "cli"
    stage = _metadata_text(deploy.get("stage")) or "deploy"
    lines.append(f"Deploy mode: {mode}")
    lines.append(f"Deploy stage: `{stage}`")
    _append_delivery_docker_lines(lines, deploy.get("docker"))


def _append_delivery_docker_lines(lines: list[str], docker: object) -> None:
    if not isinstance(docker, Mapping):
        return
    for key, label in (
        ("image", "Docker image"),
        ("image_internal", "Docker image (Drone runner)"),
        ("registry", "Docker registry"),
        ("registry_internal", "Docker registry (Drone runner)"),
        ("dockerfile", "Dockerfile"),
    ):
        value = _metadata_text(docker.get(key))
        if value:
            lines.append(f"{label}: `{value}`")
    tags = docker.get("tags")
    if isinstance(tags, list) and tags:
        safe_tags = [str(tag) for tag in tags if str(tag).strip()]
        if safe_tags:
            lines.append(f"Docker tags: {', '.join(safe_tags)}")


def _append_delivery_instruction_lines(lines: list[str], instructions: object) -> None:
    if not isinstance(instructions, list) or not instructions:
        return
    rendered = [str(item).strip() for item in instructions if str(item).strip()]
    if not rendered:
        return
    lines.append("Contract rules:")
    lines.extend(f"- {item}" for item in rendered)


def _launch_authority_actor_id(leader_agent_id: str | None) -> str:
    return leader_agent_id or WORKSPACE_PLAN_SYSTEM_ACTOR_ID


def _code_context_metadata(code_context: WorkspaceCodeContext) -> dict[str, Any]:
    return {
        "sandbox_code_root": code_context.sandbox_code_root,
        "loaded_agents_files": list(code_context.loaded_agents_paths),
        "agents_digest": code_context.agents_digest,
        "agents_excerpt": code_context.agents_excerpt,
    }


def _workspace_binding_metadata(
    *,
    workspace_id: str,
    task: WorkspaceTask,
    attempt_id: str | None,
    leader_agent_id: str | None,
) -> dict[str, str]:
    binding = {
        "workspace_id": workspace_id,
        "workspace_task_id": task.id,
    }
    workspace_agent_binding_id = task.get_workspace_agent_binding_id()
    if workspace_agent_binding_id:
        binding["workspace_agent_binding_id"] = workspace_agent_binding_id

    candidate = task.metadata.get(ROOT_GOAL_TASK_ID)
    if isinstance(candidate, str) and candidate:
        binding["root_goal_task_id"] = candidate
    if attempt_id:
        binding["attempt_id"] = attempt_id
    if leader_agent_id:
        binding["leader_agent_id"] = leader_agent_id
    return binding


def _render_workspace_binding_block(binding: Mapping[str, str]) -> str:
    lines = ["[workspace-task-binding]"]
    lines.extend(f"{key}={value}" for key, value in binding.items() if value)
    lines.append("[/workspace-task-binding]")
    return "\n".join(lines)


def _has_workspace_root_override(rendered_extra: str) -> bool:
    return any(marker in rendered_extra for marker in _WORKSPACE_ROOT_OVERRIDE_MARKERS)


def _attempt_worktree_payload(
    attempt_worktree_context: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(attempt_worktree_context, Mapping):
        return None
    payload = dict(attempt_worktree_context)
    if not payload:
        return None
    return payload


def _attempt_worktree_active_root(
    attempt_worktree_context: Mapping[str, Any] | None,
) -> str | None:
    payload = _attempt_worktree_payload(attempt_worktree_context)
    if payload is None:
        return None
    for key in ("active_root", "worktree_path"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return posixpath.normpath(value.strip().rstrip("/"))
    return None


def _attempt_worktree_setup_payload(
    attempt_worktree_context: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    payload = _attempt_worktree_payload(attempt_worktree_context)
    if payload is None:
        return None
    setup: dict[str, Any] = {
        "status": payload.get("setup_status"),
        "reason": payload.get("setup_reason"),
        "output": payload.get("setup_output"),
        "worktree_path": payload.get("worktree_path"),
        "branch_name": payload.get("branch_name"),
        "base_ref": payload.get("base_ref"),
        "attempt_id": payload.get("attempt_id"),
    }
    return {key: value for key, value in setup.items() if value is not None}


def _apply_attempt_worktree_runtime_context(
    context: dict[str, Any],
    *,
    code_context: WorkspaceCodeContext | None,
    attempt_worktree_context: Mapping[str, Any] | None,
) -> None:
    attempt_worktree_payload = _attempt_worktree_payload(attempt_worktree_context)
    active_execution_root = _attempt_worktree_active_root(attempt_worktree_payload)
    if attempt_worktree_payload is not None:
        context[ATTEMPT_WORKTREE] = attempt_worktree_payload
        if setup_payload := _attempt_worktree_setup_payload(attempt_worktree_payload):
            context[WORKTREE_SETUP] = setup_payload
    if not active_execution_root:
        return

    context[ACTIVE_EXECUTION_ROOT] = active_execution_root
    sandbox_code_root = (
        code_context.sandbox_code_root
        if code_context is not None and code_context.sandbox_code_root
        else None
    )
    if (
        sandbox_code_root is not None
        and posixpath.normpath(sandbox_code_root) == active_execution_root
    ):
        return
    context["workspace_root_override"] = {
        "source": ATTEMPT_WORKTREE,
        "rule": (
            "active_execution_root is the worker's authoritative execution root. "
            "All file tool paths, bash working directories, git operations, test "
            "outputs, generated artifacts, and temp scripts must stay under that "
            "root unless the task explicitly names another path. Treat "
            "code_context.sandbox_code_root as a baseline checkout only."
        ),
    }


def _build_worker_system_context(
    *,
    workspace_id: str,
    task: WorkspaceTask,
    attempt_id: str | None,
    leader_agent_id: str | None,
    extra_instructions: str | None = None,
    code_context: WorkspaceCodeContext | None = None,
    preferred_language: str | None = None,
    plan_node_metadata: Mapping[str, Any] | None = None,
    workspace_metadata: Mapping[str, Any] | None = None,
    attempt_worktree_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build system-level workspace context for a launched worker session."""
    binding = _workspace_binding_metadata(
        workspace_id=workspace_id,
        task=task,
        attempt_id=attempt_id,
        leader_agent_id=leader_agent_id,
    )
    context: dict[str, Any] = {
        "context_type": _WORKSPACE_APP_CONTEXT_TYPE,
        "workspace_binding": binding,
        "tool_protocol": {
            "native_tool_calls_required": True,
            "instruction": _NATIVE_TOOL_PROTOCOL_GUARD,
            "forbidden_text_markers": [
                "[TOOL_CALL]",
                "[/TOOL_CALL]",
                "{tool => ...}",
                "<minimax:tool_call>",
                "<invoke name=...>",
            ],
        },
        "reporting": {
            "required_identifiers": {
                "task_id": binding.get("workspace_task_id", ""),
                "attempt_id": binding.get("attempt_id", ""),
                "leader_agent_id": binding.get("leader_agent_id", ""),
            },
            "completion_contract": {
                "required_verification_refs": list(WORKER_COMPLETION_REQUIRED_PREFLIGHT_REFS),
                "required_change_evidence": (
                    "For any task that edits files or produces code/docs, include "
                    "commit_ref:<sha> if committed, otherwise "
                    "git_diff_summary:<changed files and verification state>."
                ),
                "harness_pipeline_gate": (
                    "For software implement/test/deploy/review tasks, the workspace harness "
                    "will run the workspace-selected CI/CD provider after your completion "
                    "report. Do not treat "
                    "self-reported tests as the final gate; provide enough context for the "
                    "harness pipeline and wait for durable pipeline evidence in follow-up work."
                ),
                "tool": "workspace_report_complete",
                "argument": "verifications",
                "example": (
                    "workspace_report_complete("
                    "verifications=['preflight:read-progress', 'preflight:git-status', "
                    "'git_diff_summary:changed src/app.ts and tests pass', ...])"
                ),
                "rule": (
                    "Do not report completed unless every required_verification_ref is "
                    "present verbatim in the verifications argument, plus a commit_ref or "
                    "git_diff_summary when files changed."
                ),
            },
            "instructions": [
                "Execute the assigned workspace task autonomously.",
                "Call workspace_report_progress periodically during long-running work.",
                "Call workspace_report_complete once when finished successfully.",
                (
                    "The completion report MUST include these exact verification refs: "
                    f"{', '.join(WORKER_COMPLETION_REQUIRED_PREFLIGHT_REFS)}."
                ),
                (
                    "If you changed files, workspace_report_complete MUST also include "
                    "commit_ref:<sha> or git_diff_summary:<changed files and verification state> "
                    "in artifacts or verifications."
                ),
                (
                    "If you include commit_ref:<sha>, first run git status --short and make "
                    "sure it is empty. Stage every intended tracked and untracked file before "
                    "committing; do not report completion with a dirty worktree."
                ),
                (
                    "For deploy/review work, include preview URL, health-check command/result, "
                    "and rollback or stop notes when available; final acceptance requires "
                    "workspace-selected pipeline/deployment evidence."
                ),
                "Call workspace_report_blocked if a hard blocker cannot be recovered.",
            ],
        },
        "code_quality_policy": {
            "source": "workspace_generic_quality_gate",
            "instructions": list(_WORKER_CODE_QUALITY_INSTRUCTIONS),
        },
        "artifact_write_policy": {
            "max_single_write_chars": WORKER_MAX_SINGLE_WRITE_CHARS,
            "max_single_bash_command_chars": WORKER_MAX_SINGLE_BASH_COMMAND_CHARS,
            "instructions": [
                (
                    "Never create or replace a source file, page, generated fixture, or long "
                    "document with one complete write call, bash heredoc, or inline Python "
                    "script. This rule is mandatory even when the file appears short enough."
                ),
                (
                    "For new files, write a tiny skeleton first, then append focused sections "
                    f"in chunks under {WORKER_RECOMMENDED_WRITE_CHUNK_CHARS} characters."
                ),
                (
                    "For existing files, prefer edit calls that replace one bounded function, "
                    "component, import block, or JSX section at a time. Do not pass the whole "
                    "file as old_string or new_string."
                ),
                (
                    "Do not write temp scripts whose embedded string is the target source "
                    "file content; that is the same failure mode as a giant heredoc."
                ),
                (
                    "If a write/edit tool reports truncated arguments or incomplete JSON, "
                    "do not retry using bash, Python, or a full-file write. Switch immediately "
                    "to smaller chunks via edit/append and record the failed attempt as evidence."
                ),
                "Split very large documentation into multiple focused files when appropriate.",
            ],
        },
        "shell_execution_policy": {
            "instructions": [
                (
                    "Never run dev servers, watch commands, or other long-lived processes "
                    "in the foreground inside bash tool calls."
                ),
                (
                    "For service verification, never use a bare background command such as "
                    "`npm run dev &` or `cd backend && npm run dev &`; the sandbox harness "
                    "may keep waiting for inherited streams or kill the process on timeout."
                ),
                (
                    "Start services with a supervised one-shot command: create a worktree-local "
                    "logs directory, run `setsid sh -lc '<cd service dir && exec start command>'` "
                    "or `nohup sh -lc '<cd service dir && exec start command>'` inside a "
                    "subshell, redirect stdout/stderr to that log, redirect stdin from "
                    "/dev/null, write the PID to a worktree-local pid file from the same "
                    "subshell, and let the bash call return immediately. Then run a separate "
                    "short curl/health-check command."
                ),
                (
                    "For Playwright/browser E2E, first try the existing browser cache or "
                    "`npx playwright install chromium`. Do not run `playwright install "
                    "--with-deps` unless an explicit OS dependency error proves it is "
                    "needed; if browser installation times out, record the blocker and "
                    "fallback HTTP/build evidence."
                ),
                (
                    "If a port is already in use, treat it as an existing service candidate: "
                    "probe /health or the documented endpoint before trying another port. If "
                    "you rebuilt or changed code after that service started, stop the stale PID "
                    "and restart the service before rerunning browser/E2E verification."
                ),
                (
                    "When setting E2E_BASE_URL or similar test URLs, use an explicit valid URL "
                    "such as http://127.0.0.1:3002; assigning an empty string is not the same "
                    "as unsetting the variable and can make Playwright navigate to an invalid URL."
                ),
                (
                    "Do not rely on ss being installed; use curl probes, ps, pgrep, lsof, "
                    "or netstat when available."
                ),
            ]
        },
    }
    if preferred_language in {"en-US", "zh-CN"}:
        context[PREFERRED_LANGUAGE] = preferred_language
    verification_integrity = _workspace_verification_integrity_context(
        task.metadata,
        plan_node_metadata,
        task_title=task.title,
        task_description=task.description,
    )
    if verification_integrity is not None:
        context["workspace_verification_integrity"] = verification_integrity
    delivery_cicd = _workspace_delivery_cicd_context(
        workspace_metadata,
        plan_node_metadata,
    )
    if delivery_cicd is not None:
        context["delivery_cicd"] = delivery_cicd
    harness_context = _task_harness_context(task)
    if harness_context:
        context["harness"] = harness_context

    if code_context is not None and code_context.sandbox_code_root:
        sandbox_code_root = code_context.sandbox_code_root
        code_context_payload: dict[str, Any] = {
            "sandbox_code_root": sandbox_code_root,
            "loaded_agents_files": list(code_context.loaded_agents_paths),
            "agents_digest": code_context.agents_digest,
            "required_tool_workdir": sandbox_code_root,
            "bootstrap_command": f"mkdir -p {sandbox_code_root} && cd {sandbox_code_root}",
            "rule": (
                "Before the first file operation or shell command, check additional_instructions "
                "for a worktree_path. If present, it overrides sandbox_code_root: use that "
                "worktree as the working directory and make every file tool file_path start with "
                "that worktree_path. Bash commands must also start from the selected root and "
                "must not create, edit, copy, move, or remove project artifacts outside it. If "
                "no worktree_path is present, ensure sandbox_code_root exists and make it the "
                "working directory. Perform repository inspection, file edits, terminal "
                "commands, git diff, and tests from the selected root. Do not create project "
                "files directly under /workspace or another sibling directory. "
                "When a worktree_path is present, treat sandbox_code_root as a baseline checkout "
                "for historical context only; do not read current reports, screenshots, git "
                "state, or test outputs from sandbox_code_root. If required evidence is missing "
                "from the worktree, regenerate it inside the worktree or report the blocker. "
                "Ignore unrelated files outside the selected root unless the task explicitly "
                "asks for them. Read and follow the listed AGENTS.md files before decomposing "
                "or executing the task."
            ),
        }
        if code_context.agents_files:
            code_context_payload["agents_files"] = [
                {
                    "sandbox_path": agents_file.sandbox_path,
                    "content": agents_file.content,
                    "truncated": agents_file.truncated,
                }
                for agents_file in code_context.agents_files
            ]
        if code_context.warnings:
            code_context_payload["warnings"] = list(code_context.warnings)
        context["code_context"] = code_context_payload

    _apply_attempt_worktree_runtime_context(
        context,
        code_context=code_context,
        attempt_worktree_context=attempt_worktree_context,
    )

    if extra_instructions:
        rendered_extra = _render_workspace_placeholders(extra_instructions.strip(), code_context)
        if rendered_extra:
            context["additional_instructions"] = rendered_extra
            if (
                _has_workspace_root_override(rendered_extra)
                and "workspace_root_override" not in context
            ):
                context["workspace_root_override"] = {
                    "source": "additional_instructions",
                    "rule": (
                        "The rendered worktree_path overrides code_context.sandbox_code_root. "
                        "All file tool file_path arguments, bash working directories, bash "
                        "writes, temp scripts, git operations, test outputs, and generated "
                        "artifacts must stay under that worktree_path unless the task "
                        "explicitly names another path. Treat code_context.sandbox_code_root "
                        "as a baseline checkout only; do not inspect it for current attempt "
                        "reports, screenshots, git status, or test output."
                    ),
                }

    return context


def _task_harness_context(task: WorkspaceTask) -> dict[str, Any] | None:
    metadata = getattr(task, "metadata", None)
    if not isinstance(metadata, Mapping):
        return None

    feature_id = metadata.get("harness_feature_id")
    checks = _normalize_preflight_checks(metadata.get("preflight_checks"))
    if not isinstance(feature_id, str) and not checks:
        return None

    return {
        "feature_id": feature_id if isinstance(feature_id, str) else None,
        "preflight_checks": checks,
        "required_evidence_prefix": "preflight:",
        "instructions": [
            "Read the feature checkpoint, handoff package, and current git status before editing.",
            "Run or inspect every required preflight check before reporting completion.",
            (
                "Record each completed preflight check as an execution verification "
                "using the form preflight:<check_id>; pass those refs in "
                "workspace_report_complete(verifications=[...])."
            ),
            "Report blocked with the failing check_id when a required preflight cannot pass.",
        ],
    }


async def _load_plan_node_metadata_for_task(
    db: AsyncSession,
    task: WorkspaceTask,
) -> dict[str, Any]:
    metadata = task.metadata if isinstance(task.metadata, Mapping) else {}
    node_id = metadata.get("workspace_plan_node_id")
    if not isinstance(node_id, str) or not node_id:
        return {}
    plan_id = metadata.get("workspace_plan_id")

    from sqlalchemy import select

    from src.infrastructure.adapters.secondary.persistence.models import PlanNodeModel

    stmt = select(PlanNodeModel.metadata_json).where(PlanNodeModel.id == node_id)
    if isinstance(plan_id, str) and plan_id:
        stmt = stmt.where(PlanNodeModel.plan_id == plan_id)
    result = await db.execute(stmt)
    value = result.scalar_one_or_none()
    node_metadata = dict(value) if isinstance(value, Mapping) else {}
    if not node_metadata:
        return {}

    source_metadata: dict[str, Any] = {}
    source_node_id = _metadata_text(node_metadata.get("repair_for_node_id"))
    seen_source_ids: set[str] = set()
    for _ in range(WORKER_REPAIR_SOURCE_METADATA_MAX_DEPTH):
        if not source_node_id or source_node_id in seen_source_ids:
            break
        seen_source_ids.add(source_node_id)
        source_stmt = select(PlanNodeModel.metadata_json).where(PlanNodeModel.id == source_node_id)
        if isinstance(plan_id, str) and plan_id:
            source_stmt = source_stmt.where(PlanNodeModel.plan_id == plan_id)
        source_result = await db.execute(source_stmt)
        source_value = source_result.scalar_one_or_none()
        candidate = dict(source_value) if isinstance(source_value, Mapping) else {}
        if not candidate:
            break
        source_metadata = candidate
        source_node_id = _metadata_text(candidate.get("repair_for_node_id"))
    return _effective_repair_plan_node_metadata(node_metadata, source_metadata)


def _effective_repair_plan_node_metadata(
    node_metadata: Mapping[str, Any],
    source_metadata: Mapping[str, Any],
) -> dict[str, Any]:
    metadata = dict(node_metadata)
    if metadata.get("allow_verification_script_changes") is True:
        return metadata

    source_phase = _metadata_text(source_metadata.get("iteration_phase"))
    explicit_source_phase = _metadata_text(metadata.get("repair_source_iteration_phase"))
    effective_source_phase = explicit_source_phase or source_phase
    if effective_source_phase is None:
        return metadata

    normalized_source_phase = effective_source_phase.lower()
    metadata.setdefault("repair_source_iteration_phase", normalized_source_phase)
    if normalized_source_phase not in _WORKER_VERIFICATION_INTEGRITY_PHASES:
        return metadata

    current_phase = _metadata_text(metadata.get("iteration_phase"))
    if current_phase is None or current_phase.lower() not in _WORKER_VERIFICATION_INTEGRITY_PHASES:
        metadata["iteration_phase"] = normalized_source_phase
    return metadata


def _normalize_preflight_checks(raw_checks: object) -> list[dict[str, Any]]:
    if not isinstance(raw_checks, list):
        return []
    checks: list[dict[str, Any]] = []
    for raw_check in raw_checks:
        if not isinstance(raw_check, Mapping):
            continue
        check_id = raw_check.get("check_id")
        if not isinstance(check_id, str) or not check_id:
            continue
        checks.append(
            {
                "check_id": check_id,
                "kind": str(raw_check.get("kind") or "custom"),
                "command": raw_check.get("command")
                if isinstance(raw_check.get("command"), str)
                else None,
                "required": bool(raw_check.get("required", True)),
                "status": str(raw_check.get("status") or "pending"),
            }
        )
    return checks


def _render_workspace_placeholders(
    instructions: str,
    code_context: WorkspaceCodeContext | None,
) -> str:
    if code_context is None or not code_context.sandbox_code_root:
        return instructions
    rendered = instructions.replace("${sandbox_code_root}", code_context.sandbox_code_root)
    return _rewrite_command_roots_for_attempt_worktree(rendered, code_context.sandbox_code_root)


def _rewrite_command_roots_for_attempt_worktree(instructions: str, sandbox_code_root: str) -> str:
    worktree_path = _extract_rendered_worktree_path(instructions)
    if not worktree_path:
        return instructions
    sandbox_root = sandbox_code_root.rstrip("/")
    if not sandbox_root:
        return instructions
    worktree_root = posixpath.normpath(worktree_path.strip()).rstrip("/")
    if not worktree_root or worktree_root == sandbox_root:
        return instructions

    return "\n".join(
        _rewrite_command_line_root(line, sandbox_root=sandbox_root, worktree_root=worktree_root)
        for line in instructions.splitlines()
    )


def _extract_rendered_worktree_path(instructions: str) -> str | None:
    for line in instructions.splitlines():
        stripped = line.strip()
        if not stripped.startswith("worktree_path="):
            continue
        value = stripped.split("=", 1)[1].strip()
        if value:
            return value
    return None


def _rewrite_command_line_root(line: str, *, sandbox_root: str, worktree_root: str) -> str:
    stripped = line.lstrip()
    indent = line[: len(line) - len(stripped)]
    for key in ("test_command=", "init_command="):
        if stripped.startswith(key):
            command = stripped[len(key) :]
            return (
                f"{indent}{key}{_rewrite_shell_command_root(command, sandbox_root, worktree_root)}"
            )

    marker = " command="
    if marker in line:
        prefix, command = line.split(marker, 1)
        return (
            f"{prefix}{marker}{_rewrite_shell_command_root(command, sandbox_root, worktree_root)}"
        )
    return line


def _rewrite_shell_command_root(command: str, sandbox_root: str, worktree_root: str) -> str:
    if sandbox_root not in command:
        return command
    return command.replace(sandbox_root, worktree_root)


def _build_worker_brief(
    *,
    workspace_id: str,
    task: WorkspaceTask,
    attempt_id: str | None,
    leader_agent_id: str | None,
    extra_instructions: str | None = None,
    code_context: WorkspaceCodeContext | None = None,
    plan_node_metadata: Mapping[str, Any] | None = None,
    workspace_metadata: Mapping[str, Any] | None = None,
    attempt_worktree_context: Mapping[str, Any] | None = None,
) -> str:
    """Compose the visible task brief for the worker agent.

    Operational policy, code-root context, AGENTS.md content, and reporting
    requirements are injected as system model context by
    :func:`_build_worker_system_context`. Attempt-scoped checkpoint/worktree
    instructions are also rendered into the visible brief because they must
    override the default sandbox checkout before any file operation.
    """
    description = (task.description or "").strip()
    binding = _workspace_binding_metadata(
        workspace_id=workspace_id,
        task=task,
        attempt_id=attempt_id,
        leader_agent_id=leader_agent_id,
    )
    rendered_extra = (
        _render_workspace_placeholders(extra_instructions.strip(), code_context)
        if extra_instructions
        else ""
    )
    should_surface_workspace_root = _has_workspace_root_override(rendered_extra)
    active_worktree_path = _attempt_worktree_active_root(attempt_worktree_context) or (
        _extract_rendered_worktree_path(rendered_extra) if should_surface_workspace_root else None
    )

    visible_intro = " ".join(
        (
            "Complete the assigned workspace task.",
            "Workspace execution policy and reporting requirements are provided",
            "as system context for this turn.",
        )
    )
    sections: list[str] = [
        visible_intro,
        _render_workspace_binding_block(binding),
        f"## Task title\n{task.title}",
    ]
    if active_worktree_path:
        baseline_root = (
            f"`{code_context.sandbox_code_root}`"
            if code_context is not None and code_context.sandbox_code_root
            else "the sandbox code root"
        )
        sections.append(
            "## Active attempt root - highest priority\n"
            f"The current attempt root is `{active_worktree_path}`. This overrides "
            f"{baseline_root}. Treat task descriptions, verifier summaries, repair briefs, "
            "handoff text, and recalled memories that mention code root, sandbox_code_root, "
            "main checkout, or master checkout as historical context only. Do not inspect "
            "those baseline paths for current reports, screenshots, git status, test output, "
            "or source files. Run project reads, edits, tests, reports, git status, commits, "
            "and evidence collection from the current attempt root. If a required artifact is "
            "missing there, regenerate it there or report a blocker instead of probing the "
            "baseline checkout. Do not switch the attempt worktree to main/master or push/merge "
            "from the sandbox; leave final changes on the attempt branch and report commit_ref "
            "so the platform harness can publish and merge after verification."
        )
    if description:
        sections.append(f"## Task description\n{description}")
    delivery_cicd = _workspace_delivery_cicd_context(
        workspace_metadata,
        plan_node_metadata,
    )
    if delivery_cicd is not None:
        sections.append(_render_delivery_cicd_brief(delivery_cicd))
    sections.append(
        "## Artifact write discipline\n"
        "Never use bash heredocs, inline Python scripts, or one-shot write calls to create "
        "a full source file, page, fixture, or long document. First create a tiny skeleton, "
        "then use edit or write mode='append' in small sections. Keep every write/edit "
        f"payload under {WORKER_RECOMMENDED_WRITE_CHUNK_CHARS} characters; the hard write "
        f"limit is {WORKER_MAX_SINGLE_WRITE_CHARS} characters and any bash command under "
        f"{WORKER_MAX_SINGLE_BASH_COMMAND_CHARS} characters. If a tool reports truncated "
        "arguments, do not retry with the same shape; immediately switch to smaller "
        "edit/append chunks."
    )
    sections.append(
        "## Shell execution discipline\n"
        "Do not run dev servers, watch commands, or other long-lived processes in the "
        "foreground. Do not use bare background commands such as `npm run dev &` or "
        "`cd backend && npm run dev &`; the sandbox harness may wait on inherited streams "
        "or kill the process on timeout. Start services with a supervised one-shot command, "
        "for example: `mkdir -p logs && (setsid sh -lc 'cd backend && exec npm run dev' > "
        "logs/backend.log 2>&1 < /dev/null & echo $! > logs/backend.pid)`, then verify "
        "with a separate short health-check command. If `setsid` is unavailable, use the "
        "same subshell shape with `nohup sh -lc`. If a port is already in use, probe the "
        "existing service before starting another one. Do not assume `ss` exists."
    )
    if code_context is not None and code_context.sandbox_code_root:
        code_root = code_context.sandbox_code_root
        sections.append(
            "## Code root discipline\n"
            f"Use `{code_root}` as the project root only when this brief does not provide a "
            "more specific attempt worktree_path. If a Workspace checkpoint/worktree section "
            "below lists a worktree_path, cd into that worktree and use it as the root for "
            "repository inspection, file edits, terminal commands, git status, commits, and "
            "tests; every file tool file_path must also start with that worktree_path, and "
            "bash commands must not create temp scripts, reports, commits, or copied "
            "artifacts outside that worktree. When a worktree_path is provided, "
            f"`{code_root}` is only a baseline checkout for historical context; do not read "
            "current reports, screenshots, git state, or test output from it. If required "
            "evidence is missing in the worktree, regenerate it inside the worktree or report "
            "the blocker. "
            "Otherwise, before creating, reading, editing, or testing project files, "
            f"run `mkdir -p {code_root} && cd {code_root}` or pass the same directory as the "
            "tool working directory. Do not place `package.json`, source files, tests, build "
            "output, or service code directly under `/workspace` or a sibling directory "
            "unless the task explicitly says to do so."
        )
    verification_integrity = _workspace_verification_integrity_context(
        task.metadata,
        plan_node_metadata,
        task_title=task.title,
        task_description=task.description,
    )
    if rendered_extra:
        if rendered_extra and should_surface_workspace_root:
            sections.append(
                "## Workspace checkpoint and worktree\n"
                f"{rendered_extra}\n\n"
                "If this section provides a worktree_path or [worktree-setup] worktree_path, "
                "use that path as the task root before any project read, edit, test, git "
                "status, or commit operation. For file tools, every absolute file_path must "
                "start with that worktree_path; never pass a main-checkout path for "
                "attempt-scoped files. For bash, do not write temp scripts, generated "
                "reports, commits, or copied artifacts outside that worktree. Do not edit "
                "or inspect the main sandbox checkout for current reports, screenshots, git "
                "state, or test output from this attempt."
            )
            if handoff_gate := _render_visible_handoff_interpretation_gate(
                rendered_extra=rendered_extra,
                verification_integrity=verification_integrity,
            ):
                sections.append(handoff_gate)
    if verification_integrity_section := _render_visible_verification_integrity_gate(
        verification_integrity
    ):
        sections.append(verification_integrity_section)
    sections.append(
        "## Code quality gate\n"
        "Before editing, read the applicable AGENTS.md/project guidance and inspect nearby "
        "patterns. Keep changes scoped to this task and prefer existing architecture, shared "
        "modules, shared types, and repository utilities. Do not duplicate frontend/backend "
        "business logic or schema/type definitions. Schema changes need reproducible "
        "migrations or rollback notes; dependency changes need matching lockfile updates. "
        "For auth, API keys, tokens, or secrets, avoid plaintext storage/logging and include "
        "focused security verification. For frontend/backend contracts, verify request, "
        "response, error state, and shared-calculation agreement. Do not silently show mock "
        "or fake data in production paths; use a real data source, explicit empty/error "
        "state, or clearly labeled demo data. Treat explicit repository guidance as hard "
        "acceptance criteria for code, docs, tests, generated artifacts, and reports; if "
        "guidance forbids a pattern or content form, do not introduce it. When guidance "
        "exists, include project_guidance:checked:<path-or-summary> in completion evidence. "
        "For test, review, audit, benchmark, and E2E nodes, never weaken or replace the "
        "verification script just to make evidence pass; fix the product behavior, preserve "
        "the original assertion strength, or report the remaining failure honestly. "
        "Because other workspace nodes may run in the same worktree, never sweep unrelated "
        "dirty files into your commit; use explicit git add <path> for owned files only and "
        "do not use git add -A, git add ., or git commit -a when unrelated changes exist."
    )
    sections.append(
        "## Completion gate\n"
        "Before calling workspace_report_complete, include these exact verification refs in "
        "the verifications argument: "
        f"{', '.join(WORKER_COMPLETION_REQUIRED_PREFLIGHT_REFS)}. "
        "Add the concrete test/build/browser evidence refs after them. If you changed "
        "files, also include commit_ref:<sha> or git_diff_summary:<changed files and "
        "verification state> in artifacts or verifications; otherwise the verifier will "
        "reject the attempt. If you include commit_ref:<sha>, run `git status --short` "
        "after the commit and do not call workspace_report_complete unless it is empty; "
        "stage intended untracked files before committing. For software delivery phases, "
        "the harness will run the final workspace-selected CI/CD gate after your report, so "
        "include preview, health, and rollback details when they exist."
    )

    return "\n\n".join(sections)


async def _is_on_cooldown(conversation_id: str) -> bool:
    """Return True if a launch was recently scheduled for this conversation."""
    from src.infrastructure.agent.state.agent_worker_state import get_redis_client

    try:
        redis = await get_redis_client()
    except Exception:
        return False
    key = f"workspace:worker_launch:cooldown:{conversation_id}"
    try:
        # SET NX EX — atomic claim. Returns truthy on success (no prior key).
        claimed = await redis.set(key, "1", nx=True, ex=WORKER_LAUNCH_COOLDOWN_SECONDS)
    except Exception:
        return False
    return not claimed


async def _refresh_launch_cooldown(conversation_id: str | None) -> None:
    """Keep the duplicate-launch guard alive while a worker stream is active."""

    if not conversation_id:
        return
    from src.infrastructure.agent.state.agent_worker_state import get_redis_client

    try:
        redis = await get_redis_client()
        key = f"workspace:worker_launch:cooldown:{conversation_id}"
        await redis.expire(key, WORKER_LAUNCH_COOLDOWN_SECONDS)
    except Exception:
        logger.debug(
            "workspace_worker_launch.cooldown_refresh_failed",
            extra={
                "event": "workspace_worker_launch.cooldown_refresh_failed",
                "conversation_id": conversation_id,
            },
            exc_info=True,
        )


async def _refresh_worker_agent_running_marker(
    conversation_id: str | None,
    attempt_id: str | None,
) -> None:
    """Keep Redis agent-running liveness present for long workspace tool calls."""

    if not conversation_id or not attempt_id:
        return
    from src.infrastructure.agent.state.agent_worker_state import get_redis_client

    try:
        redis = await get_redis_client()
        if await redis.exists(f"agent:finished:{conversation_id}"):
            return
        await redis.setex(
            f"agent:running:{conversation_id}",
            WORKER_LAUNCH_COOLDOWN_SECONDS,
            attempt_id,
        )
    except Exception:
        logger.debug(
            "workspace_worker_launch.running_marker_refresh_failed",
            extra={
                "event": "workspace_worker_launch.running_marker_refresh_failed",
                "conversation_id": conversation_id,
                "attempt_id": attempt_id,
            },
            exc_info=True,
        )


def _decode_redis_text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        return value
    return str(value)


def _append_worker_instruction_note(existing: str | None, note: str | None) -> str | None:
    if not note:
        return existing
    if not existing:
        return note.strip()
    return f"{existing.rstrip()}\n\n{note.strip()}"


async def _agent_finished_message_id(
    redis_client: object | None,
    conversation_id: str | None,
) -> str | None:
    if redis_client is None or not conversation_id:
        return None
    try:
        redis = cast(Any, redis_client)
        return _decode_redis_text(await redis.get(f"agent:finished:{conversation_id}"))
    except Exception:
        logger.debug(
            "workspace_worker_launch.finished_state_lookup_failed",
            extra={
                "event": "workspace_worker_launch.finished_state_lookup_failed",
                "conversation_id": conversation_id,
            },
            exc_info=True,
        )
        return None


async def _agent_running_exists(
    redis_client: object | None,
    conversation_id: str | None,
) -> bool:
    if redis_client is None or not conversation_id:
        return False
    try:
        redis = cast(Any, redis_client)
        return bool(await redis.exists(f"agent:running:{conversation_id}"))
    except Exception:
        logger.debug(
            "workspace_worker_launch.running_state_lookup_failed",
            extra={
                "event": "workspace_worker_launch.running_state_lookup_failed",
                "conversation_id": conversation_id,
            },
            exc_info=True,
        )
        return False


async def _clear_reused_worker_session_markers(
    redis_client: object | None,
    conversation_id: str | None,
) -> None:
    """Remove per-run Redis sentinels before appending a new repair turn."""

    if redis_client is None or not conversation_id:
        return
    try:
        redis = cast(Any, redis_client)
        await redis.delete(
            f"agent:finished:{conversation_id}",
            f"workspace:worker_launch:cooldown:{conversation_id}",
        )
    except Exception:
        logger.debug(
            "workspace_worker_launch.reuse_marker_clear_failed",
            extra={
                "event": "workspace_worker_launch.reuse_marker_clear_failed",
                "conversation_id": conversation_id,
            },
            exc_info=True,
        )


def _stream_message_id_from_event(event: Mapping[str, Any]) -> str | None:
    if event.get("type") != "message":
        return None
    data = event.get("data")
    if not isinstance(data, Mapping):
        return None
    message_id = data.get("id") or data.get("message_id")
    return message_id if isinstance(message_id, str) and message_id else None


def _should_stop_orphaned_worker_stream(
    *,
    finished_message_id: str | None,
    stream_message_id: str | None,
    running_exists: bool,
    idle_seconds: float,
    orphan_grace_seconds: int = WORKER_STREAM_ORPHAN_GRACE_SECONDS,
) -> tuple[bool, str | None]:
    if finished_message_id and (
        stream_message_id is None or finished_message_id == stream_message_id
    ):
        return True, "agent_finished_without_terminal_event"
    if not running_exists and idle_seconds >= max(1, orphan_grace_seconds):
        return True, "agent_not_running_stream_idle"
    return False, None


async def _publish_worker_launch_heartbeat(
    *,
    workspace_id: str,
    task_id: str,
    attempt_id: str | None,
    root_goal_task_id: str,
    conversation_id: str | None,
    actor_user_id: str,
    worker_agent_id: str,
    leader_agent_id: str | None,
) -> None:
    """Publish a process-owned heartbeat while a launched worker stream is active."""
    if not attempt_id:
        return
    try:
        from src.domain.model.workspace.wtp_envelope import WtpEnvelope, WtpVerb
        from src.infrastructure.agent.workspace.workspace_supervisor import (
            publish_envelope_default,
        )

        metadata: dict[str, Any] = {
            "actor_user_id": actor_user_id,
            "worker_agent_id": worker_agent_id,
            "source": "workspace_worker_launch",
        }
        if leader_agent_id:
            metadata["leader_agent_id"] = leader_agent_id
        if conversation_id:
            metadata["worker_conversation_id"] = conversation_id

        envelope = WtpEnvelope(
            verb=WtpVerb.TASK_HEARTBEAT,
            workspace_id=workspace_id,
            task_id=task_id,
            attempt_id=attempt_id,
            root_goal_task_id=root_goal_task_id or None,
            payload={},
            extra_metadata=metadata,
        )
        await publish_envelope_default(envelope)
        await _refresh_launch_cooldown(conversation_id)
        await _refresh_worker_agent_running_marker(conversation_id, attempt_id)
    except Exception:
        logger.debug(
            "workspace_worker_launch.heartbeat_publish_failed",
            extra={
                "event": "workspace_worker_launch.heartbeat_publish_failed",
                "workspace_id": workspace_id,
                "task_id": task_id,
                "attempt_id": attempt_id,
            },
            exc_info=True,
        )


async def _worker_launch_heartbeat_loop(
    *,
    stop_event: asyncio.Event,
    workspace_id: str,
    task_id: str,
    attempt_id: str | None,
    root_goal_task_id: str,
    conversation_id: str | None,
    actor_user_id: str,
    worker_agent_id: str,
    leader_agent_id: str | None,
    interval_seconds: int = WORKER_LAUNCH_HEARTBEAT_SECONDS,
) -> None:
    """Keep recovery/watchdog liveness fresh for a still-running worker stream."""
    interval = max(15, int(interval_seconds))
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
            return
        except TimeoutError:
            pass
        await _publish_worker_launch_heartbeat(
            workspace_id=workspace_id,
            task_id=task_id,
            attempt_id=attempt_id,
            root_goal_task_id=root_goal_task_id,
            conversation_id=conversation_id,
            actor_user_id=actor_user_id,
            worker_agent_id=worker_agent_id,
            leader_agent_id=leader_agent_id,
        )


async def _report_pre_stream_launch_failure(
    *,
    workspace_id: str,
    root_goal_task_id: str,
    task_id: str,
    attempt_id: str | None,
    conversation_id: str | None,
    actor_user_id: str,
    worker_agent_id: str,
    leader_agent_id: str | None,
    launch_state: str,
    summary: str,
    apply_fn: Callable[..., Awaitable[Any]],
) -> None:
    """Close a pre-stream worker launch attempt so the harness can retry."""

    if not attempt_id or not root_goal_task_id:
        return
    await _report_terminal(
        workspace_id=workspace_id,
        root_goal_task_id=root_goal_task_id,
        task_id=task_id,
        attempt_id=attempt_id,
        conversation_id=conversation_id,
        actor_user_id=actor_user_id,
        worker_agent_id=worker_agent_id,
        leader_agent_id=leader_agent_id,
        report_type="blocked",
        summary=summary,
        apply_fn=apply_fn,
    )
    await _patch_task_launch_state(
        workspace_id=workspace_id,
        task_id=task_id,
        actor_user_id=actor_user_id,
        leader_agent_id=leader_agent_id,
        launch_state=launch_state,
    )


async def launch_worker_session(  # noqa: C901, PLR0911, PLR0912, PLR0915
    *,
    workspace_id: str,
    task: WorkspaceTask,
    worker_agent_id: str,
    actor_user_id: str,
    leader_agent_id: str | None = None,
    attempt_id: str | None = None,
    extra_instructions: str | None = None,
    reuse_conversation_id: str | None = None,
    repair_brief_prompt: str | None = None,
    preferred_language: str | None = None,
    attempt_worktree_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Open or reuse a worker conversation and stream the task brief.

    Returns a structured outcome dict::

        {
            "launched": bool,
            "conversation_id": str | None,
            "attempt_id": str | None,
            "reason": "completed" | "blocked" | "no_terminal_event"
                      | "cooling_down" | "workspace_not_found"
                      | "stream_failed" | "worker_agent_id_missing"
                      | "task_id_missing",
        }

    Errors during streaming are logged and reflected as ``stream_failed``
    rather than raised, because this is invoked as a background task whose
    failure must not affect the assignment HTTP response.

    Completion detection: the stream is parsed for in-band ``error`` events
    (mirroring :class:`WorkspaceMentionRouter`). On ``error`` the attempt is
    pushed through ``apply_workspace_worker_report`` with ``report_type="blocked"``.
    A plain stream ``complete`` without an explicit workspace terminal report
    is converted into a completed candidate report so the verifier can accept
    or reject it. A stream that exits or becomes orphaned without ``complete`` /
    ``error`` is reported as ``blocked`` immediately so launcher-owned
    heartbeats cannot mask the dead worker session from recovery.
    """
    if not worker_agent_id:
        return {
            "launched": False,
            "conversation_id": None,
            "attempt_id": None,
            "reason": "worker_agent_id_missing",
        }
    if not task or not task.id:
        return {
            "launched": False,
            "conversation_id": None,
            "attempt_id": None,
            "reason": "task_id_missing",
        }

    # Lazy imports to avoid a heavy startup graph for tests that mock-out the
    # scheduler. None of these modules are needed unless we actually launch.
    from src.application.services.agent_service import AgentService
    from src.application.services.workspace_task_command_service import (
        WorkspaceTaskCommandService,
    )
    from src.application.services.workspace_task_service import (
        WorkspaceTaskAuthorityContext,
        WorkspaceTaskService,
    )
    from src.configuration.di_container import DIContainer
    from src.configuration.factories import create_llm_client
    from src.domain.model.agent import Conversation, ConversationStatus
    from src.infrastructure.adapters.secondary.persistence.database import (
        async_session_factory,
    )
    from src.infrastructure.adapters.secondary.persistence.sql_workspace_agent_repository import (
        SqlWorkspaceAgentRepository,
    )
    from src.infrastructure.adapters.secondary.persistence.sql_workspace_member_repository import (
        SqlWorkspaceMemberRepository,
    )
    from src.infrastructure.adapters.secondary.persistence.sql_workspace_repository import (
        SqlWorkspaceRepository,
    )
    from src.infrastructure.adapters.secondary.persistence.sql_workspace_task_repository import (
        SqlWorkspaceTaskRepository,
    )
    from src.infrastructure.agent.state.agent_worker_state import get_redis_client
    from src.infrastructure.agent.workspace.workspace_goal_runtime import (
        _build_attempt_service,
        _ensure_execution_attempt,
        apply_workspace_worker_report,
    )

    redis_client = await get_redis_client()

    # --- Stage 1: attempt lifecycle + deterministic conversation binding ---
    resolved_attempt_id = attempt_id
    resolved_conversation_id: str | None = None
    code_context: WorkspaceCodeContext | None = None
    plan_node_metadata: dict[str, Any] = {}
    workspace_metadata_for_context: dict[str, Any] = {}
    root_goal_task_id = ""
    candidate = task.metadata.get(ROOT_GOAL_TASK_ID)
    if isinstance(candidate, str) and candidate:
        root_goal_task_id = candidate
    resolved_preferred_language = (
        preferred_language
        if preferred_language in {"en-US", "zh-CN"}
        else _preferred_language_from_metadata(task.metadata)
    )

    try:
        async with async_session_factory() as db:
            workspace_repo = SqlWorkspaceRepository(db)
            workspace = await workspace_repo.find_by_id(workspace_id)
            if workspace is None:
                logger.warning(
                    "workspace_worker_launch.workspace_not_found",
                    extra={
                        "event": "workspace_worker_launch.workspace_not_found",
                        "workspace_id": workspace_id,
                        "task_id": task.id,
                    },
                )
                return {
                    "launched": False,
                    "conversation_id": None,
                    "attempt_id": resolved_attempt_id,
                    "reason": "workspace_not_found",
                }

            root_metadata: Mapping[str, Any] = {}
            if root_goal_task_id:
                try:
                    root_task = await SqlWorkspaceTaskRepository(db).find_by_id(root_goal_task_id)
                except Exception:
                    logger.debug(
                        "workspace_worker_launch.root_profile_lookup_failed",
                        extra={
                            "event": "workspace_worker_launch.root_profile_lookup_failed",
                            "workspace_id": workspace_id,
                            "task_id": task.id,
                            "root_goal_task_id": root_goal_task_id,
                        },
                        exc_info=True,
                    )
                else:
                    if root_task is not None and root_task.workspace_id == workspace_id:
                        root_metadata = dict(root_task.metadata or {})
                        if resolved_preferred_language is None:
                            resolved_preferred_language = _preferred_language_from_metadata(
                                root_metadata
                            )
            if resolved_preferred_language is None:
                resolved_preferred_language = await _user_preferred_language(db, task.created_by)
            workspace_metadata = dict(getattr(workspace, "metadata", {}) or {})
            workspace_metadata_for_context = workspace_metadata
            plan_node_metadata = await _load_plan_node_metadata_for_task(db, task)
            code_context_evaluation = evaluate_workspace_code_context(
                root_metadata=root_metadata,
                workspace_metadata=workspace_metadata,
            )
            if not code_context_evaluation.allowed:
                logger.warning(
                    "workspace_worker_launch.code_context_not_ready",
                    extra={
                        "event": "workspace_worker_launch.code_context_not_ready",
                        "workspace_id": workspace_id,
                        "task_id": task.id,
                        "worker_agent_id": worker_agent_id,
                        "reason": code_context_evaluation.reason,
                    },
                )
                await _report_pre_stream_launch_failure(
                    workspace_id=workspace_id,
                    root_goal_task_id=root_goal_task_id,
                    task_id=task.id,
                    attempt_id=resolved_attempt_id,
                    conversation_id=resolved_conversation_id,
                    actor_user_id=actor_user_id,
                    worker_agent_id=worker_agent_id,
                    leader_agent_id=leader_agent_id,
                    launch_state="code_context_not_ready",
                    summary=(
                        f"worker_launch.code_context_not_ready: {code_context_evaluation.reason}"
                    ),
                    apply_fn=apply_workspace_worker_report,
                )
                return {
                    "launched": False,
                    "conversation_id": None,
                    "attempt_id": resolved_attempt_id,
                    "reason": "software_code_context_not_ready",
                    "message": code_context_evaluation.reason,
                }
            code_context = load_workspace_code_context(
                project_id=workspace.project_id,
                root_metadata=root_metadata,
                workspace_metadata=workspace_metadata,
            )
            if code_context.sandbox_code_root and code_context.host_code_root is not None:
                try:
                    code_context.host_code_root.mkdir(parents=True, exist_ok=True)
                except OSError:
                    logger.warning(
                        "workspace_worker_launch.code_root_mkdir_failed",
                        extra={
                            "event": "workspace_worker_launch.code_root_mkdir_failed",
                            "workspace_id": workspace_id,
                            "task_id": task.id,
                            "sandbox_code_root": code_context.sandbox_code_root,
                            "host_code_root": str(code_context.host_code_root),
                        },
                        exc_info=True,
                    )
                else:
                    code_context = load_workspace_code_context(
                        project_id=workspace.project_id,
                        root_metadata=root_metadata,
                        workspace_metadata=workspace_metadata,
                    )

            # Defensive membership check: the worker_agent_id MUST be an
            # active workspace binding. This guards against races where a
            # binding is deactivated between task assignment and launch.
            from src.infrastructure.adapters.secondary.persistence.sql_workspace_agent_repository import (
                SqlWorkspaceAgentRepository,
            )

            workspace_agent_repo = SqlWorkspaceAgentRepository(db)
            worker_binding = await workspace_agent_repo.find_by_workspace_and_agent_id(
                workspace_id=workspace_id,
                agent_id=worker_agent_id,
            )
            if worker_binding is None or not worker_binding.is_active:
                logger.warning(
                    "workspace_worker_launch.worker_not_workspace_member",
                    extra={
                        "event": "workspace_worker_launch.worker_not_workspace_member",
                        "workspace_id": workspace_id,
                        "task_id": task.id,
                        "worker_agent_id": worker_agent_id,
                        "binding_found": worker_binding is not None,
                    },
                )
                await _report_pre_stream_launch_failure(
                    workspace_id=workspace_id,
                    root_goal_task_id=root_goal_task_id,
                    task_id=task.id,
                    attempt_id=resolved_attempt_id,
                    conversation_id=resolved_conversation_id,
                    actor_user_id=actor_user_id,
                    worker_agent_id=worker_agent_id,
                    leader_agent_id=leader_agent_id,
                    launch_state="worker_not_workspace_member",
                    summary=(
                        f"worker_launch.worker_not_workspace_member: agent_id={worker_agent_id}"
                    ),
                    apply_fn=apply_workspace_worker_report,
                )
                return {
                    "launched": False,
                    "conversation_id": None,
                    "attempt_id": resolved_attempt_id,
                    "reason": "worker_not_workspace_member",
                }

            # Leader-as-worker guard: the workspace leader orchestrates but
            # must never be dispatched as a worker for its own tasks. This
            # happens when a leader's todowrite/create_task self-assigns,
            # or when a heal sweep trusts a stale ``assignee_agent_id`` that
            # points at the leader. A single "Workspace Worker - ..."
            # conversation is created per launch (L345), so rejecting here
            # is the definitive chokepoint.
            if leader_agent_id and worker_agent_id == leader_agent_id:
                logger.warning(
                    "workspace_worker_launch.worker_is_leader",
                    extra={
                        "event": "workspace_worker_launch.worker_is_leader",
                        "workspace_id": workspace_id,
                        "task_id": task.id,
                        "worker_agent_id": worker_agent_id,
                        "leader_agent_id": leader_agent_id,
                        "attempt_id": resolved_attempt_id,
                    },
                )
                await _report_pre_stream_launch_failure(
                    workspace_id=workspace_id,
                    root_goal_task_id=root_goal_task_id,
                    task_id=task.id,
                    attempt_id=resolved_attempt_id,
                    conversation_id=resolved_conversation_id,
                    actor_user_id=actor_user_id,
                    worker_agent_id=worker_agent_id,
                    leader_agent_id=leader_agent_id,
                    launch_state="worker_is_leader",
                    summary=(
                        "worker_launch.worker_is_leader: "
                        "leader cannot execute its own assigned worker task"
                    ),
                    apply_fn=apply_workspace_worker_report,
                )
                return {
                    "launched": False,
                    "conversation_id": None,
                    "attempt_id": resolved_attempt_id,
                    "reason": "worker_is_leader",
                }

            attempt_service = _build_attempt_service(db)
            attempt = await _ensure_execution_attempt(
                attempt_service=attempt_service,
                task=task,
                leader_agent_id=leader_agent_id,
            )
            resolved_attempt_id = attempt.id

            resolved_conversation_id = reuse_conversation_id or _conversation_id_for_worker(
                workspace_id=workspace_id,
                worker_agent_id=worker_agent_id,
                task_id=task.id,
                attempt_id=attempt.id,
            )
            if reuse_conversation_id:
                if await _agent_running_exists(redis_client, resolved_conversation_id):
                    await _report_pre_stream_launch_failure(
                        workspace_id=workspace_id,
                        root_goal_task_id=root_goal_task_id,
                        task_id=task.id,
                        attempt_id=resolved_attempt_id,
                        conversation_id=resolved_conversation_id,
                        actor_user_id=actor_user_id,
                        worker_agent_id=worker_agent_id,
                        leader_agent_id=leader_agent_id,
                        launch_state="repair_conversation_running",
                        summary=(
                            "worker_launch.repair_conversation_running: reused worker "
                            "conversation still has an active agent:running marker"
                        ),
                        apply_fn=apply_workspace_worker_report,
                    )
                    return {
                        "launched": False,
                        "conversation_id": resolved_conversation_id,
                        "attempt_id": resolved_attempt_id,
                        "reason": "repair_conversation_running",
                    }
                await _clear_reused_worker_session_markers(redis_client, resolved_conversation_id)

            if await _is_on_cooldown(resolved_conversation_id):
                logger.info(
                    "workspace_worker_launch.cooling_down",
                    extra={
                        "event": "workspace_worker_launch.cooling_down",
                        "workspace_id": workspace_id,
                        "task_id": task.id,
                        "conversation_id": resolved_conversation_id,
                        "worker_agent_id": worker_agent_id,
                        "attempt_id": resolved_attempt_id,
                    },
                )
                return {
                    "launched": False,
                    "conversation_id": resolved_conversation_id,
                    "attempt_id": resolved_attempt_id,
                    "reason": "cooling_down",
                }

            # Create Conversation row FIRST so the FK on
            # workspace_task_session_attempts.conversation_id is satisfied
            # when we bind below.
            container = DIContainer(db=db, redis_client=redis_client)
            conversation_repo = container.conversation_repository()
            existing = await conversation_repo.find_by_id(resolved_conversation_id)
            if existing is None:
                conversation = Conversation(
                    **_worker_conversation_kwargs(
                        conversation_id=resolved_conversation_id,
                        workspace_id=workspace_id,
                        workspace=workspace,
                        task=task,
                        actor_user_id=actor_user_id,
                        worker_agent_id=worker_agent_id,
                        worker_binding_id=worker_binding.id,
                        root_goal_task_id=root_goal_task_id,
                        attempt_id=attempt.id,
                        active_status=ConversationStatus.ACTIVE,
                    )
                )
                await conversation_repo.save(conversation)
            else:
                linkage_conflict = _worker_conversation_linkage_conflict(
                    existing,
                    workspace_id=workspace_id,
                    task_id=task.id,
                )
                if linkage_conflict is not None:
                    logger.error(
                        "workspace_worker_launch.lost_binding_conflict",
                        extra={
                            "event": "workspace_worker_launch.lost_binding_conflict",
                            "workspace_id": workspace_id,
                            "task_id": task.id,
                            "attempt_id": resolved_attempt_id,
                            "conversation_id": resolved_conversation_id,
                            **linkage_conflict,
                        },
                    )
                    await db.commit()
                    await _report_pre_stream_launch_failure(
                        workspace_id=workspace_id,
                        root_goal_task_id=root_goal_task_id,
                        task_id=task.id,
                        attempt_id=resolved_attempt_id,
                        conversation_id=resolved_conversation_id,
                        actor_user_id=actor_user_id,
                        worker_agent_id=worker_agent_id,
                        leader_agent_id=leader_agent_id,
                        launch_state="lost_binding_conflict",
                        summary=(
                            "worker_launch.lost_binding_conflict: deterministic worker "
                            "conversation is already linked to another workspace task"
                        ),
                        apply_fn=apply_workspace_worker_report,
                    )
                    return {
                        "launched": False,
                        "conversation_id": resolved_conversation_id,
                        "attempt_id": resolved_attempt_id,
                        "reason": "lost_binding_conflict",
                    }
                if _patch_worker_conversation_linkage(
                    existing,
                    workspace_id=workspace_id,
                    task_id=task.id,
                ):
                    await conversation_repo.save(existing)

            # Bind conversation to attempt so the UI (via task metadata
            # projection below) and downstream record_candidate_output
            # always observe the same conversation_id.
            try:
                attempt = await attempt_service.bind_conversation(
                    attempt.id, resolved_conversation_id
                )
            except ValueError:
                logger.warning(
                    "workspace_worker_launch.bind_conversation_failed",
                    extra={
                        "event": "workspace_worker_launch.bind_conversation_failed",
                        "workspace_id": workspace_id,
                        "task_id": task.id,
                        "attempt_id": resolved_attempt_id,
                        "conversation_id": resolved_conversation_id,
                    },
                    exc_info=True,
                )

            # Project conversation_id onto task.metadata so the frontend
            # blackboard / status panel can surface a "View conversation"
            # link without adding a new /attempts API surface.
            task_service = WorkspaceTaskService(
                workspace_repo=workspace_repo,
                workspace_member_repo=SqlWorkspaceMemberRepository(db),
                workspace_agent_repo=SqlWorkspaceAgentRepository(db),
                workspace_task_repo=SqlWorkspaceTaskRepository(db),
            )
            command_service = WorkspaceTaskCommandService(task_service)
            try:
                launch_actor_id = _launch_authority_actor_id(leader_agent_id)
                metadata_patch: dict[str, Any] = {
                    CURRENT_ATTEMPT_ID: attempt.id,
                    "current_attempt_number": attempt.attempt_number,
                    "current_attempt_conversation_id": resolved_conversation_id,
                    "current_attempt_worker_agent_id": worker_agent_id,
                    CURRENT_ATTEMPT_WORKER_BINDING_ID: worker_binding.id,
                    "launch_state": "bound",
                }
                metadata_patch["code_context"] = _code_context_metadata(code_context)
                attempt_worktree_payload = _attempt_worktree_payload(attempt_worktree_context)
                if attempt_worktree_payload is not None:
                    metadata_patch[ATTEMPT_WORKTREE] = attempt_worktree_payload
                    if setup_payload := _attempt_worktree_setup_payload(attempt_worktree_payload):
                        metadata_patch[WORKTREE_SETUP] = setup_payload
                    if active_root := _attempt_worktree_active_root(attempt_worktree_payload):
                        metadata_patch[ACTIVE_EXECUTION_ROOT] = active_root
                verification_integrity = _workspace_verification_integrity_context(
                    task.metadata,
                    plan_node_metadata,
                    task_title=task.title,
                    task_description=task.description,
                )
                if verification_integrity is not None:
                    metadata_patch["workspace_verification_integrity"] = verification_integrity
                    metadata_patch.setdefault(
                        "iteration_phase",
                        verification_integrity["iteration_phase"],
                    )
                await command_service.update_task(
                    workspace_id=workspace_id,
                    task_id=task.id,
                    actor_user_id=actor_user_id,
                    metadata=metadata_patch,
                    actor_type="agent",
                    actor_agent_id=launch_actor_id,
                    reason="workspace_worker_launch.bind_conversation",
                    authority=WorkspaceTaskAuthorityContext.leader(launch_actor_id),
                )
            except Exception:
                logger.warning(
                    "workspace_worker_launch.task_metadata_patch_failed",
                    extra={
                        "event": "workspace_worker_launch.task_metadata_patch_failed",
                        "workspace_id": workspace_id,
                        "task_id": task.id,
                        "attempt_id": attempt.id,
                    },
                    exc_info=True,
                )

            await db.commit()
    except Exception as exc:
        logger.warning(
            "workspace_worker_launch.setup_failed",
            extra={
                "event": "workspace_worker_launch.setup_failed",
                "workspace_id": workspace_id,
                "task_id": task.id,
            },
            exc_info=True,
        )
        await _report_pre_stream_launch_failure(
            workspace_id=workspace_id,
            root_goal_task_id=root_goal_task_id,
            task_id=task.id,
            attempt_id=resolved_attempt_id,
            conversation_id=resolved_conversation_id,
            actor_user_id=actor_user_id,
            worker_agent_id=worker_agent_id,
            leader_agent_id=leader_agent_id,
            launch_state="setup_failed",
            summary=f"worker_launch.setup_failed: {exc}",
            apply_fn=apply_workspace_worker_report,
        )
        return {
            "launched": False,
            "conversation_id": resolved_conversation_id,
            "attempt_id": resolved_attempt_id,
            "reason": "stream_failed",
        }

    # --- Stage 2: stream + parse terminal event ---
    scope = _conversation_scope_for_task(task.id, resolved_attempt_id)
    user_message = _build_worker_brief(
        workspace_id=workspace_id,
        task=task,
        attempt_id=resolved_attempt_id,
        leader_agent_id=leader_agent_id,
        extra_instructions=_append_worker_instruction_note(
            repair_brief_prompt,
            extra_instructions,
        ),
        code_context=code_context,
        plan_node_metadata=plan_node_metadata,
        workspace_metadata=workspace_metadata_for_context,
        attempt_worktree_context=attempt_worktree_context,
    )
    app_model_context = _build_worker_system_context(
        workspace_id=workspace_id,
        task=task,
        attempt_id=resolved_attempt_id,
        leader_agent_id=leader_agent_id,
        extra_instructions=extra_instructions,
        code_context=code_context,
        preferred_language=resolved_preferred_language,
        plan_node_metadata=plan_node_metadata,
        workspace_metadata=workspace_metadata_for_context,
        attempt_worktree_context=attempt_worktree_context,
    )
    final_content = ""
    accumulated_text = ""
    terminal_event: str | None = None  # "complete" | "error" | None
    stream_message_id: str | None = None
    stream_orphan_reason: str | None = None
    terminal_report_tool_observed = False
    terminal_report_tool_denied = False
    terminal_report_tool_applied = False
    heartbeat_stop = asyncio.Event()
    heartbeat_task: asyncio.Task[None] | None = None
    next_event_task: asyncio.Task[dict[str, Any]] | None = None
    stream_iter: Any = None

    try:
        await _publish_worker_launch_heartbeat(
            workspace_id=workspace_id,
            task_id=task.id,
            attempt_id=resolved_attempt_id,
            root_goal_task_id=root_goal_task_id,
            conversation_id=resolved_conversation_id,
            actor_user_id=actor_user_id,
            worker_agent_id=worker_agent_id,
            leader_agent_id=leader_agent_id,
        )
        heartbeat_task = asyncio.create_task(
            _worker_launch_heartbeat_loop(
                stop_event=heartbeat_stop,
                workspace_id=workspace_id,
                task_id=task.id,
                attempt_id=resolved_attempt_id,
                root_goal_task_id=root_goal_task_id,
                conversation_id=resolved_conversation_id,
                actor_user_id=actor_user_id,
                worker_agent_id=worker_agent_id,
                leader_agent_id=leader_agent_id,
            ),
            name=f"workspace-worker-heartbeat:{resolved_attempt_id or task.id}",
        )
        async with async_session_factory() as db:
            workspace_repo = SqlWorkspaceRepository(db)
            workspace = await workspace_repo.find_by_id(workspace_id)
            if workspace is None:
                return {
                    "launched": False,
                    "conversation_id": resolved_conversation_id,
                    "attempt_id": resolved_attempt_id,
                    "reason": "workspace_not_found",
                }
            container = DIContainer(db=db, redis_client=redis_client)
            llm = await create_llm_client(workspace.tenant_id)
            agent_service: AgentService = container.agent_service(llm)
            stream_iter = agent_service.stream_chat_v2(
                conversation_id=resolved_conversation_id,
                user_message=user_message,
                project_id=workspace.project_id,
                user_id=actor_user_id,
                tenant_id=workspace.tenant_id,
                agent_id=worker_agent_id,
                app_model_context=app_model_context,
                preferred_language=resolved_preferred_language,
            ).__aiter__()
            last_stream_event_seen = time.monotonic()
            while True:
                if next_event_task is None:
                    next_event_task = asyncio.create_task(stream_iter.__anext__())
                done, _pending = await asyncio.wait(
                    {next_event_task},
                    timeout=max(1, WORKER_STREAM_FINISH_POLL_SECONDS),
                )
                if not done:
                    idle_seconds = time.monotonic() - last_stream_event_seen
                    finished_message_id = await _agent_finished_message_id(
                        redis_client,
                        resolved_conversation_id,
                    )
                    running_exists = await _agent_running_exists(
                        redis_client,
                        resolved_conversation_id,
                    )
                    should_stop, stream_orphan_reason = _should_stop_orphaned_worker_stream(
                        finished_message_id=finished_message_id,
                        stream_message_id=stream_message_id,
                        running_exists=running_exists,
                        idle_seconds=idle_seconds,
                    )
                    if not should_stop:
                        continue
                    next_event_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError, StopAsyncIteration):
                        await next_event_task
                    if stream_iter is not None:
                        with contextlib.suppress(Exception):
                            await stream_iter.aclose()
                    final_content = (
                        "Worker stream stopped without a terminal complete/error event "
                        f"({stream_orphan_reason})."
                    )
                    logger.warning(
                        "workspace_worker_launch.orphaned_stream_detected",
                        extra={
                            "event": "workspace_worker_launch.orphaned_stream_detected",
                            "workspace_id": workspace_id,
                            "task_id": task.id,
                            "conversation_id": resolved_conversation_id,
                            "attempt_id": resolved_attempt_id,
                            "reason": stream_orphan_reason,
                            "idle_seconds": idle_seconds,
                            "finished_message_id": finished_message_id,
                            "stream_message_id": stream_message_id,
                        },
                    )
                    next_event_task = None
                    break
                try:
                    event = next_event_task.result()
                except StopAsyncIteration:
                    final_content = "Worker stream ended without a terminal complete/error event."
                    next_event_task = None
                    break
                next_event_task = None
                last_stream_event_seen = time.monotonic()
                stream_message_id = stream_message_id or _stream_message_id_from_event(event)
                event_type = event.get("type")
                if event_type == "text_delta":
                    accumulated_text += event.get("data", {}).get("text", "")
                elif event_type == "observe":
                    terminal_tool_status = _terminal_report_tool_observation_status(event)
                    if terminal_tool_status is not None:
                        terminal_report_tool_observed = True
                        if terminal_tool_status == "denied":
                            terminal_report_tool_denied = True
                        elif terminal_tool_status == "applied":
                            terminal_report_tool_applied = True
                elif event_type == "complete":
                    terminal_event = "complete"
                    final_content = event.get("data", {}).get("content", "")
                    if not final_content and accumulated_text:
                        final_content = accumulated_text
                    break
                elif event_type == "error":
                    terminal_event = "error"
                    final_content = event.get("data", {}).get(
                        "message", "Worker stream reported an error"
                    )
                    break
    except Exception:
        logger.warning(
            "workspace_worker_launch.stream_failed",
            extra={
                "event": "workspace_worker_launch.stream_failed",
                "workspace_id": workspace_id,
                "task_id": task.id,
                "conversation_id": resolved_conversation_id,
                "worker_agent_id": worker_agent_id,
                "attempt_id": resolved_attempt_id,
            },
            exc_info=True,
        )
        terminal_event = "error"
        final_content = "Worker launch stream raised an exception"
    finally:
        heartbeat_stop.set()
        if next_event_task is not None and not next_event_task.done():
            next_event_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, StopAsyncIteration):
                await next_event_task
        if heartbeat_task is not None:
            heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat_task

    # --- Stage 3: terminal report -----------------------------------------
    outcome_reason: str
    if terminal_event == "complete":
        summary = _stream_completion_summary(final_content, accumulated_text)
        if _should_synthesize_stream_completion_report(
            terminal_report_tool_observed=terminal_report_tool_observed
        ):
            reported = await _report_terminal(
                workspace_id=workspace_id,
                root_goal_task_id=root_goal_task_id,
                task_id=task.id,
                attempt_id=resolved_attempt_id,
                conversation_id=resolved_conversation_id,
                actor_user_id=actor_user_id,
                worker_agent_id=worker_agent_id,
                leader_agent_id=leader_agent_id,
                report_type="completed",
                summary=summary,
                apply_fn=apply_workspace_worker_report,
            )
            outcome_reason = "completed" if reported else "report_failed"
            await _patch_task_launch_state(
                workspace_id=workspace_id,
                task_id=task.id,
                actor_user_id=actor_user_id,
                leader_agent_id=leader_agent_id,
                launch_state=("completed_via_stream" if reported else "terminal_report_failed"),
            )
            logger.info(
                "workspace_worker_launch.stream_complete_synthesized_report",
                extra={
                    "event": "workspace_worker_launch.stream_complete_synthesized_report",
                    "workspace_id": workspace_id,
                    "task_id": task.id,
                    "conversation_id": resolved_conversation_id,
                    "attempt_id": resolved_attempt_id,
                    "reported": reported,
                },
            )
        else:
            outcome_reason = (
                "terminal_report_tool_applied"
                if terminal_report_tool_applied
                else (
                    "terminal_report_tool_denied"
                    if terminal_report_tool_denied
                    else "terminal_report_tool_observed"
                )
            )
            await _patch_task_launch_state(
                workspace_id=workspace_id,
                task_id=task.id,
                actor_user_id=actor_user_id,
                leader_agent_id=leader_agent_id,
                launch_state=outcome_reason,
            )
            logger.info(
                "workspace_worker_launch.stream_complete_after_terminal_tool",
                extra={
                    "event": "workspace_worker_launch.stream_complete_after_terminal_tool",
                    "workspace_id": workspace_id,
                    "task_id": task.id,
                    "conversation_id": resolved_conversation_id,
                    "attempt_id": resolved_attempt_id,
                    "terminal_report_tool_denied": terminal_report_tool_denied,
                    "terminal_report_tool_applied": terminal_report_tool_applied,
                },
            )
    elif terminal_event == "error":
        outcome_reason = "blocked"
        summary = (final_content or "").strip()[:2000] or "Worker stream errored."
        await _report_terminal(
            workspace_id=workspace_id,
            root_goal_task_id=root_goal_task_id,
            task_id=task.id,
            attempt_id=resolved_attempt_id,
            conversation_id=resolved_conversation_id,
            actor_user_id=actor_user_id,
            worker_agent_id=worker_agent_id,
            leader_agent_id=leader_agent_id,
            report_type="blocked",
            summary=summary,
            apply_fn=apply_workspace_worker_report,
        )
        await _patch_task_launch_state(
            workspace_id=workspace_id,
            task_id=task.id,
            actor_user_id=actor_user_id,
            leader_agent_id=leader_agent_id,
            launch_state="blocked",
        )
    else:
        outcome_reason = (
            "terminal_report_tool_applied" if terminal_report_tool_applied else "no_terminal_event"
        )
        if not terminal_report_tool_applied:
            summary = (final_content or "").strip()[:2000] or (
                "Worker stream ended without a terminal complete/error event and without "
                "a workspace_report_complete/workspace_report_blocked tool call."
            )
            await _report_terminal(
                workspace_id=workspace_id,
                root_goal_task_id=root_goal_task_id,
                task_id=task.id,
                attempt_id=resolved_attempt_id,
                conversation_id=resolved_conversation_id,
                actor_user_id=actor_user_id,
                worker_agent_id=worker_agent_id,
                leader_agent_id=leader_agent_id,
                report_type="blocked",
                summary=summary,
                apply_fn=apply_workspace_worker_report,
            )
        await _patch_task_launch_state(
            workspace_id=workspace_id,
            task_id=task.id,
            actor_user_id=actor_user_id,
            leader_agent_id=leader_agent_id,
            launch_state=outcome_reason,
        )
        logger.warning(
            "workspace_worker_launch.no_terminal_event",
            extra={
                "event": "workspace_worker_launch.no_terminal_event",
                "workspace_id": workspace_id,
                "task_id": task.id,
                "conversation_id": resolved_conversation_id,
                "attempt_id": resolved_attempt_id,
            },
        )

    logger.info(
        "workspace_worker_launch.launched",
        extra={
            "event": "workspace_worker_launch.launched",
            "workspace_id": workspace_id,
            "task_id": task.id,
            "conversation_id": resolved_conversation_id,
            "worker_agent_id": worker_agent_id,
            "leader_agent_id": leader_agent_id,
            "attempt_id": resolved_attempt_id,
            "outcome": outcome_reason,
            "scope": scope,
        },
    )
    return {
        "launched": True,
        "conversation_id": resolved_conversation_id,
        "attempt_id": resolved_attempt_id,
        "reason": outcome_reason,
    }


async def _patch_task_launch_state(
    *,
    workspace_id: str,
    task_id: str,
    actor_user_id: str,
    leader_agent_id: str | None,
    launch_state: str,
) -> None:
    try:
        from src.application.services.workspace_task_command_service import (
            WorkspaceTaskCommandService,
        )
        from src.application.services.workspace_task_service import (
            WorkspaceTaskAuthorityContext,
            WorkspaceTaskService,
        )
        from src.infrastructure.adapters.secondary.persistence.database import (
            async_session_factory,
        )
        from src.infrastructure.adapters.secondary.persistence.sql_workspace_agent_repository import (
            SqlWorkspaceAgentRepository,
        )
        from src.infrastructure.adapters.secondary.persistence.sql_workspace_member_repository import (
            SqlWorkspaceMemberRepository,
        )
        from src.infrastructure.adapters.secondary.persistence.sql_workspace_repository import (
            SqlWorkspaceRepository,
        )
        from src.infrastructure.adapters.secondary.persistence.sql_workspace_task_repository import (
            SqlWorkspaceTaskRepository,
        )

        async with async_session_factory() as db:
            task_service = WorkspaceTaskService(
                workspace_repo=SqlWorkspaceRepository(db),
                workspace_member_repo=SqlWorkspaceMemberRepository(db),
                workspace_agent_repo=SqlWorkspaceAgentRepository(db),
                workspace_task_repo=SqlWorkspaceTaskRepository(db),
            )
            launch_actor_id = _launch_authority_actor_id(leader_agent_id)
            await WorkspaceTaskCommandService(task_service).update_task(
                workspace_id=workspace_id,
                task_id=task_id,
                actor_user_id=actor_user_id,
                metadata={"launch_state": launch_state},
                actor_type="agent",
                actor_agent_id=launch_actor_id,
                reason=f"workspace_worker_launch.{launch_state}",
                authority=WorkspaceTaskAuthorityContext.leader(launch_actor_id),
            )
            await db.commit()
    except Exception:
        logger.warning(
            "workspace_worker_launch.launch_state_patch_failed",
            extra={
                "event": "workspace_worker_launch.launch_state_patch_failed",
                "workspace_id": workspace_id,
                "task_id": task_id,
                "launch_state": launch_state,
            },
            exc_info=True,
        )


async def _report_terminal(
    *,
    workspace_id: str,
    root_goal_task_id: str,
    task_id: str,
    attempt_id: str | None,
    conversation_id: str | None,
    actor_user_id: str,
    worker_agent_id: str,
    leader_agent_id: str | None,
    report_type: str,
    summary: str,
    apply_fn: Callable[..., Awaitable[Any]],
) -> bool:
    """Call ``apply_workspace_worker_report`` with structured error capture.

    Failures are swallowed and logged because the launch coroutine is itself
    a background fire-and-forget task; the leader autonomy loop is the
    compensating layer.
    """
    try:
        await apply_fn(
            workspace_id=workspace_id,
            root_goal_task_id=root_goal_task_id,
            task_id=task_id,
            attempt_id=attempt_id,
            conversation_id=conversation_id,
            actor_user_id=actor_user_id,
            worker_agent_id=worker_agent_id,
            report_type=report_type,
            summary=summary,
            leader_agent_id=leader_agent_id,
        )
        return True
    except Exception:
        logger.warning(
            "workspace_worker_launch.report_failed",
            extra={
                "event": "workspace_worker_launch.report_failed",
                "workspace_id": workspace_id,
                "task_id": task_id,
                "attempt_id": attempt_id,
                "report_type": report_type,
            },
            exc_info=True,
        )
        return False


def _stream_completion_summary(final_content: str, accumulated_text: str) -> str:
    """Bound unstructured stream completion text for synthesized reports."""
    summary = (final_content or accumulated_text or "").strip()
    if not summary:
        summary = "Worker stream completed without an explicit workspace terminal report."
    if len(summary) > 2000:
        return summary[:1997] + "..."
    return summary


def _should_synthesize_stream_completion_report(*, terminal_report_tool_observed: bool) -> bool:
    """Allow text-only completion fallback only when no terminal tool was involved."""
    return not terminal_report_tool_observed


def _terminal_report_tool_observation_status(event: Mapping[str, Any]) -> str | None:
    """Classify terminal report tool observations from the agent event stream.

    A rejected ``workspace_report_complete`` must not be followed by the legacy
    text-completion fallback, otherwise failed test evidence can become a
    durable completed report after the tool already denied it.
    """
    if event.get("type") != "observe":
        return None
    data = event.get("data")
    if not isinstance(data, Mapping):
        return None
    tool_name = str(data.get("tool_name") or "").strip()
    if tool_name not in _TERMINAL_REPORT_TOOLS:
        return None
    if data.get("error"):
        return "denied"
    return _terminal_report_tool_result_status(data.get("result"))


def _terminal_report_tool_result_status(result: object) -> str:
    result_text = result if isinstance(result, str) else ""
    parsed: object | None = None
    if result_text:
        with contextlib.suppress(json.JSONDecodeError, TypeError):
            parsed = json.loads(result_text)

    if isinstance(parsed, Mapping):
        parsed_status = _parsed_terminal_report_tool_status(parsed)
        if parsed_status is not None:
            return parsed_status

    lowered = result_text.lower()
    denied = (
        "completion denied:" in lowered
        or "terminal_report_apply_failed" in lowered
        or '"error"' in lowered
    )
    return "denied" if denied else "attempted"


def _parsed_terminal_report_tool_status(parsed: Mapping[str, Any]) -> str | None:
    applied_report = parsed.get("applied_report")
    if isinstance(applied_report, Mapping) and (
        applied_report.get("applied") is True or applied_report.get("skipped") is True
    ):
        return "applied"
    if parsed.get("ok") is True:
        return "applied"
    if parsed.get("error"):
        return "denied"
    return None


def schedule_worker_session(
    *,
    workspace_id: str,
    task: WorkspaceTask,
    worker_agent_id: str,
    actor_user_id: str,
    leader_agent_id: str | None = None,
    attempt_id: str | None = None,
    extra_instructions: str | None = None,
    reuse_conversation_id: str | None = None,
    repair_brief_prompt: str | None = None,
    preferred_language: str | None = None,
    attempt_worktree_context: Mapping[str, Any] | None = None,
) -> None:
    """Fire-and-forget scheduler for ``launch_worker_session``.

    Mirrors the pattern of :func:`schedule_autonomy_tick`: failures during
    scheduling are silently absorbed; errors during the launched coroutine
    are logged inside ``launch_worker_session``.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No running loop — caller is sync. Spin one up just for this launch.
        try:
            asyncio.run(
                launch_worker_session(
                    workspace_id=workspace_id,
                    task=task,
                    worker_agent_id=worker_agent_id,
                    actor_user_id=actor_user_id,
                    leader_agent_id=leader_agent_id,
                    attempt_id=attempt_id,
                    extra_instructions=extra_instructions,
                    reuse_conversation_id=reuse_conversation_id,
                    repair_brief_prompt=repair_brief_prompt,
                    preferred_language=preferred_language,
                    attempt_worktree_context=attempt_worktree_context,
                )
            )
        except Exception:
            logger.warning(
                "workspace_worker_launch.schedule_sync_failed",
                extra={
                    "event": "workspace_worker_launch.schedule_sync_failed",
                    "workspace_id": workspace_id,
                    "task_id": task.id,
                },
                exc_info=True,
            )
        return

    bg = loop.create_task(
        launch_worker_session(
            workspace_id=workspace_id,
            task=task,
            worker_agent_id=worker_agent_id,
            actor_user_id=actor_user_id,
            leader_agent_id=leader_agent_id,
            attempt_id=attempt_id,
            extra_instructions=extra_instructions,
            reuse_conversation_id=reuse_conversation_id,
            repair_brief_prompt=repair_brief_prompt,
            preferred_language=preferred_language,
            attempt_worktree_context=attempt_worktree_context,
        )
    )
    _background_tasks.add(bg)
    bg.add_done_callback(_background_tasks.discard)


__all__ = [
    "WORKER_LAUNCH_COOLDOWN_SECONDS",
    "_build_worker_brief",
    "_build_worker_system_context",
    "_conversation_id_for_worker",
    "_conversation_scope_for_task",
    "launch_worker_session",
    "schedule_worker_session",
]
