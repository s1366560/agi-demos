"""Drone CI provider for software workspace delivery pipelines."""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import quote

import httpx

from src.infrastructure.agent.workspace_plan.pipeline import (
    DRONE_PROVIDER,
    PipelineContractSpec,
    PipelineRunResult,
    PipelineStageResult,
)

DRONE_SERVER_URL_ENV = "DRONE_SERVER_URL"
DRONE_TOKEN_ENV = "DRONE_TOKEN"
DRONE_TERMINAL_STATUSES = frozenset({"success", "failure", "error", "killed", "declined"})
DRONE_FAILED_STATUSES = frozenset({"failure", "error", "killed", "declined"})
DRONE_RUNNING_STATUSES = frozenset({"pending", "running", "blocked", "waiting"})
_DEFAULT_POLL_INTERVAL_SECONDS = 5
_HTTP_TIMEOUT_SECONDS = 30


class DroneConfigurationError(ValueError):
    """Raised when a workspace Drone contract is missing required configuration."""


class DroneClientProtocol(Protocol):
    async def create_build(
        self,
        *,
        owner: str,
        repo: str,
        branch: str | None,
        commit: str | None,
        params: Mapping[str, str],
    ) -> Mapping[str, Any]: ...

    async def get_build(self, *, owner: str, repo: str, build_number: int) -> Mapping[str, Any]: ...

    async def get_logs(
        self,
        *,
        owner: str,
        repo: str,
        build_number: int,
        stage: str,
        step: str,
    ) -> list[Mapping[str, Any]]: ...


@dataclass(frozen=True)
class DronePipelineConfig:
    owner: str
    repo: str
    server_url: str
    token: str
    branch: str | None = None
    commit: str | None = None
    target: str | None = None
    params: dict[str, str] = field(default_factory=dict)
    timeout_seconds: int = 600
    poll_interval_seconds: int = _DEFAULT_POLL_INTERVAL_SECONDS

    @classmethod
    def from_contract(cls, contract: PipelineContractSpec) -> DronePipelineConfig:
        raw = dict(contract.provider_config or {})
        repo_slug = _string(raw.get("repo") or raw.get("repository"))
        if not repo_slug or "/" not in repo_slug:
            raise DroneConfigurationError("delivery_cicd.drone.repo must be '<owner>/<repo>'")
        owner, repo = repo_slug.split("/", 1)
        owner = owner.strip()
        repo = repo.strip()
        if not owner or not repo:
            raise DroneConfigurationError("delivery_cicd.drone.repo must be '<owner>/<repo>'")

        server_url = _string(raw.get("server_url"))
        if not server_url:
            server_url = os.getenv(_string(raw.get("server_url_env")) or DRONE_SERVER_URL_ENV)
        if not server_url:
            raise DroneConfigurationError(f"{DRONE_SERVER_URL_ENV} is required for Drone CI/CD")

        token_env = _string(raw.get("token_env")) or DRONE_TOKEN_ENV
        token = os.getenv(token_env)
        if not token:
            raise DroneConfigurationError(f"{token_env} is required for Drone CI/CD")

        params = _string_mapping(raw.get("params") or raw.get("build_params"))
        target = _string(raw.get("target"))
        if target:
            params.setdefault("target", target)

        return cls(
            owner=owner,
            repo=repo,
            server_url=server_url.rstrip("/"),
            token=token,
            branch=_string(raw.get("branch")),
            commit=_string(raw.get("commit")),
            target=target,
            params=params,
            timeout_seconds=max(1, int(contract.timeout_seconds or 600)),
            poll_interval_seconds=max(
                1,
                _positive_int(raw.get("poll_interval_seconds"), _DEFAULT_POLL_INTERVAL_SECONDS),
            ),
        )

    @property
    def repo_slug(self) -> str:
        return f"{self.owner}/{self.repo}"

    def build_url(self, build_number: int) -> str:
        owner = quote(self.owner, safe="")
        repo = quote(self.repo, safe="")
        return f"{self.server_url}/{owner}/{repo}/{build_number}"


