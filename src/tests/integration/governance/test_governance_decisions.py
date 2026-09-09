"""Closed-loop acceptance for trust decision records (approvals) with samples."""

from __future__ import annotations

import pytest

from scripts.qa_governance_fixtures import QA_AGENT_INSTANCE_ID

pytestmark = pytest.mark.integration


def _trust_url(samples, suffix: str = "") -> str:
    return f"/api/v1/tenants/{samples.tenant_id}/trust{suffix}"


def _workspace_params(samples) -> dict[str, str]:
    return {"workspace_id": samples.workspace_id}


async def test_decision_records_list_returns_all_seeded_outcomes(
    authenticated_async_client, governance_runtime, qa_scope
) -> None:
    response = await authenticated_async_client.get(
        _trust_url(qa_scope, "/decision-records"),
        params=_workspace_params(qa_scope),
    )

    assert response.status_code == 200
    items = {item["id"]: item for item in response.json()["items"]}
    assert set(items) == {spec["id"] for spec in qa_scope.decision_records}
    outcomes = {item["outcome"] for item in items.values()}
    assert outcomes == {"pending", "success", "rejected"}


async def test_decision_record_detail_returns_populated_fields(
    authenticated_async_client, governance_runtime, qa_scope
) -> None:
    spec = qa_scope.decision_records[1]  # approved sample
    response = await authenticated_async_client.get(
        _trust_url(qa_scope, f"/decision-records/{spec['id']}"),
        params=_workspace_params(qa_scope),
    )

    assert response.status_code == 200
    item = response.json()
    assert item["id"] == spec["id"]
    assert item["tenant_id"] == qa_scope.tenant_id
    assert item["workspace_id"] == qa_scope.workspace_id
    assert item["agent_instance_id"] == QA_AGENT_INSTANCE_ID
    assert item["decision_type"] == spec["decision_type"]
    assert item["proposal"] == spec["proposal"]
    assert item["outcome"] == "success"
    assert item["reviewer_id"] == spec["reviewer_id"]
    assert item["review_comment"] == spec["review_comment"]
    assert item["resolved_at"] is not None


async def test_decision_record_detail_is_scoped_to_workspace(
    authenticated_async_client, governance_runtime, qa_scope
) -> None:
    spec = qa_scope.decision_records[0]
    response = await authenticated_async_client.get(
        _trust_url(qa_scope, f"/decision-records/{spec['id']}"),
        params={"workspace_id": "qa-governance-other-workspace"},
    )

    assert response.status_code == 404


async def test_approval_flow_pending_to_approved_via_api(
    authenticated_async_client, governance_runtime, qa_scope
) -> None:
    submit = await authenticated_async_client.post(
        _trust_url(qa_scope, "/approval-requests"),
        json={
            "workspace_id": qa_scope.workspace_id,
            "agent_instance_id": QA_AGENT_INSTANCE_ID,
            "action_type": "shell.execute",
            "proposal": {"command": "qa-governance --verify"},
            "context_summary": "QA governance loop: approval submitted through API",
        },
    )
    assert submit.status_code == 201
    record = submit.json()
    assert record["outcome"] == "pending"
    assert record["tenant_id"] == qa_scope.tenant_id

    resolve = await authenticated_async_client.post(
        _trust_url(qa_scope, f"/approval-requests/{record['id']}/resolve"),
        json={"decision": "allow_once"},
    )
    assert resolve.status_code == 200
    resolved = resolve.json()
    assert resolved["outcome"] == "success"
    assert resolved["review_type"] == "human"
    assert resolved["resolved_at"] is not None

    detail = await authenticated_async_client.get(
        _trust_url(qa_scope, f"/decision-records/{record['id']}"),
        params=_workspace_params(qa_scope),
    )
    assert detail.status_code == 200
    assert detail.json()["outcome"] == "success"


