"""Closed-loop acceptance for the audit log surface and its export endpoint."""

from __future__ import annotations

import csv
import io
import json

import pytest

pytestmark = pytest.mark.integration


def _audit_url(samples, suffix: str = "") -> str:
    return f"/api/v1/tenants/{samples.tenant_id}/audit-logs{suffix}"


async def test_audit_log_list_returns_populated_entries(
    authenticated_async_client, governance_runtime, qa_scope
) -> None:
    response = await authenticated_async_client.get(_audit_url(qa_scope), params={"limit": 100})

    assert response.status_code == 200
    payload = response.json()
    qa_ids = {spec["id"] for spec in qa_scope.audit_logs}
    items = {item["id"]: item for item in payload["items"] if item["id"] in qa_ids}
    assert set(items) == qa_ids
    for spec in qa_scope.audit_logs:
        item = items[spec["id"]]
        assert item["tenant_id"] == qa_scope.tenant_id
        assert item["action"] == spec["action"]
        assert item["resource_type"] == spec["resource_type"]
        assert item["resource_id"] == spec["resource_id"]
        assert item["details"]["qa_fixture"] == spec["details"]["qa_fixture"]


async def test_audit_log_action_filter_selects_seeded_rows(
    authenticated_async_client, governance_runtime, qa_scope
) -> None:
    response = await authenticated_async_client.get(
        _audit_url(qa_scope, "/filter"),
        params={"action": "trust.approval_resolved", "limit": 100},
    )

    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 2
    assert {item["action"] for item in items} == {"trust.approval_resolved"}


async def test_audit_export_json_contains_populated_rows(
    authenticated_async_client, governance_runtime, qa_scope
) -> None:
    response = await authenticated_async_client.get(
        _audit_url(qa_scope, "/export"), params={"format": "json"}
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert "audit-logs.json" in response.headers["content-disposition"]
    rows = {row["id"]: row for row in json.loads(response.text)}
    qa_ids = {spec["id"] for spec in qa_scope.audit_logs}
    assert qa_ids <= set(rows)
    for spec in qa_scope.audit_logs:
        row = rows[spec["id"]]
        assert row["actor"] == spec["actor"]
        assert row["action"] == spec["action"]
        assert row["tenant_id"] == qa_scope.tenant_id
        assert json.loads(row["details"])["qa_fixture"] == spec["details"]["qa_fixture"]


async def test_audit_export_csv_contains_populated_rows(
    authenticated_async_client, governance_runtime, qa_scope
) -> None:
    response = await authenticated_async_client.get(
        _audit_url(qa_scope, "/export"), params={"format": "csv"}
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "audit-logs.csv" in response.headers["content-disposition"]
    parsed = list(csv.DictReader(io.StringIO(response.text)))
    qa_ids = {spec["id"] for spec in qa_scope.audit_logs}
    rows = {row["id"]: row for row in parsed if row["id"] in qa_ids}
    assert set(rows) == qa_ids
    for spec in qa_scope.audit_logs:
        assert rows[spec["id"]]["action"] == spec["action"]
        assert rows[spec["id"]]["user_agent"] == "qa-governance-fixture"


async def test_audit_member_reads_but_outsider_is_rejected(
    viewer_client, governance_runtime, viewer_user, qa_scope
) -> None:
    listing = await viewer_client.get(_audit_url(qa_scope), params={"limit": 100})
    assert listing.status_code == 200

    export = await viewer_client.get(_audit_url(qa_scope, "/export"), params={"format": "json"})
    assert export.status_code == 200


async def test_audit_outsider_is_rejected_on_list_and_export(
    outsider_client, governance_runtime, outsider_user, qa_scope
) -> None:
    listing = await outsider_client.get(_audit_url(qa_scope), params={"limit": 100})
    assert listing.status_code == 403

    export = await outsider_client.get(_audit_url(qa_scope, "/export"), params={"format": "csv"})
    assert export.status_code == 403
