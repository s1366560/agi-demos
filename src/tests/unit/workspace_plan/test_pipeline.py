"""Unit tests for harness-native workspace CI/CD primitives."""

from __future__ import annotations

import asyncio
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
from src.domain.ports.services.workspace_verification_judge_port import (
    WorkspaceVerificationFeedbackItem,
    WorkspaceVerificationFeedbackKind,
    WorkspaceVerificationFeedbackSeverity,
    WorkspaceVerificationFeedbackTargetLayer,
    WorkspaceVerificationJudgeRequest,
    WorkspaceVerificationJudgeResult,
    WorkspaceVerificationJudgeVerdict,
    WorkspaceVerificationRecommendedAction,
)
from src.infrastructure.agent.workspace_plan.outbox_handlers import (
    _needs_agent_managed_pipeline_proposal,
    _node_has_required_deployment_health,
    _pipeline_completion_node_state,
    _pipeline_result_summary,
    _requires_preview_deployment,
    _workspace_proxy_service_id,
    _workspace_scoped_pipeline_contract,
)
from src.infrastructure.agent.workspace_plan.pipeline import (
    PipelineContractSpec,
    PipelineRunResult,
    PipelineServiceSpec,
    PipelineStageResult,
    PipelineStageSpec,
    SandboxNativePipelineProvider,
    build_pipeline_contract_from_metadata,
)
from src.infrastructure.agent.workspace_plan.supervisor import _should_request_pipeline_from_report
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


class _FakeVerificationJudge:
    def __init__(self, result: WorkspaceVerificationJudgeResult) -> None:
        self.result = result
        self.requests: list[WorkspaceVerificationJudgeRequest] = []

    async def judge(
        self,
        request: WorkspaceVerificationJudgeRequest,
    ) -> WorkspaceVerificationJudgeResult:
        self.requests.append(request)
        return self.result


class _SlowVerificationJudge:
    def __init__(self) -> None:
        self.requests: list[WorkspaceVerificationJudgeRequest] = []

    async def judge(
        self,
        request: WorkspaceVerificationJudgeRequest,
    ) -> WorkspaceVerificationJudgeResult:
        self.requests.append(request)
        await asyncio.sleep(10)
        return WorkspaceVerificationJudgeResult(
            verdict=WorkspaceVerificationJudgeVerdict.ACCEPTED,
            rationale="late success",
            confidence=1.0,
        )


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
async def test_verifier_rejects_current_failed_pipeline_status_over_historical_success() -> None:
    verifier = AcceptanceCriterionVerifier()
    node = _node(
        metadata={
            "iteration_phase": "deploy",
            "pipeline_required": True,
            "pipeline_status": "failed",
            "pipeline_gate_status": "failed",
            "pipeline_evidence_refs": [
                "ci_pipeline:passed",
                "pipeline_run:success:old-run",
                "ci_pipeline:failed",
                "pipeline_run:failed:new-run",
            ],
        }
    )

    report = await verifier.verify(
        VerificationContext(workspace_id="ws-1", node=node, stdout="worker completed")
    )

    assert not report.passed
    assert any(
        result.message == "harness-native CI pipeline failed; route through recovery"
        for result in report.results
    )


@pytest.mark.asyncio
async def test_verifier_ignores_stale_failed_pipeline_for_new_worker_commit() -> None:
    verifier = AcceptanceCriterionVerifier()
    node = _node(
        metadata={
            "iteration_phase": "deploy",
            "pipeline_required": True,
            "pipeline_status": "failed",
            "pipeline_gate_status": "failed",
            "source_publish_commit_ref": "e63e1104d10982494bfaa3e449e9e312f2e843c6",
            "pipeline_last_summary": "Drone build #41 failed in docker-build exited 137",
            "pipeline_evidence_refs": [
                "ci_pipeline:failed",
                "pipeline_run:failed:old-run",
            ],
        }
    )

    report = await verifier.verify(
        VerificationContext(
            workspace_id="ws-1",
            node=node,
            attempt_id="attempt-2",
            stdout="worker completed",
            artifacts={
                "candidate_artifacts": ["commit_ref:bce4286b"],
                "candidate_verifications": ["worker_report:completed"],
            },
        )
    )

    assert not report.passed
    pipeline_results = [
        result for result in report.results if result.criterion.kind is CriterionKind.CI_PIPELINE
    ]
    assert pipeline_results
    assert all(
        "previous pipeline evidence belongs to e63e1104" in r.message for r in pipeline_results
    )
    assert all("docker-build exited 137" not in r.message for r in pipeline_results)


@pytest.mark.asyncio
async def test_verifier_accepts_pipeline_result_for_source_commit_after_merge_publish() -> None:
    verifier = AcceptanceCriterionVerifier()
    node = _node(
        metadata={
            "iteration_phase": "deploy",
            "pipeline_required": True,
            "pipeline_status": "failed",
            "pipeline_gate_status": "failed",
            "source_publish_commit_ref": "6d2c2848",
            "source_publish_source_commit_ref": "bce4286b",
            "pipeline_last_summary": (
                "Drone build #43 failed in workspace-ci/deploy; "
                "server gave HTTP response to HTTPS client"
            ),
            "pipeline_evidence_refs": [
                "ci_pipeline:failed",
                "pipeline_run:failed:drone-43",
            ],
        }
    )

    report = await verifier.verify(
        VerificationContext(
            workspace_id="ws-1",
            node=node,
            attempt_id="attempt-2",
            stdout="worker completed",
            artifacts={
                "candidate_artifacts": ["commit_ref:bce4286b"],
                "candidate_verifications": ["worker_report:completed"],
            },
        )
    )

    assert not report.passed
    pipeline_results = [
        result for result in report.results if result.criterion.kind is CriterionKind.CI_PIPELINE
    ]
    assert pipeline_results
    assert any("workspace-ci/deploy" in result.message for result in pipeline_results)
    assert all(
        "previous pipeline evidence belongs" not in result.message for result in pipeline_results
    )


@pytest.mark.asyncio
async def test_verifier_uses_latest_attempt_commit_when_report_contains_history() -> None:
    verifier = AcceptanceCriterionVerifier()
    node = _node(
        metadata={
            "iteration_phase": "deploy",
            "pipeline_required": True,
            "pipeline_status": "failed",
            "pipeline_gate_status": "failed",
            "source_publish_commit_ref": "6d2c2848",
            "source_publish_source_commit_ref": "13aeda8",
            "pipeline_last_summary": "Drone build #46 failed in workspace-ci/deploy",
            "pipeline_evidence_refs": ["ci_pipeline:failed", "pipeline_run:failed:drone-46"],
        }
    )

    report = await verifier.verify(
        VerificationContext(
            workspace_id="ws-1",
            node=node,
            attempt_id="attempt-3",
            stdout="worker completed",
            artifacts={
                "candidate_artifacts": [
                    "commit_ref:bce4286b",
                    "git_diff_summary:.drone.yml old deploy fix",
                    "commit_ref:13aeda8",
                    "git_diff_summary:.drone.yml removed registry pull",
                ],
                "candidate_verifications": ["worker_report:completed"],
            },
        )
    )

    assert not report.passed
    pipeline_results = [
        result for result in report.results if result.criterion.kind is CriterionKind.CI_PIPELINE
    ]
    assert pipeline_results
    assert all(
        "previous pipeline evidence belongs" not in result.message for result in pipeline_results
    )


@pytest.mark.asyncio
async def test_verifier_hides_stale_pipeline_metadata_from_judge() -> None:
    judge = _FakeVerificationJudge(
        WorkspaceVerificationJudgeResult(
            verdict=WorkspaceVerificationJudgeVerdict.RETRY_INFRASTRUCTURE,
            rationale="missing pipeline evidence",
            failed_criteria=("ci_pipeline",),
            required_next_action="run pipeline for current commit",
            confidence=0.8,
        )
    )
    verifier = AcceptanceCriterionVerifier(verification_judge=judge)
    node = _node(
        metadata={
            "iteration_phase": "deploy",
            "pipeline_required": True,
            "pipeline_status": "failed",
            "pipeline_gate_status": "failed",
            "source_publish_commit_ref": "e63e1104d10982494bfaa3e449e9e312f2e843c6",
            "pipeline_last_summary": "Drone build #41 failed in docker-build exited 137",
            "pipeline_evidence_refs": [
                "ci_pipeline:failed",
                "pipeline_run:failed:old-run",
            ],
        }
    )

    await verifier.verify(
        VerificationContext(
            workspace_id="ws-1",
            node=node,
            attempt_id="attempt-2",
            stdout="worker completed",
            artifacts={
                "candidate_artifacts": ["commit_ref:bce4286b"],
                "candidate_verifications": ["worker_report:completed"],
            },
        )
    )

    assert judge.requests
    assert "pipeline_status" not in judge.requests[0].task_metadata
    assert "pipeline_last_summary" not in judge.requests[0].task_metadata


