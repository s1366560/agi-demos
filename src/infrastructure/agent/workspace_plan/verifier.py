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
            import jsonschema  # type: ignore[import-not-found]

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
        self, criterion: AcceptanceCriterion, schema: dict, value: Any
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
        }
        self._fallback = _InconclusiveRunner()

    def register(self, kind: CriterionKind, runner: CriterionRunner) -> None:
        self._runners[kind] = runner

    async def verify(self, ctx: VerificationContext) -> VerificationReport:
        results: list[CriterionResult] = []
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


# Keep :mod:`asyncio` imported so subclasses can override with timing logic.
_ = asyncio
