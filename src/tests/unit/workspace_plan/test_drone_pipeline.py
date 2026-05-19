"""Unit tests for Drone-backed workspace CI/CD provider support."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from src.infrastructure.agent.workspace_plan.drone import DronePipelineProvider
from src.infrastructure.agent.workspace_plan.outbox_handlers import (
    _needs_agent_managed_pipeline_proposal,
    _requires_preview_deployment,
)
from src.infrastructure.agent.workspace_plan.pipeline import (
    DRONE_PROVIDER,
    PipelineContractSpec,
    PipelineDeploySpec,
    build_pipeline_contract_from_metadata,
)


class _FakeDroneClient:
    def __init__(self, build: Mapping[str, Any]) -> None:
        self.build = build
        self.created: list[dict[str, Any]] = []
        self.log_requests: list[dict[str, Any]] = []

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
        return [{"out": f"{stage}/{step} log\n"}]


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
                            "name": "deploy-docker",
                            "status": "success",
                            "exit_code": 0,
                            "image": "plugins/docker",
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
                    "tags": ["latest", "staging"],
                    "username_secret": "docker_username",
                    "password_secret": "docker_password",
                },
            ),
        )
    )

    assert result.status == "success"
    assert result.deployment_status == "deployed"
    assert "deployment:passed:docker" in result.evidence_refs
    assert "deployment_target:staging" in result.evidence_refs
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
async def test_drone_pipeline_provider_treats_plugins_docker_step_as_docker_deploy(
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

    assert result.status == "success"
    assert result.deployment_status == "deployed"
    assert "deployment:passed:docker" in result.evidence_refs


@pytest.mark.asyncio
async def test_drone_pipeline_provider_rejects_docker_deploy_without_build_push_semantics(
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
) -> None:
    monkeypatch.delenv("DRONE_SERVER_URL", raising=False)
    monkeypatch.delenv("DRONE_TOKEN", raising=False)

    result = await DronePipelineProvider(client=_FakeDroneClient({})).run(
        PipelineContractSpec(provider=DRONE_PROVIDER, provider_config={"repo": "octo/hello"})
    )

    assert result.status == "failed"
    assert "DRONE_SERVER_URL" in (result.reason or "")
    assert "drone:configuration_failed" in result.evidence_refs


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
