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
import logging
import os
import posixpath
import re
import shlex
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any, Protocol, cast

from src.domain.model.workspace.workspace_task import WorkspaceTask
from src.infrastructure.agent.workspace.code_context import (
    WorkspaceCodeContext,
)
from src.infrastructure.agent.workspace.workspace_metadata_keys import (
    ACTIVE_EXECUTION_ROOT,
    ATTEMPT_WORKTREE,
    LAST_WORKER_REPORT_ATTEMPT_ID,
    PREFERRED_LANGUAGE,
    ROOT_GOAL_TASK_ID,
    WORKTREE_SETUP,
)
from src.infrastructure.agent.workspace_plan.pipeline import (
    DRONE_PROVIDER,
    PipelineContractSpec,
    build_pipeline_contract_from_metadata,
)

logger = logging.getLogger(__name__)

_background_tasks: set[asyncio.Task[Any]] = set()


class _WorkerOperationReservationV2(Protocol):
    """Exact generation and child operation retained for one worker launch."""

    def admit(
        self,
        *,
        operation_id: str,
        metadata: Mapping[str, object],
    ) -> contextlib.AbstractAsyncContextManager[object]: ...

    async def release(self) -> None: ...


type _WorkerLaunchFactory = Callable[[], Awaitable[dict[str, Any]]]

# Cooldown TTL — long enough to avoid double-launch on transient retries
# but short enough that a genuine re-assignment after rework can re-fire.
WORKER_LAUNCH_COOLDOWN_SECONDS = 300
WORKER_LAUNCH_HEARTBEAT_SECONDS = int(os.getenv("WORKSPACE_WORKER_LAUNCH_HEARTBEAT_SECONDS", "45"))
WORKER_STREAM_FINISH_POLL_SECONDS = int(
    os.getenv("WORKSPACE_WORKER_STREAM_FINISH_POLL_SECONDS", "15")
)
WORKER_STREAM_IDLE_PROGRESS_SECONDS = int(
    os.getenv("WORKSPACE_WORKER_STREAM_IDLE_PROGRESS_SECONDS", "180")
)
WORKER_LAUNCH_PROGRESS_SUMMARY_CHARS = 700
WORKER_STREAM_ORPHAN_GRACE_SECONDS = int(
    os.getenv("WORKSPACE_WORKER_STREAM_ORPHAN_GRACE_SECONDS", "900")
)
WORKER_LAUNCH_CONVERSATION_SOURCE = "workspace_worker_launch"
WORKER_LAUNCH_CONVERSATION_STAGE = "worker_launch"
WORKER_MAX_SINGLE_WRITE_CHARS = 900
WORKER_RECOMMENDED_WRITE_CHUNK_CHARS = 700
WORKER_MAX_SINGLE_BASH_COMMAND_CHARS = 900
WORKER_REPAIR_SOURCE_METADATA_MAX_DEPTH = 12
WORKER_LAUNCH_PIPELINE_EVIDENCE_LIMIT = 3
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
_LATEST_PIPELINE_EVIDENCE_KEY = "latest_workspace_pipeline_evidence"
_RECENT_PIPELINE_EVIDENCE_KEY = "recent_workspace_pipeline_evidence"
_WORKSPACE_ROOT_OVERRIDE_MARKERS = ("worktree_path", "[feature-checkpoint]", "[worktree-setup]")
_WORKER_VERIFICATION_INTEGRITY_PHASES = frozenset({"test", "review"})
_DRONE_DEPLOY_CONTEXT_PHASES = frozenset({"deploy", "review"})
_REPAIR_BRIEF_VERIFICATION_SCOPE_KEYS = (
    "allowed_write_scope",
    "allowed_verification_script_paths",
    "evidence",
    "evidence_refs",
    "expected_artifacts",
    "failed_items",
    "failure_signature",
    "feedback_items",
    "required_next_action",
    "summary",
    "verification_script_paths",
)
_TERMINAL_REPORT_TOOL_TYPES = {
    "workspace_report_complete": "completed",
    "workspace_report_blocked": "blocked",
}
_TERMINAL_REPORT_TOOLS = frozenset(_TERMINAL_REPORT_TOOL_TYPES)
_LOCAL_REGISTRY_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "host.docker.internal"})
_LOCAL_DOCKER_DEPLOY_STRATEGY = "local_build"
_DEFAULT_DOCKER_DEPLOY_HOST_PORT = 18080
_DEFAULT_DOCKER_DEPLOY_DEPENDENCY_STRATEGY = "compose_or_sidecars"
_DEFAULT_DOCKER_DEPLOY_NETWORK = "workspace-deploy"
_DEFAULT_DOCKER_DEPLOY_NETWORK_CREATE_COMMAND = (
    "docker network inspect workspace-deploy >/dev/null 2>&1 "
    "|| docker network create workspace-deploy"
)
_DEFAULT_DOCKER_DEPLOY_POSTGRES_IMAGE = "postgres:16-alpine"
_DEFAULT_DOCKER_DEPLOY_REDIS_IMAGE = "redis:7-alpine"
_DEFAULT_DOCKER_DEPLOY_POSTGRES_COMMAND = (
    "docker run -d --name <postgres-container> --network workspace-deploy "
    "-e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=<db> "
    "postgres:16-alpine"
)
_DEFAULT_DOCKER_DEPLOY_POSTGRES_CLEANUP_COMMAND = (
    "docker rm -f <postgres-container> 2>/dev/null || true"
)
_DEFAULT_DOCKER_DEPLOY_POSTGRES_READY_COMMAND = (
    "for i in $(seq 1 30); do docker exec <postgres-container> "
    "pg_isready -U postgres >/dev/null 2>&1 && break || sleep 1; done"
)
_DEFAULT_DOCKER_DEPLOY_REDIS_COMMAND = (
    "docker run -d --name <redis-container> --network workspace-deploy redis:7-alpine"
)
_DEFAULT_DOCKER_DEPLOY_REDIS_CLEANUP_COMMAND = "docker rm -f <redis-container> 2>/dev/null || true"
_PLATFORM_RESERVED_DOCKER_HOST_PORTS = (
    3000,  # frontend dev server
    3001,  # Drone runner / common app internal port
    5001,  # local Docker registry
    5432,  # PostgreSQL
    6379,  # Redis
    7474,  # Neo4j HTTP
    7687,  # Neo4j Bolt
    8000,  # API server
    8080,  # Drone server
)
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