class HttpDroneClient:
    """Small Drone API client for build trigger, polling, and log capture."""

    def __init__(
        self,
        *,
        server_url: str,
        token: str,
        timeout_seconds: int = _HTTP_TIMEOUT_SECONDS,
    ) -> None:
        self._server_url = server_url.rstrip("/")
        self._token = token
        self._timeout_seconds = timeout_seconds

    async def create_build(
        self,
        *,
        owner: str,
        repo: str,
        branch: str | None,
        commit: str | None,
        params: Mapping[str, str],
    ) -> Mapping[str, Any]:
        query = dict(params)
        if branch:
            query["branch"] = branch
        if commit:
            query["commit"] = commit
        raw = await self._request("POST", _build_path(owner, repo, "builds"), params=query)
        if isinstance(raw, Mapping):
            return raw
        raise DroneConfigurationError("Drone create build response was not an object")

    async def get_build(self, *, owner: str, repo: str, build_number: int) -> Mapping[str, Any]:
        raw = await self._request("GET", _build_path(owner, repo, "builds", str(build_number)))
        if isinstance(raw, Mapping):
            return raw
        raise DroneConfigurationError("Drone build response was not an object")

    async def get_logs(
        self,
        *,
        owner: str,
        repo: str,
        build_number: int,
        stage: str,
        step: str,
    ) -> list[Mapping[str, Any]]:
        path = _build_path(owner, repo, "builds", str(build_number), "logs", stage, step)
        raw = await self._request("GET", path)
        return list(raw) if isinstance(raw, list) else []

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, str] | None = None,
    ) -> object:
        headers = {"Authorization": f"Bearer {self._token}"}
        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            response = await client.request(
                method,
                f"{self._server_url}{path}",
                headers=headers,
                params=dict(params or {}),
            )
        response.raise_for_status()
        return response.json()


