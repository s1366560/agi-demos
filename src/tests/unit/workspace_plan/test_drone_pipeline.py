"""Unit tests for Drone-backed workspace CI/CD provider support."""

from __future__ import annotations

from collections.abc import Mapping
from types import SimpleNamespace
from typing import Any, cast

import pytest

from src.infrastructure.agent.workspace_plan.drone import DronePipelineConfig, DronePipelineProvider
from src.infrastructure.agent.workspace_plan.outbox_handlers import (
    _can_reflect_existing_pipeline_run,
    _needs_agent_managed_pipeline_proposal,
    _requires_preview_deployment,
)
from src.infrastructure.agent.workspace_plan.pipeline import (
    DRONE_DOCKER_DEPLOY_VALIDATION,
    DRONE_PROVIDER,
    PipelineContractSpec,
    PipelineDeploySpec,
    build_pipeline_contract_from_metadata,
)


class _FakeDroneClient:
    def __init__(
        self,
        build: Mapping[str, Any],
        logs: Mapping[tuple[str, str], list[Mapping[str, Any]]] | None = None,
        builds: list[Mapping[str, Any]] | None = None,
    ) -> None:
        self.build = build
        self.builds = list(builds or [])
        self.logs = dict(logs or {})
        self.repo: dict[str, Any] = {"trusted": True}
        self.created: list[dict[str, Any]] = []
        self.repo_updates: list[dict[str, Any]] = []
        self.list_requests: list[dict[str, Any]] = []
        self.log_requests: list[dict[str, Any]] = []
        self.stop_requests: list[dict[str, Any]] = []

    async def get_repo(self, *, owner: str, repo: str) -> Mapping[str, Any]:
        assert owner == "octo"
        assert repo == "hello"
        return dict(self.repo)

    async def update_repo(
        self,
        *,
        owner: str,
        repo: str,
        trusted: bool | None = None,
    ) -> Mapping[str, Any]:
        assert owner == "octo"
        assert repo == "hello"
        self.repo_updates.append({"trusted": trusted})
        if trusted is not None:
            self.repo["trusted"] = trusted
        return dict(self.repo)

    async def create_build(
        self,
        *,
        owner: str,
        repo: str,
        branch: str | None,
        commit: str | None,
        params: Mapping[str, str],
    ) -> Mapping[str, Any]:
        self.created.append(
            {
                "owner": owner,
                "repo": repo,
                "branch": branch,
                "commit": commit,
                "params": dict(params),
            }
        )
        return {"number": 42, "status": "pending"}

    async def get_build(self, *, owner: str, repo: str, build_number: int) -> Mapping[str, Any]:
        assert owner == "octo"
        assert repo == "hello"
        assert build_number == 42
        return self.build

    async def list_builds(
        self,
        *,
        owner: str,
        repo: str,
        per_page: int = 25,
    ) -> list[Mapping[str, Any]]:
        assert owner == "octo"
        assert repo == "hello"
        self.list_requests.append({"owner": owner, "repo": repo, "per_page": per_page})
        return list(self.builds)

    async def stop_build(self, *, owner: str, repo: str, build_number: int) -> Mapping[str, Any]:
        assert owner == "octo"
        assert repo == "hello"
        assert build_number == 42
        self.stop_requests.append({"owner": owner, "repo": repo, "build_number": build_number})
        return {
            **dict(self.build),
            "status": "killed",
            "stages": [
                {
                    "name": "default",
                    "status": "killed",
                    "steps": [{"name": "docker", "status": "killed", "exit_code": 137}],
                }
            ],
        }

    async def get_logs(
        self,
        *,
        owner: str,
        repo: str,
        build_number: int,
        stage: str,
        step: str,
    ) -> list[Mapping[str, Any]]:
        self.log_requests.append(
            {
                "owner": owner,
                "repo": repo,
                "build_number": build_number,
                "stage": stage,
                "step": step,
            }
        )
        return self.logs.get((stage, step), [{"out": f"{stage}/{step} log\n"}])


