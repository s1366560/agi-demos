"""LLM-backed structured review for completed workspace plan iterations."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Protocol

from src.domain.model.review.finding_filter import filter_findings
from src.domain.model.review.review_finding import (
    FindingVerdict,
    RawReviewFinding,
    ReviewFindingContext,
    ReviewSeverity,
    ValidatedReviewFinding,
)
from src.domain.ports.services.iteration_review_port import (
    IterationNextTask,
    IterationReviewContext,
    IterationReviewVerdict,
)
from src.infrastructure.agent.sisyphus.builtin_agent import (
    build_builtin_workspace_iteration_reviewer_agent,
)
from src.infrastructure.agent.tools.workspace_plan_contract_tools import (
    WORKSPACE_SUBMIT_ITERATION_REVIEW_TOOL_NAME,
)
from src.infrastructure.agent.workspace.contract_agent_runtime import (
    contract_tool_payload_from_event,
    workspace_contract_input_fingerprint,
)

if TYPE_CHECKING:
    from src.domain.model.agent.agent_definition import Agent

logger = logging.getLogger(__name__)

_VALID_VERDICTS = {"complete_goal", "continue_next_iteration", "needs_human_review"}
_VALID_PHASES = {"research", "plan", "implement", "test", "deploy", "review"}
_VALID_SEVERITIES = {s.value for s in ReviewSeverity}
_MIN_REVIEW_CONFIDENCE = 0.6
_MAX_FINDINGS = 12
_DEFAULT_REVIEW_MAX_STEPS = 16
_MISSING_CONTRACT_RETRY_ATTEMPTS = 1


class WorkspaceIterationReviewAgentTurnRunner(Protocol):
    """Runs one builtin workspace-iteration-reviewer turn."""

    async def run_review_turn(
        self,
        *,
        reviewer_agent: Agent,
        user_prompt: str,
        workspace_id: str,
        plan_id: str,
        iteration_index: int,
        linked_workspace_task_id: str | None = None,
    ) -> dict[str, Any] | None: ...


class RuntimeWorkspaceIterationReviewAgentTurnRunner:
    """Run the builtin iteration reviewer through the normal project ReAct runtime."""

    def __init__(
        self,
        *,
        tenant_id: str,
        project_id: str,
        max_steps: int = _DEFAULT_REVIEW_MAX_STEPS,
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

    async def run_review_turn(
        self,
        *,
        reviewer_agent: Agent,
        user_prompt: str,
        workspace_id: str,
        plan_id: str,
        iteration_index: int,
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
            plan_id,
            iteration_index,
            linked_workspace_task_id or "",
            reviewer_agent.id,
        )
        conversation_id = workspace_contract_conversation_id(
            "iteration-review",
            self._tenant_id,
            self._project_id,
            workspace_id,
            plan_id,
            iteration_index,
            linked_workspace_task_id or "",
            input_fingerprint,
        )
        diagnostics: dict[str, Any] = {
            "conversation_id": conversation_id,
            "input_fingerprint": input_fingerprint,
            "event_count": 0,
            "observed_tools": [],
            "review_submitted": False,
            "runtime_path": "agent_service.stream_chat_v2",
        }
        recovered_payload = await recover_workspace_contract_payload(
            conversation_id=conversation_id,
            extract_payload=_iteration_review_from_event,
        )
        if recovered_payload is not None:
            diagnostics["recovered_from_events"] = True
            diagnostics["review_submitted"] = True
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
            agent_id=reviewer_agent.id,
            actor_user_id=resolved_actor_user_id,
            title=f"Workspace Iteration Review - {iteration_index}",
            stage="iteration_review",
            metadata={
                "plan_id": plan_id,
                "iteration_index": iteration_index,
                "linked_workspace_task_id": linked_workspace_task_id or "",
                "conversation_scope": f"review:{plan_id}:{iteration_index}",
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
                "plan_id": plan_id,
                "iteration_index": iteration_index,
            },
            "iteration_review": {
                "plan_id": plan_id,
                "iteration_index": iteration_index,
            },
            "runtime_limits": {
                "max_steps": self._max_steps,
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
                agent_id=reviewer_agent.id,
                app_model_context=app_model_context,
            ):
                diagnostics["event_count"] += 1
                tool_name = _tool_name_from_event(event)
                if tool_name:
                    observed_tools = diagnostics["observed_tools"]
                    if tool_name not in observed_tools:
                        observed_tools.append(tool_name)
                payload = _iteration_review_from_event(event)
                if payload is not None:
                    diagnostics["review_submitted"] = True
                    self._last_diagnostics = diagnostics
                    return payload
        recovered_payload = await recover_workspace_contract_payload(
            conversation_id=conversation_id,
            extract_payload=_iteration_review_from_event,
        )
        if recovered_payload is not None:
            diagnostics["recovered_from_events"] = True
            diagnostics["review_submitted"] = True
            self._last_diagnostics = diagnostics
            return recovered_payload
        self._last_diagnostics = diagnostics
        return None


class WorkspaceIterationReviewAgentProvider:
    """Iteration review provider backed by the builtin iteration reviewer agent."""

    def __init__(
        self,
        *,
        tenant_id: str,
        project_id: str,
        linked_workspace_task_id: str | None = None,
        max_next_tasks: int = 6,
        missing_contract_retry_attempts: int = _MISSING_CONTRACT_RETRY_ATTEMPTS,
        turn_runner: WorkspaceIterationReviewAgentTurnRunner | None = None,
    ) -> None:
        super().__init__()
        self._max_next_tasks = max(1, max_next_tasks)
        self._missing_contract_retry_attempts = max(0, missing_contract_retry_attempts)
        self._linked_workspace_task_id = linked_workspace_task_id
        self._reviewer_agent = build_builtin_workspace_iteration_reviewer_agent(
            tenant_id=tenant_id,
            project_id=project_id,
        )
        self._turn_runner = turn_runner or RuntimeWorkspaceIterationReviewAgentTurnRunner(
            tenant_id=tenant_id,
            project_id=project_id,
        )

    async def review(self, context: IterationReviewContext) -> IterationReviewVerdict:
        linked_workspace_task_id = (
            context.linked_workspace_task_id or self._linked_workspace_task_id
        )
        prompt = _build_agent_user_prompt(
            context,
            max_next_tasks=self._max_next_tasks,
            linked_workspace_task_id=linked_workspace_task_id,
        )
        payload = await self._turn_runner.run_review_turn(
            reviewer_agent=self._reviewer_agent,
            user_prompt=prompt,
            workspace_id=context.workspace_id,
            plan_id=context.plan_id,
            iteration_index=context.iteration_index,
            linked_workspace_task_id=linked_workspace_task_id,
        )
        retry_index = 0
        while not payload and retry_index < self._missing_contract_retry_attempts:
            retry_index += 1
            prompt = _build_agent_contract_retry_prompt(
                context,
                max_next_tasks=self._max_next_tasks,
                linked_workspace_task_id=linked_workspace_task_id,
                diagnostics=getattr(self._turn_runner, "last_diagnostics", {}),
                retry_index=retry_index,
            )
            payload = await self._turn_runner.run_review_turn(
                reviewer_agent=self._reviewer_agent,
                user_prompt=prompt,
                workspace_id=context.workspace_id,
                plan_id=context.plan_id,
                iteration_index=context.iteration_index,
                linked_workspace_task_id=linked_workspace_task_id,
            )
        if not payload:
            diagnostics = getattr(self._turn_runner, "last_diagnostics", {})
            return _needs_human_review(
                "builtin workspace iteration reviewer did not submit iteration review: "
                f"{json.dumps(diagnostics, ensure_ascii=False, default=str)}"
            )
        parsed = _parse_review_response(
            {"content": json.dumps(payload, ensure_ascii=False)},
            context=context,
        )
        if parsed.summary != "iteration review did not return structured arguments":
            return parsed
        diagnostics = getattr(self._turn_runner, "last_diagnostics", {})
        return _needs_human_review(
            "builtin workspace iteration reviewer did not submit iteration review: "
            f"{json.dumps(diagnostics, ensure_ascii=False, default=str)}"
        )


class UnavailableIterationReviewProvider:
    """Suspends software iteration loops when the agent review surface is unavailable."""

    def __init__(self, reason: str) -> None:
        super().__init__()
        self._reason = reason

    async def review(self, context: IterationReviewContext) -> IterationReviewVerdict:
        _ = context
        return _needs_human_review(self._reason)


def _build_agent_user_prompt(
    context: IterationReviewContext,
    *,
    max_next_tasks: int,
    linked_workspace_task_id: str | None = None,
) -> str:
    return (
        "Review this completed workspace iteration using the builtin iteration review contract.\n\n"
        f"{_user_payload(context, linked_workspace_task_id=linked_workspace_task_id)}\n\n"
        f"Maximum next sprint tasks: {max_next_tasks}\n"
        "You are in read-only review mode. Do not implement, edit files, mutate workspace "
        "state, or finish in prose. Your final action must be exactly one "
        f"{WORKSPACE_SUBMIT_ITERATION_REVIEW_TOOL_NAME} call."
    )


def _build_agent_contract_retry_prompt(
    context: IterationReviewContext,
    *,
    max_next_tasks: int,
    linked_workspace_task_id: str | None = None,
    diagnostics: Mapping[str, Any] | None = None,
    retry_index: int = 1,
) -> str:
    diagnostics_json = json.dumps(diagnostics or {}, ensure_ascii=False, default=str)
    return (
        "Contract retry for the completed workspace iteration review.\n\n"
        f"Retry index: {retry_index}\n"
        "The previous review turn inspected evidence but did not call "
        f"{WORKSPACE_SUBMIT_ITERATION_REVIEW_TOOL_NAME}. Submit the contract tool in this "
        "turn. Do not end in prose.\n\n"
        f"Previous diagnostics: {diagnostics_json}\n\n"
        f"{_user_payload(context, linked_workspace_task_id=linked_workspace_task_id)}\n\n"
        f"Maximum next sprint tasks: {max_next_tasks}\n"
        "Use at most two bounded read/grep/glob/bash calls only if the payload is "
        "insufficient. If the completed tasks and deliverables satisfy the goal with no "
        "actionable follow-up, call complete_goal. If bounded follow-up remains, call "
        "continue_next_iteration with concrete next_tasks. If only a human-only decision "
        "can proceed, call needs_human_review."
    )


def _user_payload(
    context: IterationReviewContext,
    *,
    linked_workspace_task_id: str | None = None,
) -> str:
    payload = {
        "workspace_id": context.workspace_id,
        "plan_id": context.plan_id,
        "iteration_index": context.iteration_index,
        "linked_workspace_task_id": linked_workspace_task_id or "",
        "goal": {
            "title": context.goal_title,
            "description": context.goal_description,
        },
        "completed_tasks": list(context.completed_tasks),
        "deliverables": list(context.deliverables),
        "feedback_items": list(context.feedback_items),
        "max_next_tasks": context.max_next_tasks,
        "iteration_loop": context.iteration_loop,
        "runtime_constraints": _runtime_constraints_payload(context),
        "review_policy": {
            "mode": "auto",
            "complete_goal_requires": [
                "no next_sprint_goal",
                "no actionable follow-up findings",
                "no operator request to continue the loop",
            ],
            "available_next_sprint_capabilities": [
                "public web research and reference-site inspection",
                "browser_e2e workflows with screenshots and console capture",
                "API contract verification and integration tests",
                "code, test, and sandbox-native release-readiness implementation",
                "sandbox preview proxy deployment and health-check verification",
                "Drone docker CI/CD evidence through deploy-step logs and registry manifest checks",
            ],
            "continue_next_iteration_for": [
                "missing acceptance evidence",
                "public reference product parity checks",
                "UI/UX comparison work",
                "E2E user journey verification",
                "sandbox-native release-readiness checks that do not require external production authority",
            ],
            "implementation_first_rules": [
                "Every next_task must change application code, tests, configs, schemas, or infrastructure.",
                "Do NOT propose a next_task whose primary outcome is writing/updating/finalizing a markdown file, a checklist, or an acceptance/release/parity/evidence report unless the user goal explicitly asks for documentation OR the implementation is already shipped and only documentation remains.",
                "Acceptance evidence (test reports, parity reports, release reports, INDEX.md, BUILD-REPORT.md, SANDBOX-PREVIEW-EVIDENCE.md, GOAL-COMPLETION.md) is the verifier's output; never make it its own next_task.",
                "If documentation updates are required, embed them in the implementation/verification next_task that owns the changed code, not as a standalone task.",
            ],
            "runtime_rules": [
                "If runtime_constraints.sandbox_docker_runtime.available is false, do not create next_tasks requiring docker/podman/containerd CLI, Docker daemon/socket access, docker pull/run, or a deployed container stack inside the sandbox worker.",
                "For Drone docker deployment evidence under that constraint, use Drone pipeline deploy-step success, registry manifest/tag checks, and sandbox-native preview/service health or browser evidence.",
                "If a live container run is mandatory and no Docker-enabled runtime exists, choose needs_human_review instead of retrying a sandbox worker.",
            ],
            "needs_human_review_only_for": [
                "missing credentials or private access",
                "irreversible external deployment, spending, or data transmission",
                "legal, compliance, or product approval",
                "unsafe destructive action",
                "no concrete next sprint tasks can be produced",
            ],
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _runtime_constraints_payload(context: IterationReviewContext) -> dict[str, object]:
    if not _context_has_sandbox_docker_runtime_gap(context):
        return {}
    return {
        "sandbox_docker_runtime": {
            "available": False,
            "source": "completed_iteration_feedback",
            "policy": (
                "Workers in this sandbox must not be asked to run docker/podman/containerd "
                "commands or to start a deployed container stack. Treat Drone docker deploy-step "
                "success plus registry manifest/tag checks as the Docker deployment evidence, "
                "and use sandbox-native preview/service health or browser checks for worker-side "
                "verification."
            ),
        }
    }


def _context_has_sandbox_docker_runtime_gap(context: IterationReviewContext) -> bool:
    markers: list[str] = [str(item) for item in context.feedback_items if item]
    for task in context.completed_tasks:
        for key in (
            "failure_signature",
            "failed_criteria",
            "satisfied_guard_failures",
            "evidence_refs",
            "artifacts",
        ):
            value = task.get(key)
            if isinstance(value, str) and value:
                markers.append(value)
            elif isinstance(value, list | tuple):
                markers.extend(str(item) for item in value if item)
    return any(_is_sandbox_docker_runtime_gap_marker(marker) for marker in markers)


def _is_sandbox_docker_runtime_gap_marker(value: str) -> bool:
    normalized = value.strip().lower().replace("_", "-")
    if normalized in {
        "sandbox-no-docker-runtime",
        "docker-runtime-unavailable-sandbox",
        "docker-runtime-permanently-unavailable-sandbox",
        "sandbox-docker-runtime-unavailable",
    }:
        return True
    if _is_stale_sandbox_docker_runtime_gap_reference(normalized):
        return False
    has_sandbox_context = "sandbox" in normalized
    has_docker_runtime_context = any(
        token in normalized for token in ("docker runtime", "docker daemon", "docker socket")
    ) or ("docker" in normalized and "socket" in normalized)
    has_unavailable_context = any(
        token in normalized
        for token in (
            "not available",
            "unavailable",
            "permanent",
            "absent",
            "without docker",
            "lacks docker",
            "no docker",
            "no socket",
            "missing",
            "cannot access",
            "can't access",
        )
    )
    return has_sandbox_context and has_docker_runtime_context and has_unavailable_context


def _is_stale_sandbox_docker_runtime_gap_reference(normalized: str) -> bool:
    return (
        "earlier notes mentioned" in normalized
        or "did not emit" in normalized
        or "didn't emit" in normalized
        or "not emit" in normalized
    )


def _iteration_review_from_event(event: Mapping[str, Any]) -> dict[str, Any] | None:
    return contract_tool_payload_from_event(
        event,
        tool_name=WORKSPACE_SUBMIT_ITERATION_REVIEW_TOOL_NAME,
        payload_key="iteration_review",
    )


def _tool_name_from_event(event: Mapping[str, Any]) -> str | None:
    data = event.get("data")
    if not isinstance(data, Mapping):
        return None
    tool_name = data.get("tool_name") or data.get("name")
    return tool_name.strip() if isinstance(tool_name, str) and tool_name.strip() else None


def _parse_review_response(
    response: dict[str, Any], *, context: IterationReviewContext
) -> IterationReviewVerdict:
    args = _response_arguments(response)
    if args is None:
        return _needs_human_review("iteration review did not return structured arguments")

    verdict = str(args.get("verdict") or "")
    if verdict not in _VALID_VERDICTS:
        return _needs_human_review("iteration review returned an invalid verdict")

    confidence = _float_between(args.get("confidence"), default=0.0)
    summary = str(args.get("summary") or "").strip()
    if confidence < _MIN_REVIEW_CONFIDENCE:
        return _needs_human_review(summary or "iteration review confidence was too low")

    tasks = _parse_next_tasks(args.get("next_tasks"), max_next_tasks=context.max_next_tasks)
    if verdict == "continue_next_iteration" and not tasks:
        return _needs_human_review("iteration review requested continuation without next tasks")

    raw_findings = _parse_raw_findings(args.get("findings"), limit=_MAX_FINDINGS)
    kept_findings, rejected_count = _gate_findings(
        raw_findings,
        linter_covered_categories=context.linter_covered_categories,
    )
    if raw_findings:
        logger.info(
            "iteration review findings: raw=%d kept=%d rejected=%d",
            len(raw_findings),
            len(kept_findings),
            rejected_count,
        )

    return IterationReviewVerdict(
        verdict=verdict,  # type: ignore[arg-type]
        confidence=confidence,
        summary=summary or verdict,
        next_sprint_goal=str(args.get("next_sprint_goal") or "").strip(),
        feedback_items=_string_tuple(args.get("feedback_items"), limit=8),
        next_tasks=tasks,
        findings=kept_findings,
        rejected_finding_count=rejected_count,
    )


def _parse_raw_findings(value: object, *, limit: int) -> tuple[RawReviewFinding, ...]:
    if not isinstance(value, list):
        return ()
    findings: list[RawReviewFinding] = []
    for item in value[:limit]:
        if not isinstance(item, dict):
            continue
        severity_raw = str(item.get("severity") or "").strip().upper()
        if severity_raw not in _VALID_SEVERITIES:
            logger.debug("iteration review skipped finding with bad severity: %r", severity_raw)
            continue
        file_path = str(item.get("file") or "").strip()
        category = str(item.get("category") or "").strip()
        description = str(item.get("description") or "").strip()
        suggestion = str(item.get("suggestion") or "").strip()
        if not file_path or not category or not description:
            logger.debug("iteration review skipped finding with missing required fields")
            continue
        try:
            line = int(item.get("line") or 0)
        except (TypeError, ValueError):
            logger.debug("iteration review skipped finding with non-integer line")
            continue
        try:
            raw_confidence = int(item.get("raw_confidence") or 0)
        except (TypeError, ValueError):
            logger.debug("iteration review skipped finding with non-integer raw_confidence")
            continue
        findings.append(
            RawReviewFinding(
                file=file_path,
                line=max(0, line),
                category=category,
                severity=ReviewSeverity(severity_raw),
                raw_confidence=max(0, min(raw_confidence, 100)),
                description=description,
                suggestion=suggestion,
                concrete_evidence=bool(item.get("concrete_evidence")),
            )
        )
    return tuple(findings)


def _gate_findings(
    raw: tuple[RawReviewFinding, ...],
    *,
    linter_covered_categories: tuple[str, ...],
) -> tuple[tuple[ValidatedReviewFinding, ...], int]:
    if not raw:
        return ((), 0)
    review_context = ReviewFindingContext(linter_covered_categories=linter_covered_categories)
    validated = filter_findings(list(raw), review_context)
    kept = tuple(v for v in validated if v.verdict is FindingVerdict.KEEP)
    rejected = len(validated) - len(kept)
    return (kept, rejected)


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


def _parse_next_tasks(value: object, *, max_next_tasks: int) -> tuple[IterationNextTask, ...]:
    if not isinstance(value, list):
        return ()
    tasks: list[IterationNextTask] = []
    for index, item in enumerate(value[:max_next_tasks], start=1):
        if not isinstance(item, dict):
            continue
        description = str(item.get("description") or "").strip()
        if not description:
            continue
        phase = str(item.get("phase") or "").strip()
        tasks.append(
            IterationNextTask(
                id=str(item.get("id") or f"t{index}").strip() or f"t{index}",
                description=description,
                target_subagent=_optional_str(item.get("target_subagent")),
                dependencies=_string_tuple(item.get("dependencies"), limit=8),
                priority=max(0, int(item.get("priority") or 0)),
                phase=phase if phase in _VALID_PHASES else None,
                expected_artifacts=_string_tuple(item.get("expected_artifacts"), limit=6),
            )
        )
    return tuple(tasks)


def _string_tuple(value: object, *, limit: int) -> tuple[str, ...]:
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, list | tuple):
        items = [str(item) for item in value]
    else:
        return ()
    cleaned = [item.strip() for item in items if item.strip()]
    return tuple(dict.fromkeys(cleaned))[:limit]


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _float_between(value: object, *, default: float) -> float:
    if not isinstance(value, int | float | str):
        return default
    try:
        parsed = float(value)
    except ValueError:
        return default
    return max(0.0, min(parsed, 1.0))


def _needs_human_review(summary: str) -> IterationReviewVerdict:
    return IterationReviewVerdict(
        verdict="needs_human_review",
        confidence=0.0,
        summary=summary,
    )


__all__ = [
    "RuntimeWorkspaceIterationReviewAgentTurnRunner",
    "UnavailableIterationReviewProvider",
    "WorkspaceIterationReviewAgentProvider",
    "WorkspaceIterationReviewAgentTurnRunner",
]