@pytest.mark.asyncio
async def test_verifier_treats_running_pipeline_as_pending_current_evidence() -> None:
    verifier = AcceptanceCriterionVerifier()
    node = _node(
        metadata={
            "iteration_phase": "deploy",
            "pipeline_required": True,
            "pipeline_status": "running",
            "pipeline_gate_status": "running",
            "pipeline_run_id": "run-new",
            "source_publish_source_commit_ref": "c24521e0fc4da720d19893901cd4d04773782de1",
            "pipeline_failure_summary": "Drone #129 failed: Cannot find module '/app/dist/index.js'",
            "pipeline_last_summary": "Drone #129 failed: Cannot find module '/app/dist/index.js'",
            "pipeline_evidence_refs": ["ci_pipeline:failed", "pipeline_run:failed:old-run"],
        }
    )

    report = await verifier.verify(
        VerificationContext(
            workspace_id="ws-1",
            node=node,
            attempt_id="attempt-3",
            stdout="worker completed",
            artifacts={
                "candidate_artifacts": ["commit_ref:c24521e"],
                "candidate_verifications": ["worker_report:completed"],
            },
        )
    )

    pipeline_results = [
        result for result in report.results if result.criterion.kind is CriterionKind.CI_PIPELINE
    ]
    assert pipeline_results
    assert any("pipeline is running (run-new)" in result.message for result in pipeline_results)
    assert all("Cannot find module" not in result.message for result in pipeline_results)


@pytest.mark.asyncio
async def test_verifier_hides_pending_pipeline_terminal_metadata_from_judge() -> None:
    judge = _FakeVerificationJudge(
        WorkspaceVerificationJudgeResult(
            verdict=WorkspaceVerificationJudgeVerdict.RETRY_INFRASTRUCTURE,
            rationale="pipeline is still running",
            failed_criteria=("ci_pipeline",),
            required_next_action="wait for current pipeline evidence",
            confidence=0.8,
        )
    )
    verifier = AcceptanceCriterionVerifier(verification_judge=judge)
    node = _node(
        metadata={
            "iteration_phase": "deploy",
            "pipeline_required": True,
            "pipeline_status": "running",
            "pipeline_gate_status": "running",
            "pipeline_run_id": "run-new",
            "source_publish_source_commit_ref": "c24521e0fc4da720d19893901cd4d04773782de1",
            "pipeline_failure_summary": "Drone #129 failed: Cannot find module '/app/dist/index.js'",
            "pipeline_last_summary": "Drone #129 failed: Cannot find module '/app/dist/index.js'",
            "pipeline_evidence_refs": ["ci_pipeline:failed", "pipeline_run:failed:old-run"],
        }
    )

    await verifier.verify(
        VerificationContext(
            workspace_id="ws-1",
            node=node,
            attempt_id="attempt-3",
            stdout="worker completed",
            artifacts={
                "candidate_artifacts": ["commit_ref:c24521e"],
                "candidate_verifications": ["worker_report:completed"],
            },
        )
    )

    assert judge.requests
    request = judge.requests[0]
    assert request.task_metadata["pipeline_status"] == "running"
    assert request.task_metadata["pipeline_run_id"] == "run-new"
    assert "pipeline_failure_summary" not in request.task_metadata
    assert "pipeline_last_summary" not in request.task_metadata
    assert "ci_pipeline:failed" not in request.task_evidence_refs
    assert "pipeline_run:failed:old-run" not in request.task_evidence_refs
    assert "Cannot find module" not in str(request.latest_verification_results)


