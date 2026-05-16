from __future__ import annotations

import json
from datetime import UTC, datetime

from src.domain.model.audit.audit_entry import AuditEntry
from src.infrastructure.adapters.primary.web.routers.audit import _render_audit_export


def _entry() -> AuditEntry:
    return AuditEntry(
        id="audit-1",
        timestamp=datetime(2026, 5, 16, 10, 30, tzinfo=UTC),
        actor="user-1",
        action="project.created",
        resource_type="project",
        resource_id="project-1",
        tenant_id="tenant-1",
        details={"name": "Alpha", "count": 2},
        ip_address="127.0.0.1",
        user_agent="pytest",
    )


def test_render_audit_export_json() -> None:
    payload = json.loads(_render_audit_export([_entry()], "json"))

    assert payload == [
        {
            "id": "audit-1",
            "timestamp": "2026-05-16T10:30:00+00:00",
            "actor": "user-1",
            "action": "project.created",
            "resource_type": "project",
            "resource_id": "project-1",
            "tenant_id": "tenant-1",
            "details": '{"count": 2, "name": "Alpha"}',
            "ip_address": "127.0.0.1",
            "user_agent": "pytest",
        }
    ]


def test_render_audit_export_csv() -> None:
    payload = _render_audit_export([_entry()], "csv")

    assert payload.startswith("id,timestamp,actor,action,resource_type")
    assert "audit-1,2026-05-16T10:30:00+00:00,user-1,project.created,project" in payload
    assert '""count"": 2' in payload
