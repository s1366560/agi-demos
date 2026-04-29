from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.application.services.workspace_agent_autonomy import (
    build_execution_task_harness_metadata,
    build_harness_feature_item,
    build_workspace_harness_contract,
    ensure_goal_completion_allowed_for_workspace,
    reconcile_root_goal_progress,
    synthesize_goal_evidence_from_children,
    upsert_workspace_harness_feature_ledger,
    validate_autonomy_metadata,
)
from src.application.services.workspace_autonomy_profiles import (
    evaluate_workspace_code_context,
    resolve_autonomy_profile,
)
from src.domain.model.workspace.workspace_task import WorkspaceTask, WorkspaceTaskStatus


@pytest.mark.unit
def test_workspace_harness_contract_defaults_to_preflight_and_feature_ledger() -> None:
    feature = build_harness_feature_item(
        feature_id="feature-001",
        sequence=1,
        title="Implement harness",
        acceptance_refs=["criterion:worker-report"],
    )
    contract = build_workspace_harness_contract(
        goal_title="Ship long-running harness",
        goal_task_id="root-1",
        feature_items=[feature],
        core_regression_commands=["uv run pytest src/tests/unit/example.py -q"],
    )

    metadata = validate_autonomy_metadata(
        {
            "autonomy_schema_version": 1,
            "task_role": "goal_root",
            "goal_origin": "human_defined",
            "goal_source_refs": ["api:test"],
            "root_goal_policy": {
                "mutable_by_agent": True,
                "completion_requires_external_proof": True,
            },
            "workspace_harness": contract,
        }
    )

    harness = metadata["workspace_harness"]
    assert harness["mode"] == "long_running_agent"
    assert harness["goal_task_id"] == "root-1"
    assert harness["feature_ledger"][0]["feature_id"] == "feature-001"
    assert harness["feature_ledger"][0]["locked"] is True
    assert [check["check_id"] for check in harness["required_preflight_checks"]] == [
        "read-progress",
        "git-status",
        "test-command-1",
    ]


@pytest.mark.unit
def test_execution_task_harness_metadata_validates_preflight_and_checkpoint() -> None:
    harness_metadata = build_execution_task_harness_metadata(
        feature_id="feature-001",
        sequence=1,
        title="Implement harness",
        test_commands=["uv run pytest src/tests/unit/example.py -q"],
        expected_artifacts=["src/example.py"],
    )

    metadata = validate_autonomy_metadata(
        {
            "autonomy_schema_version": 1,
            "task_role": "execution_task",
            "root_goal_task_id": "root-1",
            "lineage_source": "agent",
            **harness_metadata,
        }
    )

    assert metadata["harness_feature_id"] == "feature-001"
    assert metadata["feature_checkpoint"]["feature_id"] == "feature-001"
    assert metadata["feature_checkpoint"]["expected_artifacts"] == ["src/example.py"]
    assert [check["check_id"] for check in metadata["preflight_checks"]] == [
        "read-progress",
        "git-status",
        "test-command-1",
    ]
    assert metadata["verification_commands"] == ["uv run pytest src/tests/unit/example.py -q"]


@pytest.mark.unit
def test_upsert_workspace_harness_feature_ledger_preserves_existing_features() -> None:
    root_metadata = {
        "autonomy_schema_version": 1,
        "task_role": "goal_root",
        "goal_origin": "human_defined",
        "goal_source_refs": ["api:test"],
        "root_goal_policy": {
            "mutable_by_agent": True,
            "completion_requires_external_proof": True,
        },
        "workspace_harness": build_workspace_harness_contract(
            goal_title="Ship harness",
            goal_task_id="root-1",
            feature_items=[
                build_harness_feature_item(
                    feature_id="feature-001",
                    sequence=1,
                    title="Existing feature",
                )
            ],
        ),
    }

    updated = upsert_workspace_harness_feature_ledger(
        root_metadata,
        goal_title="Ship harness",
        goal_task_id="root-1",
        feature_items=[
            build_harness_feature_item(
                feature_id="feature-002",
                sequence=2,
                title="New feature",
            )
        ],
    )

    assert [item["feature_id"] for item in updated["workspace_harness"]["feature_ledger"]] == [
        "feature-001",
        "feature-002",
    ]


