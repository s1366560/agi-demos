"""Drone CI provider for software workspace delivery pipelines."""

from __future__ import annotations

import asyncio
import os
import re
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote

import httpx
import yaml
from dotenv import dotenv_values

from src.infrastructure.agent.workspace_plan.pipeline import (
    DRONE_DOCKER_DEPLOY_VALIDATION,
    DRONE_PROVIDER,
    PipelineContractSpec,
    PipelineDeploySpec,
    PipelineRunResult,
    PipelineStageResult,
)

DRONE_SERVER_URL_ENV = "DRONE_SERVER_URL"
DRONE_TOKEN_ENV = "DRONE_TOKEN"
DRONE_DOTENV_PATH_ENV = "MEMSTACK_DRONE_DOTENV_PATH"
DRONE_TERMINAL_STATUSES = frozenset({"success", "failure", "error", "killed", "declined"})
DRONE_FAILED_STATUSES = frozenset({"failure", "error", "killed", "declined"})
DRONE_RUNNING_STATUSES = frozenset({"pending", "running", "blocked", "waiting"})
_DEFAULT_POLL_INTERVAL_SECONDS = 5
_HTTP_TIMEOUT_SECONDS = 30
_DOCKER_LOCAL_REGISTRY_PULL_OR_RUN_RE = re.compile(
    r"\bdocker(?:\s+container)?\s+(?:pull|run)\b[^\n;&|]*(?<!://)"
    r"(?:host\.docker\.internal|localhost|127\.0\.0\.1|\[?::1\]?)(?::\d+)?/",
    re.I,
)
_DOCKER_BUILD_COMMAND_RE = re.compile(r"\bdocker\s+(?:build|buildx\s+build)\b", re.I)
_DOCKER_BUILD_TAG_ARG_RE = re.compile(r"(?:^|\s)(?:-t|--tag)\s+(?P<image>[^\s\\]+)", re.I)
_DOCKER_BUILD_STEP_SERVICE_RE = re.compile(
    r"(?:^|[-_/])docker[-_]?build[-_/](?P<service>[a-z0-9][a-z0-9_.-]*)$",
    re.I,
)
_DOCKER_DEPLOY_CONTAINER_RUNNING_RE = re.compile(
    r"\bcontainer\s+[a-z0-9_.-]+\s+is\s+running\b",
    re.I,
)
_DOCKER_PS_RUNNING_ROW_RE = re.compile(r"\bup\s+(?:less than|about|\d)", re.I)
_FAILURE_SIGNAL_MARKERS = (
    "http: server gave http response to https client",
    "connection refused",
    "can't connect to remote host",
    "cannot connect to remote host",
    "connection reset",
    "no route to host",
    "exited (",
    "cannot find module",
    "module_not_found",
    "environment variable not found",
    "database_url",
    "redis_url",
    "postgres_password",
    "no migration found",
    "prisma schema validation",
    "error code: p1001",
    "error code: p1012",
    "bind for 0.0.0.0",
    "port is already allocated",
    "container name",
    "already in use",
)
_HIGH_VALUE_FAILURE_SIGNAL_MARKERS = (
    "docker:",
    "error response from daemon",
    "failed to set up container networking",
    "bind for 0.0.0.0",
    "port is already allocated",
    "already in use",
    "connection refused",
    "can't connect to remote host",
    "cannot connect to remote host",
    "no route to host",
    "exited (",
    "cannot find module",
    "module_not_found",
    "environment variable not found",
    "no migration found",
    "prisma schema validation",
    "error code:",
)


class DroneConfigurationError(ValueError):
    """Raised when a workspace Drone contract is missing required configuration."""


class DroneRepositoryNotFoundError(DroneConfigurationError):
    """Raised when Drone has not registered the configured repository yet."""


