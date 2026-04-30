"""Unit tests for workspace plan delivery snapshot projection."""

from __future__ import annotations

from datetime import UTC, datetime

from src.domain.model.workspace_plan import (
    AcceptanceCriterion,
    CriterionKind,
    PlanNode,
    PlanNodeKind,
    TaskIntent,
)
from src.infrastructure.adapters.primary.web.routers.workspace_plans import (
    WorkspaceDeliveryServiceResponse,
    WorkspaceDeploymentResponse,
    WorkspacePipelineRunResponse,
    WorkspacePipelineStageRunResponse,
    _delivery_run_assessment_response,
    _filter_current_delivery_deployments,
    _node_evidence_bundle_response,
    _node_gate_status_response,
    _node_response_metadata,
    _phase_response,
    _to_delivery_services,
)


def _deployment(service_id: str, *, created_at: datetime) -> WorkspaceDeploymentResponse:
    return WorkspaceDeploymentResponse(
        id=f"deployment-{service_id}",
        provider="sandbox_native",
        status="healthy",
        service_id=service_id,
        service_name=service_id,
        preview_url=f"http://{service_id}.project.preview.localhost:8000/",
        created_at=created_at,
    )


def test_delivery_snapshot_filters_superseded_deployments_outside_current_contract() -> None:
    now = datetime.now(UTC)
    contract_metadata = {
        "services": [
            {
                "service_id": "ws-cb8139b9-default-043afc47",
                "name": "my-game2",
                "start_command": "npm run preview -- --host 0.0.0.0 --port 3000",
                "internal_port": 3000,
                "health_path": "/",
            }
        ]
    }
    deployments = [
        _deployment("ws-cb8139b9-default-043afc47", created_at=now),
        _deployment("default", created_at=now),
    ]

    filtered = _filter_current_delivery_deployments(contract_metadata, deployments)
    services = _to_delivery_services(contract_metadata, filtered)

    assert [deployment.service_id for deployment in filtered] == ["ws-cb8139b9-default-043afc47"]
    assert [service.service_id for service in services] == ["ws-cb8139b9-default-043afc47"]
    assert services[0].preview_url == (
        "http://ws-cb8139b9-default-043afc47.project.preview.localhost:8000/"
    )


def test_delivery_snapshot_keeps_legacy_deployments_when_contract_has_no_services() -> None:
    now = datetime.now(UTC)
    deployments = [_deployment("default", created_at=now)]

    assert _filter_current_delivery_deployments({}, deployments) == deployments


def test_phase_contract_projection_marks_done_implement_missing_recovery_boundary() -> None:
    node = PlanNode(
        id="node-implement",
        plan_id="plan-1",
        kind=PlanNodeKind.TASK,
        parent_id="goal-1",
        title="Implement bounded feature",
        intent=TaskIntent.DONE,
        metadata={"iteration_phase": "implement", "write_set": ["web/src/App.tsx"]},
        acceptance_criteria=(
            AcceptanceCriterion(
                kind=CriterionKind.REGEX,
                spec={"pattern": "ok", "source": "stdout"},
                required=True,
            ),
        ),
    )

    metadata = _node_response_metadata(node)
    evidence = _node_evidence_bundle_response(node, metadata)
    gate = _node_gate_status_response(
        node,
        phase_id="implement",
        metadata=metadata,
        evidence_bundle=evidence,
    )
    phase = _phase_response("implement", [node])

    assert evidence.changed_files == ["web/src/App.tsx"]
    assert gate.status == "missing"
    assert gate.missing == ["commit or recovery ref"]
    assert phase.gate_status.status == "missing"
    assert phase.missing_artifacts == ["commit or recovery ref"]


def test_delivery_run_assessment_requires_all_required_services_healthy() -> None:
    now = datetime.now(UTC)
    run = WorkspacePipelineRunResponse(
        id="run-1",
        provider="sandbox_native",
        status="success",
        stages=[
            WorkspacePipelineStageRunResponse(
                id="stage-1",
                run_id="run-1",
                stage="test",
                status="success",
            )
        ],
        created_at=now,
    )
    services = [
        WorkspaceDeliveryServiceResponse(service_id="frontend", name="Frontend", required=True),
        WorkspaceDeliveryServiceResponse(service_id="admin", name="Admin", required=True),
    ]
    deployments = [
        _deployment("frontend", created_at=now),
        WorkspaceDeploymentResponse(
            id="deployment-admin",
            provider="sandbox_native",
            status="unhealthy",
            service_id="admin",
            service_name="Admin",
            created_at=now,
        ),
    ]

    assessment = _delivery_run_assessment_response(
        latest_run=run,
        services=services,
        deployments=deployments,
        warnings=["Admin is required but unhealthy."],
    )

    assert assessment.status == "unhealthy"
    assert assessment.required_services_total == 2
    assert assessment.required_services_healthy == 1
    assert assessment.failed_required_services == ["admin"]