@pytest.mark.unit
def test_execution_task_metadata_accepts_delegation_binding_fields() -> None:
    metadata = validate_autonomy_metadata(
        {
            "autonomy_schema_version": 1,
            "task_role": "execution_task",
            "root_goal_task_id": "root-1",
            "lineage_source": "agent",
            "delegated_subagent_name": "worker-subagent",
            "delegated_subagent_id": "sa-1",
            "delegated_task_text": "Implement the bounded task",
        }
    )

    assert metadata["delegated_subagent_name"] == "worker-subagent"
    assert metadata["delegated_subagent_id"] == "sa-1"
    assert metadata["delegated_task_text"] == "Implement the bounded task"


@pytest.mark.unit
def test_root_metadata_accepts_workspace_type_and_profile_override() -> None:
    metadata = validate_autonomy_metadata(
        {
            "autonomy_schema_version": 1,
            "task_role": "goal_root",
            "goal_origin": "human_defined",
            "workspace_type": "software_development",
            "goal_source_refs": ["api:test"],
            "root_goal_policy": {
                "mutable_by_agent": True,
                "completion_requires_external_proof": True,
            },
            "autonomy_profile": {
                "completion_policy": {
                    "required_artifact_prefixes": ["diff_bundle:"],
                }
            },
        }
    )

    profile = resolve_autonomy_profile(metadata)

    assert metadata["workspace_type"] == "software_development"
    assert profile.workspace_type == "software_development"
    assert profile.evidence.required_artifact_prefixes == ("diff_bundle:",)


def _root_task(metadata: dict) -> WorkspaceTask:
    return WorkspaceTask(
        id="root-1",
        workspace_id="ws-1",
        title="Ship code change",
        created_by="user-1",
        status=WorkspaceTaskStatus.IN_PROGRESS,
        metadata=metadata,
    )


def _child_task(
    *,
    task_id: str = "child-1",
    metadata: dict | None = None,
) -> WorkspaceTask:
    now = datetime(2026, 4, 24, 10, 0, tzinfo=UTC)
    return WorkspaceTask(
        id=task_id,
        workspace_id="ws-1",
        title="Implement code",
        created_by="user-1",
        status=WorkspaceTaskStatus.DONE,
        metadata=metadata or {},
        created_at=now,
        updated_at=now,
        completed_at=now,
    )


@pytest.mark.unit
def test_software_development_profile_does_not_turn_task_ids_into_external_evidence() -> None:
    root = _root_task(
        {
            "autonomy_schema_version": 1,
            "task_role": "goal_root",
            "goal_origin": "human_defined",
            "workspace_type": "software_development",
            "goal_source_refs": [],
            "root_goal_policy": {
                "mutable_by_agent": True,
                "completion_requires_external_proof": True,
            },
        }
    )

    evidence = synthesize_goal_evidence_from_children(
        root_task=root,
        child_tasks=[_child_task()],
        generated_by_agent_id="agent-1",
    )

    assert evidence is not None
    assert evidence["artifacts"] == []
    assert evidence["verification_grade"] == "fail"


@pytest.mark.unit
def test_software_development_profile_accepts_code_and_test_artifacts() -> None:
    root = _root_task(
        {
            "autonomy_schema_version": 1,
            "task_role": "goal_root",
            "goal_origin": "human_defined",
            "workspace_type": "software_development",
            "sandbox_code_root": "/workspace/my-evo",
            "goal_source_refs": [],
            "root_goal_policy": {
                "mutable_by_agent": True,
                "completion_requires_external_proof": True,
            },
        }
    )
    child = _child_task(
        metadata={
            "evidence_refs": [
                "git_diff:/workspace/my-evo#abc123",
                "test_run:/workspace/my-evo#jest-search",
            ],
            "execution_verifications": ["command:npm-test", "command:typecheck"],
        }
    )

    evidence = synthesize_goal_evidence_from_children(
        root_task=root,
        child_tasks=[child],
        generated_by_agent_id="agent-1",
    )
    assert evidence is not None
    root.metadata["goal_evidence"] = evidence

    ensure_goal_completion_allowed_for_workspace(root, workspace_metadata={})

    assert evidence["artifacts"] == [
        "git_diff:/workspace/my-evo#abc123",
        "test_run:/workspace/my-evo#jest-search",
    ]
    assert evidence["verification_grade"] == "pass"


