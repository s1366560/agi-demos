"""Harness-native workspace CI/CD pipeline primitives.

The v1 provider is intentionally sandbox-first. It executes bounded shell
stages in the existing project sandbox and records structured evidence for the
durable verifier. External providers can implement the same contract later.
"""

from __future__ import annotations

import re
import shlex
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

SANDBOX_NATIVE_PROVIDER = "sandbox_native"
PIPELINE_EVIDENCE_KEY = "pipeline_evidence_refs"
DEFAULT_PIPELINE_TIMEOUT_SECONDS = 600
DEFAULT_PREVIEW_PORT = 3000
_EXIT_MARKER = "__MEMSTACK_PIPELINE_EXIT_CODE__="
_EXIT_RE = re.compile(r"__MEMSTACK_PIPELINE_EXIT_CODE__=(\d+)")


class WorkspacePipelineSandboxRunner(Protocol):
    """Minimal command surface supplied by the workspace sandbox."""

    async def run_command(self, command: str, *, timeout: int = 60) -> dict[str, Any]: ...


@dataclass(frozen=True)
class PipelineStageSpec:
    stage: str
    command: str
    required: bool = True
    timeout_seconds: int = DEFAULT_PIPELINE_TIMEOUT_SECONDS

    def to_json(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "command": self.command,
            "required": self.required,
            "timeout_seconds": self.timeout_seconds,
        }


@dataclass(frozen=True)
class PipelineContractSpec:
    provider: str = SANDBOX_NATIVE_PROVIDER
    code_root: str | None = None
    stages: tuple[PipelineStageSpec, ...] = ()
    env: dict[str, str] = field(default_factory=dict)
    timeout_seconds: int = DEFAULT_PIPELINE_TIMEOUT_SECONDS
    auto_deploy: bool = True
    preview_port: int | None = None
    health_url: str | None = None
    deploy_command: str | None = None

    def commands_json(self) -> list[dict[str, Any]]:
        return [stage.to_json() for stage in self.stages]


@dataclass(frozen=True)
class PipelineStageResult:
    stage: str
    status: str
    command: str
    exit_code: int | None
    stdout_preview: str = ""
    stderr_preview: str = ""
    duration_ms: int = 0
    log_ref: str | None = None
    artifact_refs: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        return self.status in {"success", "skipped"}


@dataclass(frozen=True)
class PipelineRunResult:
    status: str
    reason: str | None
    stage_results: tuple[PipelineStageResult, ...]
    evidence_refs: tuple[str, ...]
    preview_url: str | None = None
    health_url: str | None = None
    deployment_status: str | None = None
    deployment_pid: int | None = None


def build_pipeline_contract_from_metadata(
    *,
    workspace_metadata: dict[str, Any],
    fallback_code_root: str | None,
) -> PipelineContractSpec:
    """Normalize workspace metadata into a bounded sandbox-native contract."""

    raw = workspace_metadata.get("delivery_cicd")
    config = dict(raw) if isinstance(raw, dict) else {}
    provider = _string(config.get("provider")) or SANDBOX_NATIVE_PROVIDER
    code_root = _string(config.get("code_root")) or fallback_code_root
    timeout_seconds = _positive_int(
        config.get("timeout_seconds"),
        DEFAULT_PIPELINE_TIMEOUT_SECONDS,
    )
    env = {
        str(key): str(value)
        for key, value in dict(config.get("env") or {}).items()
        if isinstance(key, str) and value is not None
    }
    auto_deploy = _bool(config.get("auto_deploy"), default=True)
    preview_port = _positive_int(config.get("preview_port"), DEFAULT_PREVIEW_PORT)
    health_url = _string(config.get("health_url"))
    deploy_command = _string(config.get("deploy_command"))
    health_command = _string(config.get("health_command"))

    stages = _configured_stage_specs(config, timeout_seconds)
    if not stages:
        stages = _default_stage_specs(timeout_seconds)
    if auto_deploy and deploy_command and not _has_stage(stages, "deploy"):
        stages.append(
            PipelineStageSpec(
                stage="deploy",
                command=_preview_deploy_command(deploy_command),
                required=True,
                timeout_seconds=timeout_seconds,
            )
        )
    if auto_deploy and (health_command or health_url) and not _has_stage(stages, "health"):
        stages.append(
            PipelineStageSpec(
                stage="health",
                command=health_command or _health_command(str(health_url)),
                required=True,
                timeout_seconds=min(timeout_seconds, 120),
            )
        )

    return PipelineContractSpec(
        provider=provider,
        code_root=code_root,
        stages=tuple(stages),
        env=env,
        timeout_seconds=timeout_seconds,
        auto_deploy=auto_deploy,
        preview_port=preview_port,
        health_url=health_url,
        deploy_command=deploy_command,
    )


