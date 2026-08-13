"""Tests for the cloud task-session creation contract."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import ValidationError

from src.infrastructure.adapters.primary.web import workspace_core_task_sessions
from src.infrastructure.adapters.primary.web.routers import task_sessions

TENANT_ID = "tenant-task-session"
PROJECT_ID = "project-task-session"


def _task_session_routes(app: FastAPI) -> list[APIRoute]:
    return [
        route
        for route in app.routes
        if isinstance(route, APIRoute) and "task-sessions" in route.path
    ]


@pytest.mark.unit
def test_avernet_task_session_gateway_registers_real_core_saga_without_legacy_routes() -> None:
    app = FastAPI()
    workspace_core_task_sessions.register_task_session_routes(app)

    response = TestClient(app).get(
        f"/api/v1/tenants/{TENANT_ID}/projects/{PROJECT_ID}/task-sessions/capabilities"
    )

    assert response.status_code == 200
    assert response.json()["atomic_creation"] is True
    assert response.json()["workspace_authority"] == "avernet"
    assert all(
        route.endpoint.__module__
        == "src.infrastructure.adapters.primary.web.workspace_core_task_sessions"
        for route in _task_session_routes(app)
    )
    assert not hasattr(task_sessions, "router")
    assert not hasattr(task_sessions, "create_task_session")


@pytest.mark.unit
def test_cloud_task_session_context_rejects_duplicates_and_oversized_metadata() -> None:
    duplicate = {
        "kind": "thread",
        "resource_id": "conversation-1",
        "label": "Conversation one",
    }
    with pytest.raises(ValidationError):
        task_sessions.InitialMessageInput(
            content="Start cloud work",
            context_items=[duplicate, duplicate],
        )

    with pytest.raises(ValidationError):
        task_sessions.InitialMessageInput(
            content="Start cloud work",
            context_items=[
                {
                    "kind": "plugin",
                    "resource_id": "plugin-1",
                    "label": "Plugin one",
                    "metadata": {"description": "x" * (4 * 1024)},
                }
            ],
        )