@pytest.mark.unit
def test_software_development_profile_rejects_code_artifact_without_test_evidence() -> None:
    root = _root_task(
        {
            "autonomy_schema_version": 1,
            "task_role": "goal_root",
            "goal_origin": "human_defined",
            "workspace_type": "software_development",
            "sandbox_code_root": "/workspace/my-evo",
            "goal_source_refs": [],
            "root_goal_policy": {
                "mutable_by_agent": True,
                "completion_requires_external_proof": True,
            },
        }
    )
    child = _child_task(
        metadata={
            "evidence_refs": ["git_diff:/workspace/my-evo#abc123"],
            "execution_verifications": ["command:typecheck"],
        }
    )

    evidence = synthesize_goal_evidence_from_children(
        root_task=root,
        child_tasks=[child],
        generated_by_agent_id="agent-1",
    )
    assert evidence is not None
    root.metadata["goal_evidence"] = evidence

    assert evidence["verification_grade"] == "fail"
    with pytest.raises(ValueError, match="verification_grade"):
        ensure_goal_completion_allowed_for_workspace(root, workspace_metadata={})


@pytest.mark.unit
def test_child_blocked_worker_report_forces_goal_evidence_failure() -> None:
    root = _root_task(
        {
            "autonomy_schema_version": 1,
            "task_role": "goal_root",
            "goal_origin": "human_defined",
            "workspace_type": "software_development",
            "sandbox_code_root": "/workspace/my-evo",
            "goal_source_refs": [],
            "root_goal_policy": {
                "mutable_by_agent": True,
                "completion_requires_external_proof": True,
            },
        }
    )
    child = _child_task(
        metadata={
            "evidence_refs": [
                "git_diff:/workspace/my-evo#abc123",
                "test_run:/workspace/my-evo#jest-search",
            ],
            "execution_verifications": ["command:npm test"],
            "last_worker_report_type": "blocked",
            "last_worker_report_summary": "recovered_stale_no_heartbeat",
        }
    )

    evidence = synthesize_goal_evidence_from_children(
        root_task=root,
        child_tasks=[child],
        generated_by_agent_id="agent-1",
    )

    assert evidence is not None
    assert evidence["verification_grade"] == "fail"
    assert "child_report_not_completed:child-1:blocked" in evidence["verifications"]


@pytest.mark.unit
def test_completed_worker_report_verification_ignores_stale_blocked_metadata() -> None:
    root = _root_task(
        {
            "autonomy_schema_version": 1,
            "task_role": "goal_root",
            "goal_origin": "human_defined",
            "workspace_type": "software_development",
            "sandbox_code_root": "/workspace/my-evo",
            "goal_source_refs": [],
            "root_goal_policy": {
                "mutable_by_agent": True,
                "completion_requires_external_proof": True,
            },
        }
    )
    child = _child_task(
        metadata={
            "evidence_refs": [
                "git_diff:/workspace/my-evo#abc123",
                "test_run:/workspace/my-evo#jest-search",
            ],
            "execution_verifications": ["command:npm test", "worker_report:completed"],
            "last_worker_report_type": "blocked",
            "last_worker_report_summary": "stale_no_heartbeat",
            "last_attempt_status": "blocked",
            "last_leader_adjudication_status": "blocked",
        }
    )

    evidence = synthesize_goal_evidence_from_children(
        root_task=root,
        child_tasks=[child],
        generated_by_agent_id="agent-1",
    )

    assert evidence is not None
    assert evidence["verification_grade"] == "pass"
    assert "child_report_not_completed:child-1:blocked" not in evidence["verifications"]
    assert "child_attempt_not_accepted:child-1:blocked" not in evidence["verifications"]