class SandboxNativePipelineProvider:
    """Executes CI/CD stages in the workspace project sandbox."""

    def __init__(self, runner: WorkspacePipelineSandboxRunner) -> None:
        self._runner = runner

    async def run(self, contract: PipelineContractSpec) -> PipelineRunResult:
        stage_results: list[PipelineStageResult] = []
        evidence_refs: list[str] = []
        failed_reason: str | None = None
        deploy_pid: int | None = None
        deployment_status: str | None = None
        preview_url = _preview_url(contract)

        for stage in contract.stages:
            result = await self.run_stage(contract, stage)
            stage_results.append(result)
            if result.passed:
                evidence_refs.append(f"pipeline_stage:{stage.stage}:passed")
            else:
                evidence_refs.append(f"pipeline_stage:{stage.stage}:failed")
            if stage.stage == "deploy" and result.passed:
                deploy_pid = _first_int(result.stdout_preview)
                deployment_status = "running"
            if stage.stage == "health":
                deployment_status = "healthy" if result.passed else "unhealthy"
                if result.passed:
                    evidence_refs.append("deployment_health:passed")
                else:
                    evidence_refs.append("deployment_health:failed")
            if not result.passed and stage.required:
                failed_reason = f"stage {stage.stage} failed with exit {result.exit_code}"
                break

        status = "success" if failed_reason is None else "failed"
        evidence_refs.insert(0, f"ci_pipeline:{'passed' if status == 'success' else 'failed'}")
        return PipelineRunResult(
            status=status,
            reason=failed_reason,
            stage_results=tuple(stage_results),
            evidence_refs=tuple(dict.fromkeys(evidence_refs)),
            preview_url=preview_url,
            health_url=contract.health_url,
            deployment_status=deployment_status,
            deployment_pid=deploy_pid,
        )

    async def run_stage(
        self,
        contract: PipelineContractSpec,
        stage: PipelineStageSpec,
    ) -> PipelineStageResult:
        command = _wrapped_command(
            stage.command,
            code_root=contract.code_root,
            env=contract.env,
        )
        started = time.monotonic()
        try:
            raw = await self._runner.run_command(command, timeout=stage.timeout_seconds)
        except Exception as exc:
            duration_ms = int((time.monotonic() - started) * 1000)
            return PipelineStageResult(
                stage=stage.stage,
                status="failed",
                command=stage.command,
                exit_code=1,
                stdout_preview="",
                stderr_preview=str(exc)[:4000],
                duration_ms=duration_ms,
            )

        duration_ms = int((time.monotonic() - started) * 1000)
        stdout = str(raw.get("stdout") or "")
        stderr = str(raw.get("stderr") or "")
        combined = f"{stdout}\n{stderr}".strip()
        exit_code = _exit_code_from_output(combined, raw)
        cleaned = _EXIT_RE.sub("", combined).strip()
        status = "success" if exit_code == 0 else "failed"
        log_ref = f"sandbox://pipeline/{uuid.uuid4()}/{stage.stage}.log"
        return PipelineStageResult(
            stage=stage.stage,
            status=status,
            command=stage.command,
            exit_code=exit_code,
            stdout_preview=_compact(cleaned),
            stderr_preview=_compact(stderr) if exit_code != 0 else "",
            duration_ms=duration_ms,
            log_ref=log_ref,
            artifact_refs=(f"pipeline_log:{stage.stage}:{log_ref}",),
        )


def _configured_stage_specs(
    config: dict[str, Any],
    default_timeout: int,
) -> list[PipelineStageSpec]:
    raw_stages = config.get("stages")
    if isinstance(raw_stages, list):
        output: list[PipelineStageSpec] = []
        for item in raw_stages:
            if not isinstance(item, dict):
                continue
            stage = _string(item.get("stage") or item.get("id"))
            command = _string(item.get("command"))
            if not stage or not command:
                continue
            output.append(
                PipelineStageSpec(
                    stage=stage,
                    command=command,
                    required=_bool(item.get("required"), default=True),
                    timeout_seconds=_positive_int(item.get("timeout_seconds"), default_timeout),
                )
            )
        return output

    command_keys = (
        ("install", "install_command"),
        ("lint", "lint_command"),
        ("test", "test_command"),
        ("build", "build_command"),
    )
    output = []
    for stage, key in command_keys:
        command = _string(config.get(key))
        if command:
            output.append(
                PipelineStageSpec(
                    stage=stage,
                    command=command,
                    required=True,
                    timeout_seconds=default_timeout,
                )
            )
    return output