def _iter_repair_brief_verification_script_scope_paths(value: object) -> list[str]:
    paths = _iter_verification_script_scope_paths(value)
    if isinstance(value, Mapping):
        mapped = cast(Mapping[str, object], value)
        for key in _REPAIR_BRIEF_VERIFICATION_SCOPE_KEYS:
            paths.extend(_iter_repair_brief_verification_script_scope_paths(mapped.get(key)))
        return list(dict.fromkeys(paths))
    if isinstance(value, (list, tuple, set)):
        for item in cast(Iterable[object], value):
            paths.extend(_iter_repair_brief_verification_script_scope_paths(item))
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
        paths.extend(_iter_verification_script_scope_paths(metadata.get("expected_artifacts")))
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
            paths.extend(_iter_repair_brief_verification_script_scope_paths(brief))
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
    contract_hints = [
        text[:1200]
        for text in (
            _metadata_text(task_title),
            _metadata_text(task_description),
        )
        if text
    ]
    allowed_script_paths = list(
        dict.fromkeys(
            [
                *_verification_script_change_allowlist(task_meta, node_meta),
                *_iter_verification_script_scope_paths(contract_hints),
            ]
        )
    )
    source = "workspace_plan_node_metadata" if node_phase else "workspace_task_metadata"
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
            f"This is a protected `{phase}` workspace node. The current task contract "
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


