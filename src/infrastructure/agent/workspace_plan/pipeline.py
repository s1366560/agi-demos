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
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit

import yaml

SANDBOX_NATIVE_PROVIDER = "sandbox_native"
SANDBOX_NATIVE_PROVIDER_ALIASES = frozenset({SANDBOX_NATIVE_PROVIDER, "memstack-sandbox"})
DRONE_PROVIDER = "drone"
DRONE_DEPLOY_MODES = frozenset({"docker", "kubernetes", "cli"})
DRONE_DOCKER_DEPLOY_VALIDATION = "explicit_deploy_step_v1"
PIPELINE_EVIDENCE_KEY = "pipeline_evidence_refs"
DEFAULT_PIPELINE_TIMEOUT_SECONDS = 600
DEFAULT_PREVIEW_PORT = 3000
DEFAULT_DRONE_DEPLOY_MODE = "cli"
DEFAULT_DRONE_DEPLOY_STAGE = "deploy"
DEFAULT_DOCKER_DEPLOY_HOST_PORT = 18080
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
class PipelineDeploySpec:
    enabled: bool = False
    mode: str = DEFAULT_DRONE_DEPLOY_MODE
    stage: str = DEFAULT_DRONE_DEPLOY_STAGE
    required: bool = True
    target: str | None = None
    docker: dict[str, Any] = field(default_factory=dict)
    kubernetes: dict[str, Any] = field(default_factory=dict)
    cli: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "enabled": self.enabled,
            "mode": self.mode,
            "stage": self.stage,
            "required": self.required,
        }
        if self.target:
            payload["target"] = self.target
        if self.docker:
            payload["docker"] = dict(self.docker)
        if self.kubernetes:
            payload["kubernetes"] = dict(self.kubernetes)
        if self.cli:
            payload["cli"] = dict(self.cli)
        return payload


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
    deploy: PipelineDeploySpec | None = None
    provider_config: dict[str, Any] = field(default_factory=dict)

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
    metadata: dict[str, Any] = field(default_factory=dict)

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
    external_id: str | None = None
    external_url: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def build_pipeline_contract_from_metadata(
    *,
    workspace_metadata: dict[str, Any],
    fallback_code_root: str | None,
    fallback_host_code_root: str | Path | None = None,
) -> PipelineContractSpec:
    """Normalize workspace metadata into a bounded sandbox-native contract."""

    raw = workspace_metadata.get("delivery_cicd")
    config = dict(raw) if isinstance(raw, dict) else {}
    provider = _normalize_provider(_string(config.get("provider")) or SANDBOX_NATIVE_PROVIDER)
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
    readable_code_root = _readable_code_root(fallback_host_code_root, code_root)
    services = _configured_service_specs(
        config,
        preview_port=preview_port,
        deploy_command=deploy_command,
        health_url=health_url,
        health_command=health_command,
        code_root=readable_code_root,
    )
    provider_config = _provider_config(config, provider)
    if provider == DRONE_PROVIDER and readable_code_root is not None:
        provider_config.setdefault("preflight_code_root", str(readable_code_root))
    deploy = _configured_deploy_spec(config, provider_config, services=services)

    stages = _configured_stage_specs(config, timeout_seconds)
    if provider == SANDBOX_NATIVE_PROVIDER and not stages:
        stages = _default_stage_specs(timeout_seconds)
    if provider == SANDBOX_NATIVE_PROVIDER and auto_deploy:
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
        deploy=deploy,
        provider_config=provider_config,
    )


def _provider_config(config: dict[str, Any], provider: str) -> dict[str, Any]:
    output: dict[str, Any] = {}
    raw_provider_config = config.get("provider_config")
    if isinstance(raw_provider_config, Mapping):
        provider_config = raw_provider_config.get(provider)
        if isinstance(provider_config, Mapping):
            output.update(dict(provider_config))
        else:
            output.update(dict(raw_provider_config))
    provider_section = config.get(provider)
    if isinstance(provider_section, Mapping):
        output.update(dict(provider_section))
    for key in (
        "repo",
        "repository",
        "branch",
        "commit",
        "target",
        "params",
        "build_params",
        "server_url",
        "server_url_env",
        "token_env",
        "poll_interval_seconds",
        "deploy",
    ):
        if key in config and key not in output:
            output[key] = config[key]
    return output


