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
import logging
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from src.application.services.workspace_autonomy_profiles import evaluate_workspace_code_context
from src.domain.model.workspace.workspace_task import WorkspaceTask
from src.infrastructure.agent.workspace.code_context import (
    WorkspaceCodeContext,
    load_workspace_code_context,
)
from src.infrastructure.agent.workspace.workspace_metadata_keys import (
    CURRENT_ATTEMPT_ID,
    CURRENT_ATTEMPT_WORKER_BINDING_ID,
    ROOT_GOAL_TASK_ID,
)

logger = logging.getLogger(__name__)

_background_tasks: set[asyncio.Task[Any]] = set()

# Cooldown TTL — long enough to avoid double-launch on transient retries
# but short enough that a genuine re-assignment after rework can re-fire.
WORKER_LAUNCH_COOLDOWN_SECONDS = 300

_WORKSPACE_APP_CONTEXT_TYPE = "workspace_worker_runtime"
_NATIVE_TOOL_PROTOCOL_GUARD = (
    "Use only the platform's native tool-call channel for tools. Do not print "
    "tool-call markup, JSON/function-call stubs, or shell command code blocks as "
    "a substitute for a tool call. In particular, never emit [TOOL_CALL], "
    "[/TOOL_CALL], {tool => ...}, <minimax:tool_call>, or <invoke name=...> text."
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


def _build_worker_system_context(
    *,
    workspace_id: str,
    task: WorkspaceTask,
    attempt_id: str | None,
    leader_agent_id: str | None,
    extra_instructions: str | None = None,
    code_context: WorkspaceCodeContext | None = None,
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
            "instructions": [
                "Execute the assigned workspace task autonomously.",
                "Call workspace_report_progress periodically during long-running work.",
                "Call workspace_report_complete once when finished successfully.",
                "Call workspace_report_blocked if a hard blocker cannot be recovered.",
            ],
        },
    }

    if code_context is not None and code_context.sandbox_code_root:
        code_context_payload: dict[str, Any] = {
            "sandbox_code_root": code_context.sandbox_code_root,
            "loaded_agents_files": list(code_context.loaded_agents_paths),
            "agents_digest": code_context.agents_digest,
            "rule": (
                "Perform repository inspection, file edits, terminal commands, git diff, "
                "and tests from sandbox_code_root. Ignore unrelated files outside that "
                "directory unless the task explicitly asks for them. Read and follow the "
                "listed AGENTS.md files before decomposing or executing the task."
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

    if extra_instructions:
        rendered_extra = _render_workspace_placeholders(extra_instructions.strip(), code_context)
        if rendered_extra:
            context["additional_instructions"] = rendered_extra

    return context


def _render_workspace_placeholders(
    instructions: str,
    code_context: WorkspaceCodeContext | None,
) -> str:
    if code_context is None or not code_context.sandbox_code_root:
        return instructions
    return instructions.replace("${sandbox_code_root}", code_context.sandbox_code_root)


def _build_worker_brief(
    *,
    workspace_id: str,
    task: WorkspaceTask,
    attempt_id: str | None,
    leader_agent_id: str | None,
    extra_instructions: str | None = None,
    code_context: WorkspaceCodeContext | None = None,
) -> str:
    """Compose the visible task brief for the worker agent.

    Operational policy, code-root context, AGENTS.md content, and reporting
    requirements are injected as system model context by
    :func:`_build_worker_system_context`. Keeping the visible user message
    task-focused avoids teaching the model to imitate tool-call protocol text.
    """
    description = (task.description or "").strip()
    binding = _workspace_binding_metadata(
        workspace_id=workspace_id,
        task=task,
        attempt_id=attempt_id,
        leader_agent_id=leader_agent_id,
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
    if description:
        sections.append(f"## Task description\n{description}")

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


async def launch_worker_session(  # noqa: C901, PLR0911, PLR0912, PLR0915
    *,
    workspace_id: str,
    task: WorkspaceTask,
    worker_agent_id: str,
    actor_user_id: str,
    leader_agent_id: str | None = None,
    attempt_id: str | None = None,
    extra_instructions: str | None = None,
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
    A plain stream ``complete`` is not a workspace terminal report; the attempt
    is left RUNNING and we log ``no_terminal_event`` so the worker must call
    the explicit workspace reporting tools.
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
    root_goal_task_id = ""
    candidate = task.metadata.get(ROOT_GOAL_TASK_ID)
    if isinstance(candidate, str) and candidate:
        root_goal_task_id = candidate

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
            workspace_metadata = dict(getattr(workspace, "metadata", {}) or {})
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

            resolved_conversation_id = _conversation_id_for_worker(
                workspace_id=workspace_id,
                worker_agent_id=worker_agent_id,
                task_id=task.id,
                attempt_id=attempt.id,
            )

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
                    id=resolved_conversation_id,
                    project_id=workspace.project_id,
                    tenant_id=workspace.tenant_id,
                    user_id=actor_user_id,
                    title=f"Workspace Worker - {task.title[:80]}",
                    status=ConversationStatus.ACTIVE,
                    agent_config={"selected_agent_id": worker_agent_id},
                    metadata={
                        "workspace_id": workspace_id,
                        "agent_id": worker_agent_id,
                        "workspace_agent_binding_id": worker_binding.id,
                        "workspace_task_id": task.id,
                        ROOT_GOAL_TASK_ID: root_goal_task_id,
                        "attempt_id": attempt.id,
                        "conversation_scope": _conversation_scope_for_task(task.id, attempt.id),
                        "source": "workspace_worker_launch",
                        "created_at": datetime.now(UTC).isoformat(),
                    },
                    message_count=0,
                    created_at=datetime.now(UTC),
                )
                await conversation_repo.save(conversation)

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
                metadata_patch: dict[str, Any] = {
                    CURRENT_ATTEMPT_ID: attempt.id,
                    "current_attempt_number": attempt.attempt_number,
                    "current_attempt_conversation_id": resolved_conversation_id,
                    "current_attempt_worker_agent_id": worker_agent_id,
                    CURRENT_ATTEMPT_WORKER_BINDING_ID: worker_binding.id,
                    "launch_state": "bound",
                }
                metadata_patch["code_context"] = _code_context_metadata(code_context)
                await command_service.update_task(
                    workspace_id=workspace_id,
                    task_id=task.id,
                    actor_user_id=actor_user_id,
                    metadata=metadata_patch,
                    actor_type="agent" if leader_agent_id else "human",
                    actor_agent_id=leader_agent_id,
                    reason="workspace_worker_launch.bind_conversation",
                    authority=(
                        WorkspaceTaskAuthorityContext.leader(leader_agent_id)
                        if leader_agent_id
                        else None
                    ),
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
    except Exception:
        logger.warning(
            "workspace_worker_launch.setup_failed",
            extra={
                "event": "workspace_worker_launch.setup_failed",
                "workspace_id": workspace_id,
                "task_id": task.id,
            },
            exc_info=True,
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
        extra_instructions=extra_instructions,
        code_context=code_context,
    )
    app_model_context = _build_worker_system_context(
        workspace_id=workspace_id,
        task=task,
        attempt_id=resolved_attempt_id,
        leader_agent_id=leader_agent_id,
        extra_instructions=extra_instructions,
        code_context=code_context,
    )
    final_content = ""
    accumulated_text = ""
    terminal_event: str | None = None  # "complete" | "error" | None

    try:
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
            async for event in agent_service.stream_chat_v2(
                conversation_id=resolved_conversation_id,
                user_message=user_message,
                project_id=workspace.project_id,
                user_id=actor_user_id,
                tenant_id=workspace.tenant_id,
                agent_id=worker_agent_id,
                app_model_context=app_model_context,
            ):
                event_type = event.get("type")
                if event_type == "text_delta":
                    accumulated_text += event.get("data", {}).get("text", "")
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

    # --- Stage 3: terminal report -----------------------------------------
    outcome_reason: str
    if terminal_event == "complete":
        outcome_reason = "no_terminal_event"
        await _patch_task_launch_state(
            workspace_id=workspace_id,
            task_id=task.id,
            actor_user_id=actor_user_id,
            leader_agent_id=leader_agent_id,
            launch_state="no_terminal_event",
        )
        logger.warning(
            "workspace_worker_launch.stream_complete_without_terminal_report",
            extra={
                "event": "workspace_worker_launch.stream_complete_without_terminal_report",
                "workspace_id": workspace_id,
                "task_id": task.id,
                "conversation_id": resolved_conversation_id,
                "attempt_id": resolved_attempt_id,
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
        outcome_reason = "no_terminal_event"
        await _patch_task_launch_state(
            workspace_id=workspace_id,
            task_id=task.id,
            actor_user_id=actor_user_id,
            leader_agent_id=leader_agent_id,
            launch_state="no_terminal_event",
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
            await WorkspaceTaskCommandService(task_service).update_task(
                workspace_id=workspace_id,
                task_id=task_id,
                actor_user_id=actor_user_id,
                metadata={"launch_state": launch_state},
                actor_type="agent" if leader_agent_id else "human",
                actor_agent_id=leader_agent_id,
                reason=f"workspace_worker_launch.{launch_state}",
                authority=(
                    WorkspaceTaskAuthorityContext.leader(leader_agent_id)
                    if leader_agent_id
                    else None
                ),
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
) -> None:
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


def schedule_worker_session(
    *,
    workspace_id: str,
    task: WorkspaceTask,
    worker_agent_id: str,
    actor_user_id: str,
    leader_agent_id: str | None = None,
    attempt_id: str | None = None,
    extra_instructions: str | None = None,
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
