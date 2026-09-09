"""Closed-loop acceptance for the tenant event log surface with populated samples."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


async def test_event_log_list_returns_populated_rows(
    authenticated_async_client, governance_runtime, qa_scope
) -> None:
    response = await authenticated_async_client.get(
        "/api/v1/events",
        params={"tenant_id": qa_scope.tenant_id, "page_size": 50},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == len(qa_scope.event_logs)
    by_id = {item["id"]: item for item in payload["items"]}
    for spec in qa_scope.event_logs:
        item = by_id[spec["id"]]
        assert item["tenant_id"] == qa_scope.tenant_id
        assert item["event_type"] == spec["event_type"]
        assert item["message"] == spec["message"]
        assert item["source"] == spec["source"]
        assert item["metadata"]["qa_fixture"] == spec["metadata"]["qa_fixture"]


async def test_event_log_type_filter_and_types_endpoint(
    authenticated_async_client, governance_runtime, qa_scope
) -> None:
    filtered = await authenticated_async_client.get(
        "/api/v1/events",
        params={"tenant_id": qa_scope.tenant_id, "event_type": "deploy.started"},
    )
    assert filtered.status_code == 200
    items = filtered.json()["items"]
    assert len(items) == 2
    assert {item["event_type"] for item in items} == {"deploy.started"}

    types = await authenticated_async_client.get(
        "/api/v1/events/types", params={"tenant_id": qa_scope.tenant_id}
    )
    assert types.status_code == 200
    assert set(types.json()) == {"user.login", "deploy.started", "gene.installed"}


async def test_event_log_tenant_isolation_hides_qa_rows(
    authenticated_async_client, governance_runtime, qa_scope, test_tenant_db
) -> None:
    response = await authenticated_async_client.get(
        "/api/v1/events",
        params={"tenant_id": test_tenant_db.id, "page_size": 50},
    )

    assert response.status_code == 200
    assert response.json()["total"] == 0


async def test_event_log_member_reads_populated_rows(
    viewer_client, governance_runtime, viewer_user, qa_scope
) -> None:
    member_response = await viewer_client.get(
        "/api/v1/events", params={"tenant_id": qa_scope.tenant_id}
    )
    assert member_response.status_code == 200
    assert member_response.json()["total"] == len(qa_scope.event_logs)


async def test_event_log_outsider_is_rejected(
    outsider_client, governance_runtime, outsider_user, qa_scope
) -> None:
    outsider_response = await outsider_client.get(
        "/api/v1/events", params={"tenant_id": qa_scope.tenant_id}
    )
    assert outsider_response.status_code == 403
