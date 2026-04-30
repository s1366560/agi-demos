"""Unit tests for harness-native workspace CI/CD primitives."""

from __future__ import annotations

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
