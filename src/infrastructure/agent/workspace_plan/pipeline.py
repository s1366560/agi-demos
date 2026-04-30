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
    service_id: str | None = None

    def to_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "stage": self.stage,
            "command": self.command,
            "required": self.required,
            "timeout_seconds": self.timeout_seconds,
        }
        if self.service_id:
            payload["service_id"] = self.service_id
        return payload


@dataclass(frozen=True)
class PipelineServiceSpec:
    service_id: str
    name: str
    start_command: str
    internal_port: int
    internal_scheme: str = "http"
    path_prefix: str = "/"
    health_path: str = "/"
    health_command: str | None = None
    required: bool = True
    auto_open: bool = True

    def to_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "service_id": self.service_id,
            "name": self.name,
            "start_command": self.start_command,
            "internal_port": self.internal_port,
            "internal_scheme": self.internal_scheme,
            "path_prefix": self.path_prefix,
            "health_path": self.health_path,
            "required": self.required,
            "auto_open": self.auto_open,
        }
        if self.health_command:
            payload["health_command"] = self.health_command
        return payload

    @property
    def internal_base_url(self) -> str:
        return f"{self.internal_scheme}://127.0.0.1:{self.internal_port}{self.path_prefix}"

    @property
    def internal_health_url(self) -> str:
        path = self.health_path or "/"
        if path.startswith("http://") or path.startswith("https://"):
            return path
        normalized = path if path.startswith("/") else f"/{path}"
        return f"{self.internal_scheme}://127.0.0.1:{self.internal_port}{normalized}"


@dataclass(frozen=True)
class PipelineContractSpec:
    provider: str = SANDBOX_NATIVE_PROVIDER
    code_root: str | None = None
    stages: tuple[PipelineStageSpec, ...] = ()
    services: tuple[PipelineServiceSpec, ...] = ()
    env: dict[str, str] = field(default_factory=dict)
    timeout_seconds: int = DEFAULT_PIPELINE_TIMEOUT_SECONDS
    auto_deploy: bool = True
    preview_port: int | None = None
    health_url: str | None = None
    deploy_command: str | None = None
    agent_managed: bool = True
    contract_source: str = "metadata"
    contract_confidence: float = 1.0

    def commands_json(self) -> list[dict[str, Any]]:
        return [stage.to_json() for stage in self.stages]

    def services_json(self) -> list[dict[str, Any]]:
        return [service.to_json() for service in self.services]


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
    agent_managed = _bool(config.get("agent_managed"), default=True)
    contract_source = _string(config.get("contract_source")) or (
        "agent_proposal" if isinstance(config.get("agent_proposal"), dict) else "metadata"
    )
    contract_confidence = _confidence(config.get("contract_confidence"), fallback=1.0)
    services = _configured_service_specs(
        config,
        preview_port=preview_port,
        deploy_command=deploy_command,
        health_url=health_url,
        health_command=health_command,
    )

    stages = _configured_stage_specs(config, timeout_seconds)
    if not stages:
        stages = _default_stage_specs(timeout_seconds)
    if auto_deploy:
        if services:
            stages.extend(
                _service_stage_specs(
                    services,
                    timeout_seconds=timeout_seconds,
                    existing_stages=stages,
                )
            )
        elif (health_command or health_url) and not _has_stage(stages, "health"):
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
        services=tuple(services),
        env=env,
        timeout_seconds=timeout_seconds,
        auto_deploy=auto_deploy,
        preview_port=preview_port,
        health_url=health_url,
        deploy_command=deploy_command,
        agent_managed=agent_managed,
        contract_source=contract_source,
        contract_confidence=contract_confidence,
    )


class SandboxNativePipelineProvider:
    """Executes CI/CD stages in the workspace project sandbox."""

    def __init__(self, runner: WorkspacePipelineSandboxRunner) -> None:
        self._runner = runner

    async def run(self, contract: PipelineContractSpec) -> PipelineRunResult:  # noqa: PLR0912
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
                if stage.service_id:
                    evidence_refs.append(f"pipeline_stage:{stage.stage}:passed:{stage.service_id}")
            else:
                evidence_refs.append(f"pipeline_stage:{stage.stage}:failed")
                if stage.service_id:
                    evidence_refs.append(f"pipeline_stage:{stage.stage}:failed:{stage.service_id}")
            if stage.stage == "deploy" and result.passed:
                deploy_pid = _first_int(result.stdout_preview)
                deployment_status = "running"
            if stage.stage == "health":
                deployment_status = "healthy" if result.passed else "unhealthy"
                if result.passed:
                    if stage.service_id:
                        evidence_refs.append(f"deployment_health:passed:{stage.service_id}")
                    else:
                        evidence_refs.append("deployment_health:passed")
                else:
                    if stage.service_id:
                        evidence_refs.append(f"deployment_health:failed:{stage.service_id}")
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


def _configured_service_specs(
    config: dict[str, Any],
    *,
    preview_port: int | None,
    deploy_command: str | None,
    health_url: str | None,
    health_command: str | None,
) -> list[PipelineServiceSpec]:
    raw_services = config.get("services")
    services: list[PipelineServiceSpec] = []
    if isinstance(raw_services, list):
        for index, item in enumerate(raw_services, start=1):
            if not isinstance(item, dict):
                continue
            service = _service_spec_from_mapping(item, index=index)
            if service is not None:
                services.append(service)
    if services:
        return _dedupe_services(services)

    if deploy_command:
        port = preview_port or DEFAULT_PREVIEW_PORT
        return [
            PipelineServiceSpec(
                service_id="default",
                name="Preview",
                start_command=deploy_command or _default_preview_start_command(port),
                internal_port=port,
                health_path=health_url or "/",
                health_command=health_command,
                required=True,
                auto_open=True,
            )
        ]
    return []


