"""Integration coverage for the V2-owned reflection route row."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI, status
from sqlalchemy import delete

from src.infrastructure.adapters.primary.web.startup.plugin_runtime_v2 import (
    initialize_plugin_runtime_v2,
    shutdown_plugin_runtime_v2,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    Playbook,
    ReflectionVerdictRecord,
    UserProject,
)

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
async def _reflection_v2_runtime(test_app: FastAPI) -> AsyncIterator[None]:
    """Exercise reflection requests through the production generation dispatcher."""
    await initialize_plugin_runtime_v2(test_app)
    assert "reflection" in test_app.state.platform_plugin_route_graph_v2.v2_owned_row_ids
    try:
        yield
    finally:
        await shutdown_plugin_runtime_v2(test_app)


async def test_reflection_lists_persisted_playbooks_and_verdicts(
    authenticated_async_client,
    test_db,
    test_project_db,
) -> None:
    playbook = Playbook(
        id="reflection-api-playbook",
        project_id=test_project_db.id,
        name="Recover from a failed check",
        status="active",
        trigger={
            "description": "A required check fails repeatedly",
            "friction_kinds": ["test_failure"],
            "lane_transitions": [["execute", "review"]],
        },
        steps=[
            {
                "order": 1,
                "instruction": "Inspect the failing check",
                "rationale": "Preserve causal evidence",
            }
        ],
        hit_count=3,
    )
    verdict = ReflectionVerdictRecord(
        id="reflection-api-verdict",
        project_id=test_project_db.id,
        action="reinforce",
        playbook_id=playbook.id,
        rationale="The recovery path succeeded",
        proposed_payload=None,
    )
    test_db.add_all([playbook, verdict])
    await test_db.commit()

    playbooks_response = await authenticated_async_client.get(
        f"/api/v1/projects/{test_project_db.id}/playbooks"
    )
    verdicts_response = await authenticated_async_client.get(
        f"/api/v1/projects/{test_project_db.id}/reflection-verdicts"
    )

    assert playbooks_response.status_code == status.HTTP_200_OK
    assert playbooks_response.json()["items"][0] == {
        "id": playbook.id,
        "project_id": test_project_db.id,
        "name": "Recover from a failed check",
        "status": "active",
        "trigger": {
            "description": "A required check fails repeatedly",
            "friction_kinds": ["test_failure"],
            "lane_transitions": [["execute", "review"]],
        },
        "steps": [
            {
                "order": 1,
                "instruction": "Inspect the failing check",
                "rationale": "Preserve causal evidence",
            }
        ],
        "hit_count": 3,
        "last_used_at": None,
        "created_at": playbooks_response.json()["items"][0]["created_at"],
        "updated_at": playbooks_response.json()["items"][0]["updated_at"],
    }
    assert verdicts_response.status_code == status.HTTP_200_OK
    assert verdicts_response.json()["items"][0] == {
        "id": verdict.id,
        "project_id": test_project_db.id,
        "action": "reinforce",
        "playbook_id": playbook.id,
        "rationale": "The recovery path succeeded",
        "proposed_payload": None,
        "created_at": verdicts_response.json()["items"][0]["created_at"],
    }


async def test_reflection_rejects_a_non_member(
    authenticated_async_client,
    test_db,
    test_project_db,
    test_user,
) -> None:
    await test_db.execute(
        delete(UserProject).where(
            UserProject.project_id == test_project_db.id,
            UserProject.user_id == test_user.id,
        )
    )
    await test_db.commit()

    response = await authenticated_async_client.get(
        f"/api/v1/projects/{test_project_db.id}/playbooks"
    )

    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert response.json()["detail"] == "Access denied to project"