@pytest.mark.asyncio
async def test_verifier_times_out_slow_verification_judge(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WORKSPACE_VERIFICATION_JUDGE_TIMEOUT_SECONDS", "0.01")
    judge = _SlowVerificationJudge()
    verifier = AcceptanceCriterionVerifier(verification_judge=judge)
    node = _node(
        metadata={
            "iteration_phase": "deploy",
            "pipeline_required": True,
            "source_publish_commit_ref": "6490da4",
        }
    )

    report = await verifier.verify(
        VerificationContext(
            workspace_id="ws-1",
            node=node,
            attempt_id="attempt-2",
            stdout="worker completed",
            artifacts={
                "candidate_artifacts": ["commit_ref:6490da4"],
                "candidate_verifications": ["worker_report:completed"],
            },
        )
    )

    judge_result = next(
        result
        for result in report.results
        if result.criterion.spec.get("name") == "retryable_infrastructure_failure"
    )
    feedback = judge_result.criterion.spec["feedback_items"][0]
    assert judge.requests
    assert not report.passed
    assert judge_result.criterion.spec["judge_verdict"] == "retry_infrastructure"
    assert "timed out after 0.01s" in (judge_result.message or "")
    assert feedback["target_layer"] == "runtime"
    assert feedback["recommended_action"] == "retry_infra"
    assert feedback["failure_signature"] == "workspace_verification_judge_timeout"
    assert _should_request_pipeline_from_report(node, report)


@pytest.mark.asyncio
async def test_supervisor_requests_pipeline_for_missing_drone_evidence_feedback() -> None:
    judge = _FakeVerificationJudge(
        WorkspaceVerificationJudgeResult(
            verdict=WorkspaceVerificationJudgeVerdict.NEEDS_REWORK,
            rationale="current commit has no Drone evidence yet",
            failed_criteria=("ci_pipeline",),
            required_next_action=(
                "Trigger Drone for commit 6490da4 and capture live pipeline output."
            ),
            feedback_items=(
                WorkspaceVerificationFeedbackItem(
                    target_layer=WorkspaceVerificationFeedbackTargetLayer.WORKER,
                    feedback_kind=WorkspaceVerificationFeedbackKind.MISSING_EVIDENCE,
                    severity=WorkspaceVerificationFeedbackSeverity.BLOCKING,
                    recommended_action=WorkspaceVerificationRecommendedAction.RETRY_WORKER,
                    summary=(
                        "CI pipeline not executed or evidence not captured for commit "
                        "6490da4. Trigger Drone and record live pipeline output."
                    ),
                    evidence_refs=(
                        "commit_ref:6490da4",
                        "ci_pipeline evidence: none for 6490da4",
                    ),
                    failure_signature="missing_ci_evidence_6490da4",
                ),
            ),
            confidence=0.7,
        )
    )
    verifier = AcceptanceCriterionVerifier(verification_judge=judge)
    node = _node(
        metadata={
            "iteration_phase": "deploy",
            "pipeline_required": True,
            "pipeline_status": "failed",
            "pipeline_gate_status": "failed",
            "source_publish_commit_ref": "1087365",
            "pipeline_evidence_refs": ["ci_pipeline:failed", "pipeline_run:failed:old-run"],
        }
    )

    report = await verifier.verify(
        VerificationContext(
            workspace_id="ws-1",
            node=node,
            attempt_id="attempt-3",
            stdout="worker completed",
            artifacts={
                "candidate_artifacts": ["commit_ref:6490da4"],
                "candidate_verifications": ["worker_report:completed"],
            },
        )
    )

    assert _should_request_pipeline_from_report(node, report)


@pytest.mark.asyncio
async def test_verifier_surfaces_pipeline_failure_summary() -> None:
    verifier = AcceptanceCriterionVerifier()
    node = _node(
        metadata={
            "iteration_phase": "deploy",
            "pipeline_required": True,
            "pipeline_status": "failed",
            "pipeline_last_summary": (
                "Drone build s1366560/my-evo#26 finished with status failure; "
                "failing stage workspace-ci/deploy exited 1; "
                'Error response from daemon: Get "https://host.docker.internal:5001/v2/": '
                "http: server gave HTTP response to HTTPS client"
            ),
        }
    )

    report = await verifier.verify(
        VerificationContext(workspace_id="ws-1", node=node, stdout="worker completed")
    )

    assert not report.passed
    assert any(
        "workspace-ci/deploy" in result.message and "HTTPS client" in result.message
        for result in report.results
        if result.criterion.kind is CriterionKind.CI_PIPELINE
    )


@pytest.mark.asyncio
async def test_verifier_routes_drone_socket_mount_failure_to_worker() -> None:
    judge = _FakeVerificationJudge(
        WorkspaceVerificationJudgeResult(
            verdict=WorkspaceVerificationJudgeVerdict.RETRY_INFRASTRUCTURE,
            rationale="docker daemon unavailable",
            failed_criteria=("ci_pipeline",),
            required_next_action="retry infrastructure",
            confidence=0.8,
        )
    )
    verifier = AcceptanceCriterionVerifier(verification_judge=judge)
    node = _node(
        metadata={
            "iteration_phase": "deploy",
            "pipeline_required": True,
            "pipeline_status": "failed",
            "last_worker_report_type": "completed",
            "last_worker_report_attempt_id": "attempt-1",
            "pipeline_last_summary": (
                "Drone build s1366560/my-evo#31 finished with status error; "
                "failing stage workspace-ci/docker-deploy exited 255; "
                "error mounting docker.proxy.sock to rootfs at /var/run: not a directory"
            ),
        }
    )

    report = await verifier.verify(
        VerificationContext(
            workspace_id="ws-1",
            node=node,
            attempt_id="attempt-1",
            stdout="worker completed",
        )
    )

    judge_result = next(
        result
        for result in report.results
        if result.criterion.spec.get("name") == "workspace_verification_judge"
    )
    feedback = judge_result.criterion.spec["feedback_items"][0]
    assert not report.passed
    assert judge_result.criterion.spec["judge_verdict"] == "needs_rework"
    assert judge_result.criterion.spec["next_action_kind"] == "retry_same_node"
    assert (
        "path to mount docker-sock at /var/run/docker.sock"
        in judge_result.criterion.spec["required_next_action"]
    )
    assert feedback["target_layer"] == "worker"
    assert feedback["failure_signature"] == "drone-docker-socket-mounted-to-var-run"


@pytest.mark.asyncio
async def test_verifier_routes_drone_yaml_unmarshal_failure_to_worker() -> None:
    judge = _FakeVerificationJudge(
        WorkspaceVerificationJudgeResult(
            verdict=WorkspaceVerificationJudgeVerdict.RETRY_INFRASTRUCTURE,
            rationale="pipeline did not run",
            failed_criteria=("ci_pipeline",),
            required_next_action="retry infrastructure",
            confidence=0.8,
        )
    )
    verifier = AcceptanceCriterionVerifier(verification_judge=judge)
    node = _node(
        metadata={
            "iteration_phase": "deploy",
            "pipeline_required": True,
            "pipeline_status": "failed",
            "last_worker_report_type": "completed",
            "last_worker_report_attempt_id": "attempt-1",
            "pipeline_last_summary": (
                "Drone build s1366560/my-evo#72 finished with status error; "
                "failing stage drone/build; yaml: unmarshal errors: "
                "line 82: cannot unmarshal !!map into string"
            ),
        }
    )

    report = await verifier.verify(
        VerificationContext(
            workspace_id="ws-1",
            node=node,
            attempt_id="attempt-1",
            stdout="worker completed",
        )
    )

    judge_result = next(
        result
        for result in report.results
        if result.criterion.spec.get("name") == "workspace_verification_judge"
    )
    feedback = judge_result.criterion.spec["feedback_items"][0]
    assert not report.passed
    assert judge_result.criterion.spec["judge_verdict"] == "needs_rework"
    assert judge_result.criterion.spec["next_action_kind"] == "retry_same_node"
    assert "quote shell commands" in judge_result.criterion.spec["required_next_action"]
    assert "commands[]` item is a string" in judge_result.criterion.spec["required_next_action"]
    assert (
        "preserve the docker deploy contract" in judge_result.criterion.spec["required_next_action"]
    )
    assert feedback["target_layer"] == "worker"
    assert feedback["failure_signature"] == "drone-yaml-configuration-unmarshal-into-string"


@pytest.mark.asyncio
async def test_verifier_routes_drone_multi_service_deploy_coverage_to_worker() -> None:
    judge = _FakeVerificationJudge(
        WorkspaceVerificationJudgeResult(
            verdict=WorkspaceVerificationJudgeVerdict.RETRY_INFRASTRUCTURE,
            rationale="pipeline config failed before build",
            failed_criteria=("ci_pipeline",),
            required_next_action="retry infrastructure",
            confidence=0.8,
        )
    )
    verifier = AcceptanceCriterionVerifier(verification_judge=judge)
    node = _node(
        metadata={
            "iteration_phase": "deploy",
            "pipeline_required": True,
            "pipeline_status": "failed",
            "last_worker_report_type": "completed",
            "last_worker_report_attempt_id": "attempt-1",
            "pipeline_last_summary": (
                "Drone build .drone.yml preflight failed; docker deploy stage deploy "
                "does not cover required services: my-evo-frontend. The deploy step must "
                "start or update every service declared in "
                "delivery_cicd.drone.deploy.docker.deploy_services."
            ),
        }
    )

    report = await verifier.verify(
        VerificationContext(
            workspace_id="ws-1",
            node=node,
            attempt_id="attempt-1",
            stdout="worker completed",
        )
    )

    judge_result = next(
        result
        for result in report.results
        if result.criterion.spec.get("name") == "workspace_verification_judge"
    )
    feedback = judge_result.criterion.spec["feedback_items"][0]
    assert not report.passed
    assert judge_result.criterion.spec["judge_verdict"] == "needs_rework"
    assert judge_result.criterion.spec["next_action_kind"] == "retry_same_node"
    assert (
        "do not deploy only the backend API" in judge_result.criterion.spec["required_next_action"]
    )
    assert feedback["target_layer"] == "worker"
    assert feedback["failure_signature"] == "drone-docker-deploy-missing-required-service"


@pytest.mark.asyncio
async def test_verifier_routes_drone_invalid_deploy_semantics_to_worker() -> None:
    judge = _FakeVerificationJudge(
        WorkspaceVerificationJudgeResult(
            verdict=WorkspaceVerificationJudgeVerdict.NEEDS_REWORK,
            rationale="pipeline failed; pull the registry image",
            failed_criteria=("ci_pipeline",),
            required_next_action="Pull host.docker.internal:5001/my-evo and rerun.",
            confidence=0.8,
        )
    )
    verifier = AcceptanceCriterionVerifier(verification_judge=judge)
    node = _node(
        metadata={
            "iteration_phase": "deploy",
            "pipeline_required": True,
            "pipeline_status": "failed",
            "pipeline_gate_status": "failed",
            "deploy_mode": "docker",
            "deployment_status": "invalid",
            "last_worker_report_type": "completed",
            "last_worker_report_attempt_id": "attempt-1",
            "deploy_validation_failure": "missing required deploy services: my-evo-app",
            "deploy_validation_issues": [
                "missing required deploy services: my-evo-app",
                "missing docker run/compose/stack/service deploy command",
            ],
            "pipeline_last_summary": (
                "Drone build s1366560/my-evo#131 deploy stage deploy did not implement "
                "docker deployment semantics"
            ),
        }
    )

    report = await verifier.verify(
        VerificationContext(
            workspace_id="ws-1",
            node=node,
            attempt_id="attempt-1",
            stdout="worker completed",
        )
    )

    judge_result = next(
        result
        for result in report.results
        if result.criterion.spec.get("name") == "workspace_verification_judge"
    )
    feedback = judge_result.criterion.spec["feedback_items"][0]
    assert not report.passed
    assert judge_result.criterion.spec["judge_verdict"] == "needs_rework"
    assert judge_result.criterion.spec["next_action_kind"] == "retry_same_node"
    assert (
        "align the docker run --name/service name"
        in (judge_result.criterion.spec["required_next_action"])
    )
    assert (
        "my-evo-app"
        in (judge_result.criterion.spec["required_next_action"])
    )
    assert feedback["target_layer"] == "worker"
    assert feedback["failure_signature"] == "drone-docker-deploy-missing-required-service"
    assert "did not observe required docker service coverage" in feedback["summary"]
    assert "my-evo-app" in feedback["summary"]


@pytest.mark.asyncio
async def test_verifier_routes_host_socket_registry_failure_to_worker() -> None:
    judge = _FakeVerificationJudge(
        WorkspaceVerificationJudgeResult(
            verdict=WorkspaceVerificationJudgeVerdict.RETRY_INFRASTRUCTURE,
            rationale="registry unavailable",
            failed_criteria=("ci_pipeline",),
            required_next_action="retry infrastructure",
            confidence=0.8,
        )
    )
    verifier = AcceptanceCriterionVerifier(verification_judge=judge)
    node = _node(
        metadata={
            "iteration_phase": "deploy",
            "pipeline_required": True,
            "pipeline_status": "failed",
            "last_worker_report_type": "completed",
            "last_worker_report_attempt_id": "attempt-1",
            "pipeline_last_summary": (
                "Drone build s1366560/my-evo#34 finished with status failure; "
                "failing stage workspace-ci/docker-deploy exited 1; "
                "+ docker pull host.docker.internal:5001/my-evo:drone-docker-e2e; "
                'Error response from daemon: Get "https://host.docker.internal:5001/v2/": '
                "http: server gave HTTP response to HTTPS client"
            ),
        }
    )

    report = await verifier.verify(
        VerificationContext(
            workspace_id="ws-1",
            node=node,
            attempt_id="attempt-1",
            stdout="worker completed",
        )
    )

    judge_result = next(
        result
        for result in report.results
        if result.criterion.spec.get("name") == "workspace_verification_judge"
    )
    feedback = judge_result.criterion.spec["feedback_items"][0]
    assert not report.passed
    assert judge_result.criterion.spec["judge_verdict"] == "needs_rework"
    assert judge_result.criterion.spec["next_action_kind"] == "retry_same_node"
    assert "deploy-local image tag" in judge_result.criterion.spec["required_next_action"]
    assert feedback["target_layer"] == "worker"
    assert feedback["failure_signature"] == "drone-host-socket-deploy-registry-host-internal"


@pytest.mark.asyncio
async def test_verifier_routes_localhost_registry_timeout_to_worker() -> None:
    judge = _FakeVerificationJudge(
        WorkspaceVerificationJudgeResult(
            verdict=WorkspaceVerificationJudgeVerdict.RETRY_INFRASTRUCTURE,
            rationale="registry unreachable",
            failed_criteria=("ci_pipeline",),
            required_next_action="retry infrastructure",
            confidence=0.8,
        )
    )
    verifier = AcceptanceCriterionVerifier(verification_judge=judge)
    node = _node(
        metadata={
            "iteration_phase": "deploy",
            "pipeline_required": True,
            "pipeline_status": "failed",
            "last_worker_report_type": "completed",
            "last_worker_report_attempt_id": "attempt-1",
            "pipeline_last_summary": (
                "Drone build s1366560/my-evo#35 finished with status failure; "
                "failing stage workspace-ci/docker-deploy exited 1; "
                "+ docker pull localhost:5001/my-evo:drone-docker-e2e; "
                'Error response from daemon: Get "http://localhost:5001/v2/": '
                "context deadline exceeded"
            ),
        }
    )

    report = await verifier.verify(
        VerificationContext(
            workspace_id="ws-1",
            node=node,
            attempt_id="attempt-1",
            stdout="worker completed",
        )
    )

    judge_result = next(
        result
        for result in report.results
        if result.criterion.spec.get("name") == "workspace_verification_judge"
    )
    feedback = judge_result.criterion.spec["feedback_items"][0]
    assert not report.passed
    assert judge_result.criterion.spec["judge_verdict"] == "needs_rework"
    assert judge_result.criterion.spec["next_action_kind"] == "retry_same_node"
    assert (
        "host.docker.internal:<port> or localhost:<port>"
        in judge_result.criterion.spec["required_next_action"]
    )
    assert feedback["target_layer"] == "worker"
    assert feedback["failure_signature"] == "drone-host-socket-localhost-registry-unreachable"


@pytest.mark.asyncio
async def test_verifier_routes_docker_host_port_conflict_to_worker() -> None:
    judge = _FakeVerificationJudge(
        WorkspaceVerificationJudgeResult(
            verdict=WorkspaceVerificationJudgeVerdict.RETRY_INFRASTRUCTURE,
            rationale="docker run failed",
            failed_criteria=("ci_pipeline",),
            required_next_action="retry infrastructure",
            confidence=0.8,
        )
    )
    verifier = AcceptanceCriterionVerifier(verification_judge=judge)
    node = _node(
        metadata={
            "iteration_phase": "deploy",
            "pipeline_required": True,
            "pipeline_status": "failed",
            "last_worker_report_type": "completed",
            "last_worker_report_attempt_id": "attempt-1",
            "pipeline_last_summary": (
                "Drone build s1366560/my-evo#54 finished with status failure; "
                "failing stage workspace-ci/deploy exited 125; "
                "+ docker run -d --name my-evo -p 8080:3001 -e PORT=3001 "
                "my-evo:drone-docker-e2e; "
                "docker: Error response from daemon: failed to set up container networking: "
                "driver failed programming external connectivity on endpoint my-evo: "
                "Bind for 0.0.0.0:8080 failed: port is already allocated"
            ),
        }
    )

    report = await verifier.verify(
        VerificationContext(
            workspace_id="ws-1",
            node=node,
            attempt_id="attempt-1",
            stdout="worker completed",
        )
    )

    judge_result = next(
        result
        for result in report.results
        if result.criterion.spec.get("name") == "workspace_verification_judge"
    )
    feedback = judge_result.criterion.spec["feedback_items"][0]
    assert not report.passed
    assert judge_result.criterion.spec["judge_verdict"] == "needs_rework"
    assert judge_result.criterion.spec["next_action_kind"] == "retry_same_node"
    assert "docker.deploy_host_port" in judge_result.criterion.spec["required_next_action"]
    assert "stale app containers" in judge_result.criterion.spec["required_next_action"]
    assert "docker inspect <container>" in judge_result.criterion.spec["required_next_action"]
    assert feedback["target_layer"] == "worker"
    assert feedback["failure_signature"] == "drone-docker-deploy-host-port-conflict"
    assert "stale containers" in feedback["summary"]


@pytest.mark.asyncio
async def test_verifier_routes_created_container_without_state_error_to_worker() -> None:
    judge = _FakeVerificationJudge(
        WorkspaceVerificationJudgeResult(
            verdict=WorkspaceVerificationJudgeVerdict.RETRY_INFRASTRUCTURE,
            rationale="container did not start",
            failed_criteria=("ci_pipeline",),
            required_next_action="retry infrastructure",
            confidence=0.8,
        )
    )
    verifier = AcceptanceCriterionVerifier(verification_judge=judge)
    node = _node(
        metadata={
            "iteration_phase": "deploy",
            "pipeline_required": True,
            "pipeline_status": "failed",
            "last_worker_report_type": "completed",
            "last_worker_report_attempt_id": "attempt-1",
            "pipeline_last_summary": (
                "Drone build s1366560/my-evo#134 finished with status failure; "
                "failing stage workspace-ci/deploy exited 1; "
                "ERROR: Container my-evo-app failed to start; "
                "CONTAINER ID IMAGE COMMAND CREATED STATUS PORTS NAMES "
                'a5a61726b3a1 my-evo:drone-docker-e2e "dumb-init -- sh -c" '
                "3 seconds ago Created my-evo-app"
            ),
        }
    )

    report = await verifier.verify(
        VerificationContext(
            workspace_id="ws-1",
            node=node,
            attempt_id="attempt-1",
            stdout="worker completed",
        )
    )

    judge_result = next(
        result
        for result in report.results
        if result.criterion.spec.get("name") == "workspace_verification_judge"
    )
    feedback = judge_result.criterion.spec["feedback_items"][0]
    assert not report.passed
    assert judge_result.criterion.spec["judge_verdict"] == "needs_rework"
    assert "docker inspect <container>" in judge_result.criterion.spec["required_next_action"]
    assert "stale app" in judge_result.criterion.spec["required_next_action"]
    assert feedback["target_layer"] == "worker"
    assert feedback["failure_signature"] == "drone-docker-deploy-container-created-not-running"


@pytest.mark.asyncio
async def test_verifier_does_not_treat_diff_failure_word_as_failed_test() -> None:
    verifier = AcceptanceCriterionVerifier()
    node = _node(
        metadata={
            "last_worker_report_type": "completed",
            "last_worker_report_attempt_id": "attempt-1",
            "candidate_artifacts": [
                "commit_ref:3df5e5a",
                "git_diff_summary:.drone.yml +3 lines (port cleanup, docker inspect on 2 failure paths)",
            ],
            "candidate_verifications": ["commit_ref:3df5e5a"],
        }
    )

    report = await verifier.verify(
        VerificationContext(
            workspace_id="ws-1",
            node=node,
            attempt_id="attempt-1",
            artifacts={
                "candidate_artifacts": [
                    "commit_ref:3df5e5a",
                    "git_diff_summary:.drone.yml +3 lines (port cleanup, docker inspect on 2 failure paths)",
                ],
                "candidate_verifications": ["commit_ref:3df5e5a"],
            },
            stdout="worker completed",
        )
    )

    failed_guard = [
        result
        for result in report.results
        if result.criterion.spec.get("name") == "failed_test_evidence"
    ]
    assert failed_guard == []


@pytest.mark.asyncio
async def test_verifier_still_flags_failed_test_run_evidence() -> None:
    verifier = AcceptanceCriterionVerifier()
    node = _node(
        metadata={
            "last_worker_report_type": "completed",
            "last_worker_report_attempt_id": "attempt-1",
            "candidate_verifications": ["test_run:npm test - 1 failed, 35 passed"],
        }
    )

    report = await verifier.verify(
        VerificationContext(
            workspace_id="ws-1",
            node=node,
            attempt_id="attempt-1",
            artifacts={
                "candidate_verifications": ["test_run:npm test - 1 failed, 35 passed"],
            },
            stdout="worker completed",
        )
    )

    failed_guard = next(
        result
        for result in report.results
        if result.criterion.spec.get("name") == "failed_test_evidence"
    )
    assert not failed_guard.passed
    assert "1 failed" in failed_guard.message


@pytest.mark.asyncio
async def test_verifier_routes_missing_deploy_probe_tool_to_worker() -> None:
    judge = _FakeVerificationJudge(
        WorkspaceVerificationJudgeResult(
            verdict=WorkspaceVerificationJudgeVerdict.RETRY_INFRASTRUCTURE,
            rationale="deploy health probe failed",
            failed_criteria=("ci_pipeline",),
            required_next_action="retry infrastructure",
            confidence=0.8,
        )
    )
    verifier = AcceptanceCriterionVerifier(verification_judge=judge)
    node = _node(
        metadata={
            "iteration_phase": "deploy",
            "pipeline_required": True,
            "pipeline_status": "failed",
            "last_worker_report_type": "completed",
            "last_worker_report_attempt_id": "attempt-1",
            "pipeline_last_summary": (
                "Drone build s1366560/my-evo#58 finished with status failure; "
                "failing stage workspace-ci/deploy exited 1; "
                "+ curl -sf http://host.docker.internal:18080/health || exit 1; "
                "/bin/sh: curl: not found"
            ),
        }
    )

    report = await verifier.verify(
        VerificationContext(
            workspace_id="ws-1",
            node=node,
            attempt_id="attempt-1",
            stdout="worker completed",
        )
    )

    judge_result = next(
        result
        for result in report.results
        if result.criterion.spec.get("name") == "workspace_verification_judge"
    )
    feedback = judge_result.criterion.spec["feedback_items"][0]
    assert not report.passed
    assert judge_result.criterion.spec["judge_verdict"] == "needs_rework"
    assert judge_result.criterion.spec["next_action_kind"] == "retry_same_node"
    assert (
        "docker.deploy_health_check_command" in judge_result.criterion.spec["required_next_action"]
    )
    assert "docker logs <container>" in judge_result.criterion.spec["required_next_action"]
    assert feedback["target_layer"] == "worker"
    assert feedback["failure_signature"] == "drone-docker-deploy-missing-health-probe-tool"


@pytest.mark.asyncio
async def test_verifier_routes_deploy_unhealthy_container_to_worker() -> None:
    judge = _FakeVerificationJudge(
        WorkspaceVerificationJudgeResult(
            verdict=WorkspaceVerificationJudgeVerdict.RETRY_INFRASTRUCTURE,
            rationale="deploy health failed",
            failed_criteria=("ci_pipeline",),
            required_next_action="retry infrastructure",
            confidence=0.8,
        )
    )
    verifier = AcceptanceCriterionVerifier(verification_judge=judge)
    node = _node(
        metadata={
            "iteration_phase": "deploy",
            "pipeline_required": True,
            "pipeline_status": "failed",
            "last_worker_report_type": "completed",
            "last_worker_report_attempt_id": "attempt-1",
            "pipeline_last_summary": (
                "Drone build s1366560/my-evo#60 finished with status failure; "
                "failing stage workspace-ci/deploy exited 1; "
                "+ docker run -d --name my-evo -p 18080:3001 "
                "-e DATABASE_URL=postgresql://postgres:password@host.docker.internal:5432/evomap "
                "my-evo:drone-docker-e2e; "
                "+ wget -qO- http://host.docker.internal:18080/health >/dev/null || exit 1; "
                "wget: can't connect to remote host (192.168.65.254): Connection refused"
            ),
        }
    )

    report = await verifier.verify(
        VerificationContext(
            workspace_id="ws-1",
            node=node,
            attempt_id="attempt-1",
            stdout="worker completed",
        )
    )

    judge_result = next(
        result
        for result in report.results
        if result.criterion.spec.get("name") == "workspace_verification_judge"
    )
    feedback = judge_result.criterion.spec["feedback_items"][0]
    assert not report.passed
    assert judge_result.criterion.spec["judge_verdict"] == "needs_rework"
    assert judge_result.criterion.spec["next_action_kind"] == "retry_same_node"
    assert "docker logs <container>" in judge_result.criterion.spec["required_next_action"]
    assert "sidecar" in judge_result.criterion.spec["required_next_action"]
    assert "DATABASE_URL" in judge_result.criterion.spec["required_next_action"]
    assert feedback["target_layer"] == "worker"
    assert feedback["failure_signature"] == "drone-docker-deploy-unhealthy-container"


@pytest.mark.asyncio
async def test_verifier_routes_started_container_health_refused_without_docker_run_to_worker() -> (
    None
):
    judge = _FakeVerificationJudge(
        WorkspaceVerificationJudgeResult(
            verdict=WorkspaceVerificationJudgeVerdict.RETRY_INFRASTRUCTURE,
            rationale="deploy health failed",
            failed_criteria=("ci_pipeline",),
            required_next_action="retry infrastructure",
            confidence=0.8,
        )
    )
    verifier = AcceptanceCriterionVerifier(verification_judge=judge)
    node = _node(
        metadata={
            "iteration_phase": "deploy",
            "pipeline_required": True,
            "pipeline_status": "failed",
            "last_worker_report_type": "completed",
            "last_worker_report_attempt_id": "attempt-1",
            "pipeline_last_summary": (
                "Drone build s1366560/my-evo#127 finished with status failure; "
                "failing stage workspace-ci/deploy exited 1; "
                "Container my-evo-deploy is running; "
                "CONTAINER ID IMAGE STATUS PORTS NAMES "
                "5a06b7897173 my-evo:drone-docker-e2e Up Less than a second "
                "(health: starting) 0.0.0.0:18080->3000/tcp my-evo-deploy; "
                "+ wget --timeout=10 -q -O- http://host.docker.internal:18080/health; "
                "wget: can't connect to remote host (192.168.65.254): Connection refused"
            ),
        }
    )

    report = await verifier.verify(
        VerificationContext(
            workspace_id="ws-1",
            node=node,
            attempt_id="attempt-1",
            stdout="worker completed",
        )
    )

    judge_result = next(
        result
        for result in report.results
        if result.criterion.spec.get("name") == "workspace_verification_judge"
    )
    feedback = judge_result.criterion.spec["feedback_items"][0]
    assert not report.passed
    assert judge_result.criterion.spec["judge_verdict"] == "needs_rework"
    assert judge_result.criterion.spec["next_action_kind"] == "retry_same_node"
    assert feedback["target_layer"] == "worker"
    assert feedback["failure_signature"] == "drone-docker-deploy-unhealthy-container"


@pytest.mark.asyncio
async def test_verifier_routes_deploy_health_signal_before_log_tail_to_worker() -> None:
    judge = _FakeVerificationJudge(
        WorkspaceVerificationJudgeResult(
            verdict=WorkspaceVerificationJudgeVerdict.NEEDS_REWORK,
            rationale="migration folder missing",
            failed_criteria=("ci_pipeline",),
            required_next_action="add migrations",
            confidence=0.8,
        )
    )
    verifier = AcceptanceCriterionVerifier(verification_judge=judge)
    node = _node(
        metadata={
            "iteration_phase": "deploy",
            "pipeline_required": True,
            "pipeline_status": "failed",
            "last_worker_report_type": "completed",
            "last_worker_report_attempt_id": "attempt-1",
            "pipeline_last_summary": (
                "Drone build s1366560/my-evo#69 finished with status failure; "
                "failing stage workspace-ci/deploy exited 1; "
                "+ docker run -d --name my-evo --network workspace-deploy "
                "-p 18080:3001 my-evo:drone-docker-e2e; "
                "failure_signals:\\n"
                "wget: can't connect to remote host (192.168.65.254): Connection refused\\n"
                "my-evo Exited (0) 9 seconds ago\\n"
                "No migration found in prisma/migrations; "
                'Datasource "db": PostgreSQL database "evomap"; '
                "No pending migrations to apply."
            ),
        }
    )

    report = await verifier.verify(
        VerificationContext(
            workspace_id="ws-1",
            node=node,
            attempt_id="attempt-1",
            stdout="worker completed",
        )
    )

    judge_result = next(
        result
        for result in report.results
        if result.criterion.spec.get("name") == "workspace_verification_judge"
    )
    feedback = judge_result.criterion.spec["feedback_items"][0]
    assert not report.passed
    assert judge_result.criterion.spec["judge_verdict"] == "needs_rework"
    assert judge.requests == []
    assert "long-lived server entrypoint" in judge_result.criterion.spec["required_next_action"]
    assert "Preserve existing deploy fixes" in judge_result.criterion.spec["required_next_action"]
    assert feedback["failure_signature"] == "drone-docker-deploy-unhealthy-container"


@pytest.mark.asyncio
async def test_verifier_routes_deploy_container_name_conflict_to_worker() -> None:
    judge = _FakeVerificationJudge(
        WorkspaceVerificationJudgeResult(
            verdict=WorkspaceVerificationJudgeVerdict.RETRY_INFRASTRUCTURE,
            rationale="deploy retry failed",
            failed_criteria=("ci_pipeline",),
            required_next_action="retry infrastructure",
            confidence=0.8,
        )
    )
    verifier = AcceptanceCriterionVerifier(verification_judge=judge)
    node = _node(
        metadata={
            "iteration_phase": "deploy",
            "pipeline_required": True,
            "pipeline_status": "failed",
            "last_worker_report_type": "completed",
            "last_worker_report_attempt_id": "attempt-1",
            "pipeline_last_summary": (
                "Drone build s1366560/my-evo#63 finished with status failure; "
                "failing stage workspace-ci/deploy exited 125; "
                "+ docker run -d --name my-evo-postgres --network workspace-deploy "
                "postgres:16-alpine; docker: Error response from daemon: Conflict. "
                'The container name "/my-evo-postgres" is already in use. '
                "You have to remove (or rename) that container to be able to reuse that name."
            ),
        }
    )

    report = await verifier.verify(
        VerificationContext(
            workspace_id="ws-1",
            node=node,
            attempt_id="attempt-1",
            stdout="worker completed",
        )
    )

    judge_result = next(
        result
        for result in report.results
        if result.criterion.spec.get("name") == "workspace_verification_judge"
    )
    feedback = judge_result.criterion.spec["feedback_items"][0]
    assert not report.passed
    assert judge_result.criterion.spec["judge_verdict"] == "needs_rework"
    assert judge_result.criterion.spec["next_action_kind"] == "retry_same_node"
    assert "docker rm -f" in judge_result.criterion.spec["required_next_action"]
    assert "<postgres-container>" in judge_result.criterion.spec["required_next_action"]
    assert feedback["target_layer"] == "worker"
    assert feedback["failure_signature"] == "drone-docker-deploy-container-name-conflict"


@pytest.mark.asyncio
async def test_verifier_routes_deploy_network_exists_to_worker() -> None:
    judge = _FakeVerificationJudge(
        WorkspaceVerificationJudgeResult(
            verdict=WorkspaceVerificationJudgeVerdict.RETRY_INFRASTRUCTURE,
            rationale="deploy retry failed",
            failed_criteria=("ci_pipeline",),
            required_next_action="retry infrastructure",
            confidence=0.8,
        )
    )
    verifier = AcceptanceCriterionVerifier(verification_judge=judge)
    node = _node(
        metadata={
            "iteration_phase": "deploy",
            "pipeline_required": True,
            "pipeline_status": "failed",
            "last_worker_report_type": "completed",
            "last_worker_report_attempt_id": "attempt-1",
            "pipeline_last_summary": (
                "Drone build s1366560/my-evo#83 finished with status failure; "
                "failing stage workspace-ci/deploy exited 1; "
                "+ docker network rm workspace-deploy 2>/dev/null || true\n"
                "+ docker network create workspace-deploy\n"
                "Error response from daemon: network with name workspace-deploy already exists"
            ),
        }
    )

    report = await verifier.verify(
        VerificationContext(
            workspace_id="ws-1",
            node=node,
            attempt_id="attempt-1",
            stdout="worker completed",
        )
    )

    judge_result = next(
        result
        for result in report.results
        if result.criterion.spec.get("name") == "workspace_verification_judge"
    )
    feedback = judge_result.criterion.spec["feedback_items"][0]
    assert not report.passed
    assert judge_result.criterion.spec["judge_verdict"] == "needs_rework"
    assert judge_result.criterion.spec["next_action_kind"] == "retry_same_node"
    assert "docker network inspect <network>" in judge_result.criterion.spec["required_next_action"]
    assert "docker network rm <network>" in judge_result.criterion.spec["required_next_action"]
    assert feedback["target_layer"] == "worker"
    assert feedback["failure_signature"] == "drone-docker-deploy-network-already-exists"


@pytest.mark.asyncio
async def test_verifier_routes_postgres_sidecar_env_failure_to_worker() -> None:
    judge = _FakeVerificationJudge(
        WorkspaceVerificationJudgeResult(
            verdict=WorkspaceVerificationJudgeVerdict.RETRY_INFRASTRUCTURE,
            rationale="deploy sidecar failed",
            failed_criteria=("ci_pipeline",),
            required_next_action="retry infrastructure",
            confidence=0.8,
        )
    )
    verifier = AcceptanceCriterionVerifier(verification_judge=judge)
    node = _node(
        metadata={
            "iteration_phase": "deploy",
            "pipeline_required": True,
            "pipeline_status": "failed",
            "last_worker_report_type": "completed",
            "last_worker_report_attempt_id": "attempt-1",
            "pipeline_last_summary": (
                "Drone build s1366560/my-evo#62 finished with status failure; "
                "failing stage workspace-ci/deploy exited 1; "
                "+ docker run -d --name my-evo-postgres --network workspace-deploy "
                "postgres:16-alpine -c POSTGRES_PASSWORD=password; "
                "Error: Database is uninitialized and superuser password is not specified. "
                "You must specify POSTGRES_PASSWORD to a non-empty value."
            ),
        }
    )

    report = await verifier.verify(
        VerificationContext(
            workspace_id="ws-1",
            node=node,
            attempt_id="attempt-1",
            stdout="worker completed",
        )
    )

    judge_result = next(
        result
        for result in report.results
        if result.criterion.spec.get("name") == "workspace_verification_judge"
    )
    feedback = judge_result.criterion.spec["feedback_items"][0]
    assert not report.passed
    assert judge_result.criterion.spec["judge_verdict"] == "needs_rework"
    assert judge_result.criterion.spec["next_action_kind"] == "retry_same_node"
    assert "-e POSTGRES_PASSWORD=postgres" in judge_result.criterion.spec["required_next_action"]
    assert (
        "Do not use `postgres:16-alpine -c POSTGRES_PASSWORD=...`"
        in (judge_result.criterion.spec["required_next_action"])
    )
    assert feedback["target_layer"] == "worker"
    assert feedback["failure_signature"] == "drone-docker-deploy-postgres-sidecar-env"


@pytest.mark.asyncio
async def test_verifier_routes_missing_build_artifact_to_worker() -> None:
    judge = _FakeVerificationJudge(
        WorkspaceVerificationJudgeResult(
            verdict=WorkspaceVerificationJudgeVerdict.RETRY_INFRASTRUCTURE,
            rationale="deploy container exited",
            failed_criteria=("ci_pipeline",),
            required_next_action="retry infrastructure",
            confidence=0.8,
        )
    )
    verifier = AcceptanceCriterionVerifier(verification_judge=judge)
    node = _node(
        metadata={
            "iteration_phase": "deploy",
            "pipeline_required": True,
            "pipeline_status": "failed",
            "last_worker_report_type": "completed",
            "last_worker_report_attempt_id": "attempt-1",
            "pipeline_last_summary": (
                "Drone build s1366560/my-evo#68 finished with status failure; "
                "failing stage workspace-ci/deploy exited 1; "
                "docker logs my-evo; Error: Cannot find module '/app/dist/index.js'; "
                "code: 'MODULE_NOT_FOUND'"
            ),
        }
    )

    report = await verifier.verify(
        VerificationContext(
            workspace_id="ws-1",
            node=node,
            attempt_id="attempt-1",
            stdout="worker completed",
        )
    )

    judge_result = next(
        result
        for result in report.results
        if result.criterion.spec.get("name") == "workspace_verification_judge"
    )
    feedback = judge_result.criterion.spec["feedback_items"][0]
    assert not report.passed
    assert judge_result.criterion.spec["judge_verdict"] == "needs_rework"
    assert judge_result.criterion.spec["next_action_kind"] == "retry_same_node"
    assert "npm install && npm run build" in judge_result.criterion.spec["required_next_action"]
    assert (
        "Preserve the existing deploy fixes" in judge_result.criterion.spec["required_next_action"]
    )
    assert judge.requests == []
    assert feedback["target_layer"] == "worker"
    assert feedback["failure_signature"] == "drone-docker-deploy-missing-build-artifact"


@pytest.mark.asyncio
async def test_verifier_routes_deploy_runtime_env_failure_to_worker() -> None:
    judge = _FakeVerificationJudge(
        WorkspaceVerificationJudgeResult(
            verdict=WorkspaceVerificationJudgeVerdict.RETRY_INFRASTRUCTURE,
            rationale="deploy container exited",
            failed_criteria=("ci_pipeline",),
            required_next_action="retry infrastructure",
            confidence=0.8,
        )
    )
    verifier = AcceptanceCriterionVerifier(verification_judge=judge)
    node = _node(
        metadata={
            "iteration_phase": "deploy",
            "pipeline_required": True,
            "pipeline_status": "failed",
            "last_worker_report_type": "completed",
            "last_worker_report_attempt_id": "attempt-1",
            "pipeline_last_summary": (
                "Drone build s1366560/my-evo#59 finished with status failure; "
                "failing stage workspace-ci/deploy exited 1; "
                "docker logs my-evo; Error: Prisma schema validation - (get-config wasm); "
                "Error code: P1012; Environment variable not found: DATABASE_URL."
            ),
        }
    )

    report = await verifier.verify(
        VerificationContext(
            workspace_id="ws-1",
            node=node,
            attempt_id="attempt-1",
            stdout="worker completed",
        )
    )

    judge_result = next(
        result
        for result in report.results
        if result.criterion.spec.get("name") == "workspace_verification_judge"
    )
    feedback = judge_result.criterion.spec["feedback_items"][0]
    assert not report.passed
    assert judge_result.criterion.spec["judge_verdict"] == "needs_rework"
    assert judge_result.criterion.spec["next_action_kind"] == "retry_same_node"
    assert "DATABASE_URL" in judge_result.criterion.spec["required_next_action"]
    assert feedback["target_layer"] == "worker"
    assert feedback["failure_signature"] == "drone-docker-deploy-missing-runtime-env"


@pytest.mark.asyncio
async def test_verifier_preserves_exact_missing_runtime_config_field() -> None:
    judge = _FakeVerificationJudge(
        WorkspaceVerificationJudgeResult(
            verdict=WorkspaceVerificationJudgeVerdict.RETRY_INFRASTRUCTURE,
            rationale="deploy container exited",
            failed_criteria=("ci_pipeline",),
            required_next_action="retry infrastructure",
            confidence=0.8,
        )
    )
    verifier = AcceptanceCriterionVerifier(verification_judge=judge)
    node = _node(
        metadata={
            "iteration_phase": "deploy",
            "pipeline_required": True,
            "pipeline_status": "failed",
            "last_worker_report_type": "completed",
            "last_worker_report_attempt_id": "attempt-1",
            "pipeline_last_summary": (
                "Drone build s1366560/my-evo#79 finished with status failure; "
                "failing stage workspace-ci/deploy exited 1; "
                "+ docker run -d --name my-evo -p 18080:3001 "
                "-e ENABLE_TRACING=false my-evo:drone-docker-e2e; "
                "wget: can't connect to remote host (192.168.65.254): Connection refused; "
                "Failed to deserialize constructor options. "
                'Error { status: InvalidArg, reason: "missing field `enableTracing`" }'
            ),
        }
    )

    report = await verifier.verify(
        VerificationContext(
            workspace_id="ws-1",
            node=node,
            attempt_id="attempt-1",
            stdout="worker completed",
        )
    )

    judge_result = next(
        result
        for result in report.results
        if result.criterion.spec.get("name") == "workspace_verification_judge"
    )
    feedback = judge_result.criterion.spec["feedback_items"][0]
    required_action = judge_result.criterion.spec["required_next_action"]
    feedback_summary = feedback["summary"]
    assert not report.passed
    assert judge_result.criterion.spec["judge_verdict"] == "needs_rework"
    assert judge_result.criterion.spec["next_action_kind"] == "retry_same_node"
    assert feedback["failure_signature"] == "drone-docker-deploy-missing-runtime-env"
    assert "`enableTracing`" in required_action
    assert "`-e enableTracing=false`" in required_action
    assert "uppercase underscore variable" in required_action
    assert "`enableTracing`" in feedback_summary


@pytest.mark.asyncio
async def test_verifier_routes_host_socket_dind_timeout_to_worker() -> None:
    judge = _FakeVerificationJudge(
        WorkspaceVerificationJudgeResult(
            verdict=WorkspaceVerificationJudgeVerdict.RETRY_INFRASTRUCTURE,
            rationale="pipeline timeout",
            failed_criteria=("ci_pipeline",),
            required_next_action="retry infrastructure",
            confidence=0.8,
        )
    )
    verifier = AcceptanceCriterionVerifier(verification_judge=judge)
    node = _node(
        metadata={
            "iteration_phase": "deploy",
            "pipeline_required": True,
            "pipeline_status": "failed",
            "last_worker_report_type": "completed",
            "last_worker_report_attempt_id": "attempt-1",
            "pipeline_last_summary": (
                "Drone build s1366560/my-evo#36 timed out; "
                "failing stage workspace-ci/docker exited 0"
            ),
        }
    )

    report = await verifier.verify(
        VerificationContext(
            workspace_id="ws-1",
            node=node,
            attempt_id="attempt-1",
            stdout="worker completed",
        )
    )

    judge_result = next(
        result
        for result in report.results
        if result.criterion.spec.get("name") == "workspace_verification_judge"
    )
    feedback = judge_result.criterion.spec["feedback_items"][0]
    assert not report.passed
    assert judge_result.criterion.spec["judge_verdict"] == "needs_rework"
    assert judge_result.criterion.spec["next_action_kind"] == "retry_same_node"
    assert (
        "removing the `docker:dind` service" in judge_result.criterion.spec["required_next_action"]
    )
    assert feedback["target_layer"] == "worker"
    assert feedback["failure_signature"] == "drone-host-socket-dind-service-timeout"


@pytest.mark.asyncio
async def test_verifier_routes_drone_docker_build_timeout_to_worker() -> None:
    judge = _FakeVerificationJudge(
        WorkspaceVerificationJudgeResult(
            verdict=WorkspaceVerificationJudgeVerdict.RETRY_INFRASTRUCTURE,
            rationale="docker build timed out",
            failed_criteria=("ci_pipeline",),
            required_next_action="retry infrastructure",
            confidence=0.8,
        )
    )
    verifier = AcceptanceCriterionVerifier(verification_judge=judge)
    node = _node(
        metadata={
            "iteration_phase": "deploy",
            "pipeline_required": True,
            "pipeline_status": "failed",
            "last_worker_report_type": "completed",
            "last_worker_report_attempt_id": "attempt-1",
            "pipeline_last_summary": (
                "Drone build s1366560/my-evo#38 finished with status killed; "
                "failing stage workspace-ci/docker-build exited 137; "
                "Sending build context to Docker daemon 1.317GB; "
                "npm warn EBADENGINE required node >=20 current node v18"
            ),
        }
    )

    report = await verifier.verify(
        VerificationContext(
            workspace_id="ws-1",
            node=node,
            attempt_id="attempt-1",
            stdout="worker completed",
        )
    )

    judge_result = next(
        result
        for result in report.results
        if result.criterion.spec.get("name") == "workspace_verification_judge"
    )
    feedback = judge_result.criterion.spec["feedback_items"][0]
    assert not report.passed
    assert judge_result.criterion.spec["judge_verdict"] == "needs_rework"
    assert judge_result.criterion.spec["next_action_kind"] == "retry_same_node"
    assert ".dockerignore" in judge_result.criterion.spec["required_next_action"]
    assert "Node 20+" in judge_result.criterion.spec["required_next_action"]
    assert feedback["target_layer"] == "worker"
    assert feedback["failure_signature"] == "drone-docker-build-timeout-context-or-node"


@pytest.mark.asyncio
async def test_verifier_routes_drone_docker_build_prisma_schema_missing_to_worker() -> None:
    judge = _FakeVerificationJudge(
        WorkspaceVerificationJudgeResult(
            verdict=WorkspaceVerificationJudgeVerdict.RETRY_INFRASTRUCTURE,
            rationale="docker build failed",
            failed_criteria=("ci_pipeline",),
            required_next_action="retry infrastructure",
            confidence=0.8,
        )
    )
    verifier = AcceptanceCriterionVerifier(verification_judge=judge)
    node = _node(
        metadata={
            "iteration_phase": "deploy",
            "pipeline_required": True,
            "pipeline_status": "failed",
            "last_worker_report_type": "completed",
            "last_worker_report_attempt_id": "attempt-1",
            "pipeline_last_summary": (
                "Drone build s1366560/my-evo#139 finished with status failure; "
                "failing stage workspace-ci/docker-build exited 1; "
                "Error: Could not find Prisma Schema that is required for this command. "
                "Checked following paths: schema.prisma: file not found; "
                "prisma/schema.prisma: file not found; "
                "The command '/bin/sh -c npm ci --include=dev --ignore-scripts "
                "&& npx prisma generate' returned a non-zero code: 1"
            ),
        }
    )

    report = await verifier.verify(
        VerificationContext(
            workspace_id="ws-1",
            node=node,
            attempt_id="attempt-1",
            stdout="worker completed",
        )
    )

    judge_result = next(
        result
        for result in report.results
        if result.criterion.spec.get("name") == "workspace_verification_judge"
    )
    feedback = judge_result.criterion.spec["feedback_items"][0]
    assert not report.passed
    assert judge_result.criterion.spec["judge_verdict"] == "needs_rework"
    assert judge_result.criterion.spec["next_action_kind"] == "retry_same_node"
    assert "COPY" in judge_result.criterion.spec["required_next_action"]
    assert "--schema" in judge_result.criterion.spec["required_next_action"]
    assert feedback["target_layer"] == "worker"
    assert feedback["failure_signature"] == "drone-docker-build-prisma-schema-missing"


@pytest.mark.asyncio
async def test_verifier_routes_external_registry_tls_timeout_to_pipeline_retry() -> None:
    judge = _FakeVerificationJudge(
        WorkspaceVerificationJudgeResult(
            verdict=WorkspaceVerificationJudgeVerdict.NEEDS_REWORK,
            rationale="network timeout",
            failed_criteria=("ci_pipeline",),
            required_next_action="change dockerfile",
            confidence=0.5,
        )
    )
    verifier = AcceptanceCriterionVerifier(verification_judge=judge)
    node = _node(
        metadata={
            "iteration_phase": "deploy",
            "pipeline_required": True,
            "pipeline_status": "failed",
            "pipeline_gate_status": "failed",
            "source_publish_commit_ref": "b8446a4",
            "last_worker_report_type": "completed",
            "last_worker_report_attempt_id": "attempt-1",
            "pipeline_last_summary": (
                "Drone build s1366560/my-evo#75 finished with status failure; "
                "failing stage workspace-ci/docker-build exited 1; "
                'Get "https://registry-1.docker.io/v2/library/node/manifests/...": '
                "net/http: TLS handshake timeout"
            ),
        }
    )

    report = await verifier.verify(
        VerificationContext(
            workspace_id="ws-1",
            node=node,
            attempt_id="attempt-1",
            stdout="worker completed",
            artifacts={
                "candidate_artifacts": ["commit_ref:b8446a4"],
                "candidate_verifications": ["worker_report:completed"],
            },
        )
    )

    judge_result = next(
        result
        for result in report.results
        if result.criterion.spec.get("name") == "retryable_infrastructure_failure"
    )
    feedback = judge_result.criterion.spec["feedback_items"][0]
    assert not report.passed
    assert judge_result.criterion.spec["judge_verdict"] == "retry_infrastructure"
    assert judge_result.criterion.spec["next_action_kind"] == "retry_same_node"
    assert feedback["target_layer"] == "runtime"
    assert feedback["recommended_action"] == "retry_infra"
    assert feedback["failure_signature"] == "drone-external-registry-transient-timeout"
    assert _should_request_pipeline_from_report(node, report)


def test_pipeline_result_summary_includes_failed_stage_stderr() -> None:
    summary = _pipeline_result_summary(
        PipelineRunResult(
            status="failed",
            reason="Drone build s1366560/my-evo#26 finished with status failure",
            stage_results=(
                PipelineStageResult(
                    stage="workspace-ci/deploy",
                    status="failed",
                    command="docker pull host.docker.internal:5001/my-evo:latest",
                    exit_code=1,
                    stderr_preview=(
                        'Error response from daemon: Get "https://host.docker.internal:5001/v2/": '
                        "http: server gave HTTP response to HTTPS client"
                    ),
                ),
            ),
            evidence_refs=("ci_pipeline:failed",),
        )
    )

    assert "workspace-ci/deploy" in summary
    assert "HTTPS client" in summary


def test_pipeline_result_summary_includes_failed_stage_error_metadata() -> None:
    summary = _pipeline_result_summary(
        PipelineRunResult(
            status="failed",
            reason="Drone build s1366560/my-evo#30 finished with status error",
            stage_results=(
                PipelineStageResult(
                    stage="workspace-ci/docker-deploy",
                    status="failed",
                    command="drone:workspace-ci/docker-deploy",
                    exit_code=255,
                    stdout_preview="Status: Downloaded newer image for docker:20-cli",
                    metadata={
                        "drone_error": (
                            "error mounting docker.proxy.sock to rootfs at /var/run: "
                            "not a directory"
                        )
                    },
                ),
            ),
            evidence_refs=("ci_pipeline:failed",),
        )
    )

    assert "workspace-ci/docker-deploy" in summary
    assert "not a directory" in summary
    assert "Downloaded newer image" in summary


def test_pipeline_result_summary_preserves_failed_stage_tail() -> None:
    long_preview = "\\n".join(f"# cached build line {index}" for index in range(400))
    summary = _pipeline_result_summary(
        PipelineRunResult(
            status="failed",
            reason="Drone build s1366560/my-evo#62 finished with status failure",
            stage_results=(
                PipelineStageResult(
                    stage="workspace-ci/deploy",
                    status="failed",
                    command="drone:workspace-ci/deploy",
                    exit_code=1,
                    stderr_preview=(
                        f"{long_preview}\\n"
                        "Error: Database is uninitialized and superuser password is not "
                        "specified. You must specify POSTGRES_PASSWORD to a non-empty value."
                    ),
                ),
            ),
            evidence_refs=("ci_pipeline:failed",),
        )
    )

    assert "# cached build line 0" in summary
    assert "POSTGRES_PASSWORD" in summary


@pytest.mark.asyncio
async def test_verifier_accepts_current_success_pipeline_status_over_historical_failure() -> None:
    verifier = AcceptanceCriterionVerifier()
    node = _node(
        metadata={
            "iteration_phase": "implement",
            "pipeline_required": True,
            "pipeline_status": "success",
            "pipeline_gate_status": "success",
            "pipeline_evidence_refs": [
                "ci_pipeline:failed",
                "pipeline_run:failed:old-run",
                "ci_pipeline:passed",
                "pipeline_run:success:new-run",
            ],
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


def test_pipeline_contract_accepts_planner_memstack_sandbox_provider_alias() -> None:
    contract = build_pipeline_contract_from_metadata(
        workspace_metadata={
            "delivery_cicd": {
                "provider": "memstack-sandbox",
                "contract_source": "planner_agent_code_analysis",
                "services": [
                    {
                        "service_id": "frontend",
                        "name": "Frontend",
                        "start_command": "npm run dev -- --port 3002",
                        "internal_port": 3002,
                        "health_path": "/api/health",
                    }
                ],
            }
        },
        fallback_code_root="/workspace/app",
    )

    assert contract.provider == "sandbox_native"
    assert [service.service_id for service in contract.services] == ["frontend"]


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


def test_service_deploy_stage_reuses_already_healthy_preview_service() -> None:
    contract = build_pipeline_contract_from_metadata(
        workspace_metadata={
            "delivery_cicd": {
                "services": [
                    {
                        "service_id": "frontend",
                        "name": "Frontend",
                        "start_command": "pnpm dev --host 0.0.0.0 --port 3000",
                        "internal_port": 3000,
                        "health_path": "/api/health",
                    }
                ]
            }
        },
        fallback_code_root="/workspace/app",
    )

    deploy_stage = next(stage for stage in contract.stages if stage.stage == "deploy")

    assert "curl -fsS http://127.0.0.1:3000/api/health" in deploy_stage.command
    assert deploy_stage.command.find("curl -fsS") < deploy_stage.command.find("nohup")
    assert "service already healthy" in deploy_stage.command


def test_agent_managed_auto_deploy_requires_planner_delivery_contract() -> None:
    contract = build_pipeline_contract_from_metadata(
        workspace_metadata={
            "delivery_cicd": {
                "agent_managed": True,
                "auto_deploy": True,
                "contract_source": "planner_agent_code_analysis",
            }
        },
        fallback_code_root="/workspace/app",
    )

    assert _requires_preview_deployment(contract)
    assert _needs_agent_managed_pipeline_proposal(contract)


def test_agent_managed_auto_deploy_rejects_stale_delivery_contract_source() -> None:
    contract = build_pipeline_contract_from_metadata(
        workspace_metadata={
            "delivery_cicd": {
                "agent_managed": True,
                "auto_deploy": True,
                "contract_source": "agent_regeneration_requested",
                "services": [
                    {
                        "service_id": "default",
                        "name": "Legacy Preview",
                        "start_command": "npm --prefix backend start",
                        "internal_port": 3001,
                        "health_path": "/",
                    }
                ],
            }
        },
        fallback_code_root="/workspace/app",
    )

    assert [service.service_id for service in contract.services] == ["default"]
    assert _needs_agent_managed_pipeline_proposal(contract)


def test_workspace_proxy_service_id_is_stable_and_workspace_scoped() -> None:
    service_a = _workspace_proxy_service_id(
        workspace_id="cb8139b9-3744-462e-8415-5ef684781fec",
        service_id="default",
    )
    service_b = _workspace_proxy_service_id(
        workspace_id="f400e7f1-e784-43df-ae29-ac28b8f1c8e3",
        service_id="default",
    )

    assert service_a == _workspace_proxy_service_id(
        workspace_id="cb8139b9-3744-462e-8415-5ef684781fec",
        service_id="default",
    )
    assert service_a.startswith("ws-cb8139b9-default-")
    assert service_b.startswith("ws-f400e7f1-default-")
    assert service_a != service_b
    assert len(service_a) <= 63


def test_workspace_scoped_pipeline_contract_rewrites_services_and_stage_ids() -> None:
    contract = PipelineContractSpec(
        stages=(
            PipelineStageSpec(stage="deploy", command="npm start", service_id="default"),
            PipelineStageSpec(stage="health", command="curl /", service_id="default"),
        ),
        services=(
            PipelineServiceSpec(
                service_id="default",
                name="Preview",
                start_command="npm start",
                internal_port=3000,
            ),
        ),
    )

    scoped = _workspace_scoped_pipeline_contract(
        contract,
        workspace_id="cb8139b9-3744-462e-8415-5ef684781fec",
    )

    scoped_service_id = scoped.services[0].service_id
    assert scoped_service_id.startswith("ws-cb8139b9-default-")
    assert [stage.service_id for stage in scoped.stages] == [
        scoped_service_id,
        scoped_service_id,
    ]


def test_node_health_idempotency_requires_scoped_service_evidence() -> None:
    contract = PipelineContractSpec(
        services=(
            PipelineServiceSpec(
                service_id="ws-cb8139b9-default-12345678",
                name="Preview",
                start_command="npm start",
                internal_port=3000,
            ),
        )
    )
    node = _node(
        metadata={
            "pipeline_evidence_refs": [
                "deployment_health:passed",
                "deployment_health:passed:default",
            ]
        }
    )

    assert not _node_has_required_deployment_health(node, contract=contract)

    node = replace(
        node,
        metadata={
            "pipeline_evidence_refs": [
                "deployment_health:passed:ws-cb8139b9-default-12345678",
            ]
        },
    )

    assert _node_has_required_deployment_health(node, contract=contract)


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