@pytest.mark.unit
def test_accepted_durable_plan_child_ignores_stale_blocked_report_metadata() -> None:
    root = _root_task(
        {
            "autonomy_schema_version": 1,
            "task_role": "goal_root",
            "goal_origin": "human_defined",
            "goal_source_refs": ["api:test"],
            "root_goal_policy": {
                "mutable_by_agent": True,
                "completion_requires_external_proof": True,
            },
        }
    )
    child = _child_task(
        metadata={
            "evidence_refs": ["artifact:file-1"],
            "execution_verifications": ["browser_assert:done"],
            "durable_plan_verdict": "accepted",
            "last_attempt_status": "awaiting_plan_verification",
            "last_worker_report_type": "blocked",
            "last_worker_report_summary": "old sandbox failure",
        }
    )

    evidence = synthesize_goal_evidence_from_children(
        root_task=root,
        child_tasks=[child],
        generated_by_agent_id="agent-1",
    )

    assert evidence is not None
    assert evidence["verification_grade"] == "pass"
    assert "child_report_not_completed:child-1:blocked" not in evidence["verifications"]


@pytest.mark.unit
def test_workspace_software_profile_synthesis_roots_relative_artifacts() -> None:
    root = _root_task(
        {
            "autonomy_schema_version": 1,
            "task_role": "goal_root",
            "goal_origin": "human_defined",
            "goal_source_refs": ["api:test"],
            "root_goal_policy": {
                "mutable_by_agent": True,
                "completion_requires_external_proof": True,
            },
        }
    )
    child = _child_task(
        metadata={
            "evidence_refs": ["src/app/page.tsx", "frontend/tests/e2e-smoke.spec.ts"],
            "execution_verifications": ["worker_report:completed"],
            "last_worker_report_summary": "UI tests: 3/3 smoke tests passed",
            "durable_plan_verdict": "accepted",
        }
    )

    evidence = synthesize_goal_evidence_from_children(
        root_task=root,
        child_tasks=[child],
        generated_by_agent_id="agent-1",
        workspace_metadata={
            "workspace_type": "software_development",
            "sandbox_code_root": "/workspace/my-evo",
        },
    )
    assert evidence is not None
    root.metadata["goal_evidence"] = evidence

    ensure_goal_completion_allowed_for_workspace(
        root,
        workspace_metadata={
            "workspace_type": "software_development",
            "sandbox_code_root": "/workspace/my-evo",
        },
    )

    assert "file_snapshot:/workspace/my-evo/src/app/page.tsx" in evidence["artifacts"]
    assert "test_run:/workspace/my-evo#worker-summary:child-1" in evidence["verifications"]
    assert evidence["verification_grade"] == "pass"


@pytest.mark.unit
def test_software_root_can_pass_with_mixed_analysis_and_code_children() -> None:
    root = _root_task(
        {
            "autonomy_schema_version": 1,
            "task_role": "goal_root",
            "goal_origin": "human_defined",
            "goal_source_refs": ["api:test"],
            "root_goal_policy": {
                "mutable_by_agent": True,
                "completion_requires_external_proof": True,
            },
        }
    )
    analysis_child = _child_task(
        task_id="analysis-child",
        metadata={
            "execution_verifications": ["worker_report:completed"],
            "durable_plan_verdict": "accepted",
        },
    )
    code_child = _child_task(
        task_id="code-child",
        metadata={
            "evidence_refs": ["src/service.ts", "src/service.test.ts"],
            "execution_verifications": ["worker_report:completed"],
            "last_worker_report_summary": "Type Check: PASSED\nBuild: SUCCESS",
            "durable_plan_verdict": "accepted",
        },
    )

    evidence = synthesize_goal_evidence_from_children(
        root_task=root,
        child_tasks=[analysis_child, code_child],
        generated_by_agent_id="agent-1",
        workspace_metadata={
            "workspace_type": "software_development",
            "sandbox_code_root": "/workspace/my-evo",
        },
    )

    assert evidence is not None
    assert evidence["verification_grade"] == "pass"
    assert "workspace_task_completed:analysis-child" in evidence["verifications"]
    assert "file_snapshot:/workspace/my-evo/src/service.ts" in evidence["artifacts"]