def _workspace_delivery_cicd_context(  # noqa: C901, PLR0915
    workspace_metadata: Mapping[str, Any] | None,
    plan_node_metadata: Mapping[str, Any] | None = None,
    *,
    fallback_code_root: str | None = None,
    fallback_host_code_root: str | Path | None = None,
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
            fallback_code_root=fallback_code_root
            or _metadata_text(workspace_metadata.get("sandbox_code_root")),
            fallback_host_code_root=fallback_host_code_root,
        )
    except Exception:
        logger.debug("workspace_worker_launch.delivery_cicd_context_failed", exc_info=True)
        return None

    phase = None
    if isinstance(plan_node_metadata, Mapping):
        phase = _metadata_text(plan_node_metadata.get("iteration_phase"))
    contract = _contract_with_phase_drone_deploy_context(contract, phase=phase)
    deploy = contract.deploy.to_json() if contract.deploy is not None else None
    services = contract.services_json()
    if isinstance(deploy, dict):
        deploy = _deploy_context_with_runner_hints(deploy, services=services)
    context: dict[str, Any] = {
        "source": "workspace.metadata.delivery_cicd",
        "provider": contract.provider,
        "code_root": contract.code_root,
        "auto_deploy": contract.auto_deploy,
        "contract_source": contract.contract_source,
        "node_phase": phase.lower() if phase else None,
        "deploy": deploy,
        "services": services,
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
            "repo": _metadata_text(
                provider_config.get("repo") or provider_config.get("repository")
            ),
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
                    "Do not wait for source-publish or memstack-source-publish refs to "
                    "auto-sync with a worker worktree, and do not retry GitHub pushes to "
                    "advance them from the sandbox. After committing the desired worktree "
                    "state, call the required workspace_report_* contract tool with the "
                    "worktree commit ref and let the platform harness perform source_publish "
                    "and Drone triggering."
                ),
                (
                    "If there are no deploy-code changes to commit, report the clean worktree "
                    "and current commit instead of fabricating a no-op change just to trigger CI."
                ),
                (
                    "Before committing `.drone.yml`, parse it and verify every "
                    "`steps[].commands[]` item is a string. YAML can parse commands such as "
                    '`echo "label: value"` as a mapping even when syntax validation passes; '
                    "quote those commands or use block scalars."
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
                "Docker deploy mode requires two separate Drone concerns: first publish the "
                "image, then run a distinct deploy step/stage named by deploy.stage that "
                "consumes the published image and performs Docker deployment. plugins/docker "
                "or docker build/push alone is image publication, not deployment evidence."
            )
            context["instructions"].append(
                "Drone Docker steps run inside runner/plugin containers; do not use localhost "
                "or 127.0.0.1 for a registry on the host. When the configured registry is local, "
                "use the Docker runner reachable registry/image values in this brief, such as "
                "host.docker.internal:<port>, for plugins/docker repo and registry settings."
            )
            context["instructions"].append(
                "A deploy step that mounts /var/run/docker.sock is different from plugins/docker: "
                "the docker CLI runs in the step container, but docker pull/run are executed by "
                "the host Docker daemon. In local Docker Desktop style environments, the daemon "
                "may neither trust host.docker.internal:<port> nor reach localhost:<port> for the "
                "plain-HTTP registry. Do not solve this by flipping between those registry hosts "
                "in deploy pull/run commands. Prefer a deploy-local image path: build or load the "
                "image into the mounted Docker daemon in the deploy step, then docker run that "
                "local tag. Keep host.docker.internal:<port> for plugins/docker build/push settings."
            )
            context["instructions"].append(
                "When docker.deploy_strategy is local_build or "
                "docker.allow_daemon_registry_pull is false, the host-socket deploy step must use "
                "the provided Docker deploy local build command or an equivalent docker load path, "
                "then docker run the Docker image (deploy local tag). It must not docker pull or "
                "docker run images from host.docker.internal:<port>, localhost:<port>, or "
                "127.0.0.1:<port> through the host Docker daemon."
            )
            context["instructions"].append(
                "Before reporting deploy completion, inspect .drone.yml. If plugins/docker still "
                "uses localhost/127.0.0.1 for the registry or image, update it to the runner "
                "reachable registry/image. If a host-socket deploy step pulls from "
                "host.docker.internal:<port> or localhost:<port> for a local insecure registry, "
                "replace that daemon-side pull with a deploy-local build/load plus docker run."
            )
            context["instructions"].append(
                "The deploy step should use Docker deployment semantics such as docker build/load "
                "plus docker run, docker pull plus docker run when the daemon can reach the registry, "
                "docker compose up, docker stack deploy, or docker service update, and should include "
                "a health check when a workspace service health path is known."
            )
            context["instructions"].append(
                "Docker deploy coverage must match application image coverage. If `.drone.yml` "
                "builds or pushes separate frontend, backend, API, worker, or other application "
                "service images, the deploy stage must run or compose every corresponding required "
                "runtime service and health-check each service with a known health path. A deploy "
                "stage that only starts the backend/API container is incomplete when a frontend "
                "or other required application image was also built."
            )
            docker_context = deploy.get("docker")
            if isinstance(docker_context, Mapping) and docker_context.get("deploy_service_count"):
                context["instructions"].append(
                    "Use docker.deploy_services as the required Docker deploy inventory. For each "
                    "required service, add or preserve a deploy-local build/load or compose path, "
                    "start the service with a distinct container name and host port, and keep its "
                    "health check in the deploy stage. Do not report Drone deploy complete until "
                    "every required service in docker.deploy_services is deployed or explicitly "
                    "covered by docker compose."
                )
            context["instructions"].append(
                "Docker deploy commands must fail fast when pull, run, compose, stack, service, "
                "or health-check commands fail. Do not mask deployment failures with `|| true`, "
                "`|| echo ... skipped`, best-effort fallbacks, or messages such as container "
                "start skipped or health check skipped. Best-effort cleanup may be limited to "
                "cleanup-only commands such as `docker rm -f ... || true`."
            )
            context["instructions"].append(
                "Treat Drone deploy repairs as cumulative. When fixing one failing condition, "
                "preserve prior .drone.yml fixes such as root build steps, deploy-local docker "
                "build/load, stale container cleanup, sidecar dependencies, runtime environment, "
                "and health-log diagnostics. Do not replace the deploy step with an older partial "
                "version that drops an already-needed fix."
            )
            context["instructions"].append(
                "For Node/TypeScript apps whose Dockerfile or startup command expects compiled "
                "artifacts such as dist/index.js, ensure those artifacts exist before Docker "
                "image creation. Add or preserve a root build step before plugins/docker and "
                "before deploy-local docker build, or move the build into Dockerfile."
            )
            context["instructions"].append(
                "Health checks executed from a Drone step container must target the host-mapped "
                "service endpoint, for example http://host.docker.internal:<service-port><health-path>; "
                "do not use localhost for a service that was started by host Docker."
            )
            context["instructions"].append(
                "The docker:cli deploy image in this environment does not guarantee curl. "
                "Use docker.deploy_health_check_command from this brief, or install curl before "
                "using it. Prefer `wget -qO- ... >/dev/null` for the deploy health probe."
            )
            context["instructions"].append(
                "If a Docker deploy health probe fails, print `docker ps -a` and "
                "`docker logs <container>` before exiting so verification can see the real "
                "runtime failure. Inspect Dockerfile, docker-compose, .env.example, and app "
                "startup code for required runtime variables such as DATABASE_URL, REDIS_URL, "
                "NODE_SECRET, and SESSION_SECRET; pass required values with the docker run "
                "environment or use a compose-based deploy that starts the required services."
            )
            context["instructions"].append(
                "Docker deploy must be self-contained for app runtime dependencies. If the "
                "image requires PostgreSQL, Redis, or another service and the workspace contract "
                "does not explicitly provide a reachable external service, start those dependencies "
                "inside the deploy step with docker compose or sidecar containers on a named Docker "
                "network before starting the app container."
            )
            context["instructions"].append(
                "Before starting app or dependency sidecar containers in a retryable Drone deploy "
                "step, remove stale containers with `docker rm -f <app-container> "
                "<postgres-container> <redis-container> 2>/dev/null || true`; otherwise failed "
                "prior attempts can make Docker return a container-name conflict before the real "
                "deploy validation runs."
            )
            context["instructions"].append(
                "Before any `docker run --network <network>` in a retryable Drone deploy step, "
                "ensure the network exists idempotently with docker.deploy_network_create_command. "
                "Do not use `docker network rm <network> || true` followed by "
                "`docker network create <network>` as the normal retry path; Docker can leave the "
                "network in place with active endpoints, and a second create then fails before "
                "real deployment validation runs."
            )
            context["instructions"].append(
                "Do not satisfy DATABASE_URL, REDIS_URL, or similar runtime endpoints by pointing "
                "at host.docker.internal:<port> unless the contract explicitly declares that host "
                "service. For disposable CI deploy verification, prefer sidecar endpoints such as "
                "postgresql://postgres:postgres@<postgres-container>:5432/<db> and "
                "redis://<redis-container>:6379 on the deploy Docker network, then wait for the "
                "dependency to become ready before running the app health check."
            )
            context["instructions"].append(
                "For PostgreSQL sidecars, pass initialization values as docker run environment "
                "flags before the image: `-e POSTGRES_USER=postgres -e "
                "POSTGRES_PASSWORD=postgres -e POSTGRES_DB=<db> postgres:16-alpine`. Do not put "
                "`-c POSTGRES_PASSWORD=...` after the image; that is parsed as a postgres server "
                "flag and the database container exits before the app can connect."
            )
            context["instructions"].append(
                "Do not bind Docker deploy containers to platform-reserved host ports listed "
                "in docker.reserved_host_ports. In particular, port 8080 is the Drone server "
                "and 3001 is reserved for runner/platform use. If older service metadata or "
                ".drone.yml examples use `-p 8080:<container-port>`, replace the host side "
                "with docker.deploy_host_port, keep the container-side port matched to the "
                "Dockerfile/app, and update the Drone health check to docker.deploy_health_url."
            )
            context["instructions"].append(
                "Before finalizing Docker deploy port mappings or health paths, inspect the "
                "project Dockerfile and application routes. Workspace service metadata may be a "
                "desired host endpoint; the container-side port and health path must match what "
                "the image actually exposes and the app actually serves."
            )
            context["instructions"].append(
                "For this infrastructure, memstack-drone-runner exposes Docker through the Unix "
                "socket /var/run/docker.sock. A Drone docker deploy step using docker:cli should "
                "mount that host socket with a top-level host volume and step volume, then use the "
                "default Unix socket. Do not set DOCKER_HOST=tcp://docker:2376 unless the pipeline "
                "also defines a matching docker:dind service."
            )
            context["instructions"].append(
                "For this workspace's host-socket deploy mode, do not add a docker:dind service, "
                "a service named docker, privileged service settings, or network_mode: host. Those "
                "belong to a separate TCP DinD design and do not fix Unix-socket host deployment."
            )
            context["instructions"].append(
                "Use this exact Drone socket volume shape: in the deploy step, add "
                "`volumes: [{ name: docker-sock, path: /var/run/docker.sock }]`; at the "
                "pipeline top level, add `volumes: [{ name: docker-sock, host: { path: "
                "/var/run/docker.sock } }]`. Never mount the socket to `/var/run`; that "
                "mounts a file onto a directory and Docker rejects the deploy step."
            )
            context["instructions"].append(
                "Drone step environment variables must use YAML mapping syntax, for example "
                "`environment: { DOCKER_HOST: unix:///var/run/docker.sock }` or a nested "
                "`DOCKER_HOST: unix:///var/run/docker.sock` mapping. Do not use list syntax such "
                "as `- DOCKER_HOST=...`; Drone rejects that shape."
            )
        elif mode == "kubernetes":
            context["instructions"].append(
                "Kubernetes deploy mode requires applying the configured manifests with the "
                "configured kubeconfig secret name; CLI-only smoke output is not enough."
            )

    return context


def _contract_with_phase_drone_deploy_context(
    contract: PipelineContractSpec,
    *,
    phase: str | None,
) -> PipelineContractSpec:
    if contract.provider != DRONE_PROVIDER:
        return contract
    if not phase or phase.lower() not in _DRONE_DEPLOY_CONTEXT_PHASES:
        return contract
    deploy = contract.deploy
    if deploy is None or deploy.enabled:
        return contract
    return replace(contract, deploy=replace(deploy, enabled=True))


