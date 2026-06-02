"""Builtin-agent backed worktree preparation for workspace worker launches."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import posixpath
from collections.abc import AsyncIterator, Mapping
from typing import TYPE_CHECKING, Any, Protocol

from src.infrastructure.agent.sisyphus.builtin_agent import (
    build_builtin_workspace_worktree_manager_agent,
)
from src.infrastructure.agent.tools.workspace_plan_contract_tools import (
    WORKSPACE_SUBMIT_WORKTREE_PREPARATION_TOOL_NAME,
)
from src.infrastructure.agent.workspace.contract_agent_runtime import (
    contract_tool_payload_from_event,
    workspace_contract_input_fingerprint,
)
from src.infrastructure.agent.workspace_plan.worktree_manager import (
    AttemptWorktreeContext,
    AttemptWorktreePreparationRequest,
    compact_command_output,
)

if TYPE_CHECKING:
    from src.domain.model.agent.agent_definition import Agent

logger = logging.getLogger(__name__)

_MISSING_CONTRACT_RETRY_ATTEMPTS = 1
_DEFAULT_WORKTREE_MANAGER_TURN_TIMEOUT_SECONDS = 300
_MAX_WORKTREE_MANAGER_TURN_TIMEOUT_SECONDS = 1800


class WorkspaceWorktreeAgentTurnRunner(Protocol):
    """Runs one builtin workspace-worktree-manager turn."""

    @property
    def last_diagnostics(self) -> dict[str, Any]: ...

    async def run_preparation_turn(
        self,
        *,
        worktree_agent: Agent,
        user_prompt: str,
        workspace_id: str,
        task_id: str,
        attempt_id: str | None,
    ) -> dict[str, Any] | None: ...


class _WorkspaceContractAgentService(Protocol):
    def stream_chat_v2(
        self,
        *,
        conversation_id: str,
        user_message: str,
        user_id: str,
        project_id: str,
        tenant_id: str,
        agent_id: str,
        app_model_context: dict[str, Any] | None = None,
    ) -> AsyncIterator[dict[str, Any]]: ...


class RuntimeWorkspaceWorktreeAgentTurnRunner:
    """Run the builtin worktree manager through the normal project ReAct runtime."""

    def __init__(
        self,
        *,
        tenant_id: str,
        project_id: str,
        max_steps: int = 8,
        max_tokens: int = 8192,
        turn_timeout_seconds: float | None = None,
    ) -> None:
        super().__init__()
        self._tenant_id = tenant_id
        self._project_id = project_id
        self._max_steps = max_steps
        self._max_tokens = max_tokens
        self._turn_timeout_seconds = (
            turn_timeout_seconds
            if turn_timeout_seconds is not None
            else _worktree_manager_turn_timeout_seconds()
        )
        self._last_diagnostics: dict[str, Any] = {}

    @property
    def last_diagnostics(self) -> dict[str, Any]:
        return dict(self._last_diagnostics)

    async def run_preparation_turn(
        self,
        *,
        worktree_agent: Agent,
        user_prompt: str,
        workspace_id: str,
        task_id: str,
        attempt_id: str | None,
    ) -> dict[str, Any] | None:
        from src.configuration.factories import create_llm_client
        from src.infrastructure.adapters.secondary.persistence.database import (
            async_session_factory,
        )
        from src.infrastructure.agent.workspace.contract_agent_runtime import (
            create_workspace_contract_agent_service,
            recover_workspace_contract_payload,
            resolve_workspace_actor_user_id,
            workspace_contract_conversation_id,
        )
        from src.infrastructure.agent.workspace.runtime_role_contract import (
            WORKSPACE_ROLE_CONTRACT,
            WORKSPACE_SESSION_ROLE_KEY,
        )
        from src.infrastructure.agent.workspace.session_conversations import (
            ensure_workspace_llm_conversation,
        )

        input_fingerprint = workspace_contract_input_fingerprint(
            user_prompt,
            workspace_id,
            task_id,
            attempt_id or "",
            worktree_agent.id,
        )
        conversation_id = workspace_contract_conversation_id(
            "worktree-manager",
            self._tenant_id,
            self._project_id,
            workspace_id,
            task_id,
            attempt_id or "none",
            input_fingerprint,
        )
        diagnostics: dict[str, Any] = {
            "conversation_id": conversation_id,
            "input_fingerprint": input_fingerprint,
            "event_count": 0,
            "observed_tools": [],
            "preparation_submitted": False,
            "runtime_path": "agent_service.stream_chat_v2",
            "turn_timeout_seconds": self._turn_timeout_seconds,
        }
        recovered_payload = await recover_workspace_contract_payload(
            conversation_id=conversation_id,
            extract_payload=_worktree_preparation_from_event,
        )
        if recovered_payload is not None:
            diagnostics["recovered_from_events"] = True
            diagnostics["preparation_submitted"] = True
            self._last_diagnostics = diagnostics
            return recovered_payload

        resolved_actor_user_id = await resolve_workspace_actor_user_id(workspace_id=workspace_id)
        diagnostics["actor_user_resolved"] = bool(resolved_actor_user_id)
        if not resolved_actor_user_id:
            self._last_diagnostics = diagnostics
            return None

        diagnostics["session_persisted"] = await ensure_workspace_llm_conversation(
            conversation_id=conversation_id,
            tenant_id=self._tenant_id,
            project_id=self._project_id,
            workspace_id=workspace_id,
            linked_workspace_task_id=task_id,
            agent_id=worktree_agent.id,
            actor_user_id=resolved_actor_user_id,
            title=f"Workspace Worktree Manager - {task_id}",
            stage="worktree_manager",
            metadata={
                "linked_workspace_task_id": task_id,
                "current_attempt_id": attempt_id or "",
                "conversation_scope": f"worktree:{task_id}:{attempt_id or 'none'}",
            },
        )
        if not diagnostics["session_persisted"]:
            self._last_diagnostics = diagnostics
            return None

        app_model_context = {
            "context_type": "workspace_worker_runtime",
            WORKSPACE_SESSION_ROLE_KEY: WORKSPACE_ROLE_CONTRACT,
            "workspace_binding": {
                "workspace_id": workspace_id,
                "linked_workspace_task_id": task_id,
                "current_attempt_id": attempt_id or "",
            },
            "worktree_manager": {
                "task_id": task_id,
                "attempt_id": attempt_id or "",
            },
            "runtime_limits": {
                "max_tokens": self._max_tokens,
            },
            "llm_overrides": {"max_tokens": self._max_tokens},
        }
        async with async_session_factory() as db:
            llm = await create_llm_client(self._tenant_id)
            agent_service = await create_workspace_contract_agent_service(db=db, llm=llm)
            payload = await self._stream_preparation_payload(
                agent_service=agent_service,
                conversation_id=conversation_id,
                user_prompt=user_prompt,
                resolved_actor_user_id=resolved_actor_user_id,
                worktree_agent_id=worktree_agent.id,
                workspace_id=workspace_id,
                task_id=task_id,
                attempt_id=attempt_id,
                app_model_context=app_model_context,
                diagnostics=diagnostics,
            )
            if payload is not None:
                return payload
        recovered_payload = await recover_workspace_contract_payload(
            conversation_id=conversation_id,
            extract_payload=_worktree_preparation_from_event,
        )
        if recovered_payload is not None:
            diagnostics["recovered_from_events"] = True
            diagnostics["preparation_submitted"] = True
            self._last_diagnostics = diagnostics
            return recovered_payload
        self._last_diagnostics = diagnostics
        return None

    async def _stream_preparation_payload(
        self,
        *,
        agent_service: _WorkspaceContractAgentService,
        conversation_id: str,
        user_prompt: str,
        resolved_actor_user_id: str,
        worktree_agent_id: str,
        workspace_id: str,
        task_id: str,
        attempt_id: str | None,
        app_model_context: Mapping[str, Any],
        diagnostics: dict[str, Any],
    ) -> dict[str, Any] | None:
        from src.infrastructure.agent.workspace.contract_agent_runtime import (
            cancel_workspace_contract_chat,
        )

        try:
            async with asyncio.timeout(self._turn_timeout_seconds):
                async for event in agent_service.stream_chat_v2(
                    conversation_id=conversation_id,
                    user_message=user_prompt,
                    user_id=resolved_actor_user_id,
                    project_id=self._project_id,
                    tenant_id=self._tenant_id,
                    agent_id=worktree_agent_id,
                    app_model_context=dict(app_model_context),
                ):
                    diagnostics["event_count"] += 1
                    tool_name = _tool_name_from_event(event)
                    if tool_name:
                        observed_tools = diagnostics["observed_tools"]
                        if tool_name not in observed_tools:
                            observed_tools.append(tool_name)
                    payload = _worktree_preparation_from_event(event)
                    if payload is not None:
                        diagnostics["preparation_submitted"] = True
                        self._last_diagnostics = diagnostics
                        await cancel_workspace_contract_chat(conversation_id)
                        return payload
        except TimeoutError:
            diagnostics["timed_out"] = True
            self._last_diagnostics = diagnostics
            await cancel_workspace_contract_chat(conversation_id)
            logger.warning(
                "Workspace worktree-manager contract turn timed out",
                extra={
                    "conversation_id": conversation_id,
                    "workspace_id": workspace_id,
                    "task_id": task_id,
                    "attempt_id": attempt_id,
                    "timeout_seconds": self._turn_timeout_seconds,
                },
            )
        except asyncio.CancelledError:
            await cancel_workspace_contract_chat(conversation_id)
            raise
        return None


class WorkspaceWorktreeAgentPreparer:
    """Attempt worktree preparer backed by the builtin worktree manager agent."""

    def __init__(
        self,
        *,
        tenant_id: str,
        project_id: str,
        missing_contract_retry_attempts: int = _MISSING_CONTRACT_RETRY_ATTEMPTS,
        turn_runner: WorkspaceWorktreeAgentTurnRunner | None = None,
    ) -> None:
        super().__init__()
        self._missing_contract_retry_attempts = max(0, missing_contract_retry_attempts)
        self._worktree_agent = build_builtin_workspace_worktree_manager_agent(
            tenant_id=tenant_id,
            project_id=project_id,
        )
        self._turn_runner = turn_runner or RuntimeWorkspaceWorktreeAgentTurnRunner(
            tenant_id=tenant_id,
            project_id=project_id,
        )

    async def prepare_worktree(
        self,
        request: AttemptWorktreePreparationRequest,
    ) -> AttemptWorktreeContext | None:
        prompt = _build_agent_user_prompt(request)
        payload = await self._turn_runner.run_preparation_turn(
            worktree_agent=self._worktree_agent,
            user_prompt=prompt,
            workspace_id=request.workspace_id,
            task_id=request.task_id,
            attempt_id=request.attempt_id,
        )
        parsed = _parse_preparation_payload(payload or {}, request=request)
        retry_index = 0
        while parsed is None and retry_index < self._missing_contract_retry_attempts:
            retry_index += 1
            prompt = _build_agent_contract_retry_prompt(
                request,
                diagnostics=self._turn_runner.last_diagnostics,
                retry_index=retry_index,
            )
            payload = await self._turn_runner.run_preparation_turn(
                worktree_agent=self._worktree_agent,
                user_prompt=prompt,
                workspace_id=request.workspace_id,
                task_id=request.task_id,
                attempt_id=request.attempt_id,
            )
            parsed = _parse_preparation_payload(payload or {}, request=request)
        if parsed is None:
            diagnostics = self._turn_runner.last_diagnostics
            logger.warning(
                "workspace_plan.worktree_manager_missing_contract",
                extra={
                    "workspace_id": request.workspace_id,
                    "task_id": request.task_id,
                    "attempt_id": request.attempt_id,
                    "diagnostics": diagnostics,
                },
            )
            return AttemptWorktreeContext(
                workspace_root=request.workspace_root,
                sandbox_code_root=request.sandbox_code_root,
                active_root=request.worktree_path,
                worktree_path=request.worktree_path,
                branch_name=request.branch_name,
                base_ref=request.base_ref,
                attempt_id=request.attempt_id,
                is_isolated=True,
                setup_status="failed",
                setup_reason=(
                    "builtin workspace worktree manager did not submit preparation: "
                    f"{json.dumps(diagnostics, ensure_ascii=False, default=str)}"
                ),
            )
        return parsed


def _build_agent_user_prompt(request: AttemptWorktreePreparationRequest) -> str:
    return (
        "Prepare this isolated attempt worktree using the builtin workspace worktree "
        "manager contract.\n\n"
        f"{_request_payload(request)}\n\n"
        "Run setup_command exactly as supplied. If it succeeds, run diagnostics_command "
        "exactly as supplied. Your final action must be exactly one "
        f"{WORKSPACE_SUBMIT_WORKTREE_PREPARATION_TOOL_NAME} call."
    )


def _build_agent_contract_retry_prompt(
    request: AttemptWorktreePreparationRequest,
    *,
    diagnostics: Mapping[str, Any],
    retry_index: int,
) -> str:
    return (
        f"Contract retry {retry_index}: the previous worktree manager turn did not call "
        f"{WORKSPACE_SUBMIT_WORKTREE_PREPARATION_TOOL_NAME}.\n\n"
        f"Diagnostics from the failed turn:\n{json.dumps(diagnostics, ensure_ascii=False, default=str)}\n\n"
        "Use the same preparation payload below. Your next and final action must be "
        f"exactly one {WORKSPACE_SUBMIT_WORKTREE_PREPARATION_TOOL_NAME} call; do not "
        "finish in prose.\n\n"
        f"{_request_payload(request)}"
    )


def _request_payload(request: AttemptWorktreePreparationRequest) -> str:
    payload = {
        "workspace_id": request.workspace_id,
        "task_id": request.task_id,
        "attempt_id": request.attempt_id,
        "workspace_root": request.workspace_root,
        "sandbox_code_root": request.sandbox_code_root,
        "worktree_path": request.worktree_path,
        "branch_name": request.branch_name,
        "base_ref": request.base_ref,
        "original_base_ref": request.original_base_ref,
        "setup_command": request.setup_command,
        "diagnostics_command": request.diagnostics_command,
        "policy": {
            "setup_command": "Run exactly as provided with bash; do not rewrite it.",
            "diagnostics_command": "Run only after setup succeeds.",
            "terminal_tool": WORKSPACE_SUBMIT_WORKTREE_PREPARATION_TOOL_NAME,
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)


def _worktree_preparation_from_event(event: Mapping[str, Any]) -> dict[str, Any] | None:
    return contract_tool_payload_from_event(
        event,
        tool_name=WORKSPACE_SUBMIT_WORKTREE_PREPARATION_TOOL_NAME,
        payload_key="worktree_preparation",
    )


def _worktree_manager_turn_timeout_seconds() -> int:
    raw_value = os.getenv("WORKSPACE_WORKTREE_MANAGER_TIMEOUT_SECONDS")
    if raw_value is None:
        return _DEFAULT_WORKTREE_MANAGER_TURN_TIMEOUT_SECONDS
    try:
        parsed = int(raw_value)
    except ValueError:
        return _DEFAULT_WORKTREE_MANAGER_TURN_TIMEOUT_SECONDS
    if parsed <= 0:
        return _DEFAULT_WORKTREE_MANAGER_TURN_TIMEOUT_SECONDS
    return min(parsed, _MAX_WORKTREE_MANAGER_TURN_TIMEOUT_SECONDS)


def _tool_name_from_event(event: Mapping[str, Any]) -> str | None:
    data = event.get("data")
    if not isinstance(data, Mapping):
        return None
    tool_name = data.get("tool_name") or data.get("name")
    return tool_name.strip() if isinstance(tool_name, str) and tool_name.strip() else None


def _parse_preparation_payload(
    payload: Mapping[str, Any],
    *,
    request: AttemptWorktreePreparationRequest,
) -> AttemptWorktreeContext | None:
    status = str(payload.get("status") or "").strip()
    if status not in {"prepared", "fallback_used", "failed", "skipped"}:
        return None
    worktree_path = str(payload.get("worktree_path") or request.worktree_path).strip()
    branch_name = str(payload.get("branch_name") or request.branch_name).strip()
    base_ref = str(payload.get("base_ref") or request.base_ref).strip()
    if not worktree_path or not branch_name or not base_ref:
        return None
    sandbox_code_root = posixpath.normpath(request.sandbox_code_root)
    normalized_worktree = posixpath.normpath(worktree_path)
    return AttemptWorktreeContext(
        workspace_root=(
            posixpath.normpath(request.workspace_root) if request.workspace_root else None
        ),
        sandbox_code_root=sandbox_code_root,
        active_root=normalized_worktree,
        worktree_path=normalized_worktree,
        branch_name=branch_name,
        base_ref=base_ref,
        attempt_id=request.attempt_id,
        is_isolated=normalized_worktree != sandbox_code_root,
        setup_status=status,
        setup_reason=_optional_string(payload.get("reason")),
        setup_output=compact_command_output(_optional_string(payload.get("output")) or ""),
        original_base_ref=_optional_string(payload.get("original_base_ref"))
        or request.original_base_ref,
        resolved_base_ref=_optional_string(payload.get("resolved_base_ref")) or base_ref,
        fallback_reason=_optional_string(payload.get("fallback_reason")),
        git_fsck_summary=compact_command_output(
            _optional_string(payload.get("git_fsck_summary")) or "",
            limit=500,
        )
        or None,
        pruned_worktrees_count=_optional_nonnegative_int(
            payload.get("pruned_worktrees_count")
        ),
    )


def _optional_string(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _optional_nonnegative_int(value: object) -> int | None:
    if value is None or not isinstance(value, int | float | str):
        return None
    try:
        parsed = int(value)
    except ValueError:
        return None
    return max(0, parsed)


__all__ = [
    "RuntimeWorkspaceWorktreeAgentTurnRunner",
    "WorkspaceWorktreeAgentPreparer",
    "WorkspaceWorktreeAgentTurnRunner",
]
