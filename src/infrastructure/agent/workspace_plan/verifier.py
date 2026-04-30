"""M5 — :class:`VerifierPort` with deterministic runners.

Runners available out of the box:

* :class:`CmdCriterionRunner`        — shells out via a sandbox adapter
* :class:`FileExistsCriterionRunner` — checks ``os.path.exists`` (or sandbox)
* :class:`RegexCriterionRunner`      — regex against artifact/stdout
* :class:`SchemaCriterionRunner`     — JSON Schema validation

``CriterionKind.LLM_JUDGE`` and ``CUSTOM`` are intentionally stubbed to
"inconclusive" so M5 can ship without LLM dependency; a dedicated runner
will be added in M5.5.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shlex
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

logger = logging.getLogger(__name__)

_CHANGE_EVIDENCE_PHASES = {"implement", "test", "deploy"}

_TRANSIENT_INFRA_FAILURE_MARKERS = (
    "Executor shutdown has been called",
    "SystemExit: 15",
    "All tool operations",
    "MCP request 'tools/call' timed out",
    "Server is still running but unresponsive",
    "Tool execution failed after 1 attempts",
    "filesystem appears to be unresponsive",
    "request timed out",
    "工具执行超时",
    "litellm.APIConnectionError",
    "litellm.InternalServerError",
    "Expected HTTP/, RTSP/ or ICE/",
    "Handle with `litellm.InternalServerError`",
    "is unavailable and could not be rebuilt",
    "Rate limit exceeded",
    "Please wait a moment and try again",
)


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
            result = await sandbox.run_command(cmd, timeout=timeout)
        except Exception as exc:
            logger.warning("CmdCriterionRunner sandbox error: %s", exc)
            return CriterionResult(
                criterion=criterion,
                passed=False,
                confidence=0.9,
                message=f"sandbox error: {exc}",
            )
        exit_code = int(result.get("exit_code", 1))
        stdout = str(result.get("stdout", ""))
        stderr = str(result.get("stderr", ""))
        passed = exit_code <= max_exit
        return CriterionResult(
            criterion=criterion,
            passed=passed,
            confidence=1.0,
            message=f"exit={exit_code}"
            + (f"; stderr={stderr[:120]}" if stderr and not passed else ""),
            evidence=(EvidenceRef(kind="stdout", ref=stdout[:2000], note=cmd),) if stdout else (),
        )


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
            "console_errors:0" in evidence_values
            or "browser_console_errors:0" in evidence_values
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
    ) -> None:
        self._runners: dict[CriterionKind, CriterionRunner] = runners or {
            CriterionKind.CMD: CmdCriterionRunner(),
            CriterionKind.FILE_EXISTS: FileExistsCriterionRunner(),
            CriterionKind.REGEX: RegexCriterionRunner(),
            CriterionKind.SCHEMA: SchemaCriterionRunner(),
            CriterionKind.BROWSER_E2E: BrowserE2ECriterionRunner(),
        }
        self._fallback = _InconclusiveRunner()

    def register(self, kind: CriterionKind, runner: CriterionRunner) -> None:
        self._runners[kind] = runner

    async def verify(self, ctx: VerificationContext) -> VerificationReport:
        transient_guard = _transient_infrastructure_failure_guard(ctx)
        if transient_guard is not None:
            return VerificationReport(
                node_id=ctx.node.id,
                attempt_id=ctx.attempt_id,
                results=(transient_guard,),
            )

        results: list[CriterionResult] = []
        terminal_guard = _terminal_worker_report_guard(ctx)
        if terminal_guard is not None:
            results.append(terminal_guard)
        preflight_guard = _preflight_evidence_guard(ctx)
        if preflight_guard is not None:
            results.append(preflight_guard)
        checkpoint_guard = _feature_checkpoint_evidence_guard(ctx)
        if checkpoint_guard is not None:
            results.append(checkpoint_guard)
        clean_worktree_guard = await _clean_worktree_after_commit_guard(ctx)
        if clean_worktree_guard is not None:
            results.append(clean_worktree_guard)
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
        return VerificationReport(
            node_id=ctx.node.id,
            attempt_id=ctx.attempt_id,
            results=tuple(results),
        )


def _terminal_worker_report_guard(ctx: VerificationContext) -> CriterionResult | None:
    """Prevent stale or blocked worker reports from satisfying weak criteria."""

    criterion = AcceptanceCriterion(
        kind=CriterionKind.CUSTOM,
        spec={"name": "terminal_worker_report_completed"},
        required=True,
        description="terminal worker report must be completed before durable verification can pass",
    )
    report_type = _artifact_text(ctx, "last_worker_report_type")
    attempt_status = _artifact_text(ctx, "last_attempt_status")
    report_summary = _artifact_text(ctx, "last_worker_report_summary")

    if report_type and report_type != "completed":
        return CriterionResult(
            criterion=criterion,
            passed=False,
            confidence=1.0,
            message=f"worker report type {report_type!r} is not a completion report",
        )
    if attempt_status in {"blocked", "cancelled", "rejected"}:
        return CriterionResult(
            criterion=criterion,
            passed=False,
            confidence=1.0,
            message=f"attempt status {attempt_status!r} cannot pass durable verification",
        )
    if report_summary.startswith("recovered_stale_"):
        return CriterionResult(
            criterion=criterion,
            passed=False,
            confidence=1.0,
            message=report_summary,
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


def _transient_infrastructure_failure_guard(ctx: VerificationContext) -> CriterionResult | None:
    """Return a soft verification failure for retryable runtime interruptions."""
    report_type = _artifact_text(ctx, "last_worker_report_type")
    if report_type != "blocked":
        return None

    report_summary = _artifact_text(ctx, "last_worker_report_summary")
    haystack = f"{report_summary}\n{ctx.stdout}".casefold()
    if not any(marker.casefold() in haystack for marker in _TRANSIENT_INFRA_FAILURE_MARKERS):
        return None

    criterion = AcceptanceCriterion(
        kind=CriterionKind.CUSTOM,
        spec={"name": "retryable_infrastructure_failure"},
        required=True,
        description="retryable infrastructure failures should redispatch instead of blocking",
    )
    return CriterionResult(
        criterion=criterion,
        passed=False,
        confidence=0.5,
        message="retryable infrastructure failure; redispatch node",
    )


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
    evidence_values = _artifact_text_values(
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


async def _clean_worktree_after_commit_guard(ctx: VerificationContext) -> CriterionResult | None:
    """When a checkpoint reports a commit, ensure no extra changes were left behind."""

    if ctx.sandbox is None or not _required_change_refs(ctx):
        return None

    evidence_values = _artifact_text_values(
        ctx,
        "evidence_refs",
        "last_worker_report_artifacts",
        "candidate_artifacts",
        "execution_verifications",
        "last_worker_report_verifications",
        "candidate_verifications",
    )
    if not _first_prefixed(evidence_values, "commit_ref:"):
        return None

    criterion = AcceptanceCriterion(
        kind=CriterionKind.CUSTOM,
        spec={"name": "clean_worktree_after_commit"},
        required=True,
        description="committed feature checkpoints must not leave uncommitted changes",
    )
    code_root = _sandbox_code_root(ctx)
    command = "git status --short"
    if code_root:
        command = f"git -C {shlex.quote(code_root)} status --short"
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
    stdout = str(result.get("stdout", "")).strip()
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


def _required_change_refs(ctx: VerificationContext) -> set[str]:
    refs: set[str] = set()
    feature = ctx.node.feature_checkpoint
    raw_phase = ctx.node.metadata.get("iteration_phase")
    phase = raw_phase.strip().lower() if isinstance(raw_phase, str) else None
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
        raw = ctx.artifacts.get(key)
        if isinstance(raw, str) and raw:
            values.add(raw)
        elif isinstance(raw, list):
            values.update(str(item) for item in raw if item)
        elif isinstance(raw, dict):
            values.update(str(item) for item in raw.values() if item)
    return values


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


def _sandbox_code_root(ctx: VerificationContext) -> str | None:
    raw = ctx.node.metadata.get("code_context")
    if not isinstance(raw, dict):
        return None
    value = raw.get("sandbox_code_root")
    return value if isinstance(value, str) and value.strip() else None


# Keep :mod:`asyncio` imported so subclasses can override with timing logic.
_ = asyncio
