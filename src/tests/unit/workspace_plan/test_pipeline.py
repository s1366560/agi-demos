"""Unit tests for harness-native workspace CI/CD primitives."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from src.domain.model.workspace_plan import (
    AcceptanceCriterion,
    CriterionKind,
    PlanNode,
    PlanNodeKind,
    TaskExecution,
    TaskIntent,
)
from src.domain.ports.services.verifier_port import VerificationContext
from src.infrastructure.agent.workspace_plan.outbox_handlers import (
    _parse_agent_managed_pipeline_probe,
    _pipeline_completion_node_state,
    _propose_agent_managed_pipeline_contract,
)
from src.infrastructure.agent.workspace_plan.pipeline import (
    PipelineContractSpec,
    PipelineStageSpec,
    SandboxNativePipelineProvider,
    build_pipeline_contract_from_metadata,
)
from src.infrastructure.agent.workspace_plan.verifier import AcceptanceCriterionVerifier


class _FakeSandboxRunner:
    def __init__(self, exit_codes: list[int]) -> None:
        self.exit_codes = exit_codes
        self.commands: list[str] = []

    async def run_command(self, command: str, *, timeout: int = 60) -> dict[str, Any]:
        self.commands.append(command)
        exit_code = self.exit_codes.pop(0) if self.exit_codes else 0
        return {
            "exit_code": 0,
            "stdout": f"stage output\n__MEMSTACK_PIPELINE_EXIT_CODE__={exit_code}\n",
            "stderr": "",
        }


class _FakeProbeRunner:
    def __init__(self, *, exit_code: int, stdout: str = "") -> None:
        self.exit_code = exit_code
        self.stdout = stdout
        self.commands: list[str] = []

    async def run_command(self, command: str, *, timeout: int = 60) -> dict[str, Any]:
        self.commands.append(command)
        return {
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": "" if self.exit_code == 0 else "probe failed",
        }


def _node(*, metadata: dict[str, object]) -> PlanNode:
    return PlanNode(
        id="node-1",
        plan_id="plan-1",
        kind=PlanNodeKind.TASK,
        parent_id="goal-1",
        title="Implement feature",
        description="Finish a software increment.",
        intent=TaskIntent.IN_PROGRESS,
        execution=TaskExecution.REPORTED,
        metadata=metadata,
        acceptance_criteria=(
            AcceptanceCriterion(
                kind=CriterionKind.REGEX,
                spec={"pattern": r"\S", "source": "stdout"},
                required=True,
            ),
        ),
    )


@pytest.mark.asyncio
async def test_sandbox_native_pipeline_success_records_stage_results() -> None:
    runner = _FakeSandboxRunner([0, 0])
    provider = SandboxNativePipelineProvider(runner)
    result = await provider.run(
        PipelineContractSpec(
            code_root="/workspace/app",
            stages=(
                PipelineStageSpec(stage="test", command="npm test", required=True),
                PipelineStageSpec(stage="build", command="npm run build", required=True),
            ),
        )
    )

    assert result.status == "success"
    assert "ci_pipeline:passed" in result.evidence_refs
    assert "pipeline_stage:test:passed" in result.evidence_refs
    assert "cd /workspace/app" in runner.commands[0]
    assert 'if [ "$code" -ne 0 ]; then' in runner.commands[0]
    assert "workspace pipeline code_root is not accessible: %s" in runner.commands[0]
    assert " /workspace/app >&2" in runner.commands[0]


@pytest.mark.asyncio
async def test_sandbox_native_pipeline_does_not_continue_when_code_root_cd_fails() -> None:
    class CdFailRunner:
        commands: list[str]

        def __init__(self) -> None:
            self.commands = []

        async def run_command(self, command: str, *, timeout: int = 60) -> dict[str, Any]:
            self.commands.append(command)
            return {
                "exit_code": 0,
                "stdout": "__MEMSTACK_PIPELINE_EXIT_CODE__=2\n",
                "stderr": "/bin/sh: 2: cd: can't cd to /workspace/missing\n",
            }

    runner = CdFailRunner()
    provider = SandboxNativePipelineProvider(runner)

    result = await provider.run(
        PipelineContractSpec(
            code_root="/workspace/missing",
            stages=(
                PipelineStageSpec(stage="install", command="npm install", required=True),
                PipelineStageSpec(stage="test", command="npm test", required=True),
            ),
        )
    )

    assert result.status == "failed"
    assert result.reason == "stage install failed with exit 2"
    assert len(runner.commands) == 1
    assert runner.commands[0].find('if [ "$code" -ne 0 ]; then') < runner.commands[0].find(
        "npm install"
    )


@pytest.mark.asyncio
async def test_sandbox_native_pipeline_stops_on_required_stage_failure() -> None:
    runner = _FakeSandboxRunner([2, 0])
    provider = SandboxNativePipelineProvider(runner)
    result = await provider.run(
        PipelineContractSpec(
            stages=(
                PipelineStageSpec(stage="test", command="npm test", required=True),
                PipelineStageSpec(stage="build", command="npm run build", required=True),
            ),
        )
    )

    assert result.status == "failed"
    assert result.reason == "stage test failed with exit 2"
    assert "ci_pipeline:failed" in result.evidence_refs
    assert len(runner.commands) == 1


@pytest.mark.asyncio
async def test_verifier_requires_pipeline_evidence_for_delivery_phase() -> None:
    verifier = AcceptanceCriterionVerifier()
    node = _node(metadata={"iteration_phase": "implement", "pipeline_required": True})

    report = await verifier.verify(
        VerificationContext(workspace_id="ws-1", node=node, stdout="worker completed")
    )

    assert not report.passed
    assert any(result.criterion.kind is CriterionKind.CI_PIPELINE for result in report.results)
    assert not report.hard_fail


@pytest.mark.asyncio
async def test_verifier_accepts_pipeline_evidence_for_delivery_phase() -> None:
    verifier = AcceptanceCriterionVerifier()
    node = _node(metadata={"iteration_phase": "implement", "pipeline_required": True})

    report = await verifier.verify(
        VerificationContext(
            workspace_id="ws-1",
            node=node,
            stdout="worker completed",
            artifacts={"pipeline_evidence_refs": ["ci_pipeline:passed"]},
        )
    )

    assert report.passed


@pytest.mark.asyncio
async def test_verifier_accepts_pipeline_evidence_from_node_metadata() -> None:
    verifier = AcceptanceCriterionVerifier()
    node = _node(
        metadata={
            "iteration_phase": "implement",
            "pipeline_required": True,
            "pipeline_evidence_refs": ["ci_pipeline:passed"],
        }
    )

    report = await verifier.verify(
        VerificationContext(workspace_id="ws-1", node=node, stdout="worker completed")
    )

    assert report.passed


@pytest.mark.asyncio
async def test_verifier_ignores_stale_attempt_status_after_pipeline_success() -> None:
    verifier = AcceptanceCriterionVerifier()
    node = _node(
        metadata={
            "iteration_phase": "implement",
            "pipeline_required": True,
            "pipeline_evidence_refs": [
                "ci_pipeline:passed",
                "pipeline_run:success:run-1",
            ],
        }
    )

    report = await verifier.verify(
        VerificationContext(
            workspace_id="ws-1",
            node=node,
            attempt_id=None,
            stdout="worker completed",
            artifacts={"last_attempt_status": "rejected"},
        )
    )

    assert report.passed


@pytest.mark.asyncio
async def test_verifier_requires_deployment_health_for_deploy_phase() -> None:
    verifier = AcceptanceCriterionVerifier()
    node = _node(
        metadata={
            "iteration_phase": "deploy",
            "pipeline_required": True,
            "pipeline_evidence_refs": [
                "ci_pipeline:passed",
                "pipeline_run:success:run-1",
            ],
        }
    )

    report = await verifier.verify(
        VerificationContext(workspace_id="ws-1", node=node, stdout="worker completed")
    )

    assert not report.passed
    assert any(
        result.criterion.kind is CriterionKind.DEPLOYMENT_HEALTH
        and "missing preview deployment health evidence" in (result.message or "")
        for result in report.results
    )


@pytest.mark.asyncio
async def test_verifier_accepts_deploy_phase_with_pipeline_and_health() -> None:
    verifier = AcceptanceCriterionVerifier()
    node = _node(
        metadata={
            "iteration_phase": "deploy",
            "pipeline_required": True,
            "pipeline_evidence_refs": [
                "ci_pipeline:passed",
                "pipeline_run:success:run-1",
                "preview_url:default:/api/v1/projects/p/sandbox/http-services/default/proxy/",
                "deployment_health:passed:default",
                "deployment_health:passed",
            ],
        }
    )

    report = await verifier.verify(
        VerificationContext(workspace_id="ws-1", node=node, stdout="worker completed")
    )

    assert report.passed


@pytest.mark.asyncio
async def test_verifier_requires_named_service_deployment_health() -> None:
    verifier = AcceptanceCriterionVerifier()
    node = _node(
        metadata={
            "iteration_phase": "deploy",
            "pipeline_required": True,
            "pipeline_evidence_refs": [
                "ci_pipeline:passed",
                "deployment_health:passed:frontend",
                "deployment_health:failed:admin",
            ],
        }
    )
    node = replace(
        node,
        acceptance_criteria=(
            AcceptanceCriterion(
                kind=CriterionKind.DEPLOYMENT_HEALTH,
                spec={"service_id": "frontend"},
                required=True,
            ),
        ),
    )

    report = await verifier.verify(
        VerificationContext(workspace_id="ws-1", node=node, stdout="worker completed")
    )

    assert report.passed


@pytest.mark.asyncio
async def test_verifier_blocks_required_service_health_failure() -> None:
    verifier = AcceptanceCriterionVerifier()
    node = _node(
        metadata={
            "iteration_phase": "deploy",
            "pipeline_required": True,
            "pipeline_evidence_refs": [
                "ci_pipeline:passed",
                "deployment_health:failed:frontend",
            ],
        }
    )
    node = replace(
        node,
        acceptance_criteria=(
            AcceptanceCriterion(
                kind=CriterionKind.DEPLOYMENT_HEALTH,
                spec={"service_id": "frontend"},
                required=True,
            ),
        ),
    )

    report = await verifier.verify(
        VerificationContext(workspace_id="ws-1", node=node, stdout="worker completed")
    )

    assert not report.passed


def test_pipeline_contract_uses_workspace_delivery_metadata() -> None:
    contract = build_pipeline_contract_from_metadata(
        workspace_metadata={
            "delivery_cicd": {
                "provider": "sandbox_native",
                "timeout_seconds": 120,
                "test_command": "pnpm test",
                "build_command": "pnpm build",
                "health_url": "http://127.0.0.1:4173",
            }
        },
        fallback_code_root="/workspace/app",
    )

    assert contract.provider == "sandbox_native"
    assert contract.code_root == "/workspace/app"
    assert [stage.stage for stage in contract.stages] == ["test", "build", "health"]


def test_default_npm_test_stage_skips_missing_test_script() -> None:
    contract = build_pipeline_contract_from_metadata(
        workspace_metadata={},
        fallback_code_root="/workspace/app",
    )

    test_stage = next(stage for stage in contract.stages if stage.stage == "test")

    assert "p.scripts&&p.scripts.test" in test_stage.command
    assert "no npm test script" in test_stage.command


def test_pipeline_contract_maps_legacy_deploy_fields_to_default_service() -> None:
    contract = build_pipeline_contract_from_metadata(
        workspace_metadata={
            "delivery_cicd": {
                "deploy_command": "pnpm dev --host 0.0.0.0 --port 4173",
                "preview_port": 4173,
                "health_command": "curl -fsS http://127.0.0.1:4173/",
            }
        },
        fallback_code_root="/workspace/app",
    )

    assert [service.service_id for service in contract.services] == ["default"]
    assert contract.services[0].internal_port == 4173
    assert contract.services[0].start_command.startswith("pnpm dev")
    assert [
        (stage.stage, stage.service_id)
        for stage in contract.stages
        if stage.stage in {"deploy", "health"}
    ] == [("deploy", "default"), ("health", "default")]


def test_pipeline_contract_supports_multiple_services() -> None:
    contract = build_pipeline_contract_from_metadata(
        workspace_metadata={
            "delivery_cicd": {
                "services": [
                    {
                        "service_id": "frontend",
                        "name": "Frontend",
                        "start_command": "pnpm dev --host 0.0.0.0 --port 3000",
                        "internal_port": 3000,
                        "health_path": "/",
                        "required": True,
                    },
                    {
                        "service_id": "admin",
                        "name": "Admin",
                        "start_command": "pnpm admin --host 0.0.0.0 --port 3001",
                        "internal_port": 3001,
                        "health_path": "/admin",
                        "required": False,
                    },
                ]
            }
        },
        fallback_code_root="/workspace/app",
    )

    assert [service.service_id for service in contract.services] == ["frontend", "admin"]
    assert [stage.service_id for stage in contract.stages if stage.stage == "deploy"] == [
        "frontend",
        "admin",
    ]


def test_agent_managed_pipeline_probe_maps_start_script_to_service() -> None:
    proposal = _parse_agent_managed_pipeline_probe(
        '{"service":{"service_id":"default","name":"tetris-game",'
        '"start_command":"npm start","internal_port":3001,'
        '"health_path":"/api/health"},"reason":"root package.json start script"}',
        preview_port=3000,
    )

    assert proposal is not None
    assert proposal["contract_source"] == "agent_sandbox_scan"
    assert proposal["contract_confidence"] >= 0.8
    assert proposal["services"] == [
        {
            "service_id": "default",
            "name": "tetris-game",
            "start_command": "npm start",
            "internal_port": 3001,
            "path_prefix": "/",
            "health_path": "/api/health",
            "required": True,
            "auto_open": True,
        }
    ]


@pytest.mark.asyncio
async def test_agent_managed_pipeline_probe_runner_exit_zero_generates_proposal() -> None:
    runner = _FakeProbeRunner(
        exit_code=0,
        stdout=(
            '{"service":{"service_id":"default","name":"tetris-game",'
            '"start_command":"npm start","internal_port":3001,'
            '"health_path":"/api/health"},"reason":"root package.json start script"}'
        ),
    )

    proposal = await _propose_agent_managed_pipeline_contract(
        runner=runner,
        code_root="/workspace/my-game",
        preview_port=3000,
    )

    assert proposal is not None
    assert proposal["services"][0]["internal_port"] == 3001
    assert runner.commands


def test_successful_deploy_pipeline_completes_node_without_worker_reverification() -> None:
    node = _node(metadata={"iteration_phase": "deploy", "pipeline_required": True})

    intent, execution = _pipeline_completion_node_state(node=node, status="success")

    assert intent is TaskIntent.DONE
    assert execution is TaskExecution.IDLE


def test_successful_implement_pipeline_still_waits_for_worker_context_without_attempt() -> None:
    node = _node(metadata={"iteration_phase": "implement", "pipeline_required": True})

    intent, execution = _pipeline_completion_node_state(node=node, status="success")

    assert intent is TaskIntent.IN_PROGRESS
    assert execution is TaskExecution.REPORTED


def test_agent_managed_pipeline_probe_adds_port_to_static_command() -> None:
    proposal = _parse_agent_managed_pipeline_probe(
        '{"service":{"service_id":"default","name":"Static Preview",'
        '"start_command":"python3 -m http.server --bind 0.0.0.0",'
        '"health_path":"/"},"reason":"public/index.html static fallback"}',
        preview_port=4123,
    )

    assert proposal is not None
    service = proposal["services"][0]
    assert service["internal_port"] == 4123
    assert service["start_command"] == "python3 -m http.server --bind 0.0.0.0 4123"


def test_agent_managed_pipeline_probe_adds_vite_port_flag() -> None:
    proposal = _parse_agent_managed_pipeline_probe(
        '{"service":{"service_id":"default","name":"vite-app",'
        '"start_command":"npm run dev -- --host 0.0.0.0",'
        '"health_path":"/"},"reason":"root package.json dev script"}',
        preview_port=5173,
    )

    assert proposal is not None
    service = proposal["services"][0]
    assert service["internal_port"] == 5173
    assert service["start_command"] == "npm run dev -- --host 0.0.0.0 --port 5173"
