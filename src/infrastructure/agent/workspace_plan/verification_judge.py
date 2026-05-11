"""LLM-backed Agent-First verification judge for workspace plan nodes."""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Protocol

from src.infrastructure.agent.sisyphus.builtin_agent import (
    build_builtin_workspace_verifier_agent,
)
from src.infrastructure.agent.tools.workspace_plan_contract_tools import (
    WORKSPACE_SUBMIT_VERIFICATION_JUDGMENT_TOOL_NAME,
)

if TYPE_CHECKING:
    from src.domain.model.agent.agent_definition import Agent
from src.domain.ports.services.workspace_verification_judge_port import (
    WorkspaceVerificationJudgeRequest,
    WorkspaceVerificationJudgeResult,
    WorkspaceVerificationJudgeVerdict,
    WorkspaceVerificationNextActionKind,
)

logger = logging.getLogger(__name__)

_VALID_VERDICTS = {item.value for item in WorkspaceVerificationJudgeVerdict}
_VALID_NEXT_ACTION_KINDS = {item.value for item in WorkspaceVerificationNextActionKind}


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
    ) -> dict[str, Any] | None:
        from src.infrastructure.agent.core.project_react_agent import (
            ProjectAgentConfig,
            ProjectReActAgent,
        )
        from src.infrastructure.agent.workspace.runtime_role_contract import (
            WORKSPACE_ROLE_WORKER,
            WORKSPACE_SESSION_ROLE_KEY,
        )

        turn_id = uuid.uuid4().hex
        conversation_id = (
            f"workspace-verifier:{workspace_id}:{node_id}:{attempt_id or 'none'}:{turn_id}"
        )
        diagnostics: dict[str, Any] = {
            "conversation_id": conversation_id,
            "event_count": 0,
            "observed_tools": [],
            "judgment_submitted": False,
        }
        agent = ProjectReActAgent(
            ProjectAgentConfig(
                tenant_id=self._tenant_id,
                project_id=self._project_id,
                agent_mode="workspace-verifier",
                temperature=0.0,
                max_tokens=self._max_tokens,
                max_steps=self._max_steps,
                persistent=False,
                enable_subagents=False,
            )
        )
        if not await agent.initialize():
            self._last_diagnostics = diagnostics
            return None

        conversation_context = [
            {
                "role": "system",
                "content": "workspace_worker_runtime\n"
                + json.dumps(
                    {
                        "context_type": "workspace_worker_runtime",
                        WORKSPACE_SESSION_ROLE_KEY: WORKSPACE_ROLE_WORKER,
                        "workspace_binding": {
                            "workspace_id": workspace_id,
                            "current_plan_node_id": node_id,
                            "current_attempt_id": attempt_id or "",
                        },
                    },
                    ensure_ascii=False,
                ),
            }
        ]
        try:
            async for event in agent.execute_chat(
                conversation_id=conversation_id,
                user_message=user_prompt,
                user_id="workspace-verifier",
                tenant_id=self._tenant_id,
                message_id=f"workspace-verifier-{turn_id}",
                conversation_context=conversation_context,
                agent_id=verifier_agent.id,
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
        finally:
            await agent.stop()
        self._last_diagnostics = diagnostics
        return None


class WorkspaceVerifierAgentJudge:
    """Workspace verification judge backed by the builtin verifier agent."""

    def __init__(
        self,
        *,
        tenant_id: str,
        project_id: str,
        turn_runner: WorkspaceVerifierAgentTurnRunner | None = None,
    ) -> None:
        super().__init__()
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
        payload = await self._turn_runner.run_verification_turn(
            verifier_agent=self._verifier_agent,
            user_prompt=_build_agent_user_prompt(request),
            workspace_id=request.workspace_id,
            node_id=request.node_id,
            attempt_id=request.attempt_id,
        )
        parsed = _parse_judge_response({"content": json.dumps(payload or {}, ensure_ascii=False)})
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


def _request_payload(request: WorkspaceVerificationJudgeRequest) -> str:
    payload = {
        "workspace_id": request.workspace_id,
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
    if event.get("type") != "observe":
        return None
    data = event.get("data")
    if not isinstance(data, Mapping):
        return None
    if data.get("tool_name") != WORKSPACE_SUBMIT_VERIFICATION_JUDGMENT_TOOL_NAME:
        return None
    observation = data.get("observation") or data.get("result")
    if not isinstance(observation, Mapping):
        return None
    payload = observation.get("verification_judgment")
    return dict(payload) if isinstance(payload, Mapping) else None


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