@pytest.mark.asyncio
async def test_drone_pipeline_provider_records_successful_build(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DRONE_SERVER_URL", "https://drone.example.test")
    monkeypatch.setenv("DRONE_TOKEN", "test-token")
    client = _FakeDroneClient(
        {
            "number": 42,
            "status": "success",
            "link": "https://git.example.test/octo/hello/compare",
            "stages": [
                {
                    "name": "default",
                    "status": "success",
                    "steps": [
                        {"name": "test", "status": "success", "exit_code": 0},
                    ],
                }
            ],
        }
    )
    provider = DronePipelineProvider(client=client, sleep=lambda _: _noop())

    result = await provider.run(
        PipelineContractSpec(
            provider=DRONE_PROVIDER,
            provider_config={
                "repo": "octo/hello",
                "branch": "main",
                "params": {"MEMSTACK_WORKSPACE_ID": "ws-1"},
            },
        )
    )

    assert result.status == "success"
    assert result.external_id == "octo/hello#42"
    assert result.external_url == "https://drone.example.test/octo/hello/42"
    assert "ci_pipeline:passed" in result.evidence_refs
    assert result.stage_results[0].stage == "default/test"
    assert result.stage_results[0].stdout_preview == "default/test log"
    assert client.created[0]["params"] == {"MEMSTACK_WORKSPACE_ID": "ws-1"}


@pytest.mark.asyncio
async def test_drone_pipeline_provider_reuses_running_build_for_same_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DRONE_SERVER_URL", "https://drone.example.test")
    monkeypatch.setenv("DRONE_TOKEN", "test-token")
    client = _FakeDroneClient(
        {
            "number": 42,
            "status": "success",
            "link": "https://git.example.test/octo/hello/compare",
            "stages": [
                {
                    "name": "default",
                    "status": "success",
                    "steps": [
                        {"name": "test", "status": "success", "exit_code": 0},
                    ],
                }
            ],
        },
        builds=[
            {
                "number": 42,
                "status": "running",
                "after": "a068cb895f5e7f0bae54d1a204072df99a9a2928",
            }
        ],
    )
    provider = DronePipelineProvider(client=client, sleep=lambda _: _noop())

    result = await provider.run(
        PipelineContractSpec(
            provider=DRONE_PROVIDER,
            provider_config={
                "repo": "octo/hello",
                "branch": "main",
                "commit": "a068cb895f5e7f0bae54d1a204072df99a9a2928",
            },
        )
    )

    assert result.status == "success"
    assert client.created == []
    assert client.list_requests == [{"owner": "octo", "repo": "hello", "per_page": 25}]


@pytest.mark.asyncio
async def test_drone_pipeline_provider_rejects_non_string_drone_commands(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    monkeypatch.setenv("DRONE_SERVER_URL", "https://drone.example.test")
    monkeypatch.setenv("DRONE_TOKEN", "test-token")
    (tmp_path / ".drone.yml").write_text(
        """
kind: pipeline
type: docker
name: workspace-ci
steps:
  - name: deploy
    image: docker:cli
    commands:
      - echo "Deployment successful: my-evo container is healthy"
""".lstrip(),
        encoding="utf-8",
    )
    client = _FakeDroneClient({"number": 42, "status": "success"})
    provider = DronePipelineProvider(client=client, sleep=lambda _: _noop())

    result = await provider.run(
        PipelineContractSpec(
            provider=DRONE_PROVIDER,
            code_root=str(tmp_path),
            provider_config={
                "repo": "octo/hello",
                "branch": "main",
            },
        )
    )

    assert result.status == "failed"
    assert "cannot unmarshal !!map into string" in result.reason
    assert "step deploy commands[1]" in result.reason
    assert "drone:configuration_failed" in result.evidence_refs
    assert result.stage_results[0].stage == "drone_config"
    assert client.created == []


@pytest.mark.asyncio
async def test_drone_pipeline_provider_stops_timed_out_build(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DRONE_SERVER_URL", "https://drone.example.test")
    monkeypatch.setenv("DRONE_TOKEN", "test-token")
    monotonic_values = iter([0.0, 0.0, 2.0])
    monkeypatch.setattr(
        "src.infrastructure.agent.workspace_plan.drone.time.monotonic",
        lambda: next(monotonic_values, 2.0),
    )
    client = _FakeDroneClient(
        {
            "number": 42,
            "status": "running",
            "stages": [
                {
                    "name": "default",
                    "status": "running",
                    "steps": [{"name": "docker", "status": "running"}],
                }
            ],
        }
    )
    cleanup_calls: list[tuple[str, int]] = []

    async def cleanup(config: Any, build_number: int) -> Mapping[str, Any]:
        cleanup_calls.append((config.repo_slug, build_number))
        return {"removed_container_count": 2, "container_ids": ["c1", "c2"]}

    result = await DronePipelineProvider(
        client=client,
        sleep=lambda _: _noop(),
        cleanup_build=cleanup,
    ).run(
        PipelineContractSpec(
            provider=DRONE_PROVIDER,
            provider_config={"repo": "octo/hello", "branch": "main"},
            timeout_seconds=1,
        )
    )

    assert result.status == "failed"
    assert result.reason == "Drone build octo/hello#42 timed out"
    assert "drone_build:timeout:octo/hello#42" in result.evidence_refs
    assert client.stop_requests == [{"owner": "octo", "repo": "hello", "build_number": 42}]
    assert cleanup_calls == [("octo/hello", 42)]
    assert result.metadata["drone_cleanup"] == {
        "removed_container_count": 2,
        "container_ids": ["c1", "c2"],
    }
    assert result.stage_results[0].stage == "default/docker"
    assert result.stage_results[0].status == "failed"


@pytest.mark.asyncio
async def test_drone_pipeline_provider_records_successful_deploy_stage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DRONE_SERVER_URL", "https://drone.example.test")
    monkeypatch.setenv("DRONE_TOKEN", "test-token")
    client = _FakeDroneClient(
        {
            "number": 42,
            "status": "success",
            "stages": [
                {
                    "name": "workspace-ci",
                    "status": "success",
                    "steps": [
                        {"name": "test", "status": "success", "exit_code": 0},
                        {
                            "name": "deploy",
                            "status": "success",
                            "exit_code": 0,
                            "image": "docker:27-cli",
                        },
                    ],
                }
            ],
        },
        logs={
            ("workspace-ci", "deploy"): [
                {"out": "docker pull registry.example.test/octo/hello:staging\n"},
                {
                    "out": (
                        "docker run -d --name hello registry.example.test/octo/hello:staging\n"
                    ),
                },
            ],
        },
    )

    result = await DronePipelineProvider(client=client, sleep=lambda _: _noop()).run(
        PipelineContractSpec(
            provider=DRONE_PROVIDER,
            provider_config={"repo": "octo/hello", "branch": "main"},
            deploy=PipelineDeploySpec(
                enabled=True,
                mode="docker",
                target="staging",
                docker={
                    "image": "registry.example.test/octo/hello",
                    "dockerfile": "Dockerfile",
                    "tags": ["latest", "staging"],
                    "username_secret": "docker_username",
                    "password_secret": "docker_password",
                },
            ),
        )
    )

    assert result.status == "success"
    assert result.deployment_status == "deployed"
    assert result.metadata["deploy_validation"] == DRONE_DOCKER_DEPLOY_VALIDATION
    assert "deployment:passed:docker" in result.evidence_refs
    assert "deployment_target:staging" in result.evidence_refs
    assert client.repo_updates == []
    assert client.created[0]["params"] == {
        "target": "staging",
        "MEMSTACK_DEPLOY_ENABLED": "true",
        "MEMSTACK_DEPLOY_MODE": "docker",
        "MEMSTACK_DEPLOY_STAGE": "deploy",
        "MEMSTACK_DEPLOY_TARGET": "staging",
        "MEMSTACK_DEPLOY_DOCKER_IMAGE": "registry.example.test/octo/hello",
        "MEMSTACK_DEPLOY_DOCKER_DOCKERFILE": "Dockerfile",
        "MEMSTACK_DEPLOY_DOCKER_TAGS": "latest,staging",
        "MEMSTACK_DEPLOY_DOCKER_USERNAME_SECRET": "docker_username",
        "MEMSTACK_DEPLOY_DOCKER_PASSWORD_SECRET": "docker_password",
    }


@pytest.mark.asyncio
async def test_drone_pipeline_provider_rejects_multi_service_deploy_missing_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DRONE_SERVER_URL", "https://drone.example.test")
    monkeypatch.setenv("DRONE_TOKEN", "test-token")
    client = _FakeDroneClient(
        {
            "number": 42,
            "status": "success",
            "stages": [
                {
                    "name": "workspace-ci",
                    "status": "success",
                    "steps": [
                        {"name": "docker-build-backend", "status": "success", "exit_code": 0},
                        {"name": "docker-build-frontend", "status": "success", "exit_code": 0},
                        {
                            "name": "deploy",
                            "status": "success",
                            "exit_code": 0,
                            "image": "docker:27-cli",
                        },
                    ],
                }
            ],
        },
        logs={
            ("workspace-ci", "deploy"): [
                {
                    "out": (
                        "docker run -d --name my-evo-backend my-evo-backend:drone-docker-e2e\n"
                    ),
                },
            ],
        },
    )

    result = await DronePipelineProvider(client=client, sleep=lambda _: _noop()).run(
        PipelineContractSpec(
            provider=DRONE_PROVIDER,
            provider_config={"repo": "octo/hello", "branch": "main"},
            deploy=PipelineDeploySpec(
                enabled=True,
                mode="docker",
                docker={
                    "deploy_services": [
                        {
                            "service_id": "backend",
                            "container_name": "my-evo-backend",
                            "image_deploy_local": "my-evo-backend:drone-docker-e2e",
                            "required": True,
                        },
                        {
                            "service_id": "frontend",
                            "container_name": "my-evo-frontend",
                            "image_deploy_local": "my-evo-frontend:drone-docker-e2e",
                            "required": True,
                        },
                    ],
                },
            ),
        )
    )

    assert result.status == "failed"
    assert result.deployment_status == "invalid"
    assert result.reason == (
        "Drone build octo/hello#42 deploy stage deploy did not implement "
        "docker deployment semantics"
    )
    assert "deployment:invalid:docker" in result.evidence_refs
    assert "deploy_validation" not in result.metadata


@pytest.mark.asyncio
async def test_drone_pipeline_provider_rejects_deploy_missing_built_image_without_inventory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DRONE_SERVER_URL", "https://drone.example.test")
    monkeypatch.setenv("DRONE_TOKEN", "test-token")
    client = _FakeDroneClient(
        {
            "number": 42,
            "status": "success",
            "stages": [
                {
                    "name": "workspace-ci",
                    "status": "success",
                    "steps": [
                        {"name": "docker-build", "status": "success", "exit_code": 0},
                        {
                            "name": "deploy",
                            "status": "success",
                            "exit_code": 0,
                            "image": "docker:27-cli",
                        },
                    ],
                }
            ],
        },
        logs={
            ("workspace-ci", "docker-build"): [
                {
                    "out": (
                        "docker build -t my-evo-backend:drone-docker-e2e -f Dockerfile .\n"
                        "docker build -t my-evo-frontend:drone-docker-e2e "
                        "-f frontend/Dockerfile frontend\n"
                    ),
                },
            ],
            ("workspace-ci", "deploy"): [
                {
                    "out": (
                        "docker run -d --name my-evo-backend my-evo-backend:drone-docker-e2e\n"
                    ),
                },
            ],
        },
    )

    result = await DronePipelineProvider(client=client, sleep=lambda _: _noop()).run(
        PipelineContractSpec(
            provider=DRONE_PROVIDER,
            provider_config={"repo": "octo/hello", "branch": "main"},
            deploy=PipelineDeploySpec(enabled=True, mode="docker"),
        )
    )

    assert result.status == "failed"
    assert result.deployment_status == "invalid"
    assert result.reason == (
        "Drone build octo/hello#42 deploy stage deploy did not implement "
        "docker deployment semantics"
    )
    assert "deployment:invalid:docker" in result.evidence_refs


@pytest.mark.asyncio
async def test_drone_pipeline_provider_preserves_failure_signal_lines_in_long_deploy_logs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DRONE_SERVER_URL", "https://drone.example.test")
    monkeypatch.setenv("DRONE_TOKEN", "test-token")
    long_build_output = "\n".join(f"# cached build line {index}" for index in range(350))
    docker_ps_output = "\n".join(f"container inventory line {index}" for index in range(350))
    client = _FakeDroneClient(
        {
            "number": 42,
            "status": "failure",
            "stages": [
                {
                    "name": "workspace-ci",
                    "status": "failure",
                    "steps": [
                        {
                            "name": "deploy",
                            "status": "failure",
                            "exit_code": 1,
                            "image": "docker:cli",
                        },
                    ],
                }
            ],
        },
        logs={
            ("workspace-ci", "deploy"): [
                {"out": f"{long_build_output}\n"},
                {
                    "out": (
                        "wget: can't connect to remote host (192.168.65.254): Connection refused\n"
                    )
                },
                {
                    "out": (
                        'e635ec65c390 my-evo:drone-docker-e2e "dumb-init -- sh -c" '
                        "Exited (0) 9 seconds ago my-evo\n"
                    )
                },
                {"out": f"{docker_ps_output}\n"},
                {
                    "out": (
                        'Datasource "db": PostgreSQL database "evomap"\n'
                        "No migration found in prisma/migrations\n"
                        "No pending migrations to apply.\n"
                    )
                },
            ],
        },
    )

    result = await DronePipelineProvider(client=client, sleep=lambda _: _noop()).run(
        PipelineContractSpec(
            provider=DRONE_PROVIDER,
            provider_config={"repo": "octo/hello", "branch": "main"},
            deploy=PipelineDeploySpec(enabled=True, mode="docker"),
        )
    )

    preview = result.stage_results[0].stderr_preview
    assert result.status == "failed"
    assert "failure_signals:" in preview
    assert "Connection refused" in preview
    assert "Exited (0)" in preview
    assert "No migration found" in preview
    assert len(preview) <= 4000


@pytest.mark.asyncio
async def test_drone_pipeline_provider_marks_docker_deploy_repo_trusted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DRONE_SERVER_URL", "https://drone.example.test")
    monkeypatch.setenv("DRONE_TOKEN", "test-token")
    client = _FakeDroneClient(
        {
            "number": 42,
            "status": "success",
            "stages": [
                {
                    "name": "workspace-ci",
                    "status": "success",
                    "steps": [
                        {
                            "name": "deploy",
                            "status": "success",
                            "exit_code": 0,
                            "image": "docker:27-cli",
                        },
                    ],
                }
            ],
        },
        logs={
            ("workspace-ci", "deploy"): [
                {"out": "docker run -d registry.example.test/octo/hello:latest\n"},
            ],
        },
    )
    client.repo["trusted"] = False

    result = await DronePipelineProvider(client=client, sleep=lambda _: _noop()).run(
        PipelineContractSpec(
            provider=DRONE_PROVIDER,
            provider_config={"repo": "octo/hello", "branch": "main"},
            deploy=PipelineDeploySpec(
                enabled=True,
                mode="docker",
                docker={"image": "registry.example.test/octo/hello"},
            ),
        )
    )

    assert result.status == "success"
    assert client.repo_updates == [{"trusted": True}]
    assert client.created


@pytest.mark.asyncio
async def test_drone_pipeline_provider_respects_docker_deploy_trusted_opt_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DRONE_SERVER_URL", "https://drone.example.test")
    monkeypatch.setenv("DRONE_TOKEN", "test-token")
    client = _FakeDroneClient(
        {
            "number": 42,
            "status": "success",
            "stages": [
                {
                    "name": "workspace-ci",
                    "status": "success",
                    "steps": [
                        {
                            "name": "deploy",
                            "status": "success",
                            "exit_code": 0,
                            "image": "docker:27-cli",
                        },
                    ],
                }
            ],
        },
        logs={
            ("workspace-ci", "deploy"): [
                {"out": "docker run -d registry.example.test/octo/hello:latest\n"},
            ],
        },
    )
    client.repo["trusted"] = False

    result = await DronePipelineProvider(client=client, sleep=lambda _: _noop()).run(
        PipelineContractSpec(
            provider=DRONE_PROVIDER,
            provider_config={"repo": "octo/hello", "branch": "main"},
            deploy=PipelineDeploySpec(
                enabled=True,
                mode="docker",
                docker={"image": "registry.example.test/octo/hello", "trusted": False},
            ),
        )
    )

    assert result.status == "success"
    assert client.repo_updates == []
    assert client.created


@pytest.mark.asyncio
async def test_drone_pipeline_provider_rejects_masked_docker_deploy_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DRONE_SERVER_URL", "https://drone.example.test")
    monkeypatch.setenv("DRONE_TOKEN", "test-token")
    client = _FakeDroneClient(
        {
            "number": 42,
            "status": "success",
            "stages": [
                {
                    "name": "workspace-ci",
                    "status": "success",
                    "steps": [
                        {
                            "name": "deploy",
                            "status": "success",
                            "exit_code": 0,
                            "image": "docker:cli",
                        },
                    ],
                }
            ],
        },
        logs={
            ("workspace-ci", "deploy"): [
                {
                    "out": (
                        'docker run -d hello || echo "Container start skipped"\n'
                        "wget http://host.docker.internal:8080/api/health "
                        '|| echo "Health check skipped"\n'
                    ),
                },
            ],
        },
    )

    result = await DronePipelineProvider(client=client, sleep=lambda _: _noop()).run(
        PipelineContractSpec(
            provider=DRONE_PROVIDER,
            provider_config={"repo": "octo/hello", "branch": "main"},
            deploy=PipelineDeploySpec(
                enabled=True,
                mode="docker",
                docker={"image": "registry.example.test/octo/hello"},
            ),
        )
    )

    assert result.status == "failed"
    assert result.deployment_status == "invalid"
    assert result.reason == (
        "Drone build octo/hello#42 deploy stage deploy did not implement "
        "docker deployment semantics"
    )
    assert "deploy_validation" not in result.metadata
    assert "deployment:invalid:docker" in result.evidence_refs


@pytest.mark.asyncio
async def test_drone_pipeline_provider_includes_step_error_in_failed_stage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DRONE_SERVER_URL", "https://drone.example.test")
    monkeypatch.setenv("DRONE_TOKEN", "test-token")
    mount_error = (
        "Error response from daemon: unable to start container process: "
        "error mounting docker.proxy.sock to rootfs at /var/run: not a directory"
    )
    client = _FakeDroneClient(
        {
            "number": 42,
            "status": "error",
            "stages": [
                {
                    "name": "workspace-ci",
                    "status": "error",
                    "steps": [
                        {"name": "docker-build", "status": "success", "exit_code": 0},
                        {
                            "name": "deploy",
                            "status": "error",
                            "exit_code": 255,
                            "error": mount_error,
                            "image": "docker:20-cli",
                        },
                    ],
                }
            ],
        },
        logs={
            ("workspace-ci", "deploy"): [
                {"out": "Status: Downloaded newer image for docker:20-cli\n"},
            ],
        },
    )

    result = await DronePipelineProvider(client=client, sleep=lambda _: _noop()).run(
        PipelineContractSpec(
            provider=DRONE_PROVIDER,
            provider_config={"repo": "octo/hello", "branch": "main"},
            deploy=PipelineDeploySpec(
                enabled=True,
                mode="docker",
                docker={"image": "registry.example.test/octo/hello"},
            ),
        )
    )

    failed_stage = next(
        stage for stage in result.stage_results if stage.stage == "workspace-ci/deploy"
    )
    assert result.status == "failed"
    assert result.deployment_status == "failed"
    assert failed_stage.metadata["drone_error"] == mount_error
    assert "not a directory" in failed_stage.stderr_preview
    assert "Downloaded newer image" in failed_stage.stderr_preview


@pytest.mark.asyncio
async def test_drone_pipeline_provider_preserves_failed_log_tail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DRONE_SERVER_URL", "https://drone.example.test")
    monkeypatch.setenv("DRONE_TOKEN", "test-token")
    long_build_prefix = "\n".join(f"# cached build line {index}" for index in range(500))
    postgres_error = (
        "Error: Database is uninitialized and superuser password is not specified. "
        "You must specify POSTGRES_PASSWORD to a non-empty value."
    )
    client = _FakeDroneClient(
        {
            "number": 42,
            "status": "failure",
            "stages": [
                {
                    "name": "workspace-ci",
                    "status": "failure",
                    "steps": [{"name": "deploy", "status": "failure", "exit_code": 1}],
                }
            ],
        },
        logs={("workspace-ci", "deploy"): [{"out": f"{long_build_prefix}\n{postgres_error}\n"}]},
    )

    result = await DronePipelineProvider(client=client, sleep=lambda _: _noop()).run(
        PipelineContractSpec(
            provider=DRONE_PROVIDER,
            provider_config={"repo": "octo/hello", "branch": "main"},
            deploy=PipelineDeploySpec(
                enabled=True,
                mode="docker",
                docker={"image": "registry.example.test/octo/hello"},
            ),
        )
    )

    failed_stage = next(
        stage for stage in result.stage_results if stage.stage == "workspace-ci/deploy"
    )
    assert result.status == "failed"
    assert "# cached build line 0" in failed_stage.stderr_preview
    assert "POSTGRES_PASSWORD" in failed_stage.stderr_preview


@pytest.mark.asyncio
async def test_drone_pipeline_provider_allows_best_effort_docker_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DRONE_SERVER_URL", "https://drone.example.test")
    monkeypatch.setenv("DRONE_TOKEN", "test-token")
    client = _FakeDroneClient(
        {
            "number": 42,
            "status": "success",
            "stages": [
                {
                    "name": "workspace-ci",
                    "status": "success",
                    "steps": [
                        {
                            "name": "deploy",
                            "status": "success",
                            "exit_code": 0,
                            "image": "docker:cli",
                        },
                    ],
                }
            ],
        },
        logs={
            ("workspace-ci", "deploy"): [
                {
                    "out": (
                        "docker pull registry.example.test/octo/hello:latest\n"
                        "docker rm -f hello || true\n"
                        "docker run -d --name hello registry.example.test/octo/hello:latest\n"
                        "curl -sf http://host.docker.internal:8080/health\n"
                    ),
                },
            ],
        },
    )

    result = await DronePipelineProvider(client=client, sleep=lambda _: _noop()).run(
        PipelineContractSpec(
            provider=DRONE_PROVIDER,
            provider_config={"repo": "octo/hello", "branch": "main"},
            deploy=PipelineDeploySpec(
                enabled=True,
                mode="docker",
                docker={"image": "registry.example.test/octo/hello"},
            ),
        )
    )

    assert result.status == "success"
    assert result.deployment_status == "deployed"
    assert result.metadata["deploy_validation"] == DRONE_DOCKER_DEPLOY_VALIDATION


@pytest.mark.asyncio
async def test_drone_pipeline_provider_rejects_host_daemon_local_registry_pull(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DRONE_SERVER_URL", "https://drone.example.test")
    monkeypatch.setenv("DRONE_TOKEN", "test-token")
    client = _FakeDroneClient(
        {
            "number": 42,
            "status": "success",
            "stages": [
                {
                    "name": "workspace-ci",
                    "status": "success",
                    "steps": [
                        {
                            "name": "deploy",
                            "status": "success",
                            "exit_code": 0,
                            "image": "docker:cli",
                        },
                    ],
                }
            ],
        },
        logs={
            ("workspace-ci", "deploy"): [
                {
                    "out": (
                        "docker pull host.docker.internal:5001/my-evo:drone-docker-e2e\n"
                        "docker run -d --name my-evo "
                        "host.docker.internal:5001/my-evo:drone-docker-e2e\n"
                    ),
                },
            ],
        },
    )

    result = await DronePipelineProvider(client=client, sleep=lambda _: _noop()).run(
        PipelineContractSpec(
            provider=DRONE_PROVIDER,
            provider_config={"repo": "octo/hello", "branch": "main"},
            deploy=PipelineDeploySpec(
                enabled=True,
                mode="docker",
                docker={"image": "host.docker.internal:5001/my-evo"},
            ),
        )
    )

    assert result.status == "failed"
    assert result.deployment_status == "invalid"
    assert result.reason == (
        "Drone build octo/hello#42 deploy stage deploy did not implement "
        "docker deployment semantics"
    )
    assert "deploy_validation" not in result.metadata
    assert "deployment:invalid:docker" in result.evidence_refs


@pytest.mark.asyncio
async def test_drone_pipeline_provider_rejects_image_publish_without_deploy_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DRONE_SERVER_URL", "https://drone.example.test")
    monkeypatch.setenv("DRONE_TOKEN", "test-token")
    client = _FakeDroneClient(
        {
            "number": 42,
            "status": "success",
            "stages": [
                {
                    "name": "workspace-ci",
                    "status": "success",
                    "steps": [
                        {"name": "test", "status": "success", "exit_code": 0},
                        {
                            "name": "docker-build",
                            "status": "success",
                            "exit_code": 0,
                            "image": "plugins/docker:20",
                        },
                    ],
                }
            ],
        }
    )

    result = await DronePipelineProvider(client=client, sleep=lambda _: _noop()).run(
        PipelineContractSpec(
            provider=DRONE_PROVIDER,
            provider_config={"repo": "octo/hello", "branch": "main"},
            deploy=PipelineDeploySpec(enabled=True, mode="docker", stage="deploy"),
        )
    )

    assert result.status == "failed"
    assert result.deployment_status == "missing"
    assert result.reason == "Drone build octo/hello#42 did not report deploy stage deploy"
    assert "deployment:missing:docker" in result.evidence_refs


def test_existing_drone_docker_run_without_explicit_deploy_validation_is_not_reused() -> None:
    run = SimpleNamespace(
        status="success",
        metadata_json={
            "deploy_mode": "docker",
            "deployment_status": "deployed",
        },
    )
    contract = PipelineContractSpec(
        provider=DRONE_PROVIDER,
        provider_config={"repo": "octo/hello"},
        deploy=PipelineDeploySpec(enabled=True, mode="docker", required=True),
    )

    assert not _can_reflect_existing_pipeline_run(
        run=cast(Any, run),
        contract=contract,
        node=cast(Any, object()),
    )


def test_existing_drone_docker_run_with_explicit_deploy_validation_is_reused() -> None:
    run = SimpleNamespace(
        status="success",
        metadata_json={
            "deploy_mode": "docker",
            "deployment_status": "deployed",
            "deploy_validation": DRONE_DOCKER_DEPLOY_VALIDATION,
        },
    )
    contract = PipelineContractSpec(
        provider=DRONE_PROVIDER,
        provider_config={"repo": "octo/hello"},
        deploy=PipelineDeploySpec(enabled=True, mode="docker", required=True),
    )

    assert _can_reflect_existing_pipeline_run(
        run=cast(Any, run),
        contract=contract,
        node=cast(Any, object()),
    )


@pytest.mark.asyncio
async def test_drone_pipeline_provider_rejects_docker_deploy_without_deploy_semantics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DRONE_SERVER_URL", "https://drone.example.test")
    monkeypatch.setenv("DRONE_TOKEN", "test-token")
    client = _FakeDroneClient(
        {
            "number": 42,
            "status": "success",
            "stages": [
                {
                    "name": "workspace-ci",
                    "status": "success",
                    "steps": [
                        {"name": "test", "status": "success", "exit_code": 0},
                        {
                            "name": "deploy",
                            "status": "success",
                            "exit_code": 0,
                            "image": "docker.io/library/alpine:3.20",
                        },
                    ],
                }
            ],
        }
    )

    result = await DronePipelineProvider(client=client, sleep=lambda _: _noop()).run(
        PipelineContractSpec(
            provider=DRONE_PROVIDER,
            provider_config={"repo": "octo/hello", "branch": "main"},
            deploy=PipelineDeploySpec(
                enabled=True,
                mode="docker",
                target="staging",
                docker={
                    "image": "registry.example.test/octo/hello",
                    "dockerfile": "Dockerfile",
                    "tags": ["latest"],
                },
            ),
        )
    )

    assert result.status == "failed"
    assert result.deployment_status == "invalid"
    assert result.reason == (
        "Drone build octo/hello#42 deploy stage deploy did not implement "
        "docker deployment semantics"
    )
    assert "deployment:invalid:docker" in result.evidence_refs


@pytest.mark.asyncio
async def test_drone_pipeline_provider_uses_drone_numbers_for_log_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DRONE_SERVER_URL", "https://drone.example.test")
    monkeypatch.setenv("DRONE_TOKEN", "test-token")
    client = _FakeDroneClient(
        {
            "number": 42,
            "status": "success",
            "stages": [
                {
                    "name": "workspace-ci",
                    "number": 1,
                    "status": "success",
                    "steps": [
                        {"name": "deploy", "number": 3, "status": "success", "exit_code": 0},
                    ],
                }
            ],
        }
    )

    result = await DronePipelineProvider(client=client, sleep=lambda _: _noop()).run(
        PipelineContractSpec(
            provider=DRONE_PROVIDER,
            provider_config={"repo": "octo/hello"},
            deploy=PipelineDeploySpec(enabled=True, mode="cli", stage="deploy"),
        )
    )

    assert result.status == "success"
    assert client.log_requests == [
        {
            "owner": "octo",
            "repo": "hello",
            "build_number": 42,
            "stage": "1",
            "step": "3",
        }
    ]
    assert result.stage_results[0].stage == "workspace-ci/deploy"
    assert result.stage_results[0].stdout_preview == "1/3 log"


@pytest.mark.asyncio
async def test_drone_pipeline_provider_fails_when_configured_deploy_stage_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DRONE_SERVER_URL", "https://drone.example.test")
    monkeypatch.setenv("DRONE_TOKEN", "test-token")
    client = _FakeDroneClient(
        {
            "number": 42,
            "status": "success",
            "stages": [
                {
                    "name": "workspace-ci",
                    "status": "success",
                    "steps": [{"name": "test", "status": "success", "exit_code": 0}],
                }
            ],
        }
    )

    result = await DronePipelineProvider(client=client, sleep=lambda _: _noop()).run(
        PipelineContractSpec(
            provider=DRONE_PROVIDER,
            provider_config={"repo": "octo/hello"},
            deploy=PipelineDeploySpec(enabled=True, mode="cli", stage="deploy"),
        )
    )

    assert result.status == "failed"
    assert result.deployment_status == "missing"
    assert result.reason == "Drone build octo/hello#42 did not report deploy stage deploy"
    assert "deployment:missing:cli" in result.evidence_refs


@pytest.mark.asyncio
async def test_drone_pipeline_provider_allows_missing_optional_deploy_stage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DRONE_SERVER_URL", "https://drone.example.test")
    monkeypatch.setenv("DRONE_TOKEN", "test-token")
    client = _FakeDroneClient(
        {
            "number": 42,
            "status": "success",
            "stages": [
                {
                    "name": "workspace-ci",
                    "status": "success",
                    "steps": [{"name": "test", "status": "success", "exit_code": 0}],
                }
            ],
        }
    )

    result = await DronePipelineProvider(client=client, sleep=lambda _: _noop()).run(
        PipelineContractSpec(
            provider=DRONE_PROVIDER,
            provider_config={"repo": "octo/hello"},
            deploy=PipelineDeploySpec(enabled=True, mode="cli", stage="deploy", required=False),
        )
    )

    assert result.status == "success"
    assert result.reason is None
    assert result.deployment_status == "missing"
    assert "deployment:missing:cli" in result.evidence_refs


@pytest.mark.asyncio
async def test_drone_pipeline_provider_reports_configuration_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    monkeypatch.delenv("DRONE_SERVER_URL", raising=False)
    monkeypatch.delenv("DRONE_TOKEN", raising=False)
    monkeypatch.setenv("MEMSTACK_DRONE_DOTENV_PATH", str(tmp_path / "missing.env"))

    result = await DronePipelineProvider(client=_FakeDroneClient({})).run(
        PipelineContractSpec(provider=DRONE_PROVIDER, provider_config={"repo": "octo/hello"})
    )

    assert result.status == "failed"
    assert "DRONE_SERVER_URL" in (result.reason or "")
    assert "drone:configuration_failed" in result.evidence_refs


def test_drone_config_uses_structured_server_environment_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    monkeypatch.delenv("DRONE_SERVER_URL", raising=False)
    monkeypatch.setenv("DRONE_TOKEN", "test-token")
    monkeypatch.setenv("MEMSTACK_DRONE_DOTENV_PATH", str(tmp_path / "missing.env"))

    config = DronePipelineConfig.from_contract(
        PipelineContractSpec(
            provider=DRONE_PROVIDER,
            provider_config={
                "repo": "octo/hello",
                "environment": {
                    "server": {
                        "server_proto": "http",
                        "server_host": "localhost:8080",
                    }
                },
            },
        )
    )

    assert config.server_url == "http://localhost:8080"
    assert config.token == "test-token"


def test_drone_contract_uses_provider_config_without_preview_requirement() -> None:
    contract = build_pipeline_contract_from_metadata(
        workspace_metadata={
            "delivery_cicd": {
                "provider": "drone",
                "drone": {
                    "repo": "octo/hello",
                    "branch": "main",
                    "poll_interval_seconds": 2,
                },
            }
        },
        fallback_code_root="/workspace/project",
    )

    assert contract.provider == DRONE_PROVIDER
    assert contract.provider_config["repo"] == "octo/hello"
    assert contract.provider_config["branch"] == "main"
    assert contract.stages == ()
    assert not _needs_agent_managed_pipeline_proposal(contract)
    assert not _requires_preview_deployment(contract)


def test_drone_contract_parses_deploy_config_from_drone_metadata() -> None:
    contract = build_pipeline_contract_from_metadata(
        workspace_metadata={
            "delivery_cicd": {
                "provider": "drone",
                "drone": {
                    "repo": "octo/hello",
                    "deploy": {
                        "enabled": True,
                        "mode": "kubernetes",
                        "target": "production",
                        "stage": "deploy",
                        "kubernetes": {
                            "namespace": "apps",
                            "manifest_paths": ["k8s/deploy.yaml"],
                            "kubeconfig_secret": "prod_kubeconfig",
                        },
                    },
                },
            }
        },
        fallback_code_root="/workspace/project",
    )

    assert contract.provider == DRONE_PROVIDER
    assert contract.deploy is not None
    assert contract.deploy.enabled is True
    assert contract.deploy.mode == "kubernetes"
    assert contract.deploy.target == "production"
    assert contract.deploy.kubernetes == {
        "namespace": "apps",
        "manifest_paths": ["k8s/deploy.yaml"],
        "kubeconfig_secret": "prod_kubeconfig",
    }


async def _noop() -> None:
    return None