async def test_approval_flow_pending_to_rejected_via_api(
    authenticated_async_client, governance_runtime, qa_scope
) -> None:
    submit = await authenticated_async_client.post(
        _trust_url(qa_scope, "/approval-requests"),
        json={
            "workspace_id": qa_scope.workspace_id,
            "agent_instance_id": QA_AGENT_INSTANCE_ID,
            "action_type": "network.egress",
            "proposal": {"url": "https://qa-governance.invalid/deny"},
        },
    )
    assert submit.status_code == 201
    record_id = submit.json()["id"]

    resolve = await authenticated_async_client.post(
        _trust_url(qa_scope, f"/approval-requests/{record_id}/resolve"),
        json={"decision": "deny"},
    )
    assert resolve.status_code == 200
    assert resolve.json()["outcome"] == "rejected"
    assert resolve.json()["review_comment"] == "Denied by reviewer"


async def test_allow_always_resolution_creates_trust_policy(
    authenticated_async_client, governance_runtime, qa_scope
) -> None:
    submit = await authenticated_async_client.post(
        _trust_url(qa_scope, "/approval-requests"),
        json={
            "workspace_id": qa_scope.workspace_id,
            "agent_instance_id": QA_AGENT_INSTANCE_ID,
            "action_type": "desktop.screenshot",
            "proposal": {"display": "qa-governance-display"},
        },
    )
    assert submit.status_code == 201
    record_id = submit.json()["id"]

    resolve = await authenticated_async_client.post(
        _trust_url(qa_scope, f"/approval-requests/{record_id}/resolve"),
        json={"decision": "allow_always"},
    )
    assert resolve.status_code == 200

    policies = await authenticated_async_client.get(
        _trust_url(qa_scope, "/policies"),
        params={**_workspace_params(qa_scope), "agent_instance_id": QA_AGENT_INSTANCE_ID},
    )
    assert policies.status_code == 200
    action_types = {item["action_type"] for item in policies.json()["items"]}
    assert {"memory.read", "desktop.screenshot"} <= action_types

    check = await authenticated_async_client.get(
        _trust_url(qa_scope, "/policies/check"),
        params={
            **_workspace_params(qa_scope),
            "agent_instance_id": QA_AGENT_INSTANCE_ID,
            "action_type": "desktop.screenshot",
        },
    )
    assert check.status_code == 200
    assert check.json() == {"trusted": True}


async def test_member_can_submit_and_read_but_cannot_resolve(
    viewer_client, governance_runtime, viewer_user, qa_scope
) -> None:
    submit = await viewer_client.post(
        _trust_url(qa_scope, "/approval-requests"),
        json={
            "workspace_id": qa_scope.workspace_id,
            "agent_instance_id": QA_AGENT_INSTANCE_ID,
            "action_type": "shell.execute",
            "proposal": {"command": "qa-governance --member"},
        },
    )
    assert submit.status_code == 201
    record_id = submit.json()["id"]

    listing = await viewer_client.get(
        _trust_url(qa_scope, "/decision-records"),
        params=_workspace_params(qa_scope),
    )
    assert listing.status_code == 200
    assert len(listing.json()["items"]) >= len(qa_scope.decision_records)

    resolve = await viewer_client.post(
        _trust_url(qa_scope, f"/approval-requests/{record_id}/resolve"),
        json={"decision": "allow_once"},
    )
    assert resolve.status_code == 403


async def test_outsider_cannot_read_or_submit(
    outsider_client, governance_runtime, outsider_user, qa_scope
) -> None:
    listing = await outsider_client.get(
        _trust_url(qa_scope, "/decision-records"),
        params=_workspace_params(qa_scope),
    )
    assert listing.status_code == 403

    submit = await outsider_client.post(
        _trust_url(qa_scope, "/approval-requests"),
        json={
            "workspace_id": qa_scope.workspace_id,
            "agent_instance_id": QA_AGENT_INSTANCE_ID,
            "action_type": "shell.execute",
            "proposal": {},
        },
    )
    assert submit.status_code == 403