class DroneClientProtocol(Protocol):
    async def get_repo(self, *, owner: str, repo: str) -> Mapping[str, Any]: ...

    async def enable_repo(self, *, owner: str, repo: str) -> Mapping[str, Any]: ...

    async def update_repo(
        self,
        *,
        owner: str,
        repo: str,
        trusted: bool | None = None,
    ) -> Mapping[str, Any]: ...

    async def create_build(
        self,
        *,
        owner: str,
        repo: str,
        branch: str | None,
        commit: str | None,
        params: Mapping[str, str],
    ) -> Mapping[str, Any]: ...

    async def list_builds(
        self,
        *,
        owner: str,
        repo: str,
        per_page: int = 25,
    ) -> list[Mapping[str, Any]]: ...

    async def get_build(self, *, owner: str, repo: str, build_number: int) -> Mapping[str, Any]: ...

    async def stop_build(
        self, *, owner: str, repo: str, build_number: int
    ) -> Mapping[str, Any]: ...

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
    deploy: PipelineDeploySpec | None = None
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
            server_url_env = _string(raw.get("server_url_env")) or DRONE_SERVER_URL_ENV
            server_url = _config_env(server_url_env) or _server_url_from_environment(
                raw.get("environment")
            )
        if not server_url:
            raise DroneConfigurationError(f"{DRONE_SERVER_URL_ENV} is required for Drone CI/CD")

        token_env = _string(raw.get("token_env")) or DRONE_TOKEN_ENV
        token = _config_env(token_env)
        if not token:
            raise DroneConfigurationError(f"{token_env} is required for Drone CI/CD")

        deploy = contract.deploy if contract.deploy and contract.deploy.enabled else None
        params = _string_mapping(raw.get("params") or raw.get("build_params"))
        target = _string(raw.get("target")) or (deploy.target if deploy is not None else None)
        if target:
            params.setdefault("target", target)
        _add_deploy_params(params, deploy)

        return cls(
            owner=owner,
            repo=repo,
            server_url=server_url.rstrip("/"),
            token=token,
            branch=_string(raw.get("branch")),
            commit=_string(raw.get("commit")),
            target=target,
            params=params,
            deploy=deploy,
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


DroneBuildCleanup = Callable[[DronePipelineConfig, int], Awaitable[Mapping[str, Any]]]


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

    async def get_repo(self, *, owner: str, repo: str) -> Mapping[str, Any]:
        try:
            raw = await self._request("GET", _build_path(owner, repo))
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                raise DroneRepositoryNotFoundError(
                    f"Drone repo {owner}/{repo} is not enabled"
                ) from exc
            raise
        if isinstance(raw, Mapping):
            return raw
        raise DroneConfigurationError("Drone repo response was not an object")

    async def enable_repo(self, *, owner: str, repo: str) -> Mapping[str, Any]:
        raw = await self._request("POST", _build_path(owner, repo))
        if isinstance(raw, Mapping):
            return raw
        raise DroneConfigurationError("Drone repo enable response was not an object")

    async def update_repo(
        self,
        *,
        owner: str,
        repo: str,
        trusted: bool | None = None,
    ) -> Mapping[str, Any]:
        payload: dict[str, Any] = {}
        if trusted is not None:
            payload["trusted"] = trusted
        raw = await self._request("PATCH", _build_path(owner, repo), json_body=payload)
        if isinstance(raw, Mapping):
            return raw
        raise DroneConfigurationError("Drone repo update response was not an object")

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

    async def list_builds(
        self,
        *,
        owner: str,
        repo: str,
        per_page: int = 25,
    ) -> list[Mapping[str, Any]]:
        raw = await self._request(
            "GET",
            _build_path(owner, repo, "builds"),
            params={"per_page": str(per_page)},
        )
        if not isinstance(raw, list):
            return []
        return [dict(item) for item in raw if isinstance(item, Mapping)]

    async def stop_build(self, *, owner: str, repo: str, build_number: int) -> Mapping[str, Any]:
        raw = await self._request("DELETE", _build_path(owner, repo, "builds", str(build_number)))
        if isinstance(raw, Mapping):
            return raw
        return {"number": build_number, "status": "killed"}

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
        json_body: Mapping[str, Any] | None = None,
    ) -> object:
        headers = {"Authorization": f"Bearer {self._token}"}
        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            response = await client.request(
                method,
                f"{self._server_url}{path}",
                headers=headers,
                params=dict(params or {}),
                json=dict(json_body or {}) if json_body is not None else None,
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
        cleanup_build: DroneBuildCleanup | None = None,
    ) -> None:
        self._client = client
        self._sleep = sleep
        self._cleanup_build = cleanup_build or _cleanup_local_drone_build_containers

    async def run(self, contract: PipelineContractSpec) -> PipelineRunResult:
        try:
            config = DronePipelineConfig.from_contract(contract)
        except DroneConfigurationError as exc:
            return _configuration_failure(str(exc))

        preflight_failure = _drone_yaml_preflight_failure(contract)
        if preflight_failure is not None:
            return preflight_failure

        client = self._client or HttpDroneClient(server_url=config.server_url, token=config.token)
        try:
            await _ensure_repo_enabled(client=client, config=config)
            await _ensure_docker_deploy_repo_trusted(client=client, config=config)
            running_build = await _running_build_for_commit(client=client, config=config)
            if running_build is None:
                created = await client.create_build(
                    owner=config.owner,
                    repo=config.repo,
                    branch=config.branch,
                    commit=config.commit,
                    params=config.params,
                )
                build_number = _required_int(created.get("number"), "Drone build number")
            else:
                build_number = _required_int(running_build.get("number"), "Drone build number")
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
        timeout_build = dict(latest)
        try:
            stopped = await client.stop_build(
                owner=config.owner,
                repo=config.repo,
                build_number=build_number,
            )
        except Exception as exc:
            timeout_build["drone_stop_error"] = str(exc)
        else:
            timeout_build = {
                **dict(stopped),
                "drone_stop_status": _status(stopped.get("status")),
            }
        cleanup = await self._cleanup_build(config, build_number)
        if cleanup:
            timeout_build["drone_cleanup"] = dict(cleanup)
        return {**timeout_build, "status": "timeout"}


async def _ensure_repo_enabled(
    *,
    client: DroneClientProtocol,
    config: DronePipelineConfig,
) -> None:
    try:
        repo = await client.get_repo(owner=config.owner, repo=config.repo)
    except DroneRepositoryNotFoundError:
        _ = await client.enable_repo(owner=config.owner, repo=config.repo)
        return
    if repo.get("active") is False:
        _ = await client.enable_repo(owner=config.owner, repo=config.repo)