class DronePipelineProvider:
    """Runs a workspace delivery contract through Drone's remote build API."""

    def __init__(
        self,
        *,
        client: DroneClientProtocol | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._client = client
        self._sleep = sleep

    async def run(self, contract: PipelineContractSpec) -> PipelineRunResult:
        try:
            config = DronePipelineConfig.from_contract(contract)
        except DroneConfigurationError as exc:
            return _configuration_failure(str(exc))

        client = self._client or HttpDroneClient(server_url=config.server_url, token=config.token)
        try:
            created = await client.create_build(
                owner=config.owner,
                repo=config.repo,
                branch=config.branch,
                commit=config.commit,
                params=config.params,
            )
            build_number = _required_int(created.get("number"), "Drone build number")
            build = await self._poll_build(client=client, config=config, build_number=build_number)
            return await _result_from_build(client=client, config=config, build=build)
        except Exception as exc:
            return _provider_failure(str(exc))

    async def _poll_build(
        self,
        *,
        client: DroneClientProtocol,
        config: DronePipelineConfig,
        build_number: int,
    ) -> Mapping[str, Any]:
        deadline = time.monotonic() + config.timeout_seconds
        latest: Mapping[str, Any] | None = None
        while time.monotonic() <= deadline:
            latest = await client.get_build(
                owner=config.owner,
                repo=config.repo,
                build_number=build_number,
            )
            status = _status(latest.get("status"))
            if status in DRONE_TERMINAL_STATUSES:
                return latest
            await self._sleep(float(config.poll_interval_seconds))
        if latest is None:
            latest = {"number": build_number, "status": "timeout", "stages": []}
        return {**dict(latest), "status": "timeout"}


async def _result_from_build(
    *,
    client: DroneClientProtocol,
    config: DronePipelineConfig,
    build: Mapping[str, Any],
) -> PipelineRunResult:
    build_number = _required_int(build.get("number"), "Drone build number")
    external_id = f"{config.repo_slug}#{build_number}"
    external_url = config.build_url(build_number)
    drone_status = _status(build.get("status"))
    run_status = _internal_status(drone_status)
    reason = _failure_reason(drone_status, external_id)
    stage_results = await _stage_results(
        client=client,
        config=config,
        build_number=build_number,
        build=build,
        external_url=external_url,
    )
    evidence_refs = [
        f"ci_pipeline:{'passed' if run_status == 'success' else 'failed'}",
        f"drone_build:{drone_status}:{external_id}",
        f"pipeline_external:{DRONE_PROVIDER}:{external_id}",
    ]
    for stage in stage_results:
        evidence_refs.append(f"pipeline_stage:{stage.stage}:{stage.status}")
    return PipelineRunResult(
        status=run_status,
        reason=reason,
        stage_results=tuple(stage_results),
        evidence_refs=tuple(dict.fromkeys(evidence_refs)),
        external_id=external_id,
        external_url=external_url,
        metadata={
            "external_provider": DRONE_PROVIDER,
            "external_id": external_id,
            "external_url": external_url,
            "drone_build_number": build_number,
            "drone_repo": config.repo_slug,
            "drone_status": drone_status,
            "drone_link": _string(build.get("link")),
        },
    )


async def _stage_results(
    *,
    client: DroneClientProtocol,
    config: DronePipelineConfig,
    build_number: int,
    build: Mapping[str, Any],
    external_url: str,
) -> list[PipelineStageResult]:
    raw_stages = build.get("stages")
    if not isinstance(raw_stages, list) or not raw_stages:
        return [
            _pipeline_stage_result(
                stage_name="drone",
                step_name="build",
                status=_status(build.get("status")),
                exit_code=_optional_int(build.get("exit_code")),
                log_text="",
                log_ref=f"drone://{config.repo_slug}/{build_number}/build",
                external_url=external_url,
            )
        ]

    output: list[PipelineStageResult] = []
    for stage in raw_stages:
        if not isinstance(stage, Mapping):
            continue
        stage_name = _string(stage.get("name")) or f"stage-{len(output) + 1}"
        raw_steps = stage.get("steps")
        if isinstance(raw_steps, list) and raw_steps:
            for step in raw_steps:
                if not isinstance(step, Mapping):
                    continue
                step_name = _string(step.get("name")) or f"step-{len(output) + 1}"
                output.append(
                    await _step_result(
                        client=client,
                        config=config,
                        build_number=build_number,
                        stage_name=stage_name,
                        step_name=step_name,
                        step=step,
                        external_url=external_url,
                    )
                )
        else:
            output.append(
                _pipeline_stage_result(
                    stage_name=stage_name,
                    step_name=stage_name,
                    status=_status(stage.get("status")),
                    exit_code=_optional_int(stage.get("exit_code")),
                    log_text="",
                    log_ref=f"drone://{config.repo_slug}/{build_number}/{stage_name}",
                    external_url=external_url,
                )
            )
    return output


async def _step_result(
    *,
    client: DroneClientProtocol,
    config: DronePipelineConfig,
    build_number: int,
    stage_name: str,
    step_name: str,
    step: Mapping[str, Any],
    external_url: str,
) -> PipelineStageResult:
    log_ref = f"drone://{config.repo_slug}/{build_number}/{stage_name}/{step_name}"
    try:
        logs = await client.get_logs(
            owner=config.owner,
            repo=config.repo,
            build_number=build_number,
            stage=stage_name,
            step=step_name,
        )
        log_text = _logs_text(logs)
    except Exception:
        log_text = ""
    return _pipeline_stage_result(
        stage_name=stage_name,
        step_name=step_name,
        status=_status(step.get("status")),
        exit_code=_optional_int(step.get("exit_code")),
        log_text=log_text,
        log_ref=log_ref,
        external_url=external_url,
    )


def _pipeline_stage_result(
    *,
    stage_name: str,
    step_name: str,
    status: str,
    exit_code: int | None,
    log_text: str,
    log_ref: str,
    external_url: str,
) -> PipelineStageResult:
    internal_status = _internal_status(status)
    stage_label = _stage_label(stage_name=stage_name, step_name=step_name)
    compact_log = _compact(log_text)
    return PipelineStageResult(
        stage=stage_label,
        status=internal_status,
        command=f"drone:{stage_name}/{step_name}",
        exit_code=exit_code,
        stdout_preview=compact_log if internal_status == "success" else "",
        stderr_preview=compact_log if internal_status == "failed" else "",
        log_ref=log_ref,
        artifact_refs=(f"drone_build:{external_url}",),
        metadata={
            "external_provider": DRONE_PROVIDER,
            "external_url": external_url,
            "drone_stage": stage_name,
            "drone_step": step_name,
            "drone_status": status,
        },
    )


def _configuration_failure(message: str) -> PipelineRunResult:
    return PipelineRunResult(
        status="failed",
        reason=message,
        stage_results=(
            PipelineStageResult(
                stage="drone_config",
                status="failed",
                command="drone:configure",
                exit_code=1,
                stderr_preview=message,
                metadata={"external_provider": DRONE_PROVIDER},
            ),
        ),
        evidence_refs=("ci_pipeline:failed", "drone:configuration_failed"),
        metadata={"external_provider": DRONE_PROVIDER, "configuration_error": message},
    )


def _provider_failure(message: str) -> PipelineRunResult:
    preview = _compact(message)
    return PipelineRunResult(
        status="failed",
        reason=preview,
        stage_results=(
            PipelineStageResult(
                stage="drone_api",
                status="failed",
                command="drone:api",
                exit_code=1,
                stderr_preview=preview,
                metadata={"external_provider": DRONE_PROVIDER},
            ),
        ),
        evidence_refs=("ci_pipeline:failed", "drone:api_failed"),
        metadata={"external_provider": DRONE_PROVIDER, "provider_error": preview},
    )


def _build_path(owner: str, repo: str, *parts: str) -> str:
    encoded = [quote(part, safe="") for part in (owner, repo, *parts)]
    return "/api/repos/" + "/".join(encoded)


def _status(value: object) -> str:
    return value.strip().lower() if isinstance(value, str) and value.strip() else "unknown"


def _internal_status(status: str) -> str:
    if status == "success":
        return "success"
    if status in DRONE_RUNNING_STATUSES:
        return "running"
    return "failed"


def _failure_reason(status: str, external_id: str) -> str | None:
    if status == "success":
        return None
    if status == "timeout":
        return f"Drone build {external_id} timed out"
    if status in DRONE_FAILED_STATUSES:
        return f"Drone build {external_id} finished with status {status}"
    return f"Drone build {external_id} did not complete successfully: {status}"


def _stage_label(*, stage_name: str, step_name: str) -> str:
    label = step_name if stage_name == step_name else f"{stage_name}/{step_name}"
    return label[:40]


def _string(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _string_mapping(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    return {
        str(key): str(item)
        for key, item in value.items()
        if isinstance(key, str) and item is not None
    }


def _positive_int(value: object, fallback: int) -> int:
    if isinstance(value, int):
        return value if value > 0 else fallback
    if isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
        return parsed if parsed > 0 else fallback
    return fallback


def _required_int(value: object, label: str) -> int:
    parsed = _optional_int(value)
    if parsed is None:
        raise DroneConfigurationError(f"{label} missing from Drone API response")
    return parsed


def _optional_int(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _logs_text(logs: list[Mapping[str, Any]]) -> str:
    return "".join(str(item.get("out") or "") for item in logs)


def _compact(value: str, *, limit: int = 4000) -> str:
    compacted = value.strip()
    if len(compacted) <= limit:
        return compacted
    return compacted[: limit - 15] + "...[truncated]"


__all__ = [
    "DRONE_PROVIDER",
    "DroneClientProtocol",
    "DroneConfigurationError",
    "DronePipelineConfig",
    "DronePipelineProvider",
    "HttpDroneClient",
]
