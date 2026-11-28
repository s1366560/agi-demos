"""Exercise redacted, principal-scoped audit events from both real package routers."""

import json
import logging

import pytest

from src.tests.unit.routers import test_optional_business_http_v2 as fixtures

http = fixtures.http
publisher = fixtures.publisher
pytestmark = pytest.mark.unit


async def test_signed_package_records_authority_execution_and_failed_validation(
    http, publisher, caplog
):
    client, keys = http
    caplog.set_level(logging.INFO, logger="plugin_audit")
    owner = {"Authorization": "Bearer " + keys["owner"]}
    base = "/api/v1/platform-plugins/v2/optional-business"
    scope = {"tenant_id": "t", "project_id": "p"}
    release, digest = publisher[1]()
    assert (await client.post(base + "/install", json=release, headers=owner)).is_success
    root = base + "/sample.notes"
    assert (await client.post(root + "/enable", json=scope, headers=owner)).is_success
    assert (
        await client.post(root + "/commands", json={**scope, "command_id": "ping"}, headers=owner)
    ).is_success
    private = "private-note-that-must-not-reach-the-audit-sink"
    denied = await client.post(
        root + "/invoke",
        json={**scope, "tool_name": "note.ping", "payload": {"op": private}},
        headers=owner,
    )
    assert denied.is_error
    assert (await client.post(root + "/disable", json=scope, headers=owner)).is_success
    events = [
        json.loads(r.getMessage())
        for r in caplog.records
        if r.name == "plugin_audit.project_package"
    ]
    assert [(e["operation"], e["outcome"]) for e in events] == [
        ("install", "ok"),
        ("enable", "ok"),
        ("command", "ok"),
        ("tool", "error"),
        ("disable", "ok"),
    ]
    for event in events:
        assert (
            event["actor_id"] == "owner"
            and event["tenant_id"] == "t"
            and event["project_id"] == "p"
        )
        assert (
            event["plugin_id"] == "sample.notes"
            and event["version"] == "1.0.0"
            and event["digest"] == digest
        )
        assert event["duration_ms"] >= 0
    assert events[2]["command_id"] == "ping" and events[3]["tool_id"] == "note.ping"
    assert private not in caplog.text and keys["owner"] not in caplog.text


async def test_audit_sink_failure_preserves_successful_guest_result(http, publisher, monkeypatch):
    client, keys = http
    owner = {"Authorization": "Bearer " + keys["owner"]}
    base = "/api/v1/platform-plugins/v2/optional-business"
    scope = {"tenant_id": "t", "project_id": "p"}
    release, _ = publisher[1]()

    def unavailable(*_args, **_kwargs):
        raise OSError("audit sink unavailable")

    for name in ("plugin_audit", "plugin_audit.project_package"):
        monkeypatch.setattr(logging.getLogger(name), "info", unavailable)
    assert (await client.post(base + "/install", json=release, headers=owner)).is_success
    root = base + "/sample.notes"
    assert (await client.post(root + "/enable", json=scope, headers=owner)).is_success
    result = await client.post(
        root + "/commands", json={**scope, "command_id": "ping"}, headers=owner
    )
    assert result.is_success and result.json()["op"] == "ping"


async def test_unauthorized_package_attempt_does_not_copy_unverified_fields(http, caplog):
    client, keys = http
    caplog.set_level(logging.INFO, logger="plugin_audit")
    unverified = "untrusted-project-selector"
    denied = await client.post(
        "/api/v1/platform-plugins/v2/optional-business/sample.notes/enable",
        json={"tenant_id": "t", "project_id": unverified},
        headers={"Authorization": "Bearer " + keys["viewer"]},
    )
    assert denied.is_error
    (record,) = (
        json.loads(r.getMessage())
        for r in caplog.records
        if r.name == "plugin_audit.project_package"
    )
    assert (
        record["actor_id"] == "viewer"
        and record["operation"] == "authorize.manage"
        and record["outcome"] == "error"
    )
    assert "project_id" not in record and unverified not in json.dumps(record)
