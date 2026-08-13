"""Compatibility tests for Workspace Plan paths retired into Workspace Core."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import HTTPException, Request
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.primary.web.routers import workspace_plans
from src.infrastructure.adapters.secondary.persistence.models import User


def _request() -> Request:
    return cast(Request, SimpleNamespace())


def _user() -> User:
    return cast(User, SimpleNamespace(id="workspace-plan-user"))


def _db() -> AsyncSession:
    return cast(AsyncSession, SimpleNamespace())


def _assert_core_unavailable(exc: HTTPException) -> None:
    assert exc.status_code == 503
    assert exc.detail["code"] == "WORKSPACE_CORE_UNAVAILABLE"
    assert exc.detail["reason"] == "workspace_core_unavailable"


@pytest.mark.parametrize(
    ("operation", "kwargs"),
    [
        (
            workspace_plans.get_workspace_plan_snapshot,
            {
                "outbox_limit": 20,
                "event_limit": 50,
                "include_details": True,
                "recover_stale_attempts": False,
                "plan_id": None,
            },
        ),
        (
            workspace_plans.recover_workspace_plan_stale_attempts,
            {"body": workspace_plans.WorkspacePlanActionRequest(reason="recover")},
        ),
        (
            workspace_plans.retry_workspace_plan_outbox_item,
            {
                "outbox_id": "retired-outbox",
                "body": workspace_plans.WorkspacePlanActionRequest(reason="retry"),
            },
        ),
        (
            workspace_plans.pause_workspace_plan_iteration_loop,
            {"body": workspace_plans.WorkspacePlanActionRequest(reason="pause")},
        ),
        (
            workspace_plans.resume_workspace_plan_iteration_loop,
            {"body": workspace_plans.WorkspacePlanActionRequest(reason="resume")},
        ),
        (
            workspace_plans.trigger_workspace_plan_next_iteration,
            {"body": workspace_plans.WorkspacePlanActionRequest(reason="next")},
        ),
        (
            workspace_plans.request_workspace_plan_pipeline_run,
            {"body": workspace_plans.WorkspacePlanPipelineRunRequest(reason="pipeline")},
        ),
        (
            workspace_plans.request_workspace_plan_delivery_contract_regeneration,
            {"body": workspace_plans.WorkspacePlanActionRequest(reason="regenerate")},
        ),
        (
            workspace_plans.request_workspace_plan_node_replan,
            {
                "node_id": "retired-node",
                "body": workspace_plans.WorkspacePlanActionRequest(reason="replan"),
            },
        ),
        (
            workspace_plans.reopen_blocked_workspace_plan_node,
            {
                "node_id": "retired-node",
                "body": workspace_plans.WorkspacePlanActionRequest(reason="reopen"),
            },
        ),
        (
            workspace_plans.accept_review_workspace_plan_node,
            {
                "node_id": "retired-node",
                "body": workspace_plans.WorkspacePlanActionRequest(reason="accept"),
            },
        ),
    ],
)
async def test_retired_python_plan_surfaces_fail_closed(
    operation: Callable[..., Awaitable[object]],
    kwargs: dict[str, Any],
) -> None:
    with pytest.raises(HTTPException) as exc_info:
        await operation(
            workspace_id="core-authoritative-workspace",
            request=_request(),
            current_user=_user(),
            db=_db(),
            **kwargs,
        )

    _assert_core_unavailable(exc_info.value)


def test_router_preserves_frozen_plan_compatibility_paths() -> None:
    registered = {
        (method, route.path)
        for route in workspace_plans.router.routes
        for method in route.methods or set()
    }

    assert registered == {
        ("GET", "/api/v1/workspaces/{workspace_id}/plan"),
        ("POST", "/api/v1/workspaces/{workspace_id}/plan/recover-stale-attempts"),
        ("POST", "/api/v1/workspaces/{workspace_id}/plan/outbox/{outbox_id}/retry"),
        ("POST", "/api/v1/workspaces/{workspace_id}/plan/iteration/pause"),
        ("POST", "/api/v1/workspaces/{workspace_id}/plan/iteration/resume"),
        ("POST", "/api/v1/workspaces/{workspace_id}/plan/iteration/trigger-next"),
        ("POST", "/api/v1/workspaces/{workspace_id}/plan/delivery/run-pipeline"),
        ("POST", "/api/v1/workspaces/{workspace_id}/plan/delivery/regenerate-contract"),
        ("POST", "/api/v1/workspaces/{workspace_id}/plan/nodes/{node_id}/request-replan"),
        ("POST", "/api/v1/workspaces/{workspace_id}/plan/nodes/{node_id}/reopen"),
        ("POST", "/api/v1/workspaces/{workspace_id}/plan/nodes/{node_id}/accept-review"),
    }


def test_plan_action_contract_rejects_unbounded_operator_input() -> None:
    with pytest.raises(ValidationError):
        workspace_plans.WorkspacePlanActionRequest(reason="x" * 501)

    with pytest.raises(ValidationError):
        workspace_plans.WorkspacePlanActionRequest(
            evidence_refs=[f"evidence-{index}" for index in range(21)]
        )


def test_plan_snapshot_schema_retains_compatible_empty_defaults() -> None:
    snapshot = workspace_plans.WorkspacePlanSnapshotResponse(
        workspace_id="core-authoritative-workspace"
    )

    assert snapshot.model_dump() == {
        "workspace_id": "core-authoritative-workspace",
        "plan": None,
        "root_goal": None,
        "iteration": None,
        "delivery": None,
        "blackboard": [],
        "outbox": [],
        "events": [],
        "plan_history": [],
        "iteration_runs": [],
        "run_health": None,
        "artifact_index": None,
    }
