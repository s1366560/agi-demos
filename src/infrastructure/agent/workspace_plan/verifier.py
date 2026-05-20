"""M5 — :class:`VerifierPort` with deterministic runners plus Agent-First judgment.

Runners available out of the box:

* :class:`CmdCriterionRunner`        — shells out via a sandbox adapter
* :class:`FileExistsCriterionRunner` — checks ``os.path.exists`` (or sandbox)
* :class:`RegexCriterionRunner`      — regex against artifact/stdout
* :class:`SchemaCriterionRunner`     — JSON Schema validation

Deterministic runners collect evidence. When a verification judge is wired, the
final semantic verdict is delegated to that structured Agent-First boundary.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import posixpath
import re
import shlex
from collections.abc import Mapping
from dataclasses import replace
from typing import Any, Protocol

from src.domain.model.workspace_plan import (
    AcceptanceCriterion,
    CriterionKind,
    CriterionResult,
    EvidenceRef,
    VerificationReport,
)
from src.domain.ports.services.verifier_port import (
    CriterionRunner,
    VerificationContext,
    VerifierPort,
)
from src.domain.ports.services.workspace_verification_judge_port import (
    WorkspaceVerificationFeedbackItem,
    WorkspaceVerificationFeedbackKind,
    WorkspaceVerificationFeedbackSeverity,
    WorkspaceVerificationFeedbackTargetLayer,
    WorkspaceVerificationJudgePort,
    WorkspaceVerificationJudgeRequest,
    WorkspaceVerificationJudgeResult,
    WorkspaceVerificationJudgeVerdict,
    WorkspaceVerificationNextActionKind,
    WorkspaceVerificationRecommendedAction,
)

logger = logging.getLogger(__name__)

_CHANGE_EVIDENCE_PHASES = {"implement", "test", "deploy"}
_NO_OUTPUT_SENTINELS = {
    "(no output)",
    "tool executed successfully (no output)",
    "tool executed successfully. (no output)",
}

_FAILED_TEST_EVIDENCE_PATTERNS = (
    re.compile(r"\b[1-9]\d*/\d+\s+(?:tests?\s+)?(?:failed|failing|failure|failures)\b", re.I),
    re.compile(r"\b[1-9]\d*\s+(?:tests?\s+)?(?:failed|failing|failure|failures)\b", re.I),
    re.compile(r"\b(?:failed|failing|failure|failures)\s*[:=]\s*[1-9]\d*\b", re.I),
)
_PARTIAL_TEST_SUMMARY_PATTERN = re.compile(r"\b([1-9]\d*)\s*/\s*([1-9]\d*)\b")
_PARTIAL_TEST_BUCKET_PATTERN = re.compile(
    r"\b[1-9]\d*\s+(?:tests?\s+)?partials?\b",
    re.I,
)
_PARTIAL_TEST_SUMMARY_CUE_PATTERN = re.compile(
    r"\b(comprehensive|e2e|pass(?:ed|ing)?|results?|summary|suite)\b",
    re.I,
)
_FAILED_TEST_DISPOSITION_PREFIXES = (
    "contract_disposition:",
    "failed_test_disposition:",
    "known_failure_disposition:",
)
_MISSING_TEST_EXECUTION_DISPOSITION_PREFIXES = (
    "contract_disposition:no_test_runner_available",
    "failed_test_disposition:no_test_runner_available",
    "known_failure_disposition:no_test_runner_available",
)
_CURRENT_TEST_FAILURE_CUE_PATTERN = re.compile(
    r"\b("
    r"results?|final\s+state|test\s+results?|test_run|"
    r"npm\s+test|pytest|vitest|jest|playwright|"
    r"passed|pass(?:ed|ing)?\s+with"
    r")\b",
    re.I,
)
_HISTORICAL_FAILURE_CUE_PATTERN = re.compile(
    r"\b("
    r"prior|previous|previously|before|earlier|old|"
    r"root\s+cause|resolved|fixed|unblocked|after|now\s+pass"
    r")\b",
    re.I,
)
_VERIFICATION_INTEGRITY_PHASES = {"test", "review"}
_VERIFICATION_SCRIPT_NAME_PATTERN = re.compile(
    r"(^|/)([^/]*(test|spec|e2e|integration|audit|benchmark)[^/]*"
    r"\.(js|jsx|ts|tsx|mjs|cjs|py|sh)|"
    r"(tests?|spec|e2e|integration|audit|benchmarks?)/.+"
    r"\.(js|jsx|ts|tsx|mjs|cjs|py|sh))$",
    re.I,
)
_VERIFICATION_OUTPUT_PATH_PREFIXES = (
    "coverage/",
    "playwright-report/",
    "reports/",
    "screenshots/",
    "test-results/",
)
_TERMINAL_WORKER_REPORT_TYPES = frozenset({"completed", "failed", "blocked", "needs_replan"})


# --- Sandbox shim -----------------------------------------------------


class SandboxRunnerLike(Protocol):
    """Minimal sandbox surface we need for cmd runners.

    Both :class:`LocalSandboxAdapter` and :class:`MCPSandboxAdapter` expose
    ``run_command`` — we accept anything that quacks.
    """

    async def run_command(self, command: str, *, timeout: int = 60) -> dict[str, Any]: ...


# --- Runners ---------------------------------------------------------


class CmdCriterionRunner(CriterionRunner):
    """Runs a shell command inside the sandbox; pass iff exit code <= max_exit."""

    def __init__(self, *, default_timeout: int = 60) -> None:
        self._default_timeout = default_timeout

    async def run(
        self, criterion: AcceptanceCriterion, ctx: VerificationContext
    ) -> CriterionResult:
        cmd = str(criterion.spec.get("cmd", ""))
        run_cmd = _command_for_active_worktree(cmd, ctx)
        max_exit = int(criterion.spec.get("max_exit", 0))
        timeout = int(criterion.spec.get("timeout", self._default_timeout))
        sandbox = ctx.sandbox
        if sandbox is None:
            return CriterionResult(
                criterion=criterion,
                passed=False,
                confidence=1.0,
                message="no sandbox available to run cmd",
            )
        try:
            result = await sandbox.run_command(run_cmd, timeout=timeout)
        except Exception as exc:
            logger.warning("CmdCriterionRunner sandbox error: %s", exc)
            return CriterionResult(
                criterion=criterion,
                passed=False,
                confidence=0.9,
                message=f"sandbox error: {exc}",
            )
        exit_code = int(result.get("exit_code", 1))
        stdout = _normalize_sandbox_no_output_text(str(result.get("stdout", "")))
        stderr = str(result.get("stderr", ""))
        passed = exit_code <= max_exit
        return CriterionResult(
            criterion=criterion,
            passed=passed,
            confidence=1.0,
            message=f"exit={exit_code}"
            + (f"; stderr={stderr[:120]}" if stderr and not passed else ""),
            evidence=(EvidenceRef(kind="stdout", ref=stdout[:2000], note=run_cmd),)
            if stdout
            else (),
        )


def _command_for_active_worktree(command: str, ctx: VerificationContext) -> str:
    active_root = _clean_worktree_git_root(ctx)
    code_root = _sandbox_code_root(ctx)
    if not active_root or active_root == code_root:
        return command

    rewritten = command
    if code_root and code_root in command and active_root not in command:
        rewritten = command.replace(code_root, active_root)
    if active_root in rewritten:
        return rewritten
    return f"cd {shlex.quote(active_root)} && {rewritten}"


class FileExistsCriterionRunner(CriterionRunner):
    """Asserts a file exists. Prefers sandbox, falls back to local FS."""

    async def run(
        self, criterion: AcceptanceCriterion, ctx: VerificationContext
    ) -> CriterionResult:
        path = str(criterion.spec.get("path", ""))
        non_empty = bool(criterion.spec.get("non_empty", False))
        exists = False
        size = 0
        sandbox = ctx.sandbox
        if sandbox is not None and hasattr(sandbox, "run_command"):
            try:
                res = await sandbox.run_command(
                    f'[ -e "{path}" ] && wc -c < "{path}" || echo __MISSING__',
                    timeout=10,
                )
                stdout = str(res.get("stdout", "")).strip()
                if stdout != "__MISSING__" and stdout.isdigit():
                    exists = True
                    size = int(stdout)
            except Exception as exc:
                logger.debug("FileExists sandbox check failed: %s", exc)
        else:
            exists = os.path.exists(path)
            if exists:
                try:
                    size = os.path.getsize(path)
                except OSError:
                    size = 0
        passed = exists and (not non_empty or size > 0)
        msg = f"path={path!r} exists={exists} size={size}"
        return CriterionResult(
            criterion=criterion,
            passed=passed,
            confidence=1.0,
            message=msg,
            evidence=(EvidenceRef(kind="file", ref=path, note=str(size)),) if exists else (),
        )


class RegexCriterionRunner(CriterionRunner):
    """Regex-matches against ``ctx.stdout`` or a named artifact."""

    async def run(
        self, criterion: AcceptanceCriterion, ctx: VerificationContext
    ) -> CriterionResult:
        pattern = str(criterion.spec.get("pattern", ""))
        source = str(criterion.spec.get("source", "stdout"))
        flags = re.MULTILINE
        if criterion.spec.get("ignore_case"):
            flags |= re.IGNORECASE
        haystack = ctx.stdout if source == "stdout" else str(ctx.artifacts.get(source, ""))
        try:
            rgx = re.compile(pattern, flags)
        except re.error as exc:
            return CriterionResult(
                criterion=criterion,
                passed=False,
                confidence=1.0,
                message=f"invalid regex: {exc}",
            )
        match = rgx.search(haystack)
        return CriterionResult(
            criterion=criterion,
            passed=match is not None,
            confidence=1.0,
            message=f"pattern={pattern!r} source={source} matched={bool(match)}",
            evidence=(EvidenceRef(kind="match", ref=match.group(0)[:200]),) if match else (),
        )


class SchemaCriterionRunner(CriterionRunner):
    """Validates a JSON artifact against a JSON Schema.

    Uses the :mod:`jsonschema` library if available; otherwise performs a
    minimal shape check (type, required keys).
    """

    async def run(
        self, criterion: AcceptanceCriterion, ctx: VerificationContext
    ) -> CriterionResult:
        schema = criterion.spec.get("schema", {})
        artifact_key = str(criterion.spec.get("artifact", "output"))
        raw = ctx.artifacts.get(artifact_key)
        if raw is None:
            return CriterionResult(
                criterion=criterion,
                passed=False,
                confidence=1.0,
                message=f"artifact {artifact_key!r} missing",
            )
        value: Any
        if isinstance(raw, str):
            try:
                value = json.loads(raw)
            except json.JSONDecodeError as exc:
                return CriterionResult(
                    criterion=criterion,
                    passed=False,
                    confidence=1.0,
                    message=f"artifact not JSON: {exc}",
                )
        else:
            value = raw
        try:
            import jsonschema

            jsonschema.validate(value, schema)
            return CriterionResult(
                criterion=criterion,
                passed=True,
                confidence=1.0,
                message="schema ok",
            )
        except ImportError:
            return self._shallow_check(criterion, schema, value)
        except Exception as exc:
            return CriterionResult(
                criterion=criterion,
                passed=False,
                confidence=1.0,
                message=f"schema: {exc}",
            )

    def _shallow_check(
        self, criterion: AcceptanceCriterion, schema: dict[str, Any], value: object
    ) -> CriterionResult:
        # jsonschema not installed — check type + required keys only.
        sch_type = schema.get("type")
        required = schema.get("required", [])
        if sch_type == "object":
            if not isinstance(value, dict):
                return CriterionResult(
                    criterion=criterion,
                    passed=False,
                    confidence=0.8,
                    message="expected object",
                )
            missing = [k for k in required if k not in value]
            if missing:
                return CriterionResult(
                    criterion=criterion,
                    passed=False,
                    confidence=0.8,
                    message=f"missing keys: {missing}",
                )
        return CriterionResult(
            criterion=criterion,
            passed=True,
            confidence=0.7,
            message="shallow schema ok (jsonschema not installed)",
        )


class BrowserE2ECriterionRunner(CriterionRunner):
    """Validates structured evidence from a browser-driven user path.

    This runner deliberately does not infer success from prose. A worker or
    browser adapter must record explicit evidence such as
    ``browser_e2e:checkout`` plus screenshot and console-clean markers.
    """

    async def run(
        self, criterion: AcceptanceCriterion, ctx: VerificationContext
    ) -> CriterionResult:
        scenario = str(criterion.spec.get("name") or criterion.spec.get("path") or "").strip()
        require_screenshot = bool(criterion.spec.get("require_screenshot", True))
        require_console_clean = bool(criterion.spec.get("require_console_clean", True))
        evidence_values = _artifact_text_values(
            ctx,
            "browser_e2e",
            "execution_verifications",
            "last_worker_report_verifications",
            "candidate_verifications",
            "evidence_refs",
            "last_worker_report_artifacts",
            "candidate_artifacts",
        )

        missing: list[str] = []
        scenario_ref = f"browser_e2e:{scenario}"
        if scenario_ref not in evidence_values:
            missing.append(scenario_ref)
        screenshot_refs = [
            value
            for value in evidence_values
            if value.startswith("screenshot:") or value.startswith("browser_screenshot:")
        ]
        if require_screenshot and not screenshot_refs:
            missing.append("screenshot evidence")
        console_clean = (
            "console_errors:0" in evidence_values or "browser_console_errors:0" in evidence_values
        )
        if require_console_clean and not console_clean:
            missing.append("console_errors:0")

        if missing:
            return CriterionResult(
                criterion=criterion,
                passed=False,
                confidence=1.0,
                message=f"missing browser e2e evidence: {', '.join(missing)}",
            )
        return CriterionResult(
            criterion=criterion,
            passed=True,
            confidence=1.0,
            message=f"browser e2e evidence recorded: {scenario}",
            evidence=tuple(
                EvidenceRef(kind="browser", ref=value)
                for value in evidence_values
                if value == scenario_ref
                or value.startswith("screenshot:")
                or value.startswith("browser_screenshot:")
                or value in {"console_errors:0", "browser_console_errors:0"}
            ),
        )


class PipelineCriterionRunner(CriterionRunner):
    """Validates structured harness-native CI/CD evidence."""

    async def run(
        self, criterion: AcceptanceCriterion, ctx: VerificationContext
    ) -> CriterionResult:
        stale_pipeline = _stale_pipeline_result_for_current_report(ctx)
        if stale_pipeline is not None:
            reported_commit, pipeline_commit = stale_pipeline
            return CriterionResult(
                criterion=criterion,
                passed=False,
                confidence=0.85,
                message=(
                    "missing harness-native CI pipeline evidence for current commit "
                    f"{reported_commit}; previous pipeline evidence belongs to {pipeline_commit}"
                ),
            )
        values = _pipeline_evidence_values(ctx)
        pipeline_status = _current_pipeline_status(ctx)
        if pipeline_status == "failed" or (
            pipeline_status is None and _has_pipeline_failure_evidence(ctx)
        ):
            return CriterionResult(
                criterion=criterion,
                passed=False,
                confidence=0.75,
                message=_pipeline_failure_message(ctx),
            )
        if pipeline_status == "success" or _has_pipeline_success_evidence(ctx):
            refs = [
                value
                for value in values
                if value.startswith(("ci_pipeline:", "pipeline_run:", "pipeline_stage:"))
            ]
            return CriterionResult(
                criterion=criterion,
                passed=True,
                confidence=1.0,
                message="harness-native CI pipeline passed",
                evidence=tuple(EvidenceRef(kind="pipeline", ref=value) for value in refs),
            )
        return CriterionResult(
            criterion=criterion,
            passed=False,
            confidence=0.7,
            message="missing harness-native CI pipeline evidence",
        )


class PipelineStageCriterionRunner(CriterionRunner):
    """Requires a named pipeline stage to have passed."""

    async def run(
        self, criterion: AcceptanceCriterion, ctx: VerificationContext
    ) -> CriterionResult:
        stage = str(criterion.spec.get("stage") or "").strip()
        service_id = str(criterion.spec.get("service_id") or "").strip()
        values = _pipeline_evidence_values(ctx)
        passed_ref = (
            f"pipeline_stage:{stage}:passed:{service_id}"
            if service_id
            else f"pipeline_stage:{stage}:passed"
        )
        failed_ref = (
            f"pipeline_stage:{stage}:failed:{service_id}"
            if service_id
            else f"pipeline_stage:{stage}:failed"
        )
        if passed_ref in values:
            return CriterionResult(
                criterion=criterion,
                passed=True,
                confidence=1.0,
                message=f"pipeline stage passed: {stage}",
                evidence=(EvidenceRef(kind="pipeline_stage", ref=passed_ref),),
            )
        if failed_ref in values:
            return CriterionResult(
                criterion=criterion,
                passed=False,
                confidence=0.75,
                message=f"pipeline stage failed: {stage}",
            )
        return CriterionResult(
            criterion=criterion,
            passed=False,
            confidence=0.7,
            message=f"missing pipeline stage evidence: {stage}",
        )


class DeploymentHealthCriterionRunner(CriterionRunner):
    """Requires preview deployment health evidence."""

    async def run(
        self, criterion: AcceptanceCriterion, ctx: VerificationContext
    ) -> CriterionResult:
        values = _pipeline_evidence_values(ctx)
        service_id = str(criterion.spec.get("service_id") or "").strip()
        passed_ref = f"deployment_health:passed:{service_id}" if service_id else None
        failed_ref = f"deployment_health:failed:{service_id}" if service_id else None
        has_passed = (
            "deployment_health:passed" in values
            or (passed_ref is not None and passed_ref in values)
            or (not service_id and _first_prefixed(values, "deployment_health:passed:") is not None)
        )
        has_failed = (
            "deployment_health:failed" in values
            or (failed_ref is not None and failed_ref in values)
            or (not service_id and _first_prefixed(values, "deployment_health:failed:") is not None)
        )
        if has_passed:
            refs = [
                value
                for value in values
                if value.startswith(("deployment_health:", "deployment:", "preview_url:"))
            ]
            return CriterionResult(
                criterion=criterion,
                passed=True,
                confidence=1.0,
                message="preview deployment is healthy",
                evidence=tuple(EvidenceRef(kind="deployment", ref=value) for value in refs),
            )
        if has_failed:
            return CriterionResult(
                criterion=criterion,
                passed=False,
                confidence=0.75,
                message="preview deployment health check failed",
            )
        return CriterionResult(
            criterion=criterion,
            passed=False,
            confidence=0.7,
            message="missing preview deployment health evidence",
        )


class PreviewE2ECriterionRunner(CriterionRunner):
    """Requires preview URL, deployment health, and browser E2E evidence."""

    async def run(
        self, criterion: AcceptanceCriterion, ctx: VerificationContext
    ) -> CriterionResult:
        scenario = str(criterion.spec.get("name") or criterion.spec.get("path") or "").strip()
        service_id = str(criterion.spec.get("service_id") or "").strip()
        values = _pipeline_evidence_values(ctx) | _artifact_text_values(
            ctx,
            "browser_e2e",
            "execution_verifications",
            "last_worker_report_verifications",
            "candidate_verifications",
            "evidence_refs",
        )
        missing: list[str] = []
        scenario_ref = (
            f"preview_e2e:{service_id}:{scenario}" if service_id else f"preview_e2e:{scenario}"
        )
        browser_ref = (
            f"browser_e2e:{service_id}:{scenario}" if service_id else f"browser_e2e:{scenario}"
        )
        if scenario_ref not in values and browser_ref not in values:
            missing.append(scenario_ref)
        preview_prefix = f"preview_url:{service_id}:" if service_id else "preview_url:"
        if not _first_prefixed(values, preview_prefix):
            missing.append("preview_url")
        health_ref = (
            f"deployment_health:passed:{service_id}" if service_id else "deployment_health:passed"
        )
        if health_ref not in values:
            missing.append(health_ref)
        if missing:
            return CriterionResult(
                criterion=criterion,
                passed=False,
                confidence=0.7,
                message=f"missing preview e2e evidence: {', '.join(missing)}",
            )
        return CriterionResult(
            criterion=criterion,
            passed=True,
            confidence=1.0,
            message=f"preview e2e evidence recorded: {scenario}",
            evidence=tuple(
                EvidenceRef(kind="preview_e2e", ref=value)
                for value in values
                if value.startswith(("preview_e2e:", "browser_e2e:", "preview_url:"))
                or value.startswith("deployment_health:passed")
            ),
        )


class _InconclusiveRunner(CriterionRunner):
    """Returns a neutral result so unknown kinds never silently pass."""

    async def run(
        self, criterion: AcceptanceCriterion, ctx: VerificationContext
    ) -> CriterionResult:
        return CriterionResult(
            criterion=criterion,
            passed=not criterion.required,
            confidence=0.3,
            message=f"no runner for kind={criterion.kind.value}",
        )


# --- Aggregator -----------------------------------------------------


class AcceptanceCriterionVerifier(VerifierPort):
    """Default :class:`VerifierPort` — dispatches by :class:`CriterionKind`."""

    def __init__(
        self,
        runners: dict[CriterionKind, CriterionRunner] | None = None,
        verification_judge: WorkspaceVerificationJudgePort | None = None,
    ) -> None:
        self._runners: dict[CriterionKind, CriterionRunner] = runners or {
            CriterionKind.CMD: CmdCriterionRunner(),
            CriterionKind.FILE_EXISTS: FileExistsCriterionRunner(),
            CriterionKind.REGEX: RegexCriterionRunner(),
            CriterionKind.SCHEMA: SchemaCriterionRunner(),
            CriterionKind.BROWSER_E2E: BrowserE2ECriterionRunner(),
            CriterionKind.CI_PIPELINE: PipelineCriterionRunner(),
            CriterionKind.PIPELINE_STAGE: PipelineStageCriterionRunner(),
            CriterionKind.DEPLOYMENT_HEALTH: DeploymentHealthCriterionRunner(),
            CriterionKind.PREVIEW_E2E: PreviewE2ECriterionRunner(),
        }
        self._fallback = _InconclusiveRunner()
        self._verification_judge = verification_judge

    def register(self, kind: CriterionKind, runner: CriterionRunner) -> None:
        self._runners[kind] = runner

    async def verify(self, ctx: VerificationContext) -> VerificationReport:
        terminal_results = _terminal_worker_report_results(ctx)
        results = list(terminal_results)
        preflight_guard = _preflight_evidence_guard(ctx)
        if preflight_guard is not None:
            results.append(preflight_guard)
        checkpoint_guard = _feature_checkpoint_evidence_guard(ctx)
        if checkpoint_guard is not None:
            results.append(checkpoint_guard)
        failed_test_guard = _failed_test_evidence_guard(ctx)
        if failed_test_guard is not None:
            results.append(failed_test_guard)
        missing_test_execution_guard = _missing_test_execution_evidence_guard(ctx)
        if missing_test_execution_guard is not None:
            results.append(missing_test_execution_guard)
        verification_script_guard = await _verification_script_mutation_guard(ctx)
        if verification_script_guard is not None:
            results.append(verification_script_guard)
        clean_worktree_guard = await _clean_worktree_after_commit_guard(ctx)
        if clean_worktree_guard is not None:
            results.append(clean_worktree_guard)
        pipeline_guard = await _pipeline_gate_guard(ctx)
        if pipeline_guard is not None:
            results.append(pipeline_guard)
        for crit in ctx.node.acceptance_criteria:
            runner = self._runners.get(crit.kind, self._fallback)
            try:
                res = await runner.run(crit, ctx)
            except Exception as exc:
                logger.warning("criterion runner errored: %s", exc)
                res = CriterionResult(
                    criterion=crit,
                    passed=False,
                    confidence=0.9,
                    message=f"runner error: {exc}",
                )
            results.append(res)
        if self._verification_judge is not None:
            results = await _apply_verification_judge(
                self._verification_judge,
                ctx=ctx,
                results=results,
            )
        return VerificationReport(
            node_id=ctx.node.id,
            attempt_id=ctx.attempt_id,
            results=tuple(results),
        )


async def _apply_verification_judge(
    judge: WorkspaceVerificationJudgePort,
    *,
    ctx: VerificationContext,
    results: list[CriterionResult],
) -> list[CriterionResult]:
    deterministic_result = _deterministic_drone_failure_judge_result(ctx, results)
    if deterministic_result is not None:
        return [
            *_normalize_results_for_judge(results, deterministic_result),
            _judge_criterion_result(deterministic_result),
        ]

    request = _build_judge_request(ctx, results)
    try:
        judge_result = await judge.judge(request)
    except Exception as exc:
        logger.warning("workspace verification judge failed: %s", exc)
        judge_result = WorkspaceVerificationJudgeResult(
            verdict=WorkspaceVerificationJudgeVerdict.RETRY_INFRASTRUCTURE,
            rationale=f"workspace verification judge failed: {exc}",
            failed_criteria=("workspace_verification_judge",),
            required_next_action="retry verification judge",
            feedback_items=(
                WorkspaceVerificationFeedbackItem(
                    target_layer=WorkspaceVerificationFeedbackTargetLayer.RUNTIME,
                    feedback_kind=WorkspaceVerificationFeedbackKind.RUNTIME_INFRA_FAILURE,
                    severity=WorkspaceVerificationFeedbackSeverity.WARNING,
                    recommended_action=WorkspaceVerificationRecommendedAction.RETRY_INFRA,
                    summary=f"workspace verification judge failed: {exc}",
                    failure_signature="workspace_verification_judge_failed",
                ),
            ),
            confidence=0.5,
        )
    judge_result = _coerce_judge_result_for_required_context(ctx, judge_result, results)
    return [
        *_normalize_results_for_judge(results, judge_result),
        _judge_criterion_result(judge_result),
    ]


def _deterministic_drone_failure_judge_result(
    ctx: VerificationContext,
    results: list[CriterionResult],
) -> WorkspaceVerificationJudgeResult | None:
    synthetic_result = WorkspaceVerificationJudgeResult(
        verdict=WorkspaceVerificationJudgeVerdict.RETRY_INFRASTRUCTURE,
        rationale=(
            "deterministic Drone failure classification from current pipeline evidence; "
            "skipping LLM judge"
        ),
        failed_criteria=("ci_pipeline",),
        required_next_action="route deterministic Drone failure",
        confidence=0.8,
    )
    coerced_result = _coerce_judge_result_for_required_context(
        ctx,
        synthetic_result,
        results,
    )
    return None if coerced_result is synthetic_result else coerced_result


def _build_judge_request(
    ctx: VerificationContext,
    results: list[CriterionResult],
) -> WorkspaceVerificationJudgeRequest:
    result_payloads = tuple(_criterion_result_payload(result) for result in results)
    failed_messages = tuple(
        result.message
        for result in results
        if result.criterion.required and not result.passed and result.message
    )[:12]
    sandbox_code_root = _sandbox_code_root(ctx)
    worktree_path = _clean_worktree_git_root(ctx)
    active_execution_root = worktree_path or sandbox_code_root
    return WorkspaceVerificationJudgeRequest(
        workspace_id=ctx.workspace_id,
        node_id=ctx.node.id,
        attempt_id=ctx.attempt_id,
        node_title=ctx.node.title,
        node_description=ctx.node.description,
        acceptance_criteria=tuple(
            {
                "kind": criterion.kind.value,
                "spec": _bounded_jsonish(criterion.spec),
                "required": criterion.required,
                "description": criterion.description,
            }
            for criterion in ctx.node.acceptance_criteria
        ),
        worker_summary=_bounded_text(
            _artifact_text(ctx, "last_worker_report_summary") or ctx.stdout,
            limit=1600,
        ),
        candidate_artifacts=tuple(
            _bounded_text(value, limit=600)
            for value in sorted(
                _attempt_scoped_artifact_text_values(
                    ctx,
                    "candidate_artifacts",
                    "last_worker_report_artifacts",
                )
            )[:20]
        ),
        candidate_verifications=tuple(
            _bounded_text(value, limit=600)
            for value in sorted(
                _attempt_scoped_artifact_text_values(
                    ctx,
                    "candidate_verifications",
                    "last_worker_report_verifications",
                    "execution_verifications",
                )
            )[:24]
        ),
        task_evidence_refs=tuple(
            _bounded_text(value, limit=600)
            for value in sorted(
                _attempt_scoped_artifact_text_values(
                    ctx,
                    "evidence_refs",
                    "pipeline_evidence_refs",
                    "verification_evidence_refs",
                )
            )[:24]
        ),
        latest_verification_results=result_payloads,
        guard_failures=failed_messages,
        sandbox_code_root=sandbox_code_root,
        worktree_path=worktree_path,
        active_execution_root=active_execution_root,
        worktree_isolation_active=_worktree_isolation_active(
            code_root=sandbox_code_root,
            worktree_path=worktree_path,
        ),
        recent_git_status=_recent_git_status_from_results(results),
        task_metadata=_metadata_summary(ctx),
    )


def _criterion_result_payload(result: CriterionResult) -> dict[str, Any]:
    return {
        "kind": result.criterion.kind.value,
        "name": result.criterion.spec.get("name"),
        "required": result.criterion.required,
        "passed": result.passed,
        "confidence": result.confidence,
        "message": _bounded_text(result.message, limit=500),
        "description": _bounded_text(result.criterion.description, limit=500),
        "evidence": [
            {
                "kind": evidence.kind,
                "ref": _bounded_text(evidence.ref, limit=500),
                "note": _bounded_text(evidence.note, limit=300),
            }
            for evidence in result.evidence[:6]
        ],
    }


def _metadata_summary(ctx: VerificationContext) -> dict[str, Any]:
    has_attempt_candidate_evidence = bool(
        ctx.attempt_id
        and (
            _text_values(ctx.artifacts.get("candidate_artifacts"))
            or _text_values(ctx.artifacts.get("candidate_verifications"))
        )
    )
    allowed_keys = (
        "code_context",
        "current_attempt_conversation_id",
        "evidence_refs",
        "execution_verifications",
        "feature_id",
        "git_diff_summary",
        "last_attempt_status",
        "last_worker_report_artifacts",
        "last_worker_report_summary",
        "last_worker_report_type",
        "last_worker_report_verifications",
        "pipeline_evidence_refs",
        "pipeline_failed_stage",
        "pipeline_failure_summary",
        "pipeline_gate_status",
        "pipeline_last_summary",
        "pipeline_run_id",
        "pipeline_status",
        "deploy_validation",
        "deployment_status",
        "external_id",
        "preflight_checks",
        "preview_url",
        "verification_commands",
        "write_set",
    )
    metadata: dict[str, Any] = {}
    stale_pipeline = _stale_pipeline_result_for_current_report(ctx) is not None
    for key in allowed_keys:
        if stale_pipeline and key in _STALE_PIPELINE_METADATA_KEYS:
            continue
        if has_attempt_candidate_evidence and key in _ATTEMPT_AGGREGATE_EVIDENCE_KEYS:
            continue
        value = ctx.node.metadata.get(key, ctx.artifacts.get(key))
        if value not in (None, "", [], {}):
            metadata[key] = _bounded_jsonish(value)
    return metadata


def _bounded_jsonish(value: object, *, limit: int = 1600) -> object:
    if isinstance(value, str):
        return _bounded_text(value, limit=limit)
    if isinstance(value, int | float | bool) or value is None:
        return value
    if isinstance(value, list | tuple | set):
        return [_bounded_jsonish(item, limit=400) for item in list(value)[:24]]
    if isinstance(value, Mapping):
        return {
            str(key): _bounded_jsonish(item, limit=400) for key, item in list(value.items())[:24]
        }
    return _bounded_text(str(value), limit=limit)


def _bounded_text(value: str, *, limit: int) -> str:
    text = value.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 15].rstrip() + " ...[truncated]"


def _recent_git_status_from_results(results: list[CriterionResult]) -> str:
    for result in results:
        if result.criterion.spec.get("name") != "clean_worktree_after_commit":
            continue
        for evidence in result.evidence:
            if evidence.kind == "git_status":
                return _bounded_text(evidence.ref, limit=1200)
        if result.passed:
            return ""
        return _bounded_text(result.message, limit=1200)
    return ""


def _coerce_judge_result_for_required_context(  # noqa: C901, PLR0911, PLR0912
    ctx: VerificationContext,
    result: WorkspaceVerificationJudgeResult,
    results: list[CriterionResult],
) -> WorkspaceVerificationJudgeResult:
    yaml_config_feedback = _drone_yaml_configuration_failure_feedback(results)
    if yaml_config_feedback is not None:
        return WorkspaceVerificationJudgeResult(
            verdict=WorkspaceVerificationJudgeVerdict.NEEDS_REWORK,
            rationale=(
                "Drone rejected the repository `.drone.yml` before running pipeline steps. "
                "This is a pipeline configuration defect that must be repaired in the "
                f"worktree, not an infrastructure retry. Judge rationale: {result.rationale}"
            ),
            failed_criteria=(
                "ci_pipeline",
                "drone_yaml_configuration_invalid",
                *result.failed_criteria,
            ),
            satisfied_guard_failures=result.satisfied_guard_failures,
            required_next_action=(
                "Fix `.drone.yml` so Drone can parse it. YAML command entries must be strings; "
                "quote shell commands that contain `: `, `{}`, or other YAML mapping syntax, "
                "or use a block scalar command. A syntax-only YAML parser is not enough; "
                "after parsing `.drone.yml`, verify every `steps[].commands[]` item is a "
                "string, especially lines like `echo \"label: value\"`. Commit, rerun Drone, "
                "and preserve the docker deploy contract: no daemon-side pull/run from "
                "host.docker.internal or localhost registry, keep the deploy-local docker "
                "build tag, stale container cleanup, dependency sidecars, runtime env, and "
                "health-log diagnostics."
            ),
            next_action_kind=WorkspaceVerificationNextActionKind.RETRY_SAME_NODE,
            repair_brief=result.repair_brief,
            feedback_items=(yaml_config_feedback, *result.feedback_items),
            confidence=max(result.confidence, 0.9),
        )
    external_registry_feedback = _drone_external_registry_transient_failure_feedback(results)
    if external_registry_feedback is not None:
        return WorkspaceVerificationJudgeResult(
            verdict=WorkspaceVerificationJudgeVerdict.RETRY_INFRASTRUCTURE,
            rationale=(
                "Drone failed while pulling an external base image or registry manifest. "
                "This is a transient CI runtime/network failure, not a product-code change. "
                f"Judge rationale: {result.rationale}"
            ),
            failed_criteria=("ci_pipeline", "drone_external_registry_transient_failure"),
            satisfied_guard_failures=result.satisfied_guard_failures,
            required_next_action=(
                "Retry the same Drone pipeline for the same commit; do not ask the worker to "
                "change `.drone.yml` or application code for external registry TLS/timeout "
                "failures."
            ),
            next_action_kind=WorkspaceVerificationNextActionKind.RETRY_SAME_NODE,
            repair_brief=result.repair_brief,
            feedback_items=(external_registry_feedback, *result.feedback_items),
            confidence=max(result.confidence, 0.9),
        )
    docker_socket_feedback = _drone_docker_socket_mount_failure_feedback(results)
    docker_socket_failure_kind = "socket_mount"
    if docker_socket_feedback is None:
        docker_socket_feedback = _drone_host_socket_dind_service_timeout_feedback(results)
        docker_socket_failure_kind = "dind_service_timeout"
    if docker_socket_feedback is not None:
        is_dind_timeout = docker_socket_failure_kind == "dind_service_timeout"
        return WorkspaceVerificationJudgeResult(
            verdict=WorkspaceVerificationJudgeVerdict.NEEDS_REWORK,
            rationale=(
                (
                    "Drone timed out because a docker:dind service remained running in a "
                    "host-socket deploy pipeline. Host-socket deploy must use the mounted "
                    "Unix socket without a DinD service. "
                )
                if is_dind_timeout
                else (
                    "Drone docker-deploy failed because the Docker socket file was mounted "
                    "to /var/run instead of /var/run/docker.sock. "
                )
            )
            + (
                f"Judge rationale: {result.rationale}"
            ),
            failed_criteria=(
                "ci_pipeline",
                (
                    "drone_host_socket_dind_service_timeout"
                    if is_dind_timeout
                    else "drone_docker_socket_volume_path"
                ),
                *result.failed_criteria,
            ),
            satisfied_guard_failures=result.satisfied_guard_failures,
            required_next_action=(
                (
                    "Fix .drone.yml by removing the `docker:dind` service, any service named "
                    "`docker`, privileged service settings, and `network_mode: host` from the "
                    "host-socket deploy pipeline. Keep only the `/var/run/docker.sock` host "
                    "volume mounted into the docker:cli deploy step, commit, and rerun Drone."
                )
                if is_dind_timeout
                else (
                    "Fix .drone.yml docker-deploy step volume path to mount docker-sock at "
                    "/var/run/docker.sock, not /var/run; keep the top-level host volume path "
                    "/var/run/docker.sock, commit, and rerun Drone."
                )
            ),
            next_action_kind=WorkspaceVerificationNextActionKind.RETRY_SAME_NODE,
            repair_brief=result.repair_brief,
            feedback_items=(docker_socket_feedback, *result.feedback_items),
            confidence=max(result.confidence, 0.9),
        )
    registry_feedback = _drone_host_socket_registry_failure_feedback(results)
    registry_failure_kind = "host_internal"
    if registry_feedback is None:
        registry_feedback = _drone_host_socket_localhost_registry_timeout_feedback(results)
        registry_failure_kind = "localhost_timeout"
    if registry_feedback is not None:
        is_localhost_timeout = registry_failure_kind == "localhost_timeout"
        return WorkspaceVerificationJudgeResult(
            verdict=WorkspaceVerificationJudgeVerdict.NEEDS_REWORK,
            rationale=(
                "Drone docker-deploy failed because the mounted host Docker daemon could not "
                "use the local HTTP registry from the deploy step. Use a deploy-local image tag "
                "instead of daemon-side registry pulls. Judge rationale: "
                f"{result.rationale}"
            ),
            failed_criteria=(
                "ci_pipeline",
                (
                    "drone_host_socket_localhost_registry_unreachable"
                    if is_localhost_timeout
                    else "drone_host_socket_registry_address"
                ),
                *result.failed_criteria,
            ),
            satisfied_guard_failures=result.satisfied_guard_failures,
            required_next_action=(
                "Fix .drone.yml docker-deploy so it does not docker pull/run "
                "host.docker.internal:<port> or localhost:<port> from the local HTTP registry "
                "through the host Docker daemon. Keep plugins/docker build/push on the "
                "runner-reachable registry, then in docker-deploy build or load a deploy-local "
                "image tag into the mounted daemon, docker run that local tag, "
                "commit, and rerun Drone."
            ),
            next_action_kind=WorkspaceVerificationNextActionKind.RETRY_SAME_NODE,
            repair_brief=result.repair_brief,
            feedback_items=(registry_feedback, *result.feedback_items),
            confidence=max(result.confidence, 0.9),
        )
    host_port_feedback = _drone_docker_host_port_conflict_feedback(results)
    if host_port_feedback is not None:
        return WorkspaceVerificationJudgeResult(
            verdict=WorkspaceVerificationJudgeVerdict.NEEDS_REWORK,
            rationale=(
                "Drone docker-deploy failed because the host-side Docker port mapping "
                "collided with a platform service port. Use the platform-provided deploy "
                "host port instead of reserved ports. Judge rationale: "
                f"{result.rationale}"
            ),
            failed_criteria=(
                "ci_pipeline",
                "drone_docker_deploy_host_port_conflict",
                *result.failed_criteria,
            ),
            satisfied_guard_failures=result.satisfied_guard_failures,
            required_next_action=(
                "Fix .drone.yml docker-deploy so `docker run -p` binds the host side to "
                "docker.deploy_host_port from the workspace delivery context, not platform "
                "reserved ports such as 8080, 3001, or 5001. Keep the container-side port "
                "matched to the Dockerfile/app, update the Drone health check to "
                "docker.deploy_health_url, commit, and rerun Drone."
            ),
            next_action_kind=WorkspaceVerificationNextActionKind.RETRY_SAME_NODE,
            repair_brief=result.repair_brief,
            feedback_items=(host_port_feedback, *result.feedback_items),
            confidence=max(result.confidence, 0.9),
        )
    container_name_conflict_feedback = _drone_docker_deploy_container_name_conflict_feedback(
        results
    )
    if container_name_conflict_feedback is not None:
        return WorkspaceVerificationJudgeResult(
            verdict=WorkspaceVerificationJudgeVerdict.NEEDS_REWORK,
            rationale=(
                "Drone docker-deploy failed before validation because a stale container from "
                "an earlier attempt still owns the requested name. Judge rationale: "
                f"{result.rationale}"
            ),
            failed_criteria=(
                "ci_pipeline",
                "drone_docker_deploy_container_name_conflict",
                *result.failed_criteria,
            ),
            satisfied_guard_failures=result.satisfied_guard_failures,
            required_next_action=(
                "Fix .drone.yml docker-deploy so every retryable deploy removes stale app and "
                "dependency sidecar containers before `docker run`, for example `docker rm -f "
                "<app-container> <postgres-container> <redis-container> 2>/dev/null || true`. "
                "Then start PostgreSQL sidecars with `-e POSTGRES_USER=postgres -e "
                "POSTGRES_PASSWORD=postgres -e POSTGRES_DB=<db>` before the image, wait for "
                "readiness, commit, and rerun Drone."
            ),
            next_action_kind=WorkspaceVerificationNextActionKind.RETRY_SAME_NODE,
            repair_brief=result.repair_brief,
            feedback_items=(container_name_conflict_feedback, *result.feedback_items),
            confidence=max(result.confidence, 0.9),
        )
    missing_probe_tool_feedback = _drone_docker_deploy_missing_health_probe_tool_feedback(results)
    if missing_probe_tool_feedback is not None:
        return WorkspaceVerificationJudgeResult(
            verdict=WorkspaceVerificationJudgeVerdict.NEEDS_REWORK,
            rationale=(
                "Drone docker-deploy failed because the health probe used a command that is "
                "not available in the docker:cli deploy image. Use the platform-provided "
                "health check command or install the tool before use. Judge rationale: "
                f"{result.rationale}"
            ),
            failed_criteria=(
                "ci_pipeline",
                "drone_docker_deploy_missing_health_probe_tool",
                *result.failed_criteria,
            ),
            satisfied_guard_failures=result.satisfied_guard_failures,
            required_next_action=(
                "Fix .drone.yml docker-deploy health checking to use "
                "docker.deploy_health_check_command from the workspace delivery context "
                "(wget-based in docker:cli) or install curl before using curl. Add a failure "
                "block that prints `docker ps -a` and `docker logs <container>` before exit, "
                "and inspect Dockerfile/docker-compose/.env.example for required runtime "
                "environment variables such as DATABASE_URL before rerunning Drone."
            ),
            next_action_kind=WorkspaceVerificationNextActionKind.RETRY_SAME_NODE,
            repair_brief=result.repair_brief,
            feedback_items=(missing_probe_tool_feedback, *result.feedback_items),
            confidence=max(result.confidence, 0.9),
        )
    postgres_sidecar_feedback = _drone_docker_deploy_postgres_sidecar_env_feedback(results)
    if postgres_sidecar_feedback is not None:
        return WorkspaceVerificationJudgeResult(
            verdict=WorkspaceVerificationJudgeVerdict.NEEDS_REWORK,
            rationale=(
                "Drone docker-deploy failed because the PostgreSQL sidecar was started without "
                "the required POSTGRES_* environment variables. Judge rationale: "
                f"{result.rationale}"
            ),
            failed_criteria=(
                "ci_pipeline",
                "drone_docker_deploy_postgres_sidecar_env",
                *result.failed_criteria,
            ),
            satisfied_guard_failures=result.satisfied_guard_failures,
            required_next_action=(
                "Fix .drone.yml docker-deploy by starting the PostgreSQL sidecar with docker "
                "run environment flags before the image, for example: `docker run -d --name "
                "<postgres-container> --network <network> -e POSTGRES_USER=postgres -e "
                "POSTGRES_PASSWORD=postgres -e POSTGRES_DB=<db> postgres:16-alpine`. Do not "
                "use `postgres:16-alpine -c POSTGRES_PASSWORD=...`. Wait with `docker exec "
                "<postgres-container> pg_isready -U postgres`, pass DATABASE_URL to the app "
                "using that sidecar hostname, print docker logs on failure, commit, and rerun "
                "Drone."
            ),
            next_action_kind=WorkspaceVerificationNextActionKind.RETRY_SAME_NODE,
            repair_brief=result.repair_brief,
            feedback_items=(postgres_sidecar_feedback, *result.feedback_items),
            confidence=max(result.confidence, 0.9),
        )
    missing_build_artifact_feedback = _drone_docker_deploy_missing_build_artifact_feedback(
        results
    )
    if missing_build_artifact_feedback is not None:
        return WorkspaceVerificationJudgeResult(
            verdict=WorkspaceVerificationJudgeVerdict.NEEDS_REWORK,
            rationale=(
                "Drone docker-deploy started the container, but the image is missing a "
                "runtime build artifact required by the startup command. Judge rationale: "
                f"{result.rationale}"
            ),
            failed_criteria=(
                "ci_pipeline",
                "drone_docker_deploy_missing_build_artifact",
                *result.failed_criteria,
            ),
            satisfied_guard_failures=result.satisfied_guard_failures,
            required_next_action=(
                "Fix .drone.yml or Dockerfile so the image contains the build output required "
                "by the runtime command, such as `/app/dist/index.js`. For Node/TypeScript "
                "apps, add or preserve a root build step (`npm install && npm run build`) before "
                "docker-build/deploy-local docker build, or move the build into Dockerfile. "
                "Preserve the existing deploy fixes while editing: deploy-local docker build, "
                "stale app/dependency container cleanup, sidecar dependencies, runtime env, and "
                "health-log diagnostics must remain in the same .drone.yml. Commit and rerun "
                "Drone."
            ),
            next_action_kind=WorkspaceVerificationNextActionKind.RETRY_SAME_NODE,
            repair_brief=result.repair_brief,
            feedback_items=(missing_build_artifact_feedback, *result.feedback_items),
            confidence=max(result.confidence, 0.9),
        )
    runtime_env_feedback = _drone_docker_deploy_runtime_env_failure_feedback(results)
    if runtime_env_feedback is not None:
        runtime_field_guidance = _runtime_config_field_guidance(
            _missing_runtime_config_fields(results)
        )
        return WorkspaceVerificationJudgeResult(
            verdict=WorkspaceVerificationJudgeVerdict.NEEDS_REWORK,
            rationale=(
                "Drone docker-deploy started the container, but application startup failed "
                "because required runtime environment or dependent services were missing. "
                f"Judge rationale: {result.rationale}"
            ),
            failed_criteria=(
                "ci_pipeline",
                "drone_docker_deploy_missing_runtime_env",
                *result.failed_criteria,
            ),
            satisfied_guard_failures=result.satisfied_guard_failures,
            required_next_action=(
                "Fix .drone.yml docker-deploy so docker run or docker compose supplies the "
                "runtime environment and dependencies required by the image. Inspect "
                "Dockerfile, docker-compose, .env.example, and app startup code; pass required "
                "values such as DATABASE_URL, REDIS_URL, NODE_SECRET, and SESSION_SECRET. "
                f"{runtime_field_guidance}"
                "Do not point database/cache URLs at host.docker.internal:<port> unless a "
                "reachable external service is explicitly declared; otherwise use docker "
                "compose or sidecar containers on a named Docker network to start the required "
                "database/cache services. "
                "Keep the health probe fail-fast and print docker logs on failure."
            ),
            next_action_kind=WorkspaceVerificationNextActionKind.RETRY_SAME_NODE,
            repair_brief=result.repair_brief,
            feedback_items=(runtime_env_feedback, *result.feedback_items),
            confidence=max(result.confidence, 0.9),
        )
    unhealthy_container_feedback = _drone_docker_deploy_unhealthy_container_feedback(results)
    if unhealthy_container_feedback is not None:
        return WorkspaceVerificationJudgeResult(
            verdict=WorkspaceVerificationJudgeVerdict.NEEDS_REWORK,
            rationale=(
                "Drone docker-deploy started the container, but the host-mapped health endpoint "
                "was not reachable. Treat this as a deploy runtime/startup failure until the "
                "container logs and dependencies prove otherwise. Judge rationale: "
                f"{result.rationale}"
            ),
            failed_criteria=(
                "ci_pipeline",
                "drone_docker_deploy_unhealthy_container",
                *result.failed_criteria,
            ),
            satisfied_guard_failures=result.satisfied_guard_failures,
            required_next_action=(
                "Fix .drone.yml docker-deploy so the app container can actually become healthy. "
                "Add a failure block that prints `docker ps -a` and `docker logs <container>` "
                "before exit. Inspect Dockerfile, docker-compose, .env.example, and startup code "
                "for required dependencies and the actual long-lived server entrypoint. If logs "
                "show migrations complete and the container exits, ensure the Dockerfile CMD runs "
                "the real server module, not an app module or one-shot script. If PostgreSQL, "
                "Redis, or another service is required and no reachable external service is "
                "declared, use docker compose or sidecar containers on a named Docker network, "
                "pass app env such as DATABASE_URL or REDIS_URL to those sidecars, wait for "
                "dependencies, then rerun Drone. Preserve existing deploy fixes: local docker "
                "build tag, stale container cleanup, sidecars, runtime env, and health-log "
                "diagnostics."
            ),
            next_action_kind=WorkspaceVerificationNextActionKind.RETRY_SAME_NODE,
            repair_brief=result.repair_brief,
            feedback_items=(unhealthy_container_feedback, *result.feedback_items),
            confidence=max(result.confidence, 0.9),
        )
    docker_build_feedback = _drone_docker_build_timeout_feedback(results)
    if docker_build_feedback is not None:
        return WorkspaceVerificationJudgeResult(
            verdict=WorkspaceVerificationJudgeVerdict.NEEDS_REWORK,
            rationale=(
                "Drone timed out in the plugins/docker build stage before deploy could run. "
                "This requires CI/Dockerfile changes, not blind pipeline retries. "
                f"Judge rationale: {result.rationale}"
            ),
            failed_criteria=(
                "ci_pipeline",
                "drone_docker_build_timeout",
                *result.failed_criteria,
            ),
            satisfied_guard_failures=result.satisfied_guard_failures,
            required_next_action=(
                "Fix the repository CI/Docker build path: add or repair `.dockerignore` so "
                "node_modules, build outputs, coverage, Playwright/Storybook artifacts, and "
                "VCS metadata are not sent as Docker context; use a Node 20+ Docker base image "
                "when package engines require Node 20; keep deploy as a separate docker:cli "
                "step without masked pull/tag fallbacks; commit, then rerun Drone."
            ),
            next_action_kind=WorkspaceVerificationNextActionKind.RETRY_SAME_NODE,
            repair_brief=result.repair_brief,
            feedback_items=(docker_build_feedback, *result.feedback_items),
            confidence=max(result.confidence, 0.9),
        )
    if (
        result.verdict is WorkspaceVerificationJudgeVerdict.ACCEPTED
        and _requires_terminal_worker_report(ctx)
        and not _has_current_terminal_worker_report(ctx)
    ):
        return WorkspaceVerificationJudgeResult(
            verdict=WorkspaceVerificationJudgeVerdict.NEEDS_REWORK,
            rationale=(
                "A current-attempt terminal worker report is required before this node can "
                "be accepted. "
                f"Judge rationale: {result.rationale}"
            ),
            failed_criteria=("terminal_worker_report_completed", *result.failed_criteria),
            satisfied_guard_failures=result.satisfied_guard_failures,
            required_next_action="collect a current-attempt terminal worker report and rerun verification",
            repair_brief=result.repair_brief,
            feedback_items=result.feedback_items,
            confidence=max(result.confidence, 0.7),
        )
    if (
        result.verdict is WorkspaceVerificationJudgeVerdict.ACCEPTED
        and _required_guard_failed(
            results,
            "failed_test_evidence",
        )
        and not _judge_satisfied_required_guard(result, "failed_test_evidence")
    ):
        return WorkspaceVerificationJudgeResult(
            verdict=WorkspaceVerificationJudgeVerdict.NEEDS_REWORK,
            rationale=(
                "Test evidence reports at least one failed/failing test, so the node cannot be "
                f"accepted as complete. Judge rationale: {result.rationale}"
            ),
            failed_criteria=("failed_test_evidence", *result.failed_criteria),
            satisfied_guard_failures=result.satisfied_guard_failures,
            required_next_action="fix or explicitly disposition failing tests before acceptance",
            repair_brief=result.repair_brief,
            feedback_items=result.feedback_items,
            confidence=max(result.confidence, 0.8),
        )
    if result.verdict is WorkspaceVerificationJudgeVerdict.ACCEPTED and _required_guard_failed(
        results,
        "missing_test_execution_evidence",
    ):
        return WorkspaceVerificationJudgeResult(
            verdict=WorkspaceVerificationJudgeVerdict.NEEDS_REWORK,
            rationale=(
                "Required test execution evidence is missing because the current attempt says "
                f"tests were not actually run. Judge rationale: {result.rationale}"
            ),
            failed_criteria=("missing_test_execution_evidence", *result.failed_criteria),
            satisfied_guard_failures=result.satisfied_guard_failures,
            required_next_action="run the required tests in the attempt worktree or report blocked",
            repair_brief=result.repair_brief,
            feedback_items=result.feedback_items,
            confidence=max(result.confidence, 0.8),
        )
    return result


def _drone_yaml_configuration_failure_feedback(
    results: list[CriterionResult],
) -> WorkspaceVerificationFeedbackItem | None:
    text = "\n".join(result.message for result in results if result.message).lower()
    if not (
        "drone build" in text
        and "yaml:" in text
        and "unmarshal" in text
        and "into string" in text
    ):
        return None
    return WorkspaceVerificationFeedbackItem(
        target_layer=WorkspaceVerificationFeedbackTargetLayer.WORKER,
        feedback_kind=WorkspaceVerificationFeedbackKind.PRODUCT_CODE_FAILURE,
        severity=WorkspaceVerificationFeedbackSeverity.BLOCKING,
        recommended_action=WorkspaceVerificationRecommendedAction.RETRY_WORKER,
        summary=(
            "Drone could not parse `.drone.yml` because a field that must be a string was "
            "written as a YAML mapping. This commonly happens when a command contains an "
            "unquoted colon, such as `echo \"label: value\"`; generic YAML syntax validation "
            "can still pass, so the parsed command item types must be checked."
        ),
        evidence_refs=(
            "drone_error:yaml_unmarshal_into_string",
            "drone_config:.drone.yml",
        ),
        failure_signature="drone-yaml-configuration-unmarshal-into-string",
    )


def _drone_external_registry_transient_failure_feedback(
    results: list[CriterionResult],
) -> WorkspaceVerificationFeedbackItem | None:
    text = "\n".join(result.message for result in results if result.message).lower()
    has_external_registry = any(
        token in text
        for token in (
            "registry-1.docker.io",
            "docker.io/v2/",
            "pulling from library/",
            "failed to resolve source metadata",
        )
    )
    has_transient_network_failure = any(
        token in text
        for token in (
            "tls handshake timeout",
            "i/o timeout",
            "net/http: request canceled",
            "context deadline exceeded",
            "temporary failure",
            "connection reset by peer",
        )
    )
    if not (has_external_registry and has_transient_network_failure):
        return None
    return WorkspaceVerificationFeedbackItem(
        target_layer=WorkspaceVerificationFeedbackTargetLayer.RUNTIME,
        feedback_kind=WorkspaceVerificationFeedbackKind.RUNTIME_INFRA_FAILURE,
        severity=WorkspaceVerificationFeedbackSeverity.WARNING,
        recommended_action=WorkspaceVerificationRecommendedAction.RETRY_INFRA,
        summary=(
            "Drone failed while pulling an external registry image or manifest due to a "
            "transient network/TLS timeout. Retry the pipeline for the same commit."
        ),
        evidence_refs=(
            "drone_error:external_registry_transient_timeout",
            "drone_stage:docker-build",
        ),
        failure_signature="drone-external-registry-transient-timeout",
    )


def _drone_docker_socket_mount_failure_feedback(
    results: list[CriterionResult],
) -> WorkspaceVerificationFeedbackItem | None:
    text = "\n".join(result.message for result in results if result.message).lower()
    if not (
        "not a directory" in text
        and "/var/run" in text
        and "mount" in text
        and ("docker.proxy.sock" in text or "docker.sock" in text)
    ):
        return None
    return WorkspaceVerificationFeedbackItem(
        target_layer=WorkspaceVerificationFeedbackTargetLayer.WORKER,
        feedback_kind=WorkspaceVerificationFeedbackKind.PRODUCT_CODE_FAILURE,
        severity=WorkspaceVerificationFeedbackSeverity.BLOCKING,
        recommended_action=WorkspaceVerificationRecommendedAction.RETRY_WORKER,
        summary=(
            "Drone docker-deploy mounts the Docker socket file to `/var/run`, which is a "
            "directory. In `.drone.yml`, the deploy step volume must use `path: "
            "/var/run/docker.sock`; the top-level host volume remains `host.path: "
            "/var/run/docker.sock`."
        ),
        evidence_refs=(
            "drone_error:not_a_directory",
            "drone_socket_volume_path:/var/run",
        ),
        failure_signature="drone-docker-socket-mounted-to-var-run",
    )


def _drone_host_socket_dind_service_timeout_feedback(
    results: list[CriterionResult],
) -> WorkspaceVerificationFeedbackItem | None:
    text = "\n".join(result.message for result in results if result.message).lower()
    if not (
        "timed out" in text
        and "failing stage" in text
        and "/docker" in text
        and "exited 0" in text
    ):
        return None
    return WorkspaceVerificationFeedbackItem(
        target_layer=WorkspaceVerificationFeedbackTargetLayer.WORKER,
        feedback_kind=WorkspaceVerificationFeedbackKind.PRODUCT_CODE_FAILURE,
        severity=WorkspaceVerificationFeedbackSeverity.BLOCKING,
        recommended_action=WorkspaceVerificationRecommendedAction.RETRY_WORKER,
        summary=(
            "The Drone pipeline timed out while the service step named `docker` stayed "
            "running. In host-socket deploy mode, `.drone.yml` must not define a "
            "`docker:dind` service, a service named `docker`, privileged service settings, "
            "or `network_mode: host`; use only the mounted `/var/run/docker.sock` volume "
            "in the docker:cli deploy step."
        ),
        evidence_refs=(
            "drone_error:pipeline_timeout",
            "drone_service:docker",
        ),
        failure_signature="drone-host-socket-dind-service-timeout",
    )


def _drone_host_socket_registry_failure_feedback(
    results: list[CriterionResult],
) -> WorkspaceVerificationFeedbackItem | None:
    text = "\n".join(result.message for result in results if result.message).lower()
    if not (
        "server gave http response to https client" in text
        and "host.docker.internal" in text
        and ("docker pull" in text or "docker run" in text or "/v2/" in text)
    ):
        return None
    return WorkspaceVerificationFeedbackItem(
        target_layer=WorkspaceVerificationFeedbackTargetLayer.WORKER,
        feedback_kind=WorkspaceVerificationFeedbackKind.PRODUCT_CODE_FAILURE,
        severity=WorkspaceVerificationFeedbackSeverity.BLOCKING,
        recommended_action=WorkspaceVerificationRecommendedAction.RETRY_WORKER,
        summary=(
            "The deploy step uses `host.docker.internal:<port>` for docker pull/run through "
            "the host Docker daemon, so Docker treats the local insecure registry as HTTPS. "
            "Do not switch this daemon-side pull to localhost. Keep `host.docker.internal:<port>` "
            "for plugins/docker build/push, then build or load a deploy-local image tag in "
            "docker-deploy and run that local tag."
        ),
        evidence_refs=(
            "drone_error:http_response_to_https_client",
            "drone_deploy_registry:host.docker.internal",
        ),
        failure_signature="drone-host-socket-deploy-registry-host-internal",
    )


def _drone_host_socket_localhost_registry_timeout_feedback(
    results: list[CriterionResult],
) -> WorkspaceVerificationFeedbackItem | None:
    text = "\n".join(result.message for result in results if result.message).lower()
    has_localhost_registry = "localhost:" in text or "127.0.0.1:" in text
    has_registry_timeout = (
        "context deadline exceeded" in text
        or "client.timeout exceeded" in text
        or "request canceled while waiting for connection" in text
    )
    if not (
        has_localhost_registry
        and has_registry_timeout
        and ("docker pull" in text or "/v2/" in text)
    ):
        return None
    return WorkspaceVerificationFeedbackItem(
        target_layer=WorkspaceVerificationFeedbackTargetLayer.WORKER,
        feedback_kind=WorkspaceVerificationFeedbackKind.PRODUCT_CODE_FAILURE,
        severity=WorkspaceVerificationFeedbackSeverity.BLOCKING,
        recommended_action=WorkspaceVerificationRecommendedAction.RETRY_WORKER,
        summary=(
            "The deploy step uses `localhost:<port>` for docker pull through the mounted host "
            "Docker daemon, but that daemon cannot reach the local registry at localhost. "
            "Avoid daemon-side local-registry pulls; build or load a deploy-local image tag "
            "inside docker-deploy and run that local tag."
        ),
        evidence_refs=(
            "drone_error:localhost_registry_timeout",
            "drone_deploy_registry:localhost",
        ),
        failure_signature="drone-host-socket-localhost-registry-unreachable",
    )


def _drone_docker_host_port_conflict_feedback(
    results: list[CriterionResult],
) -> WorkspaceVerificationFeedbackItem | None:
    text = "\n".join(result.message for result in results if result.message).lower()
    if not (
        "docker run" in text
        and (
            "port is already allocated" in text
            or "bind for 0.0.0.0:" in text
            or "failed programming external connectivity" in text
        )
    ):
        return None
    return WorkspaceVerificationFeedbackItem(
        target_layer=WorkspaceVerificationFeedbackTargetLayer.WORKER,
        feedback_kind=WorkspaceVerificationFeedbackKind.PRODUCT_CODE_FAILURE,
        severity=WorkspaceVerificationFeedbackSeverity.BLOCKING,
        recommended_action=WorkspaceVerificationRecommendedAction.RETRY_WORKER,
        summary=(
            "The deploy step binds a host port already owned by platform infrastructure. "
            "Use docker.deploy_host_port from the workspace delivery context for the host "
            "side of `docker run -p`, keep the app's container port on the container side, "
            "and update the Drone health check to docker.deploy_health_url."
        ),
        evidence_refs=(
            "drone_error:docker_host_port_allocated",
            "drone_deploy:reserved_host_port",
        ),
        failure_signature="drone-docker-deploy-host-port-conflict",
    )


def _drone_docker_deploy_missing_health_probe_tool_feedback(
    results: list[CriterionResult],
) -> WorkspaceVerificationFeedbackItem | None:
    text = "\n".join(result.message for result in results if result.message).lower()
    if not (
        "failing stage" in text
        and "deploy" in text
        and (
            "curl: not found" in text
            or "/bin/sh: curl: not found" in text
            or "wget: not found" in text
            or "/bin/sh: wget: not found" in text
        )
    ):
        return None
    return WorkspaceVerificationFeedbackItem(
        target_layer=WorkspaceVerificationFeedbackTargetLayer.WORKER,
        feedback_kind=WorkspaceVerificationFeedbackKind.PRODUCT_CODE_FAILURE,
        severity=WorkspaceVerificationFeedbackSeverity.BLOCKING,
        recommended_action=WorkspaceVerificationRecommendedAction.RETRY_WORKER,
        summary=(
            "The deploy health probe uses a command unavailable in the Drone docker:cli "
            "step image. Use the workspace docker.deploy_health_check_command, or install "
            "the probe tool before using it, and print docker logs when the probe fails."
        ),
        evidence_refs=(
            "drone_error:health_probe_tool_missing",
            "drone_deploy:docker_cli_probe",
        ),
        failure_signature="drone-docker-deploy-missing-health-probe-tool",
    )


def _drone_docker_deploy_unhealthy_container_feedback(
    results: list[CriterionResult],
) -> WorkspaceVerificationFeedbackItem | None:
    text = "\n".join(result.message for result in results if result.message).lower()
    health_connection_failed = (
        "connection refused" in text
        or "can't connect to remote host" in text
        or "cannot connect to remote host" in text
        or "connection reset" in text
        or "no route to host" in text
    )
    has_health_probe = (
        "wget" in text
        or "curl" in text
        or "health" in text
        or "deployment_health:failed" in text
    )
    if not (
        "failing stage" in text
        and "deploy" in text
        and "docker run" in text
        and has_health_probe
        and health_connection_failed
    ):
        return None
    return WorkspaceVerificationFeedbackItem(
        target_layer=WorkspaceVerificationFeedbackTargetLayer.WORKER,
        feedback_kind=WorkspaceVerificationFeedbackKind.PRODUCT_CODE_FAILURE,
        severity=WorkspaceVerificationFeedbackSeverity.BLOCKING,
        recommended_action=WorkspaceVerificationRecommendedAction.RETRY_WORKER,
        summary=(
            "The deploy step starts a container, but the host-mapped health probe cannot "
            "connect. The worker must surface container logs and make the deploy self-contained "
            "by wiring required runtime dependencies such as PostgreSQL or Redis through compose "
            "or sidecar containers when no external service is configured."
        ),
        evidence_refs=(
            "drone_error:deploy_health_connection_refused",
            "drone_deploy:container_unhealthy",
        ),
        failure_signature="drone-docker-deploy-unhealthy-container",
    )


def _drone_docker_deploy_container_name_conflict_feedback(
    results: list[CriterionResult],
) -> WorkspaceVerificationFeedbackItem | None:
    text = "\n".join(result.message for result in results if result.message).lower()
    has_container_conflict = (
        "container name" in text
        and (
            "already in use" in text
            or "you have to remove (or rename)" in text
            or "conflict. the container name" in text
        )
    )
    if not ("failing stage" in text and "deploy" in text and has_container_conflict):
        return None
    return WorkspaceVerificationFeedbackItem(
        target_layer=WorkspaceVerificationFeedbackTargetLayer.WORKER,
        feedback_kind=WorkspaceVerificationFeedbackKind.PRODUCT_CODE_FAILURE,
        severity=WorkspaceVerificationFeedbackSeverity.BLOCKING,
        recommended_action=WorkspaceVerificationRecommendedAction.RETRY_WORKER,
        summary=(
            "The deploy step reuses fixed Docker container names without removing stale app or "
            "dependency containers from previous failed attempts."
        ),
        evidence_refs=(
            "drone_error:deploy_container_name_conflict",
            "drone_deploy:retry_cleanup",
        ),
        failure_signature="drone-docker-deploy-container-name-conflict",
    )


def _drone_docker_deploy_postgres_sidecar_env_feedback(
    results: list[CriterionResult],
) -> WorkspaceVerificationFeedbackItem | None:
    text = "\n".join(result.message for result in results if result.message).lower()
    postgres_env_failure = (
        "postgres_password" in text
        and (
            "superuser password is not specified" in text
            or "must specify postgres_password" in text
            or "postgres:16-alpine -c postgres_password" in text
        )
    )
    if not ("failing stage" in text and "deploy" in text and postgres_env_failure):
        return None
    return WorkspaceVerificationFeedbackItem(
        target_layer=WorkspaceVerificationFeedbackTargetLayer.WORKER,
        feedback_kind=WorkspaceVerificationFeedbackKind.PRODUCT_CODE_FAILURE,
        severity=WorkspaceVerificationFeedbackSeverity.BLOCKING,
        recommended_action=WorkspaceVerificationRecommendedAction.RETRY_WORKER,
        summary=(
            "The PostgreSQL deploy sidecar exited because POSTGRES_* initialization values "
            "were not passed as docker run environment variables before the image."
        ),
        evidence_refs=(
            "drone_error:postgres_sidecar_env_missing",
            "drone_deploy:dependency_sidecar",
        ),
        failure_signature="drone-docker-deploy-postgres-sidecar-env",
    )


def _drone_docker_deploy_missing_build_artifact_feedback(
    results: list[CriterionResult],
) -> WorkspaceVerificationFeedbackItem | None:
    text = "\n".join(result.message for result in results if result.message).lower()
    missing_node_artifact = (
        "cannot find module" in text
        and (
            "/app/dist/" in text
            or "dist/index.js" in text
            or "module_not_found" in text
        )
    )
    if not ("failing stage" in text and "deploy" in text and missing_node_artifact):
        return None
    return WorkspaceVerificationFeedbackItem(
        target_layer=WorkspaceVerificationFeedbackTargetLayer.WORKER,
        feedback_kind=WorkspaceVerificationFeedbackKind.PRODUCT_CODE_FAILURE,
        severity=WorkspaceVerificationFeedbackSeverity.BLOCKING,
        recommended_action=WorkspaceVerificationRecommendedAction.RETRY_WORKER,
        summary=(
            "The deployed image starts with a command that references a missing build artifact "
            "such as /app/dist/index.js. The worker must keep existing deploy fixes while adding "
            "a real build step before Docker image creation or moving the build into Dockerfile."
        ),
        evidence_refs=(
            "drone_error:deploy_missing_build_artifact",
            "drone_deploy:image_startup",
        ),
        failure_signature="drone-docker-deploy-missing-build-artifact",
    )


def _drone_docker_deploy_runtime_env_failure_feedback(
    results: list[CriterionResult],
) -> WorkspaceVerificationFeedbackItem | None:
    missing_fields = _missing_runtime_config_fields(results)
    runtime_field_guidance = _runtime_config_field_guidance(missing_fields)
    text = "\n".join(result.message for result in results if result.message).lower()
    has_runtime_env_failure = any(
        marker in text
        for marker in (
            "environment variable not found",
            "node_secret is required",
            "session_secret is required",
            "prisma schema validation",
            "error code: p1012",
            "error: p1001",
            "can't reach database server",
            "cannot reach database server",
            "failed to deserialize constructor options",
            "constructoroptions",
            "missing field",
        )
    ) or bool(missing_fields)
    if not ("failing stage" in text and "deploy" in text and has_runtime_env_failure):
        return None
    return WorkspaceVerificationFeedbackItem(
        target_layer=WorkspaceVerificationFeedbackTargetLayer.WORKER,
        feedback_kind=WorkspaceVerificationFeedbackKind.PRODUCT_CODE_FAILURE,
        severity=WorkspaceVerificationFeedbackSeverity.BLOCKING,
        recommended_action=WorkspaceVerificationRecommendedAction.RETRY_WORKER,
        summary=(
            "The deployed container starts without required runtime environment or dependent "
            "services. Inspect Dockerfile, compose files, .env examples, and startup logs; "
            "pass required environment variables and use docker compose or sidecar containers "
            "to start dependencies when no external service is configured. "
            f"{runtime_field_guidance}"
        ),
        evidence_refs=(
            "drone_error:deploy_runtime_env_missing",
            "drone_deploy:container_startup",
        ),
        failure_signature="drone-docker-deploy-missing-runtime-env",
    )


def _missing_runtime_config_fields(results: list[CriterionResult]) -> tuple[str, ...]:
    text = "\n".join(result.message for result in results if result.message)
    matches = re.findall(r"missing field [`'\"]?([A-Za-z_][A-Za-z0-9_]*)[`'\"]?", text)
    return tuple(dict.fromkeys(matches))


def _runtime_config_field_guidance(fields: tuple[str, ...]) -> str:
    if not fields:
        return ""
    quoted = ", ".join(f"`{field}`" for field in fields)
    examples = []
    if "enableTracing" in fields:
        examples.append("`-e enableTracing=false`")
    example_text = f" For example, pass {', '.join(examples)}." if examples else ""
    return (
        f"Startup logs named required config field(s) {quoted}; preserve the exact spelling "
        "when passing config into the container or update startup/config code to map the "
        "environment variable before constructing the client. Do not assume an uppercase "
        f"underscore variable satisfies a camelCase field unless code explicitly maps it.{example_text} "
    )


def _drone_docker_build_timeout_feedback(
    results: list[CriterionResult],
) -> WorkspaceVerificationFeedbackItem | None:
    text = "\n".join(result.message for result in results if result.message).lower()
    stopped_by_timeout_or_kill = (
        "timed out" in text
        or "finished with status killed" in text
        or "status killed" in text
    )
    if not (
        stopped_by_timeout_or_kill
        and "failing stage" in text
        and "docker-build" in text
        and ("exited 137" in text or "exit 137" in text or "sigkill" in text)
    ):
        return None
    return WorkspaceVerificationFeedbackItem(
        target_layer=WorkspaceVerificationFeedbackTargetLayer.WORKER,
        feedback_kind=WorkspaceVerificationFeedbackKind.PRODUCT_CODE_FAILURE,
        severity=WorkspaceVerificationFeedbackSeverity.BLOCKING,
        recommended_action=WorkspaceVerificationRecommendedAction.RETRY_WORKER,
        summary=(
            "Drone timed out in the `docker-build` stage before deploy could run. The worker "
            "must shrink Docker build context with `.dockerignore`, align Dockerfile Node "
            "version with package engine requirements, and avoid deploy fallbacks that rebuild "
            "the whole repository context."
        ),
        evidence_refs=(
            "drone_error:docker_build_timeout_137",
            "drone_stage:docker-build",
        ),
        failure_signature="drone-docker-build-timeout-context-or-node",
    )


def _judge_satisfied_required_guard(
    result: WorkspaceVerificationJudgeResult,
    name: str,
) -> bool:
    return name in set(result.satisfied_guard_failures)


def _required_guard_failed(results: list[CriterionResult], name: str) -> bool:
    return any(
        result.criterion.required
        and not result.passed
        and result.criterion.spec.get("name") == name
        for result in results
    )


def _has_current_terminal_worker_report(ctx: VerificationContext) -> bool:
    report_type = _artifact_text(ctx, "last_worker_report_type")
    if report_type not in _TERMINAL_WORKER_REPORT_TYPES:
        return False
    report_attempt_id = _artifact_text(ctx, "last_worker_report_attempt_id") or _artifact_text(
        ctx,
        "last_attempt_id",
    )
    return not (ctx.attempt_id and report_attempt_id and report_attempt_id != ctx.attempt_id)


def _normalize_results_for_judge(
    results: list[CriterionResult],
    judge_result: WorkspaceVerificationJudgeResult,
) -> list[CriterionResult]:
    normalized: list[CriterionResult] = []
    for result in results:
        if result.passed or not result.criterion.required:
            normalized.append(result)
            continue
        if judge_result.verdict is WorkspaceVerificationJudgeVerdict.ACCEPTED:
            normalized.append(
                replace(
                    result,
                    criterion=replace(result.criterion, required=False),
                    message=f"advisory evidence before judge acceptance: {result.message}",
                )
            )
            continue
        if judge_result.verdict is not WorkspaceVerificationJudgeVerdict.BLOCKED_HUMAN_REQUIRED:
            normalized.append(replace(result, confidence=min(result.confidence, 0.7)))
            continue
        normalized.append(result)
    return normalized


def _judge_criterion_result(result: WorkspaceVerificationJudgeResult) -> CriterionResult:
    verdict = result.verdict
    criterion_name = (
        "retryable_infrastructure_failure"
        if verdict is WorkspaceVerificationJudgeVerdict.RETRY_INFRASTRUCTURE
        else "workspace_verification_judge"
    )
    confidence = result.confidence
    if verdict is WorkspaceVerificationJudgeVerdict.BLOCKED_HUMAN_REQUIRED:
        confidence = max(confidence, 0.9)
    elif verdict in {
        WorkspaceVerificationJudgeVerdict.NEEDS_REWORK,
        WorkspaceVerificationJudgeVerdict.RETRY_INFRASTRUCTURE,
    }:
        confidence = min(confidence, 0.7)
    message_parts = [f"judge verdict={verdict.value}", result.rationale]
    if result.required_next_action:
        message_parts.append(f"next_action={result.required_next_action}")
    message_parts.append(f"next_action_kind={result.next_action_kind.value}")
    if result.failed_criteria:
        message_parts.append("failed=" + ", ".join(result.failed_criteria[:8]))
    if result.satisfied_guard_failures:
        message_parts.append("satisfied_guards=" + ", ".join(result.satisfied_guard_failures[:8]))
    if result.feedback_items:
        targets = sorted({item.target_layer.value for item in result.feedback_items})
        message_parts.append("feedback_targets=" + ", ".join(targets[:6]))
    return CriterionResult(
        criterion=AcceptanceCriterion(
            kind=CriterionKind.CUSTOM,
            spec={
                "name": criterion_name,
                "judge_verdict": verdict.value,
                "failed_criteria": list(result.failed_criteria),
                "satisfied_guard_failures": list(result.satisfied_guard_failures),
                "required_next_action": result.required_next_action,
                "next_action_kind": result.next_action_kind.value,
                "repair_brief": result.repair_brief,
                "feedback_items": [item.to_payload() for item in result.feedback_items],
            },
            required=True,
            description="Agent-First workspace verification judge verdict",
        ),
        passed=verdict is WorkspaceVerificationJudgeVerdict.ACCEPTED,
        confidence=confidence,
        message="; ".join(part for part in message_parts if part),
        evidence=(
            EvidenceRef(
                kind="verification_judge",
                ref=verdict.value,
                note=_bounded_text(result.rationale, limit=300),
            ),
        ),
    )


def _terminal_worker_report_guard(ctx: VerificationContext) -> CriterionResult | None:  # noqa: PLR0911
    """Prevent stale or blocked worker reports from satisfying weak criteria."""

    criterion = AcceptanceCriterion(
        kind=CriterionKind.CUSTOM,
        spec={"name": "terminal_worker_report_completed"},
        required=True,
        description="terminal worker report must be completed before durable verification can pass",
    )
    report_type = _artifact_text(ctx, "last_worker_report_type")
    report_attempt_id = _artifact_text(ctx, "last_worker_report_attempt_id") or _artifact_text(
        ctx, "last_attempt_id"
    )
    attempt_status = _artifact_text(ctx, "last_attempt_status")
    report_summary = _artifact_text(ctx, "last_worker_report_summary")

    if ctx.attempt_id and report_attempt_id and report_attempt_id != ctx.attempt_id:
        return CriterionResult(
            criterion=criterion,
            passed=False,
            confidence=1.0,
            message=(
                "worker report belongs to attempt "
                f"{report_attempt_id!r}, not current attempt {ctx.attempt_id!r}"
            ),
        )
    if report_type and report_type != "completed":
        detail = f": {report_summary[:500]}" if report_type == "blocked" and report_summary else ""
        return CriterionResult(
            criterion=criterion,
            passed=False,
            confidence=1.0,
            message=f"worker report type {report_type!r} is not a completion report{detail}",
        )
    if attempt_status in {"blocked", "cancelled", "rejected"}:
        if ctx.attempt_id is None and _has_pipeline_success_evidence(ctx):
            return None
        return CriterionResult(
            criterion=criterion,
            passed=False,
            confidence=1.0,
            message=f"attempt status {attempt_status!r} cannot pass durable verification",
        )
    if report_type == "completed":
        return CriterionResult(
            criterion=criterion,
            passed=True,
            confidence=1.0,
            message="worker report completed",
        )
    if _requires_terminal_worker_report(ctx):
        return CriterionResult(
            criterion=criterion,
            passed=False,
            confidence=1.0,
            message="missing completed worker report",
        )
    return None


def _terminal_worker_report_results(ctx: VerificationContext) -> tuple[CriterionResult, ...]:
    terminal_guard = _terminal_worker_report_guard(ctx)
    return (terminal_guard,) if terminal_guard is not None else ()


def _preflight_evidence_guard(ctx: VerificationContext) -> CriterionResult | None:
    """Require structured evidence for each required harness preflight check."""

    required_check_ids = _required_preflight_check_ids(ctx)
    if not required_check_ids:
        return None

    criterion = AcceptanceCriterion(
        kind=CriterionKind.CUSTOM,
        spec={"name": "preflight_evidence_recorded"},
        required=True,
        description="required preflight checks must be evidenced before durable verification",
    )
    evidence = _structured_verification_evidence(ctx)
    missing = [
        check_id
        for check_id in required_check_ids
        if not _has_structured_verification_ref(evidence, f"preflight:{check_id}")
    ]
    if missing:
        return CriterionResult(
            criterion=criterion,
            passed=False,
            confidence=1.0,
            message=f"missing preflight evidence: {', '.join(missing)}",
        )
    return CriterionResult(
        criterion=criterion,
        passed=True,
        confidence=1.0,
        message="preflight evidence recorded",
        evidence=tuple(
            EvidenceRef(kind="verification", ref=f"preflight:{check_id}")
            for check_id in required_check_ids
        ),
    )


def _feature_checkpoint_evidence_guard(ctx: VerificationContext) -> CriterionResult | None:
    feature = ctx.node.feature_checkpoint
    write_refs = _required_change_refs(ctx)
    test_commands = _required_test_commands(ctx)
    if feature is None or (not write_refs and not test_commands):
        return None

    criterion = AcceptanceCriterion(
        kind=CriterionKind.CUSTOM,
        spec={"name": "feature_checkpoint_evidence_recorded"},
        required=True,
        description="feature checkpoint requires git/test evidence before acceptance",
    )
    evidence_values = _attempt_scoped_artifact_text_values(
        ctx,
        "evidence_refs",
        "last_worker_report_artifacts",
        "candidate_artifacts",
        "execution_verifications",
        "last_worker_report_verifications",
        "candidate_verifications",
    )

    missing: list[str] = []
    git_evidence = _first_prefixed(evidence_values, "commit_ref:") or _first_prefixed(
        evidence_values,
        "git_diff_summary:",
    )
    if write_refs and not git_evidence:
        missing.append("commit_ref or git_diff_summary")
    test_evidence = _first_prefixed(evidence_values, "test_run:")
    if test_commands and not test_evidence:
        missing.append("test_run evidence")
    if missing:
        return CriterionResult(
            criterion=criterion,
            passed=False,
            confidence=1.0,
            message=f"missing feature checkpoint evidence: {', '.join(missing)}",
        )

    refs = [
        value
        for value in evidence_values
        if value.startswith(("commit_ref:", "git_diff_summary:", "test_run:"))
    ]
    return CriterionResult(
        criterion=criterion,
        passed=True,
        confidence=1.0,
        message="feature checkpoint evidence recorded",
        evidence=tuple(EvidenceRef(kind="checkpoint", ref=value) for value in refs),
    )


def _failed_test_evidence_guard(ctx: VerificationContext) -> CriterionResult | None:
    if ctx.node.metadata.get("allow_failed_tests") is True:
        return None
    has_contract_disposition = _has_failed_test_contract_disposition(ctx)
    values = _attempt_scoped_artifact_text_values(
        ctx,
        "evidence_refs",
        "last_worker_report_artifacts",
        "last_worker_report_verifications",
        "candidate_artifacts",
        "candidate_verifications",
        "execution_verifications",
    )
    failed_value = next(
        (
            value
            for value in sorted(values)
            if any(pattern.search(value) for pattern in _FAILED_TEST_EVIDENCE_PATTERNS)
        ),
        None,
    )
    if failed_value is None:
        failed_value = _failed_test_summary_value(_artifact_text(ctx, "last_worker_report_summary"))
    if failed_value is None:
        failed_value = _partial_test_summary_value_from_context(ctx)
    if failed_value is None or has_contract_disposition:
        return None
    criterion = AcceptanceCriterion(
        kind=CriterionKind.CUSTOM,
        spec={"name": "failed_test_evidence"},
        required=True,
        description="completed worker reports must not include failing test evidence",
    )
    return CriterionResult(
        criterion=criterion,
        passed=False,
        confidence=1.0,
        message=f"test evidence reports failing tests: {_bounded_text(failed_value, limit=360)}",
        evidence=(EvidenceRef(kind="verification", ref=_bounded_text(failed_value, limit=500)),),
    )


def _missing_test_execution_evidence_guard(ctx: VerificationContext) -> CriterionResult | None:
    value = _missing_test_execution_evidence_value(ctx)
    if value is None:
        return None
    criterion = AcceptanceCriterion(
        kind=CriterionKind.CUSTOM,
        spec={"name": "missing_test_execution_evidence"},
        required=True,
        description="completed worker reports must not claim verification totals without running tests",
    )
    return CriterionResult(
        criterion=criterion,
        passed=False,
        confidence=1.0,
        message=f"test execution evidence missing: {_bounded_text(value, limit=360)}",
        evidence=(EvidenceRef(kind="verification", ref=_bounded_text(value, limit=500)),),
    )


def _missing_test_execution_evidence_value(ctx: VerificationContext) -> str | None:
    values = _attempt_scoped_artifact_text_values(
        ctx,
        "evidence_refs",
        "last_worker_report_artifacts",
        "last_worker_report_verifications",
        "candidate_artifacts",
        "candidate_verifications",
        "execution_verifications",
    )
    summary = _artifact_text(ctx, "last_worker_report_summary")
    if summary:
        values.add(summary)
    return next(
        (
            value
            for value in sorted(values)
            if value.strip().casefold().startswith(_MISSING_TEST_EXECUTION_DISPOSITION_PREFIXES)
        ),
        None,
    )


def _partial_test_summary_value_from_context(ctx: VerificationContext) -> str | None:
    values = _attempt_scoped_artifact_text_values(
        ctx,
        "evidence_refs",
        "last_worker_report_artifacts",
        "last_worker_report_verifications",
        "candidate_artifacts",
        "candidate_verifications",
        "execution_verifications",
    )
    values.add(_artifact_text(ctx, "last_worker_report_summary"))
    if not ctx.attempt_id:
        values.add(ctx.node.title)
        values.add(ctx.node.description)
    for value in sorted(item for item in values if item):
        partial = _partial_test_summary_value(value)
        if partial:
            return partial
    return None


def _partial_test_summary_value(text: str) -> str | None:
    if not text:
        return None
    for line in text.splitlines():
        value = line.strip()
        if not value or not _PARTIAL_TEST_SUMMARY_CUE_PATTERN.search(value):
            continue
        if _PARTIAL_TEST_BUCKET_PATTERN.search(value):
            return value
        for match in _PARTIAL_TEST_SUMMARY_PATTERN.finditer(value):
            passed = int(match.group(1))
            total = int(match.group(2))
            if total > 0 and passed < total:
                return value
    return None


def _has_failed_test_contract_disposition(ctx: VerificationContext) -> bool:
    values = _attempt_scoped_artifact_text_values(
        ctx,
        "last_worker_report_artifacts",
        "last_worker_report_verifications",
        "candidate_artifacts",
        "candidate_verifications",
        "execution_verifications",
    )
    return any(
        value.strip().casefold().startswith(_FAILED_TEST_DISPOSITION_PREFIXES) for value in values
    )


def _failed_test_summary_value(summary: str) -> str | None:
    if not summary:
        return None
    for line in summary.splitlines():
        value = line.strip()
        if not value:
            continue
        if not any(pattern.search(value) for pattern in _FAILED_TEST_EVIDENCE_PATTERNS):
            continue
        if _summary_line_reports_current_failed_tests(value):
            return value
    return None


def _summary_line_reports_current_failed_tests(value: str) -> bool:
    if not _CURRENT_TEST_FAILURE_CUE_PATTERN.search(value):
        return False
    failed_match = next(
        (
            pattern.search(value)
            for pattern in _FAILED_TEST_EVIDENCE_PATTERNS
            if pattern.search(value)
        ),
        None,
    )
    if failed_match is None:
        return False
    prefix = value[: failed_match.start()]
    return not _HISTORICAL_FAILURE_CUE_PATTERN.search(prefix)


async def _verification_script_mutation_guard(ctx: VerificationContext) -> CriterionResult | None:
    """Protect verification/review nodes from passing by weakening the evidence contract."""

    if ctx.node.metadata.get("allow_verification_script_changes") is True:
        return None
    if _node_iteration_phase(ctx) not in _VERIFICATION_INTEGRITY_PHASES:
        return None
    git_root = _clean_worktree_git_root(ctx)
    if ctx.sandbox is None or not git_root:
        return None

    changed_paths = await _changed_paths_for_verification_guard(ctx, git_root)
    script_paths = sorted(path for path in changed_paths if _is_verification_script_path(path))
    if not script_paths:
        return None

    criterion = AcceptanceCriterion(
        kind=CriterionKind.CUSTOM,
        spec={"name": "verification_script_mutation"},
        required=True,
        description="verification/review nodes must not weaken their own evidence scripts",
    )
    preview = "; ".join(script_paths[:8])
    if len(script_paths) > 8:
        preview += f"; +{len(script_paths) - 8} more"
    return CriterionResult(
        criterion=criterion,
        passed=False,
        confidence=0.9,
        message=(
            "verification/review node changed test or audit scripts without an explicit "
            f"allow_verification_script_changes contract: {preview}"
        ),
        evidence=tuple(EvidenceRef(kind="changed_file", ref=path) for path in script_paths[:8]),
    )


async def _changed_paths_for_verification_guard(
    ctx: VerificationContext,
    git_root: str,
) -> set[str]:
    paths: set[str] = set()
    paths.update(await _git_status_changed_paths(ctx, git_root))
    for commit_ref in _reported_commit_refs(ctx):
        paths.update(await _git_commit_changed_paths(ctx, git_root, commit_ref))
    paths.update(_reported_changed_paths(ctx))
    return paths


async def _git_status_changed_paths(ctx: VerificationContext, git_root: str) -> set[str]:
    command = f"git -C {shlex.quote(git_root)} status --short"
    try:
        result = await ctx.sandbox.run_command(command, timeout=15) if ctx.sandbox else {}
    except Exception:
        return set()
    if int(result.get("exit_code", 1)) != 0:
        return set()
    return _parse_git_status_paths(str(result.get("stdout", "")))


async def _git_commit_changed_paths(
    ctx: VerificationContext,
    git_root: str,
    commit_ref: str,
) -> set[str]:
    command = (
        f"git -C {shlex.quote(git_root)} diff-tree --no-commit-id "
        f"--name-status -r --root {shlex.quote(commit_ref)}"
    )
    try:
        result = await ctx.sandbox.run_command(command, timeout=20) if ctx.sandbox else {}
    except Exception:
        return set()
    if int(result.get("exit_code", 1)) != 0:
        return set()
    return _parse_name_status_paths(str(result.get("stdout", "")))


def _reported_commit_refs(ctx: VerificationContext) -> list[str]:
    values = _attempt_scoped_artifact_text_sequence(
        ctx,
        "evidence_refs",
        "last_worker_report_artifacts",
        "candidate_artifacts",
        "execution_verifications",
        "last_worker_report_verifications",
        "candidate_verifications",
    )
    refs: list[str] = []
    for value in values:
        if not value.startswith("commit_ref:"):
            continue
        ref = value.removeprefix("commit_ref:").strip().split(maxsplit=1)[0]
        if ref:
            refs.append(ref)
    latest_first: list[str] = []
    seen: set[str] = set()
    for ref in reversed(refs):
        if ref in seen:
            continue
        latest_first.append(ref)
        seen.add(ref)
    return latest_first[:4]


def _reported_changed_paths(ctx: VerificationContext) -> set[str]:
    values = _attempt_scoped_artifact_text_values(
        ctx,
        "evidence_refs",
        "last_worker_report_artifacts",
        "candidate_artifacts",
        "execution_verifications",
        "last_worker_report_verifications",
        "candidate_verifications",
    )
    paths: set[str] = set()
    for value in values:
        normalized = value.strip()
        if not normalized.startswith("changed_file:"):
            continue
        paths.update(_extract_path_like_tokens(normalized.removeprefix("changed_file:")))
    return paths


def _parse_git_status_paths(stdout: str) -> set[str]:
    paths: set[str] = set()
    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        payload = line[2:].strip() if len(line) > 2 else line
        if " -> " in payload:
            payload = payload.rsplit(" -> ", 1)[1].strip()
        if payload:
            paths.add(payload)
    return paths


def _parse_name_status_paths(stdout: str) -> set[str]:
    paths: set[str] = set()
    for raw_line in stdout.splitlines():
        parts = raw_line.strip().split("\t")
        if len(parts) >= 2:
            paths.add(parts[-1])
    return paths


def _extract_path_like_tokens(value: str) -> set[str]:
    paths: set[str] = set()
    for token in re.split(r"[\s,;]+", value):
        cleaned = token.strip("`'\"()[]{}:")
        if "/" not in cleaned and "." not in cleaned:
            continue
        if _is_verification_script_path(cleaned):
            paths.add(cleaned)
    return paths


def _is_verification_script_path(path: str) -> bool:
    normalized = path.replace("\\", "/").lstrip("./")
    if not normalized:
        return False
    if normalized.startswith(_VERIFICATION_OUTPUT_PATH_PREFIXES):
        return False
    return bool(_VERIFICATION_SCRIPT_NAME_PATTERN.search(normalized))


async def _clean_worktree_after_commit_guard(  # noqa: PLR0911
    ctx: VerificationContext,
) -> CriterionResult | None:
    """When a checkpoint reports a commit, ensure no extra changes were left behind."""

    if ctx.sandbox is None:
        return None

    evidence_values = _attempt_scoped_artifact_text_values(
        ctx,
        "evidence_refs",
        "last_worker_report_artifacts",
        "candidate_artifacts",
        "execution_verifications",
        "last_worker_report_verifications",
        "candidate_verifications",
    )
    if not _should_check_clean_worktree(ctx, evidence_values):
        return None

    criterion = AcceptanceCriterion(
        kind=CriterionKind.CUSTOM,
        spec={"name": "clean_worktree_after_commit"},
        required=True,
        description="committed feature checkpoints must not leave uncommitted changes",
    )
    git_root = _clean_worktree_git_root(ctx)
    if not git_root:
        suffix = " after pipeline success" if _has_pipeline_success_evidence(ctx) else ""
        return CriterionResult(
            criterion=criterion,
            passed=True,
            confidence=0.4,
            message=f"clean worktree check skipped: code root unavailable{suffix}",
        )
    command = f"git -C {shlex.quote(git_root)} status --short"
    try:
        result = await ctx.sandbox.run_command(command, timeout=15)
    except Exception as exc:
        return CriterionResult(
            criterion=criterion,
            passed=True,
            confidence=0.4,
            message=f"clean worktree check skipped: {exc}",
        )

    exit_code = int(result.get("exit_code", 1))
    stdout = _normalize_sandbox_no_output_text(str(result.get("stdout", "")))
    stderr = str(result.get("stderr", "")).strip()
    if exit_code != 0:
        return CriterionResult(
            criterion=criterion,
            passed=False,
            confidence=0.9,
            message=f"git status failed: {stderr or stdout or exit_code}",
        )
    if stdout:
        preview = stdout.replace("\n", "; ")[:300]
        return CriterionResult(
            criterion=criterion,
            passed=False,
            confidence=1.0,
            message=f"uncommitted changes remain after commit_ref: {preview}",
            evidence=(EvidenceRef(kind="git_status", ref=stdout[:2000], note=command),),
        )
    return CriterionResult(
        criterion=criterion,
        passed=True,
        confidence=1.0,
        message="clean worktree after commit",
    )


def _should_check_clean_worktree(ctx: VerificationContext, evidence_values: set[str]) -> bool:
    if _required_change_refs(ctx):
        return _first_prefixed(evidence_values, "commit_ref:") is not None
    if not ctx.attempt_id:
        return False
    # Repair/test nodes may not declare a write_set, but a worker can still report
    # a commit/checkpoint. In that case, provide current git-status evidence so the
    # judge does not reason from stale repair descriptions.
    return _first_prefixed(evidence_values, "commit_ref:") is not None


async def _pipeline_gate_guard(ctx: VerificationContext) -> CriterionResult | None:
    if not _requires_pipeline_gate(ctx):
        return None
    pipeline_criterion = AcceptanceCriterion(
        kind=CriterionKind.CI_PIPELINE,
        spec={},
        required=True,
        description="software workspace tasks require harness-native CI/CD evidence",
    )
    pipeline_result = await PipelineCriterionRunner().run(pipeline_criterion, ctx)
    if not pipeline_result.passed:
        return pipeline_result

    phase = _node_iteration_phase(ctx)
    if phase in {"deploy", "review"}:
        health_criterion = AcceptanceCriterion(
            kind=CriterionKind.DEPLOYMENT_HEALTH,
            spec={},
            required=True,
            description="deploy/review tasks require a healthy sandbox preview deployment",
        )
        health_result = await DeploymentHealthCriterionRunner().run(health_criterion, ctx)
        if not health_result.passed:
            return health_result
    return pipeline_result


def _requires_pipeline_gate(ctx: VerificationContext) -> bool:
    raw_required = ctx.node.metadata.get("pipeline_required")
    if isinstance(raw_required, bool):
        return raw_required
    return False


def _node_iteration_phase(ctx: VerificationContext) -> str | None:
    raw_phase = ctx.node.metadata.get("iteration_phase")
    return raw_phase.strip().lower() if isinstance(raw_phase, str) and raw_phase.strip() else None


def _required_change_refs(ctx: VerificationContext) -> set[str]:
    refs: set[str] = set()
    feature = ctx.node.feature_checkpoint
    phase = _node_iteration_phase(ctx)
    if feature is not None and (phase is None or phase in _CHANGE_EVIDENCE_PHASES):
        refs.update(str(item) for item in feature.expected_artifacts if item)
    raw_write_set = ctx.node.metadata.get("write_set")
    if isinstance(raw_write_set, list):
        refs.update(str(item) for item in raw_write_set if item)
    return refs


def _required_test_commands(ctx: VerificationContext) -> list[str]:
    commands: list[str] = []
    feature = ctx.node.feature_checkpoint
    if feature is not None:
        commands.extend(str(command) for command in feature.test_commands if command)
    raw_commands = ctx.node.metadata.get("verification_commands")
    if isinstance(raw_commands, list):
        commands.extend(str(command) for command in raw_commands if command)
    return list(dict.fromkeys(commands))


def _required_preflight_check_ids(ctx: VerificationContext) -> list[str]:
    raw_checks = ctx.node.metadata.get("preflight_checks")
    if not isinstance(raw_checks, list):
        return []
    check_ids: list[str] = []
    for raw_check in raw_checks:
        if not isinstance(raw_check, dict):
            continue
        check_id = raw_check.get("check_id")
        if not isinstance(check_id, str) or not check_id:
            continue
        if raw_check.get("required", True) is False:
            continue
        check_ids.append(check_id)
    return list(dict.fromkeys(check_ids))


def _structured_verification_evidence(ctx: VerificationContext) -> set[str]:
    evidence: set[str] = set()
    for key in (
        "execution_verifications",
        "last_worker_report_verifications",
        "candidate_verifications",
    ):
        raw_values = ctx.artifacts.get(key)
        if not isinstance(raw_values, list):
            continue
        evidence.update(str(value) for value in raw_values if value)
    return evidence


def _pipeline_evidence_values(ctx: VerificationContext) -> set[str]:
    return _artifact_text_values(
        ctx,
        "pipeline_evidence_refs",
        "pipeline_evidence",
        "delivery_evidence_refs",
        "evidence_refs",
        "execution_verifications",
        "last_worker_report_artifacts",
        "last_worker_report_verifications",
        "candidate_artifacts",
        "candidate_verifications",
    )


def _has_pipeline_success_evidence(ctx: VerificationContext) -> bool:
    if _stale_pipeline_result_for_current_report(ctx) is not None:
        return False
    values = _pipeline_evidence_values(ctx)
    return (
        "ci_pipeline:passed" in values
        or _first_prefixed(values, "pipeline_run:success:") is not None
    )


def _has_pipeline_failure_evidence(ctx: VerificationContext) -> bool:
    if _stale_pipeline_result_for_current_report(ctx) is not None:
        return False
    values = _pipeline_evidence_values(ctx)
    return (
        "ci_pipeline:failed" in values
        or _first_prefixed(values, "pipeline_run:failed:") is not None
    )


def _pipeline_failure_message(ctx: VerificationContext) -> str:
    summary = str(
        ctx.node.metadata.get("pipeline_failure_summary")
        or ctx.artifacts.get("pipeline_failure_summary")
        or ctx.node.metadata.get("pipeline_last_summary")
        or ctx.artifacts.get("pipeline_last_summary")
        or ""
    ).strip()
    if not summary:
        return "harness-native CI pipeline failed; route through recovery"
    return (
        "harness-native CI pipeline failed: "
        f"{_bounded_text(summary, limit=2000)}; route through recovery"
    )


def _current_pipeline_status(ctx: VerificationContext) -> str | None:
    if _stale_pipeline_result_for_current_report(ctx) is not None:
        return None
    for key in ("pipeline_status", "pipeline_gate_status"):
        value = str(ctx.node.metadata.get(key) or "").strip().lower()
        if value in {"success", "failed"}:
            return value
    return None


_STALE_PIPELINE_METADATA_KEYS = frozenset(
    {
        "deploy_validation",
        "deployment_status",
        "external_id",
        "external_provider",
        "external_url",
        "pipeline_evidence_refs",
        "pipeline_failed_stage",
        "pipeline_failure_summary",
        "pipeline_gate_status",
        "pipeline_last_summary",
        "pipeline_run_id",
        "pipeline_status",
    }
)


def _stale_pipeline_result_for_current_report(ctx: VerificationContext) -> tuple[str, str] | None:
    reported_commit = _current_report_commit_ref(ctx)
    if not reported_commit:
        return None
    pipeline_commit = _pipeline_result_commit_ref(ctx)
    if not pipeline_commit:
        return None
    if _commit_refs_match(reported_commit, pipeline_commit):
        return None
    return reported_commit, pipeline_commit


def _current_report_commit_ref(ctx: VerificationContext) -> str | None:
    refs = _reported_commit_refs(ctx)
    return refs[0] if refs else None


def _pipeline_result_commit_ref(ctx: VerificationContext) -> str | None:
    for key in (
        "source_publish_source_commit_ref",
        "source_publish_commit_ref",
        "pipeline_commit_ref",
        "pipeline_run_commit_ref",
        "verified_commit_ref",
    ):
        value = _commit_ref_token(ctx.node.metadata.get(key))
        if value:
            return value
        value = _commit_ref_token(ctx.artifacts.get(key))
        if value:
            return value
    return None


def _commit_ref_token(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    token = value.strip().split(maxsplit=1)[0]
    return token or None


def _commit_refs_match(left: str, right: str) -> bool:
    left_ref = left.strip()
    right_ref = right.strip()
    if not left_ref or not right_ref:
        return False
    if left_ref == right_ref:
        return True
    short_len = min(len(left_ref), len(right_ref))
    if short_len < 7:
        return False
    return left_ref.startswith(right_ref) or right_ref.startswith(left_ref)


def _has_structured_verification_ref(evidence: set[str], expected_ref: str) -> bool:
    return any(
        value == expected_ref
        or (
            value.startswith(expected_ref)
            and len(value) > len(expected_ref)
            and not value[len(expected_ref)].isalnum()
            and value[len(expected_ref)] not in {"_", "-"}
        )
        for value in evidence
    )


def _artifact_text_values(ctx: VerificationContext, *keys: str) -> set[str]:
    values: set[str] = set()
    for key in keys:
        values.update(_text_values(ctx.artifacts.get(key)))
        values.update(_text_values(ctx.node.metadata.get(key)))
    return values


_ATTEMPT_AGGREGATE_EVIDENCE_KEYS = frozenset(
    {
        "evidence_refs",
        "execution_verifications",
        "last_worker_report_artifacts",
        "last_worker_report_verifications",
    }
)


def _attempt_scoped_artifact_text_values(ctx: VerificationContext, *keys: str) -> set[str]:
    values: set[str] = set()
    has_attempt_candidate_evidence = bool(
        _text_values(ctx.artifacts.get("candidate_artifacts"))
        or _text_values(ctx.artifacts.get("candidate_verifications"))
    )
    for key in keys:
        if (
            ctx.attempt_id
            and has_attempt_candidate_evidence
            and key in _ATTEMPT_AGGREGATE_EVIDENCE_KEYS
        ):
            continue
        values.update(_text_values(ctx.artifacts.get(key)))
    if ctx.attempt_id:
        return values
    for key in keys:
        values.update(_text_values(ctx.node.metadata.get(key)))
    return values


def _attempt_scoped_artifact_text_sequence(ctx: VerificationContext, *keys: str) -> list[str]:
    values: list[str] = []
    has_attempt_candidate_evidence = bool(
        _text_value_list(ctx.artifacts.get("candidate_artifacts"))
        or _text_value_list(ctx.artifacts.get("candidate_verifications"))
    )
    for key in keys:
        if (
            ctx.attempt_id
            and has_attempt_candidate_evidence
            and key in _ATTEMPT_AGGREGATE_EVIDENCE_KEYS
        ):
            continue
        values.extend(_text_value_list(ctx.artifacts.get(key)))
    if ctx.attempt_id:
        return values
    for key in keys:
        values.extend(_text_value_list(ctx.node.metadata.get(key)))
    return values


def _text_value_list(raw: object) -> list[str]:
    if isinstance(raw, str) and raw:
        return [raw]
    if isinstance(raw, list | tuple | set):
        return [str(item) for item in raw if item]
    if isinstance(raw, dict):
        return [str(item) for item in raw.values() if item]
    return []


def _text_values(raw: object) -> set[str]:
    if isinstance(raw, str) and raw:
        return {raw}
    if isinstance(raw, list | tuple | set):
        return {str(item) for item in raw if item}
    if isinstance(raw, dict):
        return {str(item) for item in raw.values() if item}
    return set()


def _normalize_sandbox_no_output_text(value: str) -> str:
    text = value.strip()
    return "" if text.casefold() in _NO_OUTPUT_SENTINELS else text


def _first_prefixed(values: set[str], prefix: str) -> str | None:
    for value in sorted(values):
        if value.startswith(prefix):
            return value
    return None


def _requires_terminal_worker_report(ctx: VerificationContext) -> bool:
    return any(
        bool(criterion.spec.get("requires_terminal_worker_report"))
        for criterion in ctx.node.acceptance_criteria
    )


def _artifact_text(ctx: VerificationContext, key: str) -> str:
    value = ctx.artifacts.get(key)
    return value.strip() if isinstance(value, str) else ""


def _clean_worktree_git_root(ctx: VerificationContext) -> str | None:
    code_root = _sandbox_code_root(ctx)
    checkpoint = ctx.node.feature_checkpoint
    if checkpoint is not None and checkpoint.worktree_path:
        worktree_path = checkpoint.worktree_path.strip()
        if "${sandbox_code_root}" in worktree_path:
            if code_root:
                return worktree_path.replace("${sandbox_code_root}", code_root)
            return None
        return worktree_path
    return code_root


def _worktree_isolation_active(
    *,
    code_root: str | None,
    worktree_path: str | None,
) -> bool:
    if not code_root or not worktree_path:
        return False
    return _normalize_posix_path(code_root) != _normalize_posix_path(worktree_path)


def _normalize_posix_path(path: str) -> str:
    return posixpath.normpath(path.rstrip("/"))


def _sandbox_code_root(ctx: VerificationContext) -> str | None:
    for raw in (ctx.node.metadata.get("code_context"), ctx.artifacts.get("code_context")):
        value = _sandbox_code_root_value(raw)
        if value:
            return value
    return None


def _sandbox_code_root_value(raw: object) -> str | None:
    if not isinstance(raw, Mapping):
        return None
    value = raw.get("sandbox_code_root")
    return value if isinstance(value, str) and value.strip() else None


# Keep :mod:`asyncio` imported so subclasses can override with timing logic.
_ = asyncio
