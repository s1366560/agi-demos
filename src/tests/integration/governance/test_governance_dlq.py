"""Closed-loop acceptance for the admin DLQ surface with populated Redis samples."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


def _sample_ids(samples) -> dict[str, str]:
    by_status: dict[str, str] = {}
    for message in samples.dlq_messages:
        by_status.setdefault(message.status.value, message.id)
    return by_status


async def test_dlq_list_and_stats_return_populated_entries(
    authenticated_async_client, governance_runtime, qa_dlq
) -> None:
    listing = await authenticated_async_client.get(
        "/api/v1/admin/dlq/messages", params={"limit": 50}
    )
    assert listing.status_code == 200
    payload = listing.json()
    qa_ids = {message.id for message in qa_dlq.dlq_messages}
    listed = {m["id"]: m for m in payload["messages"] if m["id"] in qa_ids}
    assert set(listed) == qa_ids
    for message in qa_dlq.dlq_messages:
        item = listed[message.id]
        assert item["event_type"] == message.event_type
        assert item["error_type"] == message.error_type
        assert item["routing_key"] == message.routing_key
        assert item["status"] == message.status.value
        assert item["metadata"]["qa_fixture"] == message.metadata["qa_fixture"]

    stats = await authenticated_async_client.get("/api/v1/admin/dlq/stats")
    assert stats.status_code == 200
    stats_payload = stats.json()
    assert stats_payload["total_messages"] >= len(qa_dlq.dlq_messages)
    assert stats_payload["error_type_counts"]["TimeoutError"] >= 1
    assert stats_payload["event_type_counts"]["memory.created"] >= 1


async def test_dlq_status_filter_selects_seeded_states(
    authenticated_async_client, governance_runtime, qa_dlq
) -> None:
    response = await authenticated_async_client.get(
        "/api/v1/admin/dlq/messages", params={"status": "resolved", "limit": 50}
    )
    assert response.status_code == 200
    resolved_ids = {m["id"] for m in response.json()["messages"]}
    expected = {m.id for m in qa_dlq.dlq_messages if m.status.value == "resolved"}
    assert expected <= resolved_ids


async def test_dlq_detail_view_returns_full_message(
    authenticated_async_client, governance_runtime, qa_dlq
) -> None:
    message = qa_dlq.dlq_messages[0]
    response = await authenticated_async_client.get(f"/api/v1/admin/dlq/messages/{message.id}")

    assert response.status_code == 200
    item = response.json()
    assert item["id"] == message.id
    assert item["event_id"] == message.event_id
    assert item["event_data"] == message.event_data
    assert item["error"] == message.error
    assert item["retry_count"] == message.retry_count
    assert item["max_retries"] == message.max_retries
    assert item["can_retry"] is True


async def test_dlq_retry_transitions_pending_message_to_resolved(
    authenticated_async_client, governance_runtime, qa_dlq
) -> None:
    message = qa_dlq.dlq_messages[0]
    assert message.status.value == "pending"

    retry = await authenticated_async_client.post(f"/api/v1/admin/dlq/messages/{message.id}/retry")
    assert retry.status_code == 200
    assert retry.json() == {
        "message_id": message.id,
        "success": True,
        "message": "Retry initiated",
    }

    detail = await authenticated_async_client.get(f"/api/v1/admin/dlq/messages/{message.id}")
    assert detail.status_code == 200
    assert detail.json()["status"] == "resolved"
    assert detail.json()["can_retry"] is False


async def test_dlq_retry_is_idempotency_safe_for_terminal_states(
    authenticated_async_client, governance_runtime, qa_dlq
) -> None:
    resolved_id = _sample_ids(qa_dlq)["resolved"]

    retry = await authenticated_async_client.post(f"/api/v1/admin/dlq/messages/{resolved_id}/retry")
    assert retry.status_code == 409

    detail = await authenticated_async_client.get(f"/api/v1/admin/dlq/messages/{resolved_id}")
    assert detail.status_code == 200
    assert detail.json()["status"] == "resolved"
    assert detail.json()["retry_count"] == 2


async def test_dlq_discard_marks_message_and_preserves_reason(
    authenticated_async_client, governance_runtime, qa_dlq
) -> None:
    pending_ids = [m.id for m in qa_dlq.dlq_messages if m.status.value == "pending"]
    target = pending_ids[1]

    discard = await authenticated_async_client.request(
        "DELETE",
        f"/api/v1/admin/dlq/messages/{target}",
        params={"reason": "qa governance acceptance discard"},
    )
    assert discard.status_code == 200
    assert discard.json()["success"] is True

    detail = await authenticated_async_client.get(f"/api/v1/admin/dlq/messages/{target}")
    assert detail.status_code == 200
    assert detail.json()["status"] == "discarded"
    assert detail.json()["metadata"]["discard_reason"] == "qa governance acceptance discard"


async def test_dlq_batch_retry_reports_per_message_results(
    authenticated_async_client, governance_runtime, qa_dlq
) -> None:
    ids = _sample_ids(qa_dlq)
    response = await authenticated_async_client.post(
        "/api/v1/admin/dlq/messages/retry",
        json={"message_ids": [ids["pending"], ids["resolved"]]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["results"][ids["pending"]] is True
    assert payload["results"][ids["resolved"]] is False
    assert payload["success_count"] == 1
    assert payload["failure_count"] == 1


async def test_dlq_missing_message_returns_404(
    authenticated_async_client, governance_runtime, qa_dlq
) -> None:
    detail = await authenticated_async_client.get(
        "/api/v1/admin/dlq/messages/qa-governance-missing"
    )
    assert detail.status_code == 404

    retry = await authenticated_async_client.post(
        "/api/v1/admin/dlq/messages/qa-governance-missing/retry"
    )
    assert retry.status_code == 404


async def test_dlq_non_admin_member_is_forbidden_on_all_operations(
    viewer_client, governance_runtime, viewer_user, qa_dlq
) -> None:
    message_id = qa_dlq.dlq_messages[0].id

    listing = await viewer_client.get("/api/v1/admin/dlq/messages")
    assert listing.status_code == 403

    detail = await viewer_client.get(f"/api/v1/admin/dlq/messages/{message_id}")
    assert detail.status_code == 403

    retry = await viewer_client.post(f"/api/v1/admin/dlq/messages/{message_id}/retry")
    assert retry.status_code == 403

    discard = await viewer_client.request(
        "DELETE", f"/api/v1/admin/dlq/messages/{message_id}", params={"reason": "forbidden"}
    )
    assert discard.status_code == 403

    stats = await viewer_client.get("/api/v1/admin/dlq/stats")
    assert stats.status_code == 403