def _service_spec_from_mapping(
    item: dict[str, Any],
    *,
    index: int,
) -> PipelineServiceSpec | None:
    service_id = _safe_service_id(
        _string(item.get("service_id") or item.get("id")) or f"service-{index}"
    )
    name = _string(item.get("name")) or service_id
    start_command = _string(item.get("start_command") or item.get("deploy_command"))
    port = _positive_int(item.get("internal_port") or item.get("port"), 0)
    if not start_command or port <= 0:
        return None
    scheme = _string(item.get("internal_scheme") or item.get("scheme")) or "http"
    if scheme not in {"http", "https"}:
        scheme = "http"
    return PipelineServiceSpec(
        service_id=service_id,
        name=name,
        start_command=start_command,
        internal_port=port,
        internal_scheme=scheme,
        path_prefix=_normalize_path(_string(item.get("path_prefix")) or "/"),
        health_path=_normalize_path(_string(item.get("health_path")) or "/"),
        health_command=_string(item.get("health_command")),
        required=_bool(item.get("required"), default=True),
        auto_open=_bool(item.get("auto_open"), default=True),
    )


def _dedupe_services(services: list[PipelineServiceSpec]) -> list[PipelineServiceSpec]:
    output: list[PipelineServiceSpec] = []
    seen: set[str] = set()
    for service in services:
        service_id = service.service_id
        if service_id in seen:
            suffix = 2
            while f"{service_id}-{suffix}" in seen:
                suffix += 1
            service = PipelineServiceSpec(
                service_id=f"{service_id}-{suffix}",
                name=service.name,
                start_command=service.start_command,
                internal_port=service.internal_port,
                internal_scheme=service.internal_scheme,
                path_prefix=service.path_prefix,
                health_path=service.health_path,
                health_command=service.health_command,
                required=service.required,
                auto_open=service.auto_open,
            )
        seen.add(service.service_id)
        output.append(service)
    return output


def _service_stage_specs(
    services: list[PipelineServiceSpec],
    *,
    timeout_seconds: int,
    existing_stages: list[PipelineStageSpec],
) -> list[PipelineStageSpec]:
    output: list[PipelineStageSpec] = []
    for service in services:
        if service.start_command and not _has_stage(existing_stages + output, "deploy", service):
            output.append(
                PipelineStageSpec(
                    stage="deploy",
                    command=_preview_deploy_command(service.start_command, service=service),
                    required=service.required,
                    timeout_seconds=timeout_seconds,
                    service_id=service.service_id,
                )
            )
        if not _has_stage(existing_stages + output, "health", service):
            output.append(
                PipelineStageSpec(
                    stage="health",
                    command=service.health_command or _health_command(service.internal_health_url),
                    required=service.required,
                    timeout_seconds=min(timeout_seconds, 120),
                    service_id=service.service_id,
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


def _default_preview_start_command(port: int) -> str:
    return f"npm run preview -- --host 0.0.0.0 --port {port}"


def _preview_deploy_command(command: str, *, service: PipelineServiceSpec | None = None) -> str:
    service_label = service.service_id if service is not None else "default"
    quoted = shlex.quote(command)
    log_path = f"/tmp/memstack-workspace-preview/{shlex.quote(service_label)}.log"
    return (
        "mkdir -p /tmp/memstack-workspace-preview && "
        f"nohup sh -lc {quoted} "
        f"> {log_path} 2>&1 & echo $!"
    )


def _health_command(url: str) -> str:
    quoted_url = shlex.quote(url)
    return (
        "i=0; "
        'while [ "$i" -lt 20 ]; do '
        f"curl -fsS {quoted_url} >/dev/null && exit 0; "
        "i=$((i + 1)); sleep 1; "
        "done; "
        f"curl -fsS {quoted_url} >/dev/null"
    )


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
    if contract.services:
        return None
    return contract.health_url


def _has_stage(
    stages: list[PipelineStageSpec],
    stage: str,
    service: PipelineServiceSpec | None = None,
) -> bool:
    service_id = service.service_id if service is not None else None
    return any(item.stage == stage and item.service_id == service_id for item in stages)


def _string(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _normalize_path(value: str) -> str:
    normalized = value.strip() or "/"
    if normalized.startswith("http://") or normalized.startswith("https://"):
        return normalized
    return normalized if normalized.startswith("/") else f"/{normalized}"


def _safe_service_id(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._:-]+", "-", value.strip())[:128].strip("-")
    return normalized or "default"


def _bool(value: object, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return default


def _confidence(value: object, *, fallback: float) -> float:
    try:
        parsed = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return fallback
    return max(0.0, min(1.0, parsed))


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
    "PipelineServiceSpec",
    "PipelineStageResult",
    "PipelineStageSpec",
    "SandboxNativePipelineProvider",
    "WorkspacePipelineSandboxRunner",
    "build_pipeline_contract_from_metadata",
]