@pytest.mark.unit
async def test_reconcile_done_root_clears_ready_for_completion_summary() -> None:
    root = _root_task(
        {
            "autonomy_schema_version": 1,
            "task_role": "goal_root",
            "goal_origin": "human_defined",
            "goal_source_refs": ["api:test"],
            "root_goal_policy": {
                "mutable_by_agent": True,
                "completion_requires_external_proof": True,
            },
            "remediation_status": "ready_for_completion",
            "remediation_summary": "root auto-complete failed: stale evidence",
        }
    )
    root.status = WorkspaceTaskStatus.DONE
    child = _child_task(task_id="child-done", metadata={"task_role": "execution_task"})

    class Repo:
        async def find_by_id(self, task_id: str) -> WorkspaceTask | None:
            return root if task_id == root.id else None

        async def find_by_root_goal_task_id(
            self,
            workspace_id: str,
            root_goal_task_id: str,
        ) -> list[WorkspaceTask]:
            assert workspace_id == "ws-1"
            assert root_goal_task_id == "root-1"
            return [child]

        async def save(self, task: WorkspaceTask) -> WorkspaceTask:
            return task

    reconciled = await reconcile_root_goal_progress(
        task_repo=Repo(),
        workspace_id="ws-1",
        root_goal_task_id="root-1",
    )

    assert reconciled is not None
    assert reconciled.metadata["remediation_status"] == "none"
    assert reconciled.metadata["remediation_summary"] is None
    assert reconciled.metadata["goal_health"] == "achieved"


@pytest.mark.unit
def test_workspace_type_metadata_can_drive_completion_policy_when_root_has_no_type() -> None:
    root = _root_task(
        {
            "autonomy_schema_version": 1,
            "task_role": "goal_root",
            "goal_origin": "human_defined",
            "goal_source_refs": [],
            "root_goal_policy": {
                "mutable_by_agent": True,
                "completion_requires_external_proof": True,
            },
            "goal_evidence": {
                "goal_task_id": "root-1",
                "goal_text_snapshot": "Ship code change",
                "outcome_status": "achieved",
                "summary": "child tasks done",
                "artifacts": ["workspace_task:child-1"],
                "verifications": ["workspace_task_completed:child-1"],
                "generated_by_agent_id": "agent-1",
                "recorded_at": "2026-04-24T10:00:00Z",
                "verification_grade": "warn",
            },
        }
    )

    with pytest.raises(ValueError, match="verification_grade"):
        ensure_goal_completion_allowed_for_workspace(
            root,
            workspace_metadata={
                "workspace_type": "software_development",
                "sandbox_code_root": "/workspace/my-evo",
            },
        )


@pytest.mark.unit
def test_workspace_autonomy_profile_type_can_drive_completion_policy() -> None:
    root = _root_task(
        {
            "autonomy_schema_version": 1,
            "task_role": "goal_root",
            "goal_origin": "human_defined",
            "goal_source_refs": [],
            "root_goal_policy": {
                "mutable_by_agent": True,
                "completion_requires_external_proof": True,
            },
            "goal_evidence": {
                "goal_task_id": "root-1",
                "goal_text_snapshot": "Ship code change",
                "outcome_status": "achieved",
                "summary": "child tasks done",
                "artifacts": ["workspace_task:child-1"],
                "verifications": ["workspace_task_completed:child-1"],
                "generated_by_agent_id": "agent-1",
                "recorded_at": "2026-04-24T10:00:00Z",
                "verification_grade": "warn",
            },
        }
    )

    with pytest.raises(ValueError, match="verification_grade"):
        ensure_goal_completion_allowed_for_workspace(
            root,
            workspace_metadata={
                "autonomy_profile": {"workspace_type": "software_development"},
                "sandbox_code_root": "/workspace/my-evo",
            },
        )


@pytest.mark.unit
def test_software_development_requires_isolated_sandbox_code_root() -> None:
    missing = evaluate_workspace_code_context(
        root_metadata={"workspace_type": "software_development"},
        workspace_metadata={},
    )
    assert missing.allowed is False
    assert "sandbox_code_root" in str(missing.reason)

    root_workspace = evaluate_workspace_code_context(
        root_metadata={
            "workspace_type": "software_development",
            "sandbox_code_root": "/workspace",
        },
        workspace_metadata={},
    )
    assert root_workspace.allowed is False
    assert "not /workspace itself" in str(root_workspace.reason)

    ready = evaluate_workspace_code_context(
        root_metadata={},
        workspace_metadata={
            "workspace_type": "software_development",
            "code_context": {"sandbox_code_root": "my-evo"},
        },
    )
    assert ready.allowed is True
    assert ready.sandbox_code_root == "/workspace/my-evo"