def _default_stage_specs(timeout_seconds: int) -> list[PipelineStageSpec]:
    return [
        PipelineStageSpec("install", _default_install_command(), True, timeout_seconds),
        PipelineStageSpec("lint", _default_lint_command(), False, timeout_seconds),
        PipelineStageSpec("test", _default_test_command(), True, timeout_seconds),
        PipelineStageSpec("build", _default_build_command(), True, timeout_seconds),
    ]


def _default_install_command() -> str:
    return (
        "if [ -f package.json ]; then "
        "if [ -f pnpm-lock.yaml ] && command -v pnpm >/dev/null 2>&1; "
        "then pnpm install --frozen-lockfile || pnpm install; "
        "elif [ -f package-lock.json ]; then npm ci || npm install; "
        "else npm install; fi; "
        "elif [ -f pyproject.toml ] && command -v uv >/dev/null 2>&1; then uv sync; "
        "else echo 'no install step'; fi"
    )


def _default_lint_command() -> str:
    return (
        "if [ -f Makefile ] && grep -qE '^lint:' Makefile; then make lint; "
        "elif [ -f package.json ]; then npm run lint --if-present; "
        "else echo 'no lint step'; fi"
    )


def _default_test_command() -> str:
    return (
        "if [ -f Makefile ] && grep -qE '^test:' Makefile; then make test; "
        "elif [ -f package.json ]; then npm test -- --runInBand=false 2>/dev/null || npm test; "
        "elif [ -d tests ]; then pytest; else echo 'no test step'; fi"
    )


def _default_build_command() -> str:
    return (
        "if [ -f Makefile ] && grep -qE '^build:' Makefile; then make build; "
        "elif [ -f package.json ]; then npm run build --if-present; "
        "else echo 'no build step'; fi"
    )


def _preview_deploy_command(command: str) -> str:
    quoted = shlex.quote(command)
    return (
        "mkdir -p /tmp/memstack-workspace-preview && "
        f"nohup sh -lc {quoted} "
        "> /tmp/memstack-workspace-preview/preview.log 2>&1 & echo $!"
    )


def _health_command(url: str) -> str:
    return f"curl -fsS {shlex.quote(url)} >/dev/null"


def _wrapped_command(command: str, *, code_root: str | None, env: dict[str, str]) -> str:
    lines = ["set +e"]
    if code_root:
        lines.append(f"cd {shlex.quote(code_root)}")
    for key, value in sorted(env.items()):
        if key.replace("_", "").isalnum():
            lines.append(f"export {key}={shlex.quote(value)}")
    lines.extend(
        [
            "(",
            command,
            ")",
            "code=$?",
            f'printf "\\n{_EXIT_MARKER}%s\\n" "$code"',
            "exit 0",
        ]
    )
    return "\n".join(lines)


def _exit_code_from_output(output: str, raw: dict[str, Any]) -> int:
    match = _EXIT_RE.search(output)
    if match:
        return int(match.group(1))
    try:
        return int(raw.get("exit_code", 1))
    except (TypeError, ValueError):
        return 1


def _preview_url(contract: PipelineContractSpec) -> str | None:
    if contract.health_url:
        return contract.health_url
    if contract.preview_port:
        return f"http://127.0.0.1:{contract.preview_port}"
    return None


def _has_stage(stages: list[PipelineStageSpec], stage: str) -> bool:
    return any(item.stage == stage for item in stages)


def _string(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _bool(value: object, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return default


def _positive_int(value: object, fallback: int) -> int:
    if isinstance(value, int):
        return value if value > 0 else fallback
    if isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
        return parsed if parsed > 0 else fallback
    return fallback


def _first_int(value: str) -> int | None:
    match = re.search(r"\b(\d+)\b", value)
    return int(match.group(1)) if match else None


def _compact(value: str, *, limit: int = 4000) -> str:
    compacted = value.strip()
    if len(compacted) <= limit:
        return compacted
    return compacted[: limit - 15] + "...[truncated]"


__all__ = [
    "PIPELINE_EVIDENCE_KEY",
    "SANDBOX_NATIVE_PROVIDER",
    "PipelineContractSpec",
    "PipelineRunResult",
    "PipelineStageResult",
    "PipelineStageSpec",
    "SandboxNativePipelineProvider",
    "WorkspacePipelineSandboxRunner",
    "build_pipeline_contract_from_metadata",
]
