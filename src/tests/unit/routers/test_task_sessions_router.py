"""Tests for the cloud task-session creation contract."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.infrastructure.adapters.primary.web.routers import task_sessions
from src.infrastructure.adapters.primary.web.routers.workspace_agent_policy import (
    WorkspaceAgentPolicyResponse,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    Project,
    Tenant,
    UserProject,
    UserTenant,
    WorkspaceMemberModel,
    WorkspaceModel,
)

TENANT_ID = "tenant-task-session"
PROJECT_ID = "project-task-session"
WORKSPACE_ID = "workspace-task-session"
USER_ID = "550e8400-e29b-41d4-a716-446655440000"


async def _seed_task_session_scope(test_db) -> None:
    test_db.add_all(
        [
            Tenant(
                id=TENANT_ID,
                name="Task Session Tenant",
                slug="task-session-tenant",
                owner_id=USER_ID,
            ),
            Project(
                id=PROJECT_ID,
                tenant_id=TENANT_ID,
                name="Task Session Project",
                owner_id=USER_ID,
            ),
            UserTenant(
                id="ut-task-session",
                user_id=USER_ID,
                tenant_id=TENANT_ID,
                role="owner",
            ),
            UserProject(
                id="up-task-session",
                user_id=USER_ID,
                project_id=PROJECT_ID,
                role="owner",
            ),
            WorkspaceModel(
                id=WORKSPACE_ID,
                tenant_id=TENANT_ID,
                project_id=PROJECT_ID,
                name="Task Session Workspace",
                created_by=USER_ID,
            ),
            WorkspaceMemberModel(
                id="wm-task-session",
                workspace_id=WORKSPACE_ID,
                user_id=USER_ID,
                role="owner",
                invited_by=USER_ID,
            ),
        ]
    )
    await test_db.commit()


def _stub_default_policy(monkeypatch) -> None:
    async def policy_response(_db, workspace, _policy) -> WorkspaceAgentPolicyResponse:
        return WorkspaceAgentPolicyResponse(
            tenant_id=workspace.tenant_id,
            project_id=workspace.project_id,
            workspace_id=workspace.id,
            revision=0,
            roles={"default": None, "fast": None, "coding": None, "vision": None},
            fallbacks=[],
            reasoning_effort="medium",
            permission_mode="ask",
            capability_version="workspace-agent-policy-v1",
            updated_at="2026-07-21T00:00:00+00:00",
        )

    monkeypatch.setattr(task_sessions, "_policy_response", policy_response)


@pytest.mark.unit
async def test_create_cloud_task_session_accepts_and_persists_composer_context(
    test_db,
    client,
    test_user,
    monkeypatch,
) -> None:
    await _seed_task_session_scope(test_db)
    _stub_default_policy(monkeypatch)
    context_items = [
        {
            "kind": "plugin",
            "resource_id": "plugin-review",
            "label": "Review plugin",
            "metadata": {"enabled": True, "priority": 1},
        }
    ]

    response = client.post(
        f"/api/v1/tenants/{TENANT_ID}/projects/{PROJECT_ID}/task-sessions",
        json={
            "idempotency_key": "desktop-cloud-session-context-1",
            "workspace": {"kind": "existing", "workspace_id": WORKSPACE_ID},
            "conversation": {"title": "Review the release", "capability_mode": "work"},
            "initial_message": {
                "content": "Review the release plan",
                "context_items": context_items,
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["initial_message"]["metadata"]["context_items"] == context_items


@pytest.mark.unit
async def test_create_cloud_task_session_accepts_empty_composer_context(
    test_db,
    client,
    test_user,
    monkeypatch,
) -> None:
    await _seed_task_session_scope(test_db)
    _stub_default_policy(monkeypatch)

    response = client.post(
        f"/api/v1/tenants/{TENANT_ID}/projects/{PROJECT_ID}/task-sessions",
        json={
            "idempotency_key": "desktop-cloud-session-empty-context-1",
            "workspace": {"kind": "existing", "workspace_id": WORKSPACE_ID},
            "conversation": {"title": "Start cloud work", "capability_mode": "work"},
            "initial_message": {
                "content": "Start cloud work",
                "context_items": [],
            },
        },
    )

    assert response.status_code == 200
    assert response.json()["initial_message"]["metadata"]["context_items"] == []


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