def _configured_deploy_spec(
    config: dict[str, Any],
    provider_config: dict[str, Any],
    *,
    services: list[PipelineServiceSpec],
) -> PipelineDeploySpec | None:
    raw = config.get("deploy")
    if not isinstance(raw, Mapping):
        raw = provider_config.get("deploy")
    if not isinstance(raw, Mapping):
        mode = _string(config.get("deploy_mode") or provider_config.get("deploy_mode"))
        if not mode:
            return None
        raw = {"mode": mode, "enabled": True}

    raw_deploy = dict(raw)
    mode = _normalize_deploy_mode(
        _string(raw_deploy.get("mode") or raw_deploy.get("type") or raw_deploy.get("pipeline_type"))
    )
    enabled = _bool(raw_deploy.get("enabled"), default=False)
    stage = _safe_stage_name(_string(raw_deploy.get("stage") or raw_deploy.get("step")))
    target = _string(
        raw_deploy.get("target") or config.get("target") or provider_config.get("target")
    )
    return PipelineDeploySpec(
        enabled=enabled,
        mode=mode,
        stage=stage,
        required=_bool(raw_deploy.get("required"), default=True),
        target=target,
        docker=_docker_deploy_config_with_services(
            _json_mapping(raw_deploy.get("docker")),
            services=services,
        ),
        kubernetes=_json_mapping(raw_deploy.get("kubernetes")),
        cli=_json_mapping(raw_deploy.get("cli")),
    )


def _docker_deploy_config_with_services(
    docker: dict[str, Any],
    *,
    services: list[PipelineServiceSpec],
) -> dict[str, Any]:
    if not services:
        return docker
    deploy_services = [
        _docker_deploy_service_from_pipeline_service(service)
        for service in services
        if _is_application_deploy_service(service)
    ]
    if not deploy_services:
        return docker

    existing_key = "deploy_services" if isinstance(docker.get("deploy_services"), list) else None
    if existing_key is None and isinstance(docker.get("services"), list):
        existing_key = "services"
    if existing_key is not None:
        existing = [
            dict(item) for item in docker.get(existing_key, []) if isinstance(item, Mapping)
        ]
        existing_ids = {
            _safe_service_id(
                _string(item.get("service_id") or item.get("id") or item.get("name"))
                or f"service-{index}"
            )
            for index, item in enumerate(existing, start=1)
        }
        for service in deploy_services:
            service_id = _safe_service_id(
                _string(service.get("service_id") or service.get("id") or service.get("name")) or ""
            )
            if service_id and service_id not in existing_ids:
                existing.append(service)
                existing_ids.add(service_id)
        docker[existing_key] = _docker_deploy_services_with_host_ports(docker, existing)
        return docker

    if not docker.get("services"):
        docker["deploy_services"] = _docker_deploy_services_with_host_ports(
            docker,
            deploy_services,
        )
    return docker