@pytest.mark.unit
def test_software_completion_artifacts_must_reference_code_root() -> None:
    root = _root_task(
        {
            "autonomy_schema_version": 1,
            "task_role": "goal_root",
            "goal_origin": "human_defined",
            "workspace_type": "software_development",
            "sandbox_code_root": "/workspace/my-evo",
            "goal_source_refs": [],
            "root_goal_policy": {
                "mutable_by_agent": True,
                "completion_requires_external_proof": True,
            },
            "goal_evidence": {
                "goal_task_id": "root-1",
                "goal_text_snapshot": "Ship code change",
                "outcome_status": "achieved",
                "summary": "child tasks done",
                "artifacts": ["test_run:/workspace#vitest"],
                "verifications": ["command:vitest"],
                "generated_by_agent_id": "agent-1",
                "recorded_at": "2026-04-24T10:00:00Z",
                "verification_grade": "pass",
            },
        }
    )

    with pytest.raises(ValueError, match="sandbox_code_root"):
        ensure_goal_completion_allowed_for_workspace(root, workspace_metadata={})


@pytest.mark.unit
def test_software_completion_artifacts_must_match_exact_code_root_boundary() -> None:
    root = _root_task(
        {
            "autonomy_schema_version": 1,
            "task_role": "goal_root",
            "goal_origin": "human_defined",
            "workspace_type": "software_development",
            "sandbox_code_root": "/workspace/my-evo",
            "goal_source_refs": [],
            "root_goal_policy": {
                "mutable_by_agent": True,
                "completion_requires_external_proof": True,
            },
            "goal_evidence": {
                "goal_task_id": "root-1",
                "goal_text_snapshot": "Ship code change",
                "outcome_status": "achieved",
                "summary": "child tasks done",
                "artifacts": ["git_diff:/workspace/my-evo2#abc123"],
                "verifications": ["command:git-diff"],
                "generated_by_agent_id": "agent-1",
                "recorded_at": "2026-04-24T10:00:00Z",
                "verification_grade": "pass",
            },
        }
    )

    with pytest.raises(ValueError, match="sandbox_code_root"):
        ensure_goal_completion_allowed_for_workspace(root, workspace_metadata={})


@pytest.mark.unit
def test_root_workspace_type_can_override_workspace_default_type() -> None:
    root = _root_task(
        {
            "autonomy_schema_version": 1,
            "task_role": "goal_root",
            "goal_origin": "human_defined",
            "workspace_type": "general",
            "goal_source_refs": [],
            "root_goal_policy": {
                "mutable_by_agent": True,
                "completion_requires_external_proof": True,
            },
            "goal_evidence": {
                "goal_task_id": "root-1",
                "goal_text_snapshot": "Ship code change",
                "outcome_status": "achieved",
                "summary": "child tasks done",
                "artifacts": ["workspace_task:child-1"],
                "verifications": ["workspace_task_completed:child-1"],
                "generated_by_agent_id": "agent-1",
                "recorded_at": "2026-04-24T10:00:00Z",
                "verification_grade": "warn",
            },
        }
    )

    ensure_goal_completion_allowed_for_workspace(
        root,
        workspace_metadata={"workspace_type": "software_development"},
    )


@pytest.mark.unit
def test_general_workspace_preserves_internal_task_evidence_compatibility() -> None:
    root = _root_task(
        {
            "autonomy_schema_version": 1,
            "task_role": "goal_root",
            "goal_origin": "human_defined",
            "goal_source_refs": [],
            "root_goal_policy": {
                "mutable_by_agent": True,
                "completion_requires_external_proof": True,
            },
            "goal_evidence": {
                "goal_task_id": "root-1",
                "goal_text_snapshot": "Ship code change",
                "outcome_status": "achieved",
                "summary": "child tasks done",
                "artifacts": ["workspace_task:child-1"],
                "verifications": ["workspace_task_completed:child-1"],
                "generated_by_agent_id": "agent-1",
                "recorded_at": "2026-04-24T10:00:00Z",
                "verification_grade": "warn",
            },
        }
    )

    ensure_goal_completion_allowed_for_workspace(root, workspace_metadata={})