async def _ensure_docker_deploy_repo_trusted(
    *,
    client: DroneClientProtocol,
    config: DronePipelineConfig,
) -> None:
    if not _docker_deploy_requires_trusted_repo(config.deploy):
        return
    repo = await client.get_repo(owner=config.owner, repo=config.repo)
    if repo.get("trusted") is True:
        return
    updated = await client.update_repo(owner=config.owner, repo=config.repo, trusted=True)
    if updated.get("trusted") is not True:
        raise DroneConfigurationError(
            f"Drone repo {config.repo_slug} must be trusted for docker deploy host volumes"
        )


async def _running_build_for_commit(
    *,
    client: DroneClientProtocol,
    config: DronePipelineConfig,
) -> Mapping[str, Any] | None:
    if not config.commit:
        return None
    try:
        builds = await client.list_builds(owner=config.owner, repo=config.repo, per_page=25)
    except Exception:
        return None
    for build in builds:
        if _status(build.get("status")) not in DRONE_RUNNING_STATUSES:
            continue
        if _build_matches_commit(build, config.commit):
            return build
    return None


def _build_matches_commit(build: Mapping[str, Any], commit: str) -> bool:
    for key in ("after", "commit", "sha"):
        value = _string(build.get(key))
        if value and (value == commit or value.startswith(commit) or commit.startswith(value)):
            return True
    return False


def _docker_deploy_requires_trusted_repo(deploy: PipelineDeploySpec | None) -> bool:
    if deploy is None or deploy.mode != "docker":
        return False
    value = deploy.docker.get("trusted") if isinstance(deploy.docker, Mapping) else None
    return value is not False


async def _cleanup_local_drone_build_containers(
    config: DronePipelineConfig,
    build_number: int,
) -> Mapping[str, Any]:
    try:
        ps = await _run_process(
            "docker",
            "ps",
            "-aq",
            "--filter",
            "label=io.drone=true",
            "--filter",
            f"label=io.drone.repo.slug={config.repo_slug}",
            "--filter",
            f"label=io.drone.build.number={build_number}",
        )
    except OSError as exc:
        return {"cleanup_error": str(exc)}
    container_ids = [line.strip() for line in ps["stdout"].splitlines() if line.strip()]
    if not container_ids:
        return {"removed_container_count": 0}
    try:
        rm = await _run_process("docker", "rm", "-f", *container_ids)
    except OSError as exc:
        return {
            "removed_container_count": 0,
            "cleanup_error": str(exc),
            "container_ids": container_ids[:20],
        }
    return {
        "removed_container_count": len(container_ids),
        "container_ids": container_ids[:20],
        "stdout_preview": _compact_text(rm["stdout"], limit=400),
        "stderr_preview": _compact_text(rm["stderr"], limit=400),
    }


async def _run_process(*args: str) -> dict[str, str]:
    process = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    return {
        "stdout": stdout.decode(errors="replace"),
        "stderr": stderr.decode(errors="replace"),
        "returncode": str(process.returncode),
    }


def _compact_text(value: str, *, limit: int) -> str:
    normalized = value.strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(0, limit - 3)].rstrip() + "..."


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
        deploy=config.deploy,
    )
    deploy_state = _deploy_state(stage_results, config.deploy)
    deploy_validation_issues = (
        _deploy_validation_issues(stage_results, config.deploy)
        if deploy_state == "invalid"
        else []
    )
    if (
        config.deploy is not None
        and deploy_state in {"failed", "missing", "invalid"}
        and config.deploy.required
        and run_status == "success"
    ):
        run_status = "failed"
        reason = _deploy_failure_reason(
            config.deploy,
            external_id,
            deploy_state,
            validation_issues=deploy_validation_issues,
        )
    evidence_refs = [
        f"ci_pipeline:{'passed' if run_status == 'success' else 'failed'}",
        f"drone_build:{drone_status}:{external_id}",
        f"pipeline_external:{DRONE_PROVIDER}:{external_id}",
    ]
    for stage in stage_results:
        evidence_refs.append(f"pipeline_stage:{stage.stage}:{stage.status}")
    if config.deploy is not None and deploy_state is not None:
        evidence_refs.append(
            f"deployment:{'passed' if deploy_state == 'passed' else deploy_state}:{config.deploy.mode}"
        )
        if config.deploy.target:
            evidence_refs.append(f"deployment_target:{config.deploy.target}")
    return PipelineRunResult(
        status=run_status,
        reason=reason,
        stage_results=tuple(stage_results),
        evidence_refs=tuple(dict.fromkeys(evidence_refs)),
        external_id=external_id,
        external_url=external_url,
        deployment_status=_deployment_status(deploy_state),
        metadata={
            "external_provider": DRONE_PROVIDER,
            "external_id": external_id,
            "external_url": external_url,
            "drone_build_number": build_number,
            "drone_repo": config.repo_slug,
            "drone_status": drone_status,
            "drone_link": _string(build.get("link")),
            **_drone_timeout_metadata(build),
            **_deploy_metadata(
                config.deploy,
                deploy_state,
                validation_issues=deploy_validation_issues,
            ),
        },
    )