def _docker_deploy_services_with_host_ports(
    docker: Mapping[str, Any],
    services: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    base_host_port = _positive_int(
        docker.get("deploy_host_port") or docker.get("host_port"),
        0,
    )
    if base_host_port <= 0:
        return services
    reserved_ports = _positive_int_set(docker.get("reserved_host_ports"))
    used_host_ports: set[int] = set()
    output: list[dict[str, Any]] = []
    for index, service in enumerate(services):
        item = dict(service)
        host_port = _positive_int(item.get("deploy_host_port") or item.get("host_port"), 0)
        if host_port <= 0 or host_port in reserved_ports or host_port in used_host_ports:
            host_port = _next_available_host_port(
                base_host_port + index,
                reserved_ports=reserved_ports,
                used_host_ports=used_host_ports,
            )
        used_host_ports.add(host_port)
        item["deploy_host_port"] = host_port
        item.setdefault("host_port", host_port)
        container_port = _positive_int(
            item.get("container_port") or item.get("internal_port") or item.get("port"),
            0,
        )
        if container_port > 0:
            item.setdefault("container_port", container_port)
            item.setdefault("deploy_port_mapping", f"{host_port}:{container_port}")
        output.append(item)
    return output


def _positive_int_set(value: object) -> set[int]:
    if not isinstance(value, list | tuple | set):
        return set()
    return {parsed for item in value if (parsed := _positive_int(item, 0)) > 0}


def _next_available_host_port(
    start: int,
    *,
    reserved_ports: set[int],
    used_host_ports: set[int],
) -> int:
    candidate = max(start, DEFAULT_DOCKER_DEPLOY_HOST_PORT)
    while candidate in reserved_ports or candidate in used_host_ports:
        candidate += 1
    return candidate


def _docker_deploy_service_from_pipeline_service(
    service: PipelineServiceSpec,
) -> dict[str, Any]:
    return {
        "service_id": service.service_id,
        "name": service.name,
        "container_name": _safe_service_id(service.service_id),
        "container_port": service.internal_port,
        "internal_port": service.internal_port,
        "internal_scheme": service.internal_scheme,
        "path_prefix": service.path_prefix,
        "health_path": service.health_path,
        "health_command": service.health_command,
        "required": service.required,
        "auto_open": service.auto_open,
        "start_command": service.start_command,
    }


def _is_application_deploy_service(service: PipelineServiceSpec) -> bool:
    service_id = service.service_id.lower()
    name = service.name.lower()
    start_command = service.start_command.lower()
    if service_id in {"drone-ci", "drone-runner"} or service_id.startswith("drone-"):
        return False
    return not (
        name.startswith("drone ")
        or "drone server" in start_command
        or "drone-runner" in start_command
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
                    service_id=_string(item.get("service_id")),
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
    code_root: Path | None = None,
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
    compose_services = _compose_application_service_specs(code_root)
    if _should_prefer_compose_services(services, compose_services):
        return _dedupe_services(compose_services)
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


_COMPOSE_FILE_NAMES = (
    "compose.yaml",
    "compose.yml",
    "docker-compose.yaml",
    "docker-compose.yml",
)
_COMPOSE_OVERRIDE_FILE_NAMES = (
    "compose.override.yaml",
    "compose.override.yml",
    "docker-compose.override.yaml",
    "docker-compose.override.yml",
)
_INFRA_COMPOSE_SERVICE_IDS = frozenset(
    {
        "adminer",
        "cache",
        "database",
        "db",
        "drone",
        "drone-ci",
        "drone-runner",
        "mailhog",
        "minio",
        "neo4j",
        "nginx",
        "pgadmin",
        "postgres",
        "postgresql",
        "proxy",
        "redis",
    }
)


@dataclass(frozen=True)
class _ComposeTaggedValue:
    tag: str
    value: object


class _ComposeLoader(yaml.SafeLoader):
    """YAML loader that preserves Compose merge control tags."""


def _compose_tag_constructor(
    loader: yaml.SafeLoader,
    tag_suffix: str,
    node: yaml.Node,
) -> _ComposeTaggedValue:
    tag = f"!{tag_suffix}"
    if isinstance(node, yaml.ScalarNode):
        value = loader.construct_scalar(node)
    elif isinstance(node, yaml.SequenceNode):
        value = loader.construct_sequence(node)
    elif isinstance(node, yaml.MappingNode):
        value = loader.construct_mapping(node)
    else:
        value = None
    return _ComposeTaggedValue(tag=tag, value=value)


_ComposeLoader.add_multi_constructor("!", _compose_tag_constructor)


def _readable_code_root(*candidates: str | Path | None) -> Path | None:
    for candidate in candidates:
        if candidate is None:
            continue
        path = Path(candidate)
        if path.is_dir():
            return path
    return None


def _compose_application_service_specs(code_root: Path | None) -> list[PipelineServiceSpec]:
    if code_root is None:
        return []
    parsed = _load_default_compose_model(code_root)
    if parsed is None:
        return []
    raw_services = parsed.get("services")
    if not isinstance(raw_services, Mapping):
        return []
    services: list[PipelineServiceSpec] = []
    for index, (service_id, raw_service) in enumerate(raw_services.items(), start=1):
        if not isinstance(service_id, str) or not isinstance(raw_service, Mapping):
            continue
        service = _compose_service_spec(service_id, raw_service, index=index)
        if service is not None:
            services.append(service)
    return services


def _load_default_compose_model(code_root: Path) -> Mapping[str, Any] | None:
    base_path = _first_existing_file(code_root, _COMPOSE_FILE_NAMES)
    if base_path is None:
        return None
    try:
        parsed: object = _load_compose_yaml(base_path)
        for override_path in _existing_files(code_root, _COMPOSE_OVERRIDE_FILE_NAMES):
            override = _load_compose_yaml(override_path)
            parsed = _merge_compose_value(parsed, override)
    except (OSError, yaml.YAMLError):
        return None
    return parsed if isinstance(parsed, Mapping) else None


def _first_existing_file(root: Path, names: tuple[str, ...]) -> Path | None:
    for name in names:
        path = root / name
        if path.is_file():
            return path
    return None


def _existing_files(root: Path, names: tuple[str, ...]) -> list[Path]:
    return [path for name in names if (path := root / name).is_file()]


def _load_compose_yaml(path: Path) -> object:
    return yaml.load(path.read_text(encoding="utf-8"), Loader=_ComposeLoader) or {}  # noqa: S506


def _merge_compose_value(base: object, override: object, *, key: str | None = None) -> object:
    if isinstance(override, _ComposeTaggedValue):
        if override.tag == "!reset":
            return _compose_reset_value(override.value)
        if override.tag == "!override":
            return override.value
        override = override.value
    if isinstance(base, _ComposeTaggedValue):
        base = base.value

    if isinstance(base, Mapping) and isinstance(override, Mapping):
        merged: dict[str, Any] = {
            str(base_key): base_value for base_key, base_value in base.items()
        }
        for override_key, override_value in override.items():
            key_text = str(override_key)
            merged[key_text] = _merge_compose_value(
                merged.get(key_text),
                override_value,
                key=key_text,
            )
        return merged
    if isinstance(base, list) and isinstance(override, list):
        return _merge_compose_sequence(base, override, key=key)
    return override


def _compose_reset_value(value: object) -> object:
    if isinstance(value, list):
        return []
    if isinstance(value, Mapping):
        return {}
    return None


def _merge_compose_sequence(
    base: list[object],
    override: list[object],
    *,
    key: str | None,
) -> list[object]:
    if key == "ports":
        return _merge_compose_unique_sequence(base, override, _compose_port_unique_key)
    if key in {"volumes", "secrets", "configs"}:
        return _merge_compose_unique_sequence(base, override, _compose_target_unique_key)
    return [*base, *override]


def _merge_compose_unique_sequence(
    base: list[object],
    override: list[object],
    key_fn: Callable[[object], object | None],
) -> list[object]:
    merged = list(base)
    key_to_index: dict[object, int] = {}
    for index, item in enumerate(merged):
        item_key = key_fn(item)
        if item_key is not None:
            key_to_index[item_key] = index
    for item in override:
        item_key = key_fn(item)
        if item_key is not None and item_key in key_to_index:
            merged[key_to_index[item_key]] = item
        else:
            if item_key is not None:
                key_to_index[item_key] = len(merged)
            merged.append(item)
    return merged


def _compose_port_unique_key(value: object) -> tuple[str, str, str, str] | None:
    if isinstance(value, Mapping):
        target = _string(value.get("target"))
        published = _string(value.get("published")) or ""
        protocol = _string(value.get("protocol")) or "tcp"
        ip = _string(value.get("host_ip") or value.get("ip")) or ""
        return (ip, target, published, protocol) if target else None
    if not isinstance(value, str):
        return None
    port = value.strip()
    if not port:
        return None
    without_protocol, _, protocol = port.partition("/")
    protocol = protocol or "tcp"
    parts = without_protocol.split(":")
    target = parts[-1] if parts else ""
    published = parts[-2] if len(parts) >= 2 else ""
    ip = ":".join(parts[:-2]) if len(parts) > 2 else ""
    return (ip, target, published, protocol) if target else None


def _compose_target_unique_key(value: object) -> str | None:
    if isinstance(value, Mapping):
        return _string(value.get("target"))
    if not isinstance(value, str):
        return None
    parts = value.split(":")
    if len(parts) < 2:
        return None
    return parts[1].strip() or None


def _compose_service_spec(
    service_id: str,
    raw_service: Mapping[str, Any],
    *,
    index: int,
) -> PipelineServiceSpec | None:
    safe_id = _safe_service_id(service_id)
    if not _is_application_compose_service(safe_id, raw_service):
        return None
    port = _compose_internal_port(raw_service)
    if port <= 0:
        return None
    return PipelineServiceSpec(
        service_id=safe_id or f"service-{index}",
        name=_string(raw_service.get("container_name")) or safe_id or f"service-{index}",
        start_command=f"docker compose up -d {shlex.quote(service_id)}",
        internal_port=port,
        health_path=_compose_health_path(raw_service),
        required=True,
        auto_open=True,
    )


def _is_application_compose_service(
    service_id: str,
    raw_service: Mapping[str, Any],
) -> bool:
    normalized = service_id.lower()
    if normalized in _INFRA_COMPOSE_SERVICE_IDS or normalized.startswith("drone-"):
        return False
    if normalized.endswith(("-db", "-redis", "-postgres", "-nginx", "-proxy")):
        return False
    return raw_service.get("build") is not None


def _compose_internal_port(raw_service: Mapping[str, Any]) -> int:
    raw_ports = raw_service.get("ports")
    if isinstance(raw_ports, list):
        for item in raw_ports:
            port = _compose_port_target(item)
            if port > 0:
                return port
    raw_expose = raw_service.get("expose")
    if isinstance(raw_expose, list):
        for item in raw_expose:
            port = _positive_int(item, 0)
            if port > 0:
                return port
    return 0


def _compose_port_target(value: object) -> int:
    if isinstance(value, Mapping):
        target = _positive_int(value.get("target"), 0)
        return target or _positive_int(value.get("published"), 0)
    if isinstance(value, int):
        return value
    if not isinstance(value, str):
        return 0
    without_protocol = value.split("/", 1)[0]
    target_text = without_protocol.rsplit(":", 1)[-1]
    return _positive_int(target_text, 0)


def _compose_health_path(raw_service: Mapping[str, Any]) -> str:
    raw_healthcheck = raw_service.get("healthcheck")
    if not isinstance(raw_healthcheck, Mapping):
        return "/"
    raw_test = raw_healthcheck.get("test")
    if isinstance(raw_test, list):
        command = " ".join(str(part) for part in raw_test)
    elif isinstance(raw_test, str):
        command = raw_test
    else:
        return "/"
    match = re.search(r"https?://[^\s'\"<>]+", command)
    if not match:
        return "/"
    path = urlsplit(match.group(0)).path
    return _normalize_path(path or "/")


def _should_prefer_compose_services(
    services: list[PipelineServiceSpec],
    compose_services: list[PipelineServiceSpec],
) -> bool:
    if not compose_services:
        return False
    if not services:
        return True
    if len(compose_services) <= len(services):
        return False
    return len(compose_services) > 1


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
        "elif [ -f package.json ]; then "
        "if node -e \"const p=require('./package.json');"
        'process.exit(p.scripts&&p.scripts.test?0:1)"; '
        "then npm test -- --runInBand=false 2>/dev/null || npm test; "
        "else echo 'no npm test script'; fi; "
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
    health_probe = ""
    if service is not None:
        health_url = shlex.quote(service.internal_health_url)
        health_probe = (
            f"curl -fsS {health_url} >/dev/null 2>&1 "
            "&& { echo 'service already healthy'; exit 0; }; "
        )
    return (
        "mkdir -p /tmp/memstack-workspace-preview && "
        f"{health_probe}"
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
        quoted_code_root = shlex.quote(code_root)
        lines.extend(
            [
                f"cd {quoted_code_root}",
                "code=$?",
                'if [ "$code" -ne 0 ]; then',
                (
                    "  printf 'workspace pipeline code_root is not accessible: %s\\n' "
                    f"{quoted_code_root} >&2"
                ),
                f'  printf "\\n{_EXIT_MARKER}%s\\n" "$code"',
                "  exit 0",
                "fi",
            ]
        )
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


def _normalize_provider(provider: str) -> str:
    normalized = provider.strip()
    if normalized in SANDBOX_NATIVE_PROVIDER_ALIASES:
        return SANDBOX_NATIVE_PROVIDER
    return normalized


def _normalize_deploy_mode(value: str | None) -> str:
    normalized = (value or DEFAULT_DRONE_DEPLOY_MODE).strip().lower()
    return normalized if normalized in DRONE_DEPLOY_MODES else DEFAULT_DRONE_DEPLOY_MODE


def _safe_stage_name(value: str | None) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.:-]+", "-", (value or DEFAULT_DRONE_DEPLOY_STAGE).strip())
    return normalized.strip("-") or DEFAULT_DRONE_DEPLOY_STAGE


def _json_mapping(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): item for key, item in value.items() if isinstance(key, str)}


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
    "DRONE_DEPLOY_MODES",
    "DRONE_DOCKER_DEPLOY_VALIDATION",
    "DRONE_PROVIDER",
    "PIPELINE_EVIDENCE_KEY",
    "SANDBOX_NATIVE_PROVIDER",
    "PipelineContractSpec",
    "PipelineDeploySpec",
    "PipelineRunResult",
    "PipelineServiceSpec",
    "PipelineStageResult",
    "PipelineStageSpec",
    "SandboxNativePipelineProvider",
    "WorkspacePipelineSandboxRunner",
    "build_pipeline_contract_from_metadata",
]
