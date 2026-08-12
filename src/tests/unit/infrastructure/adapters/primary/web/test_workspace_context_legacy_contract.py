"""Golden contract for the legacy Workspace Context HTTP surface."""

from datetime import UTC, datetime

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from src.application.schemas.workspace_context import (
    WorkspaceContextSnapshotResponse,
    WorkspaceContextSwitchRequest,
)
from src.domain.model.auth.workspace_context import (
    WorkspaceContextError,
    WorkspaceContextErrorCode,
)
from src.infrastructure.adapters.primary.web.routers.workspace_context import (
    _raise_workspace_context_http_error,
)

pytestmark = pytest.mark.unit


def _validation_client() -> TestClient:
    app = FastAPI()

    @app.post("/workspace-context/switch")
    async def validate(body: WorkspaceContextSwitchRequest) -> WorkspaceContextSwitchRequest:
        return body

    return TestClient(app)


def test_workspace_context_validation_envelope_is_frozen() -> None:
    response = _validation_client().post(
        "/workspace-context/switch",
        json={
            "tenant_id": "tenant-1",
            "project_id": "project-1",
            "expected_revision": -1,
            "idempotency_key": "switch-1",
            "extra": True,
        },
    )

    assert response.status_code == 422
    assert response.json() == {
        "detail": [
            {
                "type": "greater_than_equal",
                "loc": ["body", "expected_revision"],
                "msg": "Input should be greater than or equal to 0",
                "input": -1,
                "ctx": {"ge": 0},
            },
            {
                "type": "extra_forbidden",
                "loc": ["body", "extra"],
                "msg": "Extra inputs are not permitted",
                "input": True,
            },
        ]
    }


@pytest.mark.parametrize(
    ("code", "status_code", "detail"),
    [
        (
            WorkspaceContextErrorCode.UNAVAILABLE,
            404,
            {"code": "workspace_context_unavailable"},
        ),
        (
            WorkspaceContextErrorCode.MEMBERSHIP_REQUIRED,
            403,
            {"code": "workspace_context_membership_required"},
        ),
        (
            WorkspaceContextErrorCode.PROJECT_UNAVAILABLE,
            403,
            {"code": "workspace_context_project_unavailable"},
        ),
        (
            WorkspaceContextErrorCode.IDEMPOTENCY_CONFLICT,
            409,
            {"code": "workspace_context_idempotency_conflict"},
        ),
    ],
)
def test_workspace_context_error_envelope_is_frozen(
    code: WorkspaceContextErrorCode,
    status_code: int,
    detail: dict[str, str],
) -> None:
    with pytest.raises(HTTPException) as caught:
        _raise_workspace_context_http_error(WorkspaceContextError(code))

    assert caught.value.status_code == status_code
    assert caught.value.detail == detail


def test_workspace_context_revision_conflict_and_timestamp_are_frozen() -> None:
    with pytest.raises(HTTPException) as caught:
        _raise_workspace_context_http_error(
            WorkspaceContextError(
                WorkspaceContextErrorCode.REVISION_CONFLICT,
                expected_revision=2,
                actual_revision=3,
            )
        )
    snapshot = WorkspaceContextSnapshotResponse(
        tenant_id="tenant-1",
        project_id="project-1",
        revision=3,
        updated_at=datetime(2026, 8, 11, 1, 2, 3, 456789, UTC),
    )

    assert caught.value.status_code == 409
    assert caught.value.detail == {
        "code": "workspace_context_revision_conflict",
        "expected_revision": 2,
        "actual_revision": 3,
    }
    assert snapshot.model_dump(mode="json")["updated_at"] == "2026-08-11T01:02:03.456789Z"