def _drone_timeout_metadata(build: Mapping[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for key in ("drone_stop_status", "drone_stop_error", "drone_cleanup"):
        value = build.get(key)
        if value:
            metadata[key] = dict(value) if isinstance(value, Mapping) else value
    return metadata


async def _stage_results(
    *,
    client: DroneClientProtocol,
    config: DronePipelineConfig,
    build_number: int,
    build: Mapping[str, Any],
    external_url: str,
    deploy: PipelineDeploySpec | None,
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
                error_text=_string(build.get("error")),
                log_ref=f"drone://{config.repo_slug}/{build_number}/build",
                external_url=external_url,
                deploy=deploy,
                step_image=None,
            )
        ]

    output: list[PipelineStageResult] = []
    for stage in raw_stages:
        if not isinstance(stage, Mapping):
            continue
        stage_name = _string(stage.get("name")) or f"stage-{len(output) + 1}"
        stage_log_ref = _log_part(stage.get("number")) or stage_name
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
                        stage_log_ref=stage_log_ref,
                        step_name=step_name,
                        step=step,
                        external_url=external_url,
                        deploy=deploy,
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
                    error_text=_string(stage.get("error")),
                    log_ref=f"drone://{config.repo_slug}/{build_number}/{stage_name}",
                    external_url=external_url,
                    deploy=deploy,
                    step_image=None,
                )
            )
    return output


async def _step_result(
    *,
    client: DroneClientProtocol,
    config: DronePipelineConfig,
    build_number: int,
    stage_name: str,
    stage_log_ref: str,
    step_name: str,
    step: Mapping[str, Any],
    external_url: str,
    deploy: PipelineDeploySpec | None,
) -> PipelineStageResult:
    log_ref = f"drone://{config.repo_slug}/{build_number}/{stage_name}/{step_name}"
    try:
        step_log_ref = _log_part(step.get("number")) or step_name
        logs = await client.get_logs(
            owner=config.owner,
            repo=config.repo,
            build_number=build_number,
            stage=stage_log_ref,
            step=step_log_ref,
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
        error_text=_string(step.get("error")),
        log_ref=log_ref,
        external_url=external_url,
        deploy=deploy,
        step_image=_string(step.get("image")),
    )


def _pipeline_stage_result(
    *,
    stage_name: str,
    step_name: str,
    status: str,
    exit_code: int | None,
    log_text: str,
    error_text: str | None,
    log_ref: str,
    external_url: str,
    deploy: PipelineDeploySpec | None = None,
    step_image: str | None = None,
) -> PipelineStageResult:
    internal_status = _internal_status(status)
    stage_label = _stage_label(stage_name=stage_name, step_name=step_name)
    compact_log = (
        _compact_failure_preview(log_text) if internal_status == "failed" else _compact(log_text)
    )
    compact_error = _compact(error_text or "")
    metadata = {
        "external_provider": DRONE_PROVIDER,
        "external_url": external_url,
        "drone_stage": stage_name,
        "drone_step": step_name,
        "drone_status": status,
    }
    if compact_error:
        metadata["drone_error"] = compact_error
    if step_image:
        metadata["drone_image"] = step_image
    if _is_deploy_stage(stage_name=stage_name, step_name=step_name, deploy=deploy):
        metadata["drone_step_kind"] = "deploy"
        if deploy is not None:
            metadata["deploy_mode"] = deploy.mode
            metadata["deploy_stage"] = deploy.stage
            if deploy.target:
                metadata["deploy_target"] = deploy.target
    failure_preview = _combine_failure_preview(compact_error, compact_log)
    return PipelineStageResult(
        stage=stage_label,
        status=internal_status,
        command=f"drone:{stage_name}/{step_name}",
        exit_code=exit_code,
        stdout_preview=compact_log if internal_status == "success" else "",
        stderr_preview=failure_preview if internal_status == "failed" else "",
        log_ref=log_ref,
        artifact_refs=(f"drone_build:{external_url}",),
        metadata=metadata,
    )


def _combine_failure_preview(error_text: str, log_text: str) -> str:
    parts = []
    for text in (error_text, log_text):
        value = text.strip()
        if value and value not in parts:
            parts.append(value)
    return _compact_failure_preview("\n".join(parts))


