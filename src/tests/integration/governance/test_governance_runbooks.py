"""Closed-loop acceptance for the playbook (runbook) library with populated samples."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


async def test_playbook_library_lists_populated_runbooks(
    authenticated_async_client, governance_runtime, qa_scope
) -> None:
    response = await authenticated_async_client.get(
        f"/api/v1/projects/{qa_scope.project_id}/playbooks"
    )

    assert response.status_code == 200
    items = {item["id"]: item for item in response.json()["items"]}
    assert set(items) == {spec["id"] for spec in qa_scope.playbooks}
    for spec in qa_scope.playbooks:
        item = items[spec["id"]]
        assert item["project_id"] == qa_scope.project_id
        assert item["name"] == spec["name"]
        assert item["status"] == "active"
        assert item["trigger"]["description"] == spec["trigger"]["description"]
        assert [step["instruction"] for step in item["steps"]] == [
            step["instruction"] for step in spec["steps"]
        ]
        assert item["hit_count"] == spec["hit_count"]


async def test_playbook_verdict_history_lists_execution_records(
    authenticated_async_client, governance_runtime, qa_scope
) -> None:
    response = await authenticated_async_client.get(
        f"/api/v1/projects/{qa_scope.project_id}/reflection-verdicts"
    )

    assert response.status_code == 200
    items = {item["id"]: item for item in response.json()["items"]}
    assert set(items) == {spec["id"] for spec in qa_scope.verdicts}
    for spec in qa_scope.verdicts:
        item = items[spec["id"]]
        assert item["action"] == spec["action"]
        assert item["playbook_id"] == spec["playbook_id"]
        assert item["rationale"] == spec["rationale"]


async def test_playbook_member_reads_populated_library(
    viewer_client, governance_runtime, viewer_user, qa_scope
) -> None:
    response = await viewer_client.get(f"/api/v1/projects/{qa_scope.project_id}/playbooks")

    assert response.status_code == 200
    assert len(response.json()["items"]) == len(qa_scope.playbooks)


async def test_playbook_outsider_is_rejected(
    outsider_client, governance_runtime, outsider_user, qa_scope
) -> None:
    playbooks = await outsider_client.get(f"/api/v1/projects/{qa_scope.project_id}/playbooks")
    assert playbooks.status_code == 403

    verdicts = await outsider_client.get(
        f"/api/v1/projects/{qa_scope.project_id}/reflection-verdicts"
    )
    assert verdicts.status_code == 403
