"""LLM-backed Agent-First verification judge for workspace plan nodes."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import replace
from typing import TYPE_CHECKING, Any, Protocol

from src.infrastructure.agent.sisyphus.builtin_agent import (
    build_builtin_workspace_verifier_agent,
)
from src.infrastructure.agent.tools.workspace_plan_contract_tools import (
    WORKSPACE_SUBMIT_VERIFICATION_JUDGMENT_TOOL_NAME,
)
from src.infrastructure.agent.workspace.contract_agent_runtime import (
    contract_tool_payload_from_event,
    workspace_contract_input_fingerprint,
)

if TYPE_CHECKING:
    from src.domain.model.agent.agent_definition import Agent
from src.domain.ports.services.workspace_verification_judge_port import (
    WorkspaceVerificationFeedbackItem,
    WorkspaceVerificationFeedbackKind,
    WorkspaceVerificationFeedbackSeverity,
    WorkspaceVerificationFeedbackTargetLayer,
    WorkspaceVerificationJudgeRequest,
    WorkspaceVerificationJudgeResult,
    WorkspaceVerificationJudgeVerdict,
    WorkspaceVerificationNextActionKind,
    WorkspaceVerificationRecommendedAction,
)

logger = logging.getLogger(__name__)

_VALID_VERDICTS = {item.value for item in WorkspaceVerificationJudgeVerdict}
_VALID_NEXT_ACTION_KINDS = {item.value for item in WorkspaceVerificationNextActionKind}
_VALID_FEEDBACK_TARGET_LAYERS = {item.value for item in WorkspaceVerificationFeedbackTargetLayer}
_VALID_FEEDBACK_KINDS = {item.value for item in WorkspaceVerificationFeedbackKind}
_VALID_FEEDBACK_SEVERITIES = {item.value for item in WorkspaceVerificationFeedbackSeverity}
_VALID_RECOMMENDED_ACTIONS = {item.value for item in WorkspaceVerificationRecommendedAction}
_MISSING_CONTRACT_RETRY_ATTEMPTS = 1


class WorkspaceVerifierAgentTurnRunner(Protocol):
    """Runs one builtin workspace-verifier turn and returns the captured judgment."""

    async def run_verification_turn(
        self,
        *,
        verifier_agent: Agent,
        user_prompt: str,
        workspace_id: str,
        node_id: str,
        attempt_id: str | None,
        linked_workspace_task_id: str | None = None,
    ) -> dict[str, Any] | None: ...


class RuntimeWorkspaceVerifierAgentTurnRunner:
    """Run the builtin verifier through the normal project ReAct runtime."""

    def __init__(
        self,
        *,
        tenant_id: str,
        project_id: str,
        max_steps: int = 8,
        max_tokens: int = 8192,
    ) -> None:
        super().__init__()
        self._tenant_id = tenant_id
        self._project_id = project_id
        self._max_steps = max_steps
        self._max_tokens = max_tokens
        self._last_diagnostics: dict[str, Any] = {}

    @property
    def last_diagnostics(self) -> dict[str, Any]:
        return dict(self._last_diagnostics)

    async def run_verification_turn(
        self,
        *,
        verifier_agent: Agent,
        user_prompt: str,
        workspace_id: str,
        node_id: str,
        attempt_id: str | None,
        linked_workspace_task_id: str | None = None,
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
            node_id,
            attempt_id or "",
            linked_workspace_task_id or "",
            verifier_agent.id,
        )
        conversation_id = workspace_contract_conversation_id(
            "verifier",
            self._tenant_id,
            self._project_id,
            workspace_id,
            node_id,
            attempt_id or "none",
            linked_workspace_task_id or "",
            input_fingerprint,
        )
        diagnostics: dict[str, Any] = {
            "conversation_id": conversation_id,
            "input_fingerprint": input_fingerprint,
            "event_count": 0,
            "observed_tools": [],
            "judgment_submitted": False,
            "runtime_path": "agent_service.stream_chat_v2",
        }
        recovered_payload = await recover_workspace_contract_payload(
            conversation_id=conversation_id,
            extract_payload=_verification_judgment_from_event,
        )
        if recovered_payload is not None:
            diagnostics["recovered_from_events"] = True
            diagnostics["judgment_submitted"] = True
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
            linked_workspace_task_id=linked_workspace_task_id,
            agent_id=verifier_agent.id,
            actor_user_id=resolved_actor_user_id,
            title=f"Workspace Verification Gate - {node_id}",
            stage="verification_judge",
            metadata={
                "current_plan_node_id": node_id,
                "current_attempt_id": attempt_id or "",
                "linked_workspace_task_id": linked_workspace_task_id or "",
                "conversation_scope": f"verification:{node_id}:{attempt_id or 'none'}",
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
                "linked_workspace_task_id": linked_workspace_task_id or "",
                "current_plan_node_id": node_id,
                "current_attempt_id": attempt_id or "",
            },
            "verification_judge": {
                "node_id": node_id,
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
            async for event in agent_service.stream_chat_v2(
                conversation_id=conversation_id,
                user_message=user_prompt,
                user_id=resolved_actor_user_id,
                project_id=self._project_id,
                tenant_id=self._tenant_id,
                agent_id=verifier_agent.id,
                app_model_context=app_model_context,
            ):
                diagnostics["event_count"] += 1
                tool_name = _tool_name_from_event(event)
                if tool_name:
                    observed_tools = diagnostics["observed_tools"]
                    if tool_name not in observed_tools:
                        observed_tools.append(tool_name)
                payload = _verification_judgment_from_event(event)
                if payload is not None:
                    diagnostics["judgment_submitted"] = True
                    self._last_diagnostics = diagnostics
                    return payload
        recovered_payload = await recover_workspace_contract_payload(
            conversation_id=conversation_id,
            extract_payload=_verification_judgment_from_event,
        )
        if recovered_payload is not None:
            diagnostics["recovered_from_events"] = True
            diagnostics["judgment_submitted"] = True
            self._last_diagnostics = diagnostics
            return recovered_payload
        self._last_diagnostics = diagnostics
        return None


class WorkspaceVerifierAgentJudge:
    """Workspace verification judge backed by the builtin verifier agent."""

    def __init__(
        self,
        *,
        tenant_id: str,
        project_id: str,
        linked_workspace_task_id: str | None = None,
        missing_contract_retry_attempts: int = _MISSING_CONTRACT_RETRY_ATTEMPTS,
        turn_runner: WorkspaceVerifierAgentTurnRunner | None = None,
    ) -> None:
        super().__init__()
        self._linked_workspace_task_id = linked_workspace_task_id
        self._missing_contract_retry_attempts = max(0, missing_contract_retry_attempts)
        self._verifier_agent = build_builtin_workspace_verifier_agent(
            tenant_id=tenant_id,
            project_id=project_id,
        )
        self._turn_runner = turn_runner or RuntimeWorkspaceVerifierAgentTurnRunner(
            tenant_id=tenant_id,
            project_id=project_id,
        )

    async def judge(
        self,
        request: WorkspaceVerificationJudgeRequest,
    ) -> WorkspaceVerificationJudgeResult:
        linked_workspace_task_id = (
            request.linked_workspace_task_id or self._linked_workspace_task_id
        )
        resolved_request = (
            replace(request, linked_workspace_task_id=linked_workspace_task_id)
            if linked_workspace_task_id != request.linked_workspace_task_id
            else request
        )
        prompt = _build_agent_user_prompt(resolved_request)
        payload = await self._turn_runner.run_verification_turn(
            verifier_agent=self._verifier_agent,
            user_prompt=prompt,
            workspace_id=request.workspace_id,
            node_id=request.node_id,
            attempt_id=request.attempt_id,
            linked_workspace_task_id=linked_workspace_task_id,
        )
        parsed = _parse_judge_response({"content": json.dumps(payload or {}, ensure_ascii=False)})
        retry_index = 0
        while parsed is None and retry_index < self._missing_contract_retry_attempts:
            retry_index += 1
            prompt = _build_agent_contract_retry_prompt(
                resolved_request,
                diagnostics=getattr(self._turn_runner, "last_diagnostics", {}),
                retry_index=retry_index,
            )
            payload = await self._turn_runner.run_verification_turn(
                verifier_agent=self._verifier_agent,
                user_prompt=prompt,
                workspace_id=request.workspace_id,
                node_id=request.node_id,
                attempt_id=request.attempt_id,
                linked_workspace_task_id=linked_workspace_task_id,
            )
            parsed = _parse_judge_response(
                {"content": json.dumps(payload or {}, ensure_ascii=False)}
            )
        if parsed is None:
            diagnostics = getattr(self._turn_runner, "last_diagnostics", {})
            raise ValueError(
                "builtin workspace verifier did not submit verification judgment: "
                f"{json.dumps(diagnostics, ensure_ascii=False, default=str)}"
            )
        return parsed


class UnavailableWorkspaceVerificationJudge:
    """Force retry/recovery when the Agent-First judge surface is unavailable."""

    def __init__(self, reason: str) -> None:
        self._reason = reason

    async def judge(
        self,
        request: WorkspaceVerificationJudgeRequest,
    ) -> WorkspaceVerificationJudgeResult:
        _ = request
        return WorkspaceVerificationJudgeResult(
            verdict=WorkspaceVerificationJudgeVerdict.RETRY_INFRASTRUCTURE,
            rationale=self._reason,
            failed_criteria=("workspace_verification_judge",),
            required_next_action="retry verification when judge agent is available",
            next_action_kind=WorkspaceVerificationNextActionKind.RETRY_SAME_NODE,
            feedback_items=(
                WorkspaceVerificationFeedbackItem(
                    target_layer=WorkspaceVerificationFeedbackTargetLayer.RUNTIME,
                    feedback_kind=WorkspaceVerificationFeedbackKind.RUNTIME_INFRA_FAILURE,
                    severity=WorkspaceVerificationFeedbackSeverity.WARNING,
                    recommended_action=WorkspaceVerificationRecommendedAction.RETRY_INFRA,
                    summary=self._reason,
                    failure_signature="workspace_verification_judge_unavailable",
                ),
            ),
            confidence=0.5,
        )


def _build_agent_user_prompt(request: WorkspaceVerificationJudgeRequest) -> str:
    return (
        "Verify this workspace plan node using the builtin workspace verifier contract.\n\n"
        f"{_request_payload(request)}\n\n"
        "You are in read-only verification mode. Do not implement, edit files, mutate "
        "workspace state, or finish in prose. Your final action must be exactly one "
        f"{WORKSPACE_SUBMIT_VERIFICATION_JUDGMENT_TOOL_NAME} call."
    )


def _build_agent_contract_retry_prompt(
    request: WorkspaceVerificationJudgeRequest,
    *,
    diagnostics: Mapping[str, Any],
    retry_index: int,
) -> str:
    return (
        f"Contract retry {retry_index}: the previous verifier turn did not call "
        f"{WORKSPACE_SUBMIT_VERIFICATION_JUDGMENT_TOOL_NAME}.\n\n"
        f"Diagnostics from the failed turn:\n{json.dumps(diagnostics, ensure_ascii=False, default=str)}\n\n"
        "Use the same verification payload below. You may make at most one or two "
        "read-only checks only if essential. Your next and final action must be exactly "
        f"one {WORKSPACE_SUBMIT_VERIFICATION_JUDGMENT_TOOL_NAME} call; do not finish in prose.\n\n"
        f"{_request_payload(request)}"
    )


def _request_payload(request: WorkspaceVerificationJudgeRequest) -> str:
    payload = {
        "workspace_id": request.workspace_id,
        "linked_workspace_task_id": request.linked_workspace_task_id,
        "node": {
            "id": request.node_id,
            "title": request.node_title,
            "description": request.node_description,
            "acceptance_criteria": list(request.acceptance_criteria),
        },
        "attempt": {
            "id": request.attempt_id,
            "worker_summary": request.worker_summary,
            "candidate_artifacts": list(request.candidate_artifacts),
            "candidate_verifications": list(request.candidate_verifications),
        },
        "evidence": {
            "task_evidence_refs": list(request.task_evidence_refs),
            "latest_verification_results": list(request.latest_verification_results),
            "guard_failures": list(request.guard_failures),
            "recent_git_status": request.recent_git_status,
        },
        "sandbox": {
            "code_root": request.sandbox_code_root,
            "worktree_path": request.worktree_path,
            "active_execution_root": request.active_execution_root,
            "worktree_isolation_active": request.worktree_isolation_active,
            "code_root_role": (
                "baseline_only_when_worktree_is_active"
                if request.worktree_isolation_active
                else "active_root"
            ),
            "verification_scope": (
                "current_attempt_worktree"
                if request.worktree_isolation_active
                else "sandbox_code_root"
            ),
        },
        "task_metadata": request.task_metadata,
        "policy": {
            "verdicts": sorted(_VALID_VERDICTS),
            "next_action_kinds": {
                "none": "Use with accepted verdicts when no further work is required.",
                "retry_same_node": (
                    "Use only when the same node can fix the issue and retry within its "
                    "allowed contract."
                ),
                "create_repair_node": (
                    "Use when a needs_rework verdict requires a separate implementation "
                    "or test-infra node before this node can be retried."
                ),
                "human_required": "Use only with human-only blockers.",
            },
            "feedback_routing": {
                "target_layers": sorted(_VALID_FEEDBACK_TARGET_LAYERS),
                "feedback_kinds": sorted(_VALID_FEEDBACK_KINDS),
                "severities": sorted(_VALID_FEEDBACK_SEVERITIES),
                "recommended_actions": sorted(_VALID_RECOMMENDED_ACTIONS),
                "rules": [
                    (
                        "Emit feedback_items for every actionable non-acceptance or "
                        "special acceptance disposition."
                    ),
                    (
                        "Use target_layer=worker only when the same worker can fix the "
                        "issue inside this node contract."
                    ),
                    (
                        "Use target_layer=planner for stale, nonexistent, superseded, or "
                        "scope-invalid task targets; recommend obsolete_node or "
                        "revise_plan_node instead of retrying the worker."
                    ),
                    (
                        "Use target_layer=verifier_policy for contradictions in "
                        "verification policy or protected test-script guard behavior."
                    ),
                    (
                        "Use target_layer=runtime for sandbox, LLM, tool, or "
                        "infrastructure failures that should not count as product code "
                        "quality."
                    ),
                    "Include stable failure_signature values so repeated loops can be deduplicated.",
                ],
            },
            "blocked_human_required_only_for": [
                "credentials or private access",
                "permissions or external authority",
                "irreversible deployment, spending, or destructive action",
                "legal, compliance, or product approval",
            ],
            "needs_rework_for": [
                "missing evidence",
                "failed tests or failed quality checks",
                "test_run evidence that reports a non-zero failed or failing test count",
                "partial test totals such as 202/203 or 85/86 unless fresh current-attempt evidence includes an explicit contract_disposition, failed_test_disposition, or known_failure_disposition ref",
                "dirty or ambiguous git worktree evidence",
                "incomplete worker output",
                "explicit repository guidance or AGENTS.md noncompliance",
                "cross-task commit contamination or unrelated files in the reported diff",
                "verification, E2E, audit, or benchmark scripts changed to make a test/review node pass without an explicit allow_verification_script_changes contract",
                "tests or audits that cannot fail because every branch records success",
                "unconditional success counters or catch blocks that convert failures into passes",
                "synthetic benchmarks or shallow scans reported as real browser, rendering, accessibility, security, or end-to-end proof",
            ],
            "terminal_worker_reports": [
                "A current-attempt terminal report with type blocked, failed, or needs_replan is semantic evidence, not an automatic verdict.",
                "Use accepted with next_action_kind=none only when fresh current-attempt evidence proves the named target is stale, nonexistent, or no longer applicable, the current contract is satisfied, and relevant equivalent checks pass.",
                "When accepting despite a terminal_worker_report_completed guard, list terminal_worker_report_completed in satisfied_guard_failures and cite concrete evidence in the rationale.",
                "Use needs_rework when the terminal report shows incomplete work, missing evidence, unresolved failures, or a fix that remains possible inside the same node contract.",
            ],
            "repository_guidance": [
                "If task_metadata.code_context.agents_excerpt is present, use it as acceptance context.",
                "Require a project_guidance:checked evidence ref when project guidance exists and the node edits software artifacts.",
                "Reject visible violations of explicit guidance in code, docs, tests, generated artifacts, reports, or commit evidence.",
            ],
            "commit_isolation": [
                "In shared worktrees, a node must only commit files owned by its task.",
                "Reject commits whose diff includes another node's artifact or unrelated dirty files.",
                "Prefer explicit changed-file evidence over broad git add/git commit summaries.",
                "If recent_git_status or a guard failure reports dirty files, do not accept a worker's textual clean-worktree claim without stronger contrary evidence.",
                "Do not treat prior failure text, repair descriptions, or task metadata as current dirty-worktree evidence unless recent_git_status or latest_verification_results also reports current dirty files.",
            ],
            "attempt_worktree_isolation": [
                "The sandbox.worktree_path is the active execution root for worker attempts.",
                "When sandbox.worktree_isolation_active is true, sandbox.active_execution_root is the only current acceptance root.",
                "Do not fail because sandbox.code_root, sandbox_code_root, or the main checkout lacks the current attempt's worktree commits, files, reports, grep results, screenshots, or generated artifacts.",
                "A tool denial caused by writing verification artifacts outside sandbox.worktree_path is an intentional policy failure, not a transient retry_infrastructure condition.",
                "Do not recommend running from the main checkout, symlinking into the main checkout, copying artifacts outside the attempt worktree, or bypassing the worktree root.",
                "Judge candidate state from sandbox.worktree_path and reported commit_refs; do not require commit_refs to already be merged into sandbox.code_root, the main checkout, or another master branch before acceptance.",
                "Treat node descriptions, prior verifier text, repair descriptions, task metadata, or prior criteria that mention code root, sandbox_code_root, master, or main checkout as historical context while sandbox.worktree_isolation_active is true unless latest_verification_results or recent_git_status came from sandbox.active_execution_root.",
                "Do not create repair nodes whose purpose is to copy or re-apply current attempt worktree commits into sandbox.code_root, sandbox_code_root, the main checkout, or another master branch.",
                "If prior criteria mention master or main checkout while sandbox.worktree_path is present, reinterpret that as the active attempt worktree branch unless a separate integration node explicitly owns merging.",
                "If protected test or review scripts hardcode main-checkout artifact paths, use needs_rework and require bounded follow-up work to make those scripts worktree-relative or environment-configurable.",
            ],
            "quality_evidence": [
                "Tests must contain assertions or checks that can fail for the claimed behavior.",
                "If a test/review node changed test, E2E, audit, or benchmark code, compare the diff against the node contract and reject weaker or substituted assertions.",
                "Treat verification-script mutation guard failures as evidence to adjudicate, not as automatic failure: reject weakened, substituted, or unconditional scripts; accept bounded path, environment, or worktree-compatibility repairs only when assertions are preserved or strengthened.",
                "Accessibility and security audits must verify the claimed property, not only count generic page structure.",
                "Performance evidence must distinguish HTTP response timing, browser page-load timing, and synthetic simulations.",
            ],
            "repair_brief_contract": [
                "When next_action_kind=retry_same_node, include a compact repair_brief object.",
                "The brief must describe only current-attempt failures and fresh evidence requirements.",
                "Do not include cumulative historical failure prose as current evidence.",
                "Prefer keys: failed_items, evidence, allowed_write_scope, forbidden_actions, minimum_verifications, fresh_evidence_requirements.",
            ],
            "satisfied_guard_failures": [
                "When accepting despite guard_failures, list only guard ids that fresh current-attempt evidence satisfies.",
                "For failed_test_evidence, require concrete current-attempt contract, known-failure, or failed-test disposition evidence for every failing or partial test.",
                "Do not list a guard because a worker summary says it is acceptable; cite evidence in the rationale.",
            ],
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)


def _verification_judgment_from_event(event: Mapping[str, Any]) -> dict[str, Any] | None:
    return contract_tool_payload_from_event(
        event,
        tool_name=WORKSPACE_SUBMIT_VERIFICATION_JUDGMENT_TOOL_NAME,
        payload_key="verification_judgment",
    )


def _tool_name_from_event(event: Mapping[str, Any]) -> str | None:
    data = event.get("data")
    if not isinstance(data, Mapping):
        return None
    tool_name = data.get("tool_name") or data.get("name")
    return tool_name.strip() if isinstance(tool_name, str) and tool_name.strip() else None


def _parse_judge_response(response: dict[str, Any]) -> WorkspaceVerificationJudgeResult | None:
    args = _response_arguments(response)
    if not args:
        return None
    raw_verdict = str(args.get("verdict") or "").strip()
    if raw_verdict not in _VALID_VERDICTS:
        return None
    rationale = str(args.get("rationale") or "").strip()
    next_action = str(args.get("required_next_action") or "").strip()
    next_action_kind = _next_action_kind(args.get("next_action_kind"), raw_verdict)
    failed = _string_tuple(args.get("failed_criteria"), limit=12)
    satisfied = _string_tuple(args.get("satisfied_guard_failures"), limit=12)
    return WorkspaceVerificationJudgeResult(
        verdict=WorkspaceVerificationJudgeVerdict(raw_verdict),
        rationale=rationale or raw_verdict,
        failed_criteria=failed,
        satisfied_guard_failures=satisfied,
        required_next_action=next_action,
        next_action_kind=next_action_kind,
        repair_brief=_repair_brief(args.get("repair_brief")),
        feedback_items=_feedback_items(args.get("feedback_items")),
        confidence=_float_between(args.get("confidence"), default=0.0),
    )


def _next_action_kind(
    value: object,
    verdict: str,
) -> WorkspaceVerificationNextActionKind:
    raw = str(value or "").strip()
    if raw in _VALID_NEXT_ACTION_KINDS:
        return WorkspaceVerificationNextActionKind(raw)
    if verdict == WorkspaceVerificationJudgeVerdict.ACCEPTED.value:
        return WorkspaceVerificationNextActionKind.NONE
    if verdict == WorkspaceVerificationJudgeVerdict.BLOCKED_HUMAN_REQUIRED.value:
        return WorkspaceVerificationNextActionKind.HUMAN_REQUIRED
    return WorkspaceVerificationNextActionKind.RETRY_SAME_NODE


def _response_arguments(response: dict[str, Any]) -> dict[str, Any] | None:  # noqa: PLR0911
    tool_calls = response.get("tool_calls", [])
    if tool_calls:
        tool_call = tool_calls[0]
        function_data = _read_field(tool_call, "function", tool_call)
        args_raw = _read_field(function_data, "arguments", "{}")
        if isinstance(args_raw, str):
            try:
                parsed = json.loads(args_raw)
            except json.JSONDecodeError:
                return None
            return parsed if isinstance(parsed, dict) else None
        return args_raw if isinstance(args_raw, dict) else None
    content = response.get("content")
    if not isinstance(content, str) or not content.strip():
        return None
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3:
            text = "\n".join(lines[1:-1]).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            parsed = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
    return parsed if isinstance(parsed, dict) else None


def _read_field(source: object, key: str, default: object) -> object:
    if isinstance(source, dict):
        return source.get(key, default)
    return getattr(source, key, default)


def _string_tuple(value: object, *, limit: int) -> tuple[str, ...]:
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, list | tuple):
        items = [str(item) for item in value]
    else:
        return ()
    cleaned = [item.strip() for item in items if item.strip()]
    return tuple(dict.fromkeys(cleaned))[:limit]


def _repair_brief(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _feedback_items(
    value: object,
    *,
    limit: int = 8,
) -> tuple[WorkspaceVerificationFeedbackItem, ...]:
    if not isinstance(value, list | tuple):
        return ()
    items: list[WorkspaceVerificationFeedbackItem] = []
    for raw in value[:limit]:
        if not isinstance(raw, Mapping):
            continue
        target_layer = str(raw.get("target_layer") or "").strip()
        feedback_kind = str(raw.get("feedback_kind") or "").strip()
        severity = str(raw.get("severity") or "").strip()
        recommended_action = str(raw.get("recommended_action") or "").strip()
        if target_layer not in _VALID_FEEDBACK_TARGET_LAYERS:
            continue
        if feedback_kind not in _VALID_FEEDBACK_KINDS:
            continue
        if severity not in _VALID_FEEDBACK_SEVERITIES:
            continue
        if recommended_action not in _VALID_RECOMMENDED_ACTIONS:
            continue
        items.append(
            WorkspaceVerificationFeedbackItem(
                target_layer=WorkspaceVerificationFeedbackTargetLayer(target_layer),
                feedback_kind=WorkspaceVerificationFeedbackKind(feedback_kind),
                severity=WorkspaceVerificationFeedbackSeverity(severity),
                recommended_action=WorkspaceVerificationRecommendedAction(recommended_action),
                summary=str(raw.get("summary") or "").strip()[:1200],
                evidence_refs=_string_tuple(raw.get("evidence_refs"), limit=12),
                failure_signature=str(raw.get("failure_signature") or "").strip()[:300],
            )
        )
    return tuple(items)


def _float_between(value: object, *, default: float) -> float:
    if not isinstance(value, int | float | str):
        return default
    try:
        parsed = float(value)
    except ValueError:
        return default
    return max(0.0, min(parsed, 1.0))


__all__ = [
    "RuntimeWorkspaceVerifierAgentTurnRunner",
    "UnavailableWorkspaceVerificationJudge",
    "WorkspaceVerifierAgentJudge",
    "WorkspaceVerifierAgentTurnRunner",
]