def _compact_failure_preview(value: str, *, limit: int = 4000) -> str:
    compacted = value.strip()
    if len(compacted) <= limit:
        return compacted
    signal_preview = _failure_signal_preview(compacted)
    marker = "...[truncated]..."
    signal_prefix = f"failure_signals:\n{signal_preview}\n" if signal_preview else ""
    remaining = limit - len(signal_prefix) - len(marker)
    if remaining <= 20:
        return f"{signal_prefix}{compacted[-max(1, limit - len(signal_prefix)) :]}"[:limit]
    head_size = max(1, remaining // 2)
    tail_size = max(1, remaining - head_size)
    return f"{signal_prefix}{compacted[:head_size]}{marker}{compacted[-tail_size:]}"


def _failure_signal_preview(value: str, *, limit: int = 900) -> str:
    candidates: list[tuple[int, int, str]] = []
    seen: set[str] = set()
    for index, line in enumerate(value.splitlines()):
        normalized = line.strip()
        if not normalized:
            continue
        lower = normalized.lower()
        if not any(marker in lower for marker in _FAILURE_SIGNAL_MARKERS):
            continue
        capped = normalized[:320]
        if capped in seen:
            continue
        seen.add(capped)
        candidates.append((_failure_signal_rank(lower), index, capped))
    selected: list[str] = []
    for _, _, line in sorted(candidates):
        selected.append(line)
        joined = "\n".join(selected)
        if len(joined) >= limit:
            return joined[:limit]
    return "\n".join(selected)


def _failure_signal_rank(lower_line: str) -> int:
    if any(marker in lower_line for marker in _HIGH_VALUE_FAILURE_SIGNAL_MARKERS):
        return 0
    return 1


def _add_deploy_params(params: dict[str, str], deploy: PipelineDeploySpec | None) -> None:
    if deploy is None:
        return
    params.setdefault("MEMSTACK_DEPLOY_ENABLED", "true")
    params.setdefault("MEMSTACK_DEPLOY_MODE", deploy.mode)
    params.setdefault("MEMSTACK_DEPLOY_STAGE", deploy.stage)
    if deploy.target:
        params.setdefault("MEMSTACK_DEPLOY_TARGET", deploy.target)

    if deploy.mode == "docker":
        _add_prefixed_params(params, "MEMSTACK_DEPLOY_DOCKER", deploy.docker)
    elif deploy.mode == "kubernetes":
        _add_prefixed_params(params, "MEMSTACK_DEPLOY_KUBERNETES", deploy.kubernetes)
    elif deploy.mode == "cli":
        _add_prefixed_params(params, "MEMSTACK_DEPLOY_CLI", deploy.cli)


def _add_prefixed_params(
    params: dict[str, str],
    prefix: str,
    values: Mapping[str, Any],
) -> None:
    for key, value in values.items():
        param_value = _param_value(value)
        if param_value is None:
            continue
        safe_key = "".join(char if char.isalnum() else "_" for char in key.upper()).strip("_")
        if safe_key:
            params.setdefault(f"{prefix}_{safe_key}", param_value)


def _param_value(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, list | tuple):
        items = [str(item).strip() for item in value if str(item).strip()]
        return ",".join(items) if items else None
    return None


def _deploy_state(
    stage_results: list[PipelineStageResult],
    deploy: PipelineDeploySpec | None,
) -> str | None:
    if deploy is None:
        return None
    deploy_results = [
        result
        for result in stage_results
        if result.metadata.get("drone_step_kind") == "deploy"
        or _is_deploy_label(result.stage, deploy=deploy)
    ]
    if not deploy_results:
        return "missing"
    if not all(result.passed for result in deploy_results):
        return "failed"
    if not any(
        _deploy_result_matches_mode(result, deploy=deploy, stage_results=stage_results)
        for result in deploy_results
    ):
        return "invalid"
    return "passed"


def _deploy_failure_reason(
    deploy: PipelineDeploySpec,
    external_id: str,
    deploy_state: str,
    *,
    validation_issues: list[str] | None = None,
) -> str:
    if deploy_state == "missing":
        return f"Drone build {external_id} did not report deploy stage {deploy.stage}"
    if deploy_state == "invalid":
        if validation_issues:
            issue_text = "; ".join(validation_issues[:4])
            return (
                f"Drone build {external_id} deploy stage {deploy.stage} did not implement "
                f"{deploy.mode} deployment semantics: {issue_text}"
            )
        return (
            f"Drone build {external_id} deploy stage {deploy.stage} did not implement "
            f"{deploy.mode} deployment semantics"
        )
    return f"Drone build {external_id} deploy stage {deploy.stage} failed"


def _deployment_status(deploy_state: str | None) -> str | None:
    if deploy_state == "passed":
        return "deployed"
    if deploy_state in {"failed", "missing", "invalid"}:
        return deploy_state
    return None


def _deploy_metadata(
    deploy: PipelineDeploySpec | None,
    deploy_state: str | None,
    *,
    validation_issues: list[str] | None = None,
) -> dict[str, Any]:
    if deploy is None:
        return {}
    metadata: dict[str, Any] = {
        "deploy_enabled": True,
        "deploy_mode": deploy.mode,
        "deploy_stage": deploy.stage,
        "deployment_status": _deployment_status(deploy_state),
    }
    if deploy.target:
        metadata["deploy_target"] = deploy.target
    if deploy.mode == "docker" and deploy_state == "passed":
        metadata["deploy_validation"] = DRONE_DOCKER_DEPLOY_VALIDATION
    if validation_issues:
        metadata["deploy_validation_failure"] = "; ".join(validation_issues[:4])
        metadata["deploy_validation_issues"] = validation_issues[:8]
    return metadata


def _is_deploy_stage(
    *,
    stage_name: str,
    step_name: str,
    deploy: PipelineDeploySpec | None,
) -> bool:
    if deploy is None:
        return False
    return _is_deploy_label(stage_name, deploy=deploy) or _is_deploy_label(
        step_name,
        deploy=deploy,
    )


def _is_deploy_label(value: str, *, deploy: PipelineDeploySpec) -> bool:
    normalized = value.strip().lower()
    configured = deploy.stage.strip().lower()
    return (
        normalized == configured
        or normalized.endswith(f"/{configured}")
        or normalized.startswith("deploy-")
        or normalized.endswith("-deploy")
        or normalized == "deployment"
    )


def _deploy_result_matches_mode(
    result: PipelineStageResult,
    *,
    deploy: PipelineDeploySpec,
    stage_results: list[PipelineStageResult],
) -> bool:
    if deploy.mode == "docker":
        return _docker_deploy_evidence(result, deploy=deploy, stage_results=stage_results)
    if deploy.mode == "kubernetes":
        return _kubernetes_deploy_evidence(result)
    return deploy.mode == "cli"


def _docker_deploy_evidence(
    result: PipelineStageResult,
    *,
    deploy: PipelineDeploySpec,
    stage_results: list[PipelineStageResult],
) -> bool:
    return not _docker_deploy_validation_issues(
        result,
        deploy=deploy,
        stage_results=stage_results,
    )


def _docker_deploy_validation_issues(
    result: PipelineStageResult,
    *,
    deploy: PipelineDeploySpec,
    stage_results: list[PipelineStageResult],
) -> list[str]:
    output = _result_output(result).lower()
    issues: list[str] = []
    if _docker_deploy_output_masks_failure(output):
        issues.append("deploy output contains failure markers despite a successful Drone step")
    if _docker_deploy_uses_forbidden_local_registry_pull(output):
        issues.append(
            "deploy step pulls or runs host.docker.internal/localhost local-registry images "
            "through the mounted host Docker daemon"
        )

    missing_services = _missing_docker_deploy_required_services(output, deploy=deploy)
    if missing_services:
        issues.append("missing required deploy services: " + ", ".join(missing_services))

    missing_images = _missing_docker_deploy_built_images(
        output,
        deploy=deploy,
        stage_results=stage_results,
    )
    if missing_images:
        issues.append("missing built image deploy references: " + ", ".join(missing_images))

    if not _docker_deploy_has_run_marker(output):
        issues.append("missing docker run/compose/stack/service deploy command")
    return list(dict.fromkeys(issues))


def _deploy_validation_issues(
    stage_results: list[PipelineStageResult],
    deploy: PipelineDeploySpec | None,
) -> list[str]:
    if deploy is None or deploy.mode != "docker":
        return []
    deploy_results = [
        result
        for result in stage_results
        if result.metadata.get("drone_step_kind") == "deploy"
        or _is_deploy_label(result.stage, deploy=deploy)
    ]
    issues: list[str] = []
    for result in deploy_results:
        result_issues = _docker_deploy_validation_issues(
            result,
            deploy=deploy,
            stage_results=stage_results,
        )
        if not result_issues:
            return []
        issues.extend(result_issues)
    return list(dict.fromkeys(issues))


def _docker_deploy_has_run_marker(output: str) -> bool:
    if any(
        marker in output
        for marker in (
            "docker run",
            "docker container run",
            "docker compose up",
            "docker-compose up",
            "docker stack deploy",
            "docker service create",
            "docker service update",
        )
    ):
        return True
    return _docker_deploy_has_running_container_evidence(output)


def _docker_deploy_has_running_container_evidence(output: str) -> bool:
    if _DOCKER_DEPLOY_CONTAINER_RUNNING_RE.search(output):
        return True
    return (
        "container id" in output
        and "names" in output
        and _DOCKER_PS_RUNNING_ROW_RE.search(output) is not None
    )


def _missing_docker_deploy_required_services(
    output: str,
    *,
    deploy: PipelineDeploySpec,
) -> list[str]:
    requirements = _docker_deploy_service_requirements(deploy)
    if not requirements:
        return []
    return [
        _service_requirement_label(markers)
        for markers in requirements
        if not any(marker in output for marker in markers)
    ]


def _missing_docker_deploy_built_images(
    output: str,
    *,
    deploy: PipelineDeploySpec,
    stage_results: list[PipelineStageResult],
) -> list[str]:
    requirements = _docker_build_service_requirements(stage_results, deploy=deploy)
    if not requirements:
        return []
    return [
        _service_requirement_label(markers)
        for markers in requirements
        if not any(marker in output for marker in markers)
    ]


def _docker_deploy_service_requirements(deploy: PipelineDeploySpec) -> list[tuple[str, ...]]:
    raw = deploy.docker.get("deploy_services")
    if not isinstance(raw, list):
        raw = deploy.docker.get("services")
    if not isinstance(raw, list):
        return []

    requirements: list[tuple[str, ...]] = []
    for item in raw:
        if not isinstance(item, Mapping) or item.get("required") is False:
            continue
        markers = tuple(
            dict.fromkeys(
                marker.lower()
                for marker in (
                    _string(item.get("container_name")),
                    _string(item.get("image_deploy_local")),
                    _string(item.get("image_host_docker")),
                    _string(item.get("image")),
                    _string(item.get("service_id") or item.get("id")),
                )
                if marker
            )
        )
        if markers:
            requirements.append(markers)
    return requirements


def _docker_build_service_requirements(
    stage_results: list[PipelineStageResult],
    *,
    deploy: PipelineDeploySpec,
) -> list[tuple[str, ...]]:
    requirements: list[tuple[str, ...]] = []
    seen: set[tuple[str, ...]] = set()
    for result in stage_results:
        if result.metadata.get("drone_step_kind") == "deploy" or _is_deploy_label(
            result.stage,
            deploy=deploy,
        ):
            continue
        for markers in _docker_build_requirement_markers(result):
            if markers in seen:
                continue
            seen.add(markers)
            requirements.append(markers)
    return requirements


def _docker_build_requirement_markers(result: PipelineStageResult) -> list[tuple[str, ...]]:
    output = _result_output(result)
    identity = _docker_build_identity_text(result)
    service = _docker_build_service_name(identity)
    image_marker_groups = [
        _docker_image_marker_candidates(image) for image in _docker_build_tag_images(output)
    ]

    if not service and not image_marker_groups:
        return []
    if service is None and not _DOCKER_BUILD_COMMAND_RE.search(output):
        return []

    if service:
        markers = [service]
        for image_markers in image_marker_groups:
            markers.extend(image_markers)
        return [tuple(dict.fromkeys(marker.lower() for marker in markers if marker))]
    return [
        tuple(dict.fromkeys(marker.lower() for marker in image_markers if marker))
        for image_markers in image_marker_groups
        if image_markers
    ]


def _docker_build_identity_text(result: PipelineStageResult) -> str:
    values = [
        result.stage,
        result.command,
        _string(result.metadata.get("drone_stage")),
        _string(result.metadata.get("drone_step")),
    ]
    return "\n".join(value for value in values if value)


def _docker_build_service_name(value: str) -> str | None:
    for part in re.split(r"[\s:]+", value):
        match = _DOCKER_BUILD_STEP_SERVICE_RE.search(part)
        if match:
            return match.group("service").strip().lower() or None
    return None


def _docker_build_tag_images(output: str) -> list[str]:
    images: list[str] = []
    for line in output.splitlines():
        if not _DOCKER_BUILD_COMMAND_RE.search(line):
            continue
        for match in _DOCKER_BUILD_TAG_ARG_RE.finditer(line):
            image = match.group("image").strip().strip("'\"")
            if image and _docker_image_ref_is_named_artifact(image):
                images.append(image)
    return images


def _docker_image_marker_candidates(image: str) -> list[str]:
    normalized = image.strip().strip("'\",")
    if not normalized:
        return []
    without_digest = normalized.split("@", 1)[0]
    path_parts = without_digest.split("/")
    if len(path_parts) > 1 and _docker_image_first_part_is_registry(path_parts[0]):
        without_registry = "/".join(path_parts[1:])
    else:
        without_registry = without_digest
    repository = without_registry
    last_part = repository.rsplit("/", 1)[-1]
    if ":" in last_part:
        repository = repository.rsplit(":", 1)[0]
    basename = repository.rsplit("/", 1)[-1]
    markers = [normalized, repository, basename]
    for separator in ("-", "_", "."):
        if separator in basename:
            markers.append(basename.rsplit(separator, 1)[-1])
    return list(dict.fromkeys(marker for marker in markers if marker))


def _docker_image_first_part_is_registry(value: str) -> bool:
    return "." in value or ":" in value or value == "localhost"


def _docker_image_ref_is_named_artifact(image: str) -> bool:
    normalized = image.strip().strip("'\",")
    if not normalized:
        return False
    without_digest = normalized.split("@", 1)[0]
    basename = without_digest.rsplit("/", 1)[-1]
    return (
        "/" in without_digest
        or ":" in basename
        or any(separator in basename for separator in ("-", "_", "."))
    )


def _docker_deploy_uses_forbidden_local_registry_pull(output: str) -> bool:
    return any(
        _DOCKER_LOCAL_REGISTRY_PULL_OR_RUN_RE.search(line) is not None
        for line in output.splitlines()
    )


def _docker_deploy_output_masks_failure(output: str) -> bool:
    if any(
        marker in output
        for marker in (
            "|| echo",
            "container start skipped",
            "health check skipped",
            "image may not exist yet",
            "deployment skipped",
            "deploy skipped",
        )
    ):
        return True
    return any(_line_masks_docker_deploy_failure(line) for line in output.splitlines())


def _line_masks_docker_deploy_failure(line: str) -> bool:
    if "|| true" not in line:
        return False
    if "docker rm" in line or "docker container rm" in line:
        return False
    return any(
        marker in line
        for marker in (
            "docker pull",
            "docker run",
            "docker container run",
            "docker compose up",
            "docker-compose up",
            "docker stack deploy",
            "docker service create",
            "docker service update",
            "wget ",
            "curl ",
        )
    )


def _kubernetes_deploy_evidence(result: PipelineStageResult) -> bool:
    image = str(result.metadata.get("drone_image") or "").lower()
    output = _result_output(result).lower()
    return "kubectl" in image or "kubectl apply" in output or "helm upgrade" in output


def _result_output(result: PipelineStageResult) -> str:
    return "\n".join(value for value in (result.stdout_preview, result.stderr_preview) if value)


def _drone_yaml_preflight_failure(contract: PipelineContractSpec) -> PipelineRunResult | None:
    code_root = _drone_preflight_code_root(contract)
    if code_root is None:
        return None
    drone_path = code_root / ".drone.yml"
    if not drone_path.is_file():
        return None
    try:
        parsed = yaml.safe_load(drone_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        return _configuration_failure(f"Drone build .drone.yml preflight failed; yaml: {exc}")
    command_issue = _first_non_string_drone_command(parsed)
    if command_issue is not None:
        step_name, command_index, tag, preview = command_issue
        return _configuration_failure(
            "Drone build .drone.yml preflight failed; yaml: unmarshal errors: "
            f"step {step_name} commands[{command_index}] cannot unmarshal {tag} into string; "
            f"value={preview}"
        )
    deploy_issue = _docker_deploy_yaml_coverage_issue(parsed, contract.deploy)
    if deploy_issue is not None:
        return _configuration_failure(deploy_issue)
    return None


def _drone_preflight_code_root(contract: PipelineContractSpec) -> Path | None:
    for value in (
        contract.provider_config.get("preflight_code_root"),
        contract.provider_config.get("host_code_root"),
        contract.code_root,
    ):
        if not isinstance(value, str) or not value.strip():
            continue
        path = Path(value.strip())
        if path.is_dir():
            return path
    return None


def _first_non_string_drone_command(
    parsed: object,
) -> tuple[str, int, str, str] | None:
    for step_number, step in enumerate(_drone_step_mappings(parsed), 1):
        step_name = _string(step.get("name")) or f"step-{step_number}"
        commands = step.get("commands")
        if not isinstance(commands, list):
            continue
        for command_index, command in enumerate(commands, 1):
            if not isinstance(command, str):
                return (
                    step_name,
                    command_index,
                    _yaml_type_tag(command),
                    _compact(str(command), limit=300),
                )
    return None


def _docker_deploy_yaml_coverage_issue(
    parsed: object,
    deploy: PipelineDeploySpec | None,
) -> str | None:
    if deploy is None or deploy.mode != "docker" or not deploy.required:
        return None
    requirements = _docker_deploy_service_requirements(deploy)
    if not requirements:
        return None

    deploy_output = _drone_deploy_commands_text(parsed, deploy=deploy)
    if not deploy_output:
        return (
            "Drone build .drone.yml preflight failed; docker deploy stage "
            f"{deploy.stage} is required but no matching deploy commands were found"
        )

    missing = [
        _service_requirement_label(markers)
        for markers in requirements
        if not any(marker in deploy_output for marker in markers)
    ]
    if not missing:
        return None
    missing_services = ", ".join(missing)
    return (
        "Drone build .drone.yml preflight failed; docker deploy stage "
        f"{deploy.stage} does not cover required services: {missing_services}. "
        "The deploy step must start or update every service declared in "
        "delivery_cicd.drone.deploy.docker.deploy_services."
    )


def _drone_deploy_commands_text(parsed: object, *, deploy: PipelineDeploySpec) -> str:
    commands: list[str] = []
    for step_number, step in enumerate(_drone_step_mappings(parsed), 1):
        step_name = _string(step.get("name")) or f"step-{step_number}"
        if not _is_deploy_label(step_name, deploy=deploy):
            continue
        raw_commands = step.get("commands")
        if not isinstance(raw_commands, list):
            continue
        commands.extend(command.lower() for command in raw_commands if isinstance(command, str))
    return "\n".join(commands)


def _drone_step_mappings(parsed: object) -> list[Mapping[str, Any]]:
    if isinstance(parsed, Mapping):
        steps = parsed.get("steps")
        if isinstance(steps, list):
            return [step for step in steps if isinstance(step, Mapping)]
        return []
    if isinstance(parsed, list):
        output: list[Mapping[str, Any]] = []
        for document in parsed:
            output.extend(_drone_step_mappings(document))
        return output
    return []


def _service_requirement_label(markers: tuple[str, ...]) -> str:
    return markers[0] if markers else "unknown"


def _yaml_type_tag(value: object) -> str:
    if isinstance(value, Mapping):
        return "!!map"
    if isinstance(value, list):
        return "!!seq"
    if value is None:
        return "!!null"
    return type(value).__name__


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


def _config_env(name: str) -> str | None:
    value = _string(os.getenv(name))
    if value:
        return value
    dotenv = _drone_dotenv_values(_drone_dotenv_path())
    return _string(dotenv.get(name))


def _drone_dotenv_path() -> str:
    return os.getenv(DRONE_DOTENV_PATH_ENV, ".env")


@lru_cache(maxsize=8)
def _drone_dotenv_values(path: str) -> Mapping[str, str | None]:
    dotenv_path = Path(path)
    if not dotenv_path.exists() or not dotenv_path.is_file():
        return {}
    return dotenv_values(dotenv_path)


def _server_url_from_environment(value: object) -> str | None:
    if not isinstance(value, Mapping):
        return None
    server = value.get("server")
    if not isinstance(server, Mapping):
        return None
    server_url = _string(server.get("server_url"))
    if server_url:
        return server_url
    host = _string(server.get("server_host"))
    port = _positive_int(server.get("server_port"), 0)
    if not host and port > 0:
        host = f"localhost:{port}"
    if not host:
        return None
    if "://" in host:
        return host
    proto = _string(server.get("server_proto")) or "http"
    return f"{proto}://{host}"


def _log_part(value: object) -> str | None:
    if isinstance(value, int):
        return str(value) if value > 0 else None
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


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
    "DroneRepositoryNotFoundError",
    "HttpDroneClient",
]
