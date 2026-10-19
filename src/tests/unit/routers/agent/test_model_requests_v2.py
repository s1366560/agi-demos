"""Prepared inputs use history authorization and never invoke a live generation."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from src.infrastructure.adapters.primary.web.routers.agent import model_requests_v2 as subject

pytestmark = pytest.mark.unit


@pytest.fixture
def boundary(monkeypatch):
    access = AsyncMock(return_value=SimpleNamespace(project_id="project"))
    store = SimpleNamespace(read_message_events=AsyncMock(return_value=[]))
    monkeypatch.setattr(subject, "_get_accessible_conversation", access)
    monkeypatch.setattr(subject, "SqlSessionEventLogStoreV2", lambda: store)
    return access, store


async def read(project_id="project"):
    return await subject.get_model_request_v2(
        "conversation", "message", "attempt", MagicMock(), project_id, MagicMock(), MagicMock()
    )


def record(**fields):
    return SimpleNamespace(
        conversation_id="conversation",
        message_id="message",
        event_type="model_request_prepared",
        event_data={
            "schema_version": 1,
            "format": "provider.http.json/v1",
            "attempt_id": "attempt",
            "provider": "gemini",
            "model": "model-test",
            "request": {"contents": [{"parts": [{"text": "stored guidance"}]}]},
            **fields,
        },
    )


async def test_exact_request_survives_without_any_current_generation(boundary):
    access, store = boundary
    original = record()
    store.read_message_events.return_value = [original]
    result = await read()
    assert result["status"] == "available"
    assert result["request"]["body"] == original.event_data["request"]
    assert result["request"]["model"] == "model-test"
    assert result["request"]["body"] is not original.event_data["request"]
    assert access.await_count == 2
    store.read_message_events.assert_awaited_once_with(
        conversation_id="conversation", message_id="message"
    )


@pytest.mark.parametrize("records", [[], [record(schema_version=0)], [record(), record()]])
async def test_missing_or_legacy_snapshot_is_explicit(boundary, records):
    boundary[1].read_message_events.return_value = records
    result = await read()
    assert result["status"] == "snapshot_missing"
    assert result["reason_code"] == "model_request_snapshot_missing"
    assert result["request"] is None


async def test_access_denied_never_reads_private_model_input(boundary):
    boundary[0].side_effect = HTTPException(status_code=403, detail="denied")
    with pytest.raises(HTTPException) as caught:
        await read()
    assert caught.value.status_code == 403
    boundary[1].read_message_events.assert_not_awaited()


async def test_cross_project_never_reads_private_model_input(boundary):
    with pytest.raises(HTTPException) as caught:
        await read("other-project")
    assert caught.value.status_code == 403
    boundary[1].read_message_events.assert_not_awaited()


async def test_revocation_during_read_prevents_response(boundary):
    boundary[0].side_effect = [
        SimpleNamespace(project_id="project"),
        HTTPException(status_code=403, detail="revoked"),
    ]
    boundary[1].read_message_events.return_value = [record()]
    with pytest.raises(HTTPException) as caught:
        await read()
    assert caught.value.status_code == 403