def _deploy_context_with_runner_hints(
    deploy: dict[str, Any],
    *,
    services: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    docker = deploy.get("docker")
    if not isinstance(docker, Mapping):
        return deploy
    if str(deploy.get("mode") or "") != "docker" and not _has_docker_deploy_hints(docker):
        return deploy

    docker_context = dict(docker)
    registry = _metadata_text(docker_context.get("registry"))
    registry_internal = _add_docker_registry_hints(docker_context, registry)
    image = _metadata_text(docker_context.get("image"))
    _add_docker_image_hints(docker_context, registry, registry_internal, image)
    _add_docker_deploy_strategy_hints(docker_context, registry, image)
    _add_docker_deploy_port_hints(docker_context, services=services)
    _add_docker_deploy_service_hints(
        docker_context,
        services=services,
        registry=registry,
        registry_internal=registry_internal,
    )
    _add_docker_deploy_dependency_hints(docker_context)
    docker_context.setdefault("runner_docker_socket", "/var/run/docker.sock")
    docker_context.setdefault("runner_docker_socket_volume", "docker-sock")

    output = dict(deploy)
    output["docker"] = docker_context
    return output


def _has_docker_deploy_hints(docker: Mapping[str, Any]) -> bool:
    for key in (
        "deploy_host_port",
        "host_port",
        "container_port",
        "deploy_services",
        "services",
        "deploy_strategy",
    ):
        if docker.get(key) is not None:
            return True
    return False


def _add_docker_registry_hints(
    docker_context: dict[str, Any],
    registry: str | None,
) -> str | None:
    if registry:
        docker_context.setdefault("registry_host_docker", registry)
    registry_internal = _drone_runner_localhost_alias(registry)
    if registry_internal:
        docker_context.setdefault("registry_internal", registry_internal)
    return registry_internal


def _add_docker_image_hints(
    docker_context: dict[str, Any],
    registry: str | None,
    registry_internal: str | None,
    image: str | None,
) -> None:
    if image:
        docker_context.setdefault("image_host_docker", image)
    if image and registry and registry_internal and image.startswith(f"{registry}/"):
        image_without_registry = image.removeprefix(f"{registry}/")
        deploy_local_image = _docker_image_with_primary_tag(image_without_registry, docker_context)
        docker_context.setdefault(
            "image_internal",
            f"{registry_internal}/{image_without_registry}",
        )
        docker_context.setdefault("image_deploy_local", deploy_local_image)
    elif image:
        docker_context.setdefault(
            "image_deploy_local",
            _docker_image_with_primary_tag(image, docker_context),
        )


def _add_docker_deploy_strategy_hints(
    docker_context: dict[str, Any],
    registry: str | None,
    image: str | None,
) -> None:
    strategy = _metadata_text(docker_context.get("deploy_strategy"))
    if strategy:
        strategy = strategy.lower()
    elif _docker_registry_is_local(registry) or _docker_image_registry_is_local(image):
        strategy = _LOCAL_DOCKER_DEPLOY_STRATEGY
    else:
        strategy = "registry_pull"
    docker_context["deploy_strategy"] = strategy
    if strategy == _LOCAL_DOCKER_DEPLOY_STRATEGY:
        docker_context["allow_daemon_registry_pull"] = False
        deploy_local_image = _metadata_text(docker_context.get("image_deploy_local"))
        if deploy_local_image:
            dockerfile = _metadata_text(docker_context.get("dockerfile")) or "Dockerfile"
            context_path = _metadata_text(docker_context.get("context")) or "."
            docker_context.setdefault(
                "deploy_local_build_command",
                f"docker build -t {deploy_local_image} -f {dockerfile} {context_path}",
            )
    else:
        docker_context.setdefault("allow_daemon_registry_pull", True)


def _add_docker_deploy_port_hints(
    docker_context: dict[str, Any],
    *,
    services: Iterable[Mapping[str, Any]],
) -> None:
    reserved_ports = tuple(sorted(_PLATFORM_RESERVED_DOCKER_HOST_PORTS))
    docker_context.setdefault("reserved_host_ports", list(reserved_ports))
    configured_host_port = _positive_int_metadata(
        docker_context.get("deploy_host_port")
        or docker_context.get("host_port")
        or docker_context.get("service_port")
    )
    if configured_host_port in _PLATFORM_RESERVED_DOCKER_HOST_PORTS:
        docker_context.setdefault("requested_host_port", configured_host_port)
        configured_host_port = None

    deploy_host_port = configured_host_port or _DEFAULT_DOCKER_DEPLOY_HOST_PORT
    docker_context["deploy_host_port"] = deploy_host_port
    docker_context.setdefault("host_port", deploy_host_port)

    container_port = _positive_int_metadata(
        docker_context.get("container_port") or docker_context.get("internal_port")
    ) or _first_service_internal_port(services)
    if container_port is not None:
        docker_context.setdefault("container_port", container_port)
        docker_context.setdefault(
            "deploy_port_mapping",
            f"{deploy_host_port}:{container_port}",
        )

    health_path = _first_service_health_path(services)
    if health_path:
        health_url = _docker_deploy_health_url(health_path, host_port=deploy_host_port)
        docker_context.setdefault("deploy_health_url", health_url)
        docker_context.setdefault(
            "deploy_health_check_command",
            _docker_deploy_health_check_command(health_url),
        )


def _add_docker_deploy_dependency_hints(docker_context: dict[str, Any]) -> None:
    docker_context.setdefault(
        "deploy_dependency_strategy",
        _DEFAULT_DOCKER_DEPLOY_DEPENDENCY_STRATEGY,
    )
    docker_context.setdefault("deploy_dependency_network", _DEFAULT_DOCKER_DEPLOY_NETWORK)
    docker_context.setdefault(
        "deploy_network_create_command",
        _DEFAULT_DOCKER_DEPLOY_NETWORK_CREATE_COMMAND,
    )
    docker_context.setdefault(
        "deploy_postgres_sidecar_image",
        _DEFAULT_DOCKER_DEPLOY_POSTGRES_IMAGE,
    )
    docker_context.setdefault(
        "deploy_postgres_sidecar_command",
        _DEFAULT_DOCKER_DEPLOY_POSTGRES_COMMAND,
    )
    docker_context.setdefault(
        "deploy_postgres_cleanup_command",
        _DEFAULT_DOCKER_DEPLOY_POSTGRES_CLEANUP_COMMAND,
    )
    docker_context.setdefault(
        "deploy_postgres_readiness_command",
        _DEFAULT_DOCKER_DEPLOY_POSTGRES_READY_COMMAND,
    )
    docker_context.setdefault("deploy_redis_sidecar_image", _DEFAULT_DOCKER_DEPLOY_REDIS_IMAGE)
    docker_context.setdefault("deploy_redis_sidecar_command", _DEFAULT_DOCKER_DEPLOY_REDIS_COMMAND)
    docker_context.setdefault(
        "deploy_redis_cleanup_command", _DEFAULT_DOCKER_DEPLOY_REDIS_CLEANUP_COMMAND
    )


def _add_docker_deploy_service_hints(
    docker_context: dict[str, Any],
    *,
    services: Iterable[Mapping[str, Any]],
    registry: str | None,
    registry_internal: str | None,
) -> None:
    rows = _docker_deploy_service_rows(docker_context, services=services)
    if not rows:
        return

    base_host_port = (
        _positive_int_metadata(docker_context.get("deploy_host_port"))
        or _DEFAULT_DOCKER_DEPLOY_HOST_PORT
    )
    strategy = _metadata_text(docker_context.get("deploy_strategy")) or ""
    used_host_ports: set[int] = set()
    deploy_services: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        deploy_service = _docker_deploy_service_hint(
            row,
            docker_context=docker_context,
            registry=registry,
            registry_internal=registry_internal,
            base_host_port=base_host_port,
            service_index=index,
            used_host_ports=used_host_ports,
            multiple_services=len(rows) > 1,
            local_build=strategy == _LOCAL_DOCKER_DEPLOY_STRATEGY,
        )
        if deploy_service:
            deploy_services.append(deploy_service)

    if not deploy_services:
        return
    docker_context["deploy_services"] = deploy_services
    docker_context["deploy_service_count"] = len(deploy_services)
    docker_context["deploy_required_service_ids"] = [
        service["service_id"] for service in deploy_services if service.get("required") is not False
    ]
    local_build_commands = [
        str(service["deploy_local_build_command"])
        for service in deploy_services
        if service.get("deploy_local_build_command")
    ]
    if local_build_commands:
        docker_context["deploy_local_build_commands"] = local_build_commands


def _docker_deploy_service_rows(
    docker_context: Mapping[str, Any],
    *,
    services: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    configured = _configured_docker_deploy_services(docker_context)
    candidates = [
        dict(service)
        for service in services
        if isinstance(service, Mapping) and _is_docker_deploy_candidate_service(service)
    ]
    if not configured:
        return candidates

    candidates_by_id = {
        service_id: service
        for service in candidates
        if (service_id := _metadata_text(service.get("service_id")))
    }
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in configured:
        service_id = _metadata_text(item.get("service_id") or item.get("id"))
        merged = dict(candidates_by_id.get(service_id or "", {}))
        merged.update(item)
        rows.append(merged)
        if service_id:
            seen.add(service_id)
    for service in candidates:
        service_id = _metadata_text(service.get("service_id"))
        if service_id and service_id not in seen:
            rows.append(dict(service))
    return rows


def _configured_docker_deploy_services(docker_context: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = docker_context.get("deploy_services")
    if not isinstance(raw, list):
        raw = docker_context.get("services")
    if not isinstance(raw, list):
        return []
    return [dict(item) for item in raw if isinstance(item, Mapping)]


def _is_docker_deploy_candidate_service(service: Mapping[str, Any]) -> bool:
    service_id = (_metadata_text(service.get("service_id")) or "").lower()
    name = (_metadata_text(service.get("name")) or "").lower()
    start_command = (_metadata_text(service.get("start_command")) or "").lower()
    if service_id in {"drone-ci", "drone-runner"} or service_id.startswith("drone-"):
        return False
    return not (
        name.startswith("drone ")
        or "drone server" in start_command
        or "drone-runner" in start_command
    )


def _docker_deploy_service_hint(
    row: Mapping[str, Any],
    *,
    docker_context: Mapping[str, Any],
    registry: str | None,
    registry_internal: str | None,
    base_host_port: int,
    service_index: int,
    used_host_ports: set[int],
    multiple_services: bool,
    local_build: bool,
) -> dict[str, Any]:
    service_id = (
        _metadata_text(row.get("service_id") or row.get("id")) or f"service-{service_index + 1}"
    )
    name = _metadata_text(row.get("name")) or service_id
    container_port = _positive_int_metadata(
        row.get("container_port") or row.get("internal_port") or row.get("port")
    ) or (
        _positive_int_metadata(
            docker_context.get("container_port") or docker_context.get("internal_port")
        )
        if not multiple_services
        else None
    )
    deploy_host_port = _positive_int_metadata(row.get("deploy_host_port") or row.get("host_port"))
    if deploy_host_port is None or deploy_host_port in _PLATFORM_RESERVED_DOCKER_HOST_PORTS:
        deploy_host_port = _next_docker_deploy_host_port(
            base_host_port + service_index,
            used_host_ports=used_host_ports,
        )
    used_host_ports.add(deploy_host_port)

    entry: dict[str, Any] = {
        "service_id": service_id,
        "name": name,
        "required": row.get("required") is not False,
        "container_name": _metadata_text(row.get("container_name"))
        or _safe_docker_container_name(service_id),
        "deploy_host_port": deploy_host_port,
    }
    start_command = _metadata_text(row.get("start_command"))
    if start_command:
        entry["start_command"] = start_command
    if container_port is not None:
        entry["container_port"] = container_port
        entry["deploy_port_mapping"] = f"{deploy_host_port}:{container_port}"

    image = (
        _metadata_text(row.get("image") or row.get("image_host_docker"))
        or _docker_run_image_from_command(start_command)
        or (_metadata_text(docker_context.get("image")) if not multiple_services else None)
    )
    if image:
        _add_docker_service_image_hints(
            entry,
            docker_context=docker_context,
            registry=registry,
            registry_internal=registry_internal,
            image=image,
        )

    dockerfile = _metadata_text(row.get("dockerfile")) or (
        _metadata_text(docker_context.get("dockerfile")) if not multiple_services else None
    )
    context_path = _metadata_text(row.get("context") or row.get("build_context")) or (
        _metadata_text(docker_context.get("context")) if not multiple_services else None
    )
    if dockerfile:
        entry["dockerfile"] = dockerfile
    if context_path:
        entry["context"] = context_path
    deploy_local_image = _metadata_text(entry.get("image_deploy_local"))
    if local_build and deploy_local_image and dockerfile and context_path:
        entry["deploy_local_build_command"] = (
            f"docker build -t {deploy_local_image} -f {dockerfile} {context_path}"
        )

    health_path = _metadata_text(row.get("health_path"))
    if health_path:
        entry["health_path"] = health_path
        health_url = _docker_deploy_health_url(health_path, host_port=deploy_host_port)
        entry["deploy_health_url"] = health_url
        entry["deploy_health_check_command"] = _docker_deploy_health_check_command(health_url)
    health_command = _metadata_text(row.get("health_command"))
    if health_command:
        entry["health_command"] = health_command
    return entry


def _add_docker_service_image_hints(
    entry: dict[str, Any],
    *,
    docker_context: Mapping[str, Any],
    registry: str | None,
    registry_internal: str | None,
    image: str,
) -> None:
    entry["image"] = image
    entry.setdefault("image_host_docker", image)
    if registry and registry_internal and image.startswith(f"{registry}/"):
        image_without_registry = image.removeprefix(f"{registry}/")
        entry.setdefault("image_internal", f"{registry_internal}/{image_without_registry}")
        entry.setdefault(
            "image_deploy_local",
            _docker_image_with_primary_tag(image_without_registry, docker_context),
        )
        return
    entry.setdefault("image_deploy_local", _docker_image_with_primary_tag(image, docker_context))


def _next_docker_deploy_host_port(start: int, *, used_host_ports: set[int]) -> int:
    port = max(1, start)
    while port in used_host_ports or port in _PLATFORM_RESERVED_DOCKER_HOST_PORTS:
        port += 1
    return port


def _safe_docker_container_name(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-")
    return normalized or "workspace-service"


def _docker_run_image_from_command(command: str | None) -> str | None:
    if not command:
        return None
    try:
        parts = shlex.split(command)
    except ValueError:
        return None
    run_index = _docker_run_index(parts)
    if run_index is None:
        return None
    options_with_value = {
        "--add-host",
        "--cidfile",
        "--env",
        "--env-file",
        "--expose",
        "--hostname",
        "--label",
        "--mount",
        "--name",
        "--network",
        "--publish",
        "--user",
        "--volume",
        "--workdir",
        "-e",
        "-h",
        "-l",
        "-m",
        "-p",
        "-u",
        "-v",
        "-w",
    }
    index = run_index + 1
    while index < len(parts):
        token = parts[index]
        if token == "--":
            index += 1
            break
        if token.startswith("-"):
            if "=" in token:
                index += 1
            elif token in options_with_value:
                index += 2
            else:
                index += 1
            continue
        return token
    if index < len(parts):
        return parts[index]
    return None


def _docker_run_index(parts: list[str]) -> int | None:
    for index, token in enumerate(parts):
        command = token.rsplit("/", 1)[-1]
        if command != "docker":
            continue
        if index + 1 < len(parts) and parts[index + 1] == "run":
            return index + 1
        if index + 2 < len(parts) and parts[index + 1] == "container" and parts[index + 2] == "run":
            return index + 2
    return None


def _positive_int_metadata(value: Any) -> int | None:  # noqa: ANN401
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _first_service_internal_port(services: Iterable[Mapping[str, Any]]) -> int | None:
    for service in services:
        value = _positive_int_metadata(service.get("internal_port"))
        if value is not None:
            return value
    return None


def _first_service_health_path(services: Iterable[Mapping[str, Any]]) -> str | None:
    for service in services:
        health_path = _metadata_text(service.get("health_path"))
        if health_path:
            return health_path
    return None


def _docker_deploy_health_url(health_path: str, *, host_port: int) -> str:
    if health_path.startswith("http://") or health_path.startswith("https://"):
        return health_path
    normalized_path = health_path if health_path.startswith("/") else f"/{health_path}"
    return f"http://host.docker.internal:{host_port}{normalized_path}"


def _docker_deploy_health_check_command(health_url: str) -> str:
    return f"wget -qO- {health_url} >/dev/null"


def _docker_image_with_primary_tag(image: str, docker: Mapping[str, Any]) -> str:
    if _docker_image_has_tag(image):
        return image
    tag = _primary_docker_tag(docker)
    return f"{image}:{tag}" if tag else image


def _docker_image_has_tag(image: str) -> bool:
    last_segment = image.rsplit("/", 1)[-1]
    return ":" in last_segment


def _primary_docker_tag(docker: Mapping[str, Any]) -> str | None:
    tags = docker.get("tags")
    if not isinstance(tags, list):
        return None
    for tag in tags:
        value = str(tag).strip()
        if value:
            return value
    return None


def _docker_registry_is_local(value: str | None) -> bool:
    host = _docker_registry_host(value)
    return bool(host and host in _LOCAL_REGISTRY_HOSTS)


def _docker_image_registry_is_local(value: str | None) -> bool:
    if not value:
        return False
    first_segment = value.split("/", 1)[0]
    if "." not in first_segment and ":" not in first_segment and first_segment != "localhost":
        return False
    return _docker_registry_is_local(first_segment)


def _docker_registry_host(value: str | None) -> str | None:
    if not value:
        return None
    rest = value.strip()
    if "://" in rest:
        rest = rest.split("://", 1)[1]
    rest = rest.rsplit("@", 1)[-1].split("/", 1)[0]
    if rest.startswith("[") and "]" in rest:
        return rest[1 : rest.index("]")].lower()
    return rest.split(":", 1)[0].lower()


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
    _append_delivery_service_lines(lines, context.get("services"), deploy=context.get("deploy"))
    _append_delivery_instruction_lines(lines, context.get("instructions"))
    return "\n".join(lines)


def _pipeline_evidence_from_metadata(
    plan_node_metadata: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(plan_node_metadata, Mapping):
        return None
    value = plan_node_metadata.get(_LATEST_PIPELINE_EVIDENCE_KEY)
    if isinstance(value, Mapping):
        return dict(value)
    recent = plan_node_metadata.get(_RECENT_PIPELINE_EVIDENCE_KEY)
    if isinstance(recent, list):
        for item in recent:
            if isinstance(item, Mapping):
                return dict(item)
    return None


def _render_pipeline_evidence_brief(evidence: Mapping[str, Any] | None) -> str | None:
    if not isinstance(evidence, Mapping) or not evidence:
        return None

    lines = [
        "## Latest platform pipeline evidence",
        "Source: `workspace_pipeline_runs` (platform-persisted, current CI/CD evidence)",
    ]
    for key, label in (
        ("id", "Pipeline run"),
        ("provider", "Provider"),
        ("status", "Status"),
        ("commit_ref", "Commit"),
        ("reason", "Reason"),
        ("created_at", "Created at"),
        ("completed_at", "Completed at"),
    ):
        value = _metadata_display_value(evidence.get(key))
        if value:
            lines.append(f"{label}: `{value}`")

    metadata = evidence.get("metadata")
    if isinstance(metadata, Mapping):
        for key, label in (
            ("external_id", "External run"),
            ("external_url", "External URL"),
            ("drone_build_number", "Drone build"),
            ("drone_repo", "Drone repo"),
            ("drone_status", "Drone status"),
            ("deployment_status", "Deployment status"),
            ("deploy_validation", "Deploy validation"),
            ("deploy_validation_failure", "Deploy validation failure"),
            ("pipeline_failure_summary", "Pipeline failure summary"),
            ("pipeline_last_summary", "Pipeline summary"),
        ):
            value = _metadata_display_value(metadata.get(key))
            if value:
                lines.append(f"{label}: `{value}`")

    lines.extend(
        [
            "Evidence rule: treat this platform-persisted pipeline evidence as the current "
            "CI/CD state for this workspace. Older pipeline_failure_summary, "
            "pipeline_failed_stage, handoff notes, or recalled Drone failures are historical "
            "unless they reference this same run id, external run, or commit.",
            "Secret rule: do not retrieve, echo, or print CI/CD tokens just to confirm this "
            "pipeline state. Query external logs only when this evidence is insufficient, and "
            "never include token values in shell commands or reports.",
        ]
    )
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
        ("image_host_docker", "Docker image (host Docker deploy)"),
        ("image_deploy_local", "Docker image (deploy local tag)"),
        ("deploy_strategy", "Docker deploy strategy"),
        ("deploy_local_build_command", "Docker deploy local build command"),
        ("deploy_host_port", "Docker deploy host port"),
        ("container_port", "Docker deploy container port"),
        ("deploy_port_mapping", "Docker deploy port mapping"),
        ("deploy_health_url", "Docker deploy health URL"),
        ("deploy_health_check_command", "Docker deploy health check command"),
        ("deploy_dependency_strategy", "Docker deploy dependency strategy"),
        ("deploy_dependency_network", "Docker deploy dependency network"),
        ("deploy_network_create_command", "Docker deploy network create command"),
        ("deploy_postgres_sidecar_image", "Docker deploy PostgreSQL sidecar image"),
        ("deploy_postgres_sidecar_command", "Docker deploy PostgreSQL sidecar command"),
        ("deploy_postgres_cleanup_command", "Docker deploy PostgreSQL cleanup command"),
        ("deploy_postgres_readiness_command", "Docker deploy PostgreSQL readiness command"),
        ("deploy_redis_sidecar_image", "Docker deploy Redis sidecar image"),
        ("deploy_redis_sidecar_command", "Docker deploy Redis sidecar command"),
        ("deploy_redis_cleanup_command", "Docker deploy Redis cleanup command"),
        ("registry", "Docker registry"),
        ("registry_internal", "Docker registry (Drone runner)"),
        ("registry_host_docker", "Docker registry (host Docker deploy)"),
        ("dockerfile", "Dockerfile"),
        ("runner_docker_socket", "Drone Docker socket"),
        ("runner_docker_socket_volume", "Drone Docker socket volume"),
    ):
        value = _metadata_display_value(docker.get(key))
        if value:
            lines.append(f"{label}: `{value}`")
    if isinstance(docker.get("allow_daemon_registry_pull"), bool):
        value = str(docker["allow_daemon_registry_pull"]).lower()
        lines.append(f"Docker daemon registry pull allowed: `{value}`")
    reserved_ports = docker.get("reserved_host_ports")
    if isinstance(reserved_ports, list) and reserved_ports:
        safe_ports = [str(port) for port in reserved_ports if str(port).strip()]
        if safe_ports:
            lines.append(f"Reserved Docker host ports: {', '.join(safe_ports)}")
    tags = docker.get("tags")
    if isinstance(tags, list) and tags:
        safe_tags = [str(tag) for tag in tags if str(tag).strip()]
        if safe_tags:
            lines.append(f"Docker tags: {', '.join(safe_tags)}")
    _append_delivery_docker_service_lines(lines, docker)


def _append_delivery_docker_service_lines(lines: list[str], docker: Mapping[str, Any]) -> None:
    deploy_services = docker.get("deploy_services")
    if not isinstance(deploy_services, list) or not deploy_services:
        return
    rendered: list[str] = []
    for service in deploy_services:
        if not isinstance(service, Mapping):
            continue
        service_id = _metadata_text(service.get("service_id")) or "service"
        name = _metadata_text(service.get("name")) or service_id
        parts = [f"- {service_id} ({name})"]
        for key, label in (
            ("container_name", "container"),
            ("image", "image"),
            ("image_internal", "runner image"),
            ("image_deploy_local", "deploy image"),
            ("dockerfile", "dockerfile"),
            ("context", "context"),
            ("deploy_local_build_command", "local build"),
            ("deploy_port_mapping", "port"),
            ("deploy_health_url", "health"),
            ("deploy_health_check_command", "health command"),
        ):
            value = _metadata_display_value(service.get(key))
            if value:
                parts.append(f"{label}: `{value}`")
        if service.get("required") is False:
            parts.append("required: `false`")
        rendered.append("; ".join(parts))
    if rendered:
        lines.append("Docker deploy services:")
        lines.extend(rendered)


def _append_delivery_service_lines(
    lines: list[str],
    services: object,
    *,
    deploy: object = None,
) -> None:
    if not isinstance(services, list) or not services:
        return
    rendered: list[str] = []
    for service in services:
        if not isinstance(service, Mapping):
            continue
        service_id = _metadata_text(service.get("service_id")) or "service"
        name = _metadata_text(service.get("name")) or service_id
        start_command = _metadata_text(service.get("start_command"))
        internal_port = service.get("internal_port")
        health_path = _metadata_text(service.get("health_path"))
        parts = [f"- {service_id} ({name})"]
        if start_command:
            parts.append(f"start: `{start_command}`")
        if isinstance(internal_port, int):
            parts.append(f"port: {internal_port}")
        if health_path:
            parts.append(f"health: `{health_path}`")
        deploy_service = _docker_deploy_service_for_display(service, deploy)
        drone_health_url = _drone_runner_service_health_url(
            service,
            deploy_service=deploy_service,
        )
        if drone_health_url:
            parts.append(f"Drone step health: `{drone_health_url}`")
        rendered.append("; ".join(parts))
    if rendered:
        lines.append("Deployment services:")
        lines.extend(rendered)


def _metadata_display_value(value: object) -> str | None:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return str(value)
    return _metadata_text(value)


def _docker_deploy_service_for_display(
    service: Mapping[str, Any],
    deploy: object,
) -> Mapping[str, Any] | None:
    if not isinstance(deploy, Mapping):
        return None
    docker = deploy.get("docker")
    if not isinstance(docker, Mapping):
        return None
    raw_services = docker.get("deploy_services")
    if not isinstance(raw_services, list):
        raw_services = docker.get("services")
    if not isinstance(raw_services, list):
        return None

    service_id = (_metadata_text(service.get("service_id")) or "").lower()
    service_name = (_metadata_text(service.get("name")) or "").lower()
    for item in raw_services:
        if not isinstance(item, Mapping):
            continue
        item_id = (
            _metadata_text(item.get("service_id") or item.get("id") or item.get("name")) or ""
        ).lower()
        item_name = (_metadata_text(item.get("name")) or "").lower()
        if item_id and item_id == service_id:
            return item
        if item_name and item_name == service_name:
            return item
    return None


def _drone_runner_service_health_url(
    service: Mapping[str, Any],
    *,
    deploy_service: Mapping[str, Any] | None = None,
) -> str | None:
    deploy_health_url = (
        _metadata_text(deploy_service.get("deploy_health_url")) if deploy_service else None
    )
    if deploy_health_url:
        return deploy_health_url
    host_port = (
        _positive_int_metadata(
            deploy_service.get("deploy_host_port") or deploy_service.get("host_port")
        )
        if deploy_service
        else None
    )
    internal_port = service.get("internal_port")
    port = host_port or (internal_port if isinstance(internal_port, int) else None)
    if not isinstance(port, int) or port <= 0:
        return None
    scheme = _metadata_text(service.get("internal_scheme")) or "http"
    if scheme not in {"http", "https"}:
        scheme = "http"
    health_path = (
        (_metadata_text(deploy_service.get("health_path")) if deploy_service else None)
        or _metadata_text(service.get("health_path"))
        or "/"
    )
    if health_path.startswith("http://") or health_path.startswith("https://"):
        return health_path
    normalized_path = health_path if health_path.startswith("/") else f"/{health_path}"
    return f"{scheme}://host.docker.internal:{port}{normalized_path}"


def _append_delivery_instruction_lines(lines: list[str], instructions: object) -> None:
    if not isinstance(instructions, list) or not instructions:
        return
    rendered = [str(item).strip() for item in instructions if str(item).strip()]
    if not rendered:
        return
    lines.append("Contract rules:")
    lines.extend(f"- {item}" for item in rendered)


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
                (
                    "In this sandbox, oversized MCP tool arguments can time out without reaching "
                    "the server. Keep each edit/write/bash payload below the stated limits even "
                    "when the apparent source change is small."
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
        fallback_code_root=code_context.sandbox_code_root if code_context is not None else None,
        fallback_host_code_root=code_context.host_code_root if code_context is not None else None,
    )
    if delivery_cicd is not None:
        context["delivery_cicd"] = delivery_cicd
    if pipeline_evidence := _pipeline_evidence_from_metadata(plan_node_metadata):
        context[_LATEST_PIPELINE_EVIDENCE_KEY] = pipeline_evidence
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
    allowed_script_paths = _verification_script_change_allowlist(metadata, source_metadata)
    if allowed_script_paths:
        metadata["allowed_verification_script_paths"] = allowed_script_paths
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
        fallback_code_root=code_context.sandbox_code_root if code_context is not None else None,
        fallback_host_code_root=code_context.host_code_root if code_context is not None else None,
    )
    if delivery_cicd is not None:
        sections.append(_render_delivery_cicd_brief(delivery_cicd))
    if pipeline_evidence_brief := _render_pipeline_evidence_brief(
        _pipeline_evidence_from_metadata(plan_node_metadata)
    ):
        sections.append(pipeline_evidence_brief)
    sections.append(
        "## Artifact write discipline\n"
        "Never use bash heredocs, inline Python scripts, or one-shot write calls to create "
        "a full source file, page, fixture, or long document. First create a tiny skeleton, "
        "then use edit or write mode='append' in small sections. Keep every write/edit "
        f"payload under {WORKER_RECOMMENDED_WRITE_CHUNK_CHARS} characters; the hard write "
        f"limit is {WORKER_MAX_SINGLE_WRITE_CHARS} characters and any bash command under "
        f"{WORKER_MAX_SINGLE_BASH_COMMAND_CHARS} characters. If a tool reports truncated "
        "arguments or times out, do not retry with the same shape; immediately switch to smaller "
        "edit/append chunks. Oversized MCP tool arguments can time out without reaching the "
        "sandbox server."
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
        elif _contains_repair_turn_prompt(rendered_extra):
            sections.append(
                "## Repair turn instructions - highest priority\n"
                f"{rendered_extra}\n\n"
                "Treat this repair turn as the active task context. Address the listed "
                "verification failures before reusing any older worker report or completion "
                "summary."
            )
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


def _contains_repair_turn_prompt(value: str) -> bool:
    return "[repair-turn]" in value and "[/repair-turn]" in value


async def launch_worker_session(
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
    """Reject retired platform-owned worker launch without constructing services."""
    from src.infrastructure.workspace_core.legacy_runtime import legacy_workspace_runtime_retired

    legacy_workspace_runtime_retired("Workspace worker launch")


def _terminal_report_metadata_matches_attempt(
    metadata: Mapping[str, Any] | None,
    *,
    attempt_id: str | None,
    report_type: str | None,
) -> bool:
    if not attempt_id or not isinstance(metadata, Mapping):
        return False
    if metadata.get(LAST_WORKER_REPORT_ATTEMPT_ID) != attempt_id:
        return False
    return not report_type or metadata.get("last_worker_report_type") == report_type


async def _run_reserved_worker_session(
    reservation: _WorkerOperationReservationV2,
    launch: _WorkerLaunchFactory,
    *,
    operation_id: str,
    metadata: Mapping[str, object],
) -> None:
    async with reservation.admit(
        operation_id=operation_id,
        metadata=metadata,
    ):
        _ = await launch()


def _finish_reserved_worker_session(
    completed: asyncio.Task[None],
    reservation: _WorkerOperationReservationV2,
) -> None:
    _background_tasks.discard(completed)
    cleanup = asyncio.create_task(
        reservation.release(),
        name=f"{completed.get_name()}:release-generation",
    )
    _background_tasks.add(cleanup)
    cleanup.add_done_callback(_background_tasks.discard)


async def schedule_worker_session(
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
    """Fork the active Agent operation and schedule ``launch_worker_session``.

    Reservation failures are surfaced before returning to the caller. Errors
    during the launched coroutine are logged inside ``launch_worker_session``.
    """
    from src.infrastructure.plugins.v2.boundary import (
        detached_operation_task_context_v2,
        fork_current_agent_operation_v2,
    )

    reservation = await fork_current_agent_operation_v2()
    operation_id = f"workspace-worker-launch:{task.id}"
    operation_metadata: dict[str, object] = {
        "kind": "workspace-worker-launch",
        "workspace_id": workspace_id,
        "task_id": task.id,
        "worker_agent_id": worker_agent_id,
    }
    if attempt_id:
        operation_metadata["attempt_id"] = attempt_id

    def launch() -> Awaitable[dict[str, Any]]:
        return launch_worker_session(
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

    drive_launch = _run_reserved_worker_session(
        reservation,
        launch,
        operation_id=operation_id,
        metadata=operation_metadata,
    )
    try:
        bg = asyncio.create_task(
            drive_launch,
            name=operation_id,
            context=detached_operation_task_context_v2(),
        )
    except BaseException:
        drive_launch.close()
        await reservation.release()
        raise

    _background_tasks.add(bg)
    bg.add_done_callback(lambda completed: _finish_reserved_worker_session(completed, reservation))


__all__ = [
    "WORKER_LAUNCH_COOLDOWN_SECONDS",
    "_build_worker_brief",
    "_build_worker_system_context",
    "_conversation_id_for_worker",
    "_conversation_scope_for_task",
    "_effective_repair_plan_node_metadata",
    "_terminal_report_metadata_matches_attempt",
    "launch_worker_session",
    "schedule_worker_session",
]
