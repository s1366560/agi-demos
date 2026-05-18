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
    build_pipeline_contract_from_metadata,
)


class _FakeDroneClient:
    def __init__(self, build: Mapping[str, Any]) -> None:
        self.build = build
        self.created: list[dict[str, Any]] = []

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


async def _noop() -> None:
    return None
