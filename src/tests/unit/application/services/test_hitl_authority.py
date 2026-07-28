"""Tests for the protocol-level HITL authority snapshot."""

from datetime import UTC, datetime, timedelta

import pytest

from src.application.services.hitl_authority import classify_hitl_authority_conflict
from src.domain.model.agent.hitl_request import HITLRequest, HITLRequestStatus, HITLRequestType
from src.infrastructure.adapters.secondary.persistence.sql_conversation_session_projection_reader import (
    SqlConversationSessionProjectionReader,
)


def _request(
    *,
    status: HITLRequestStatus,
    created_at: datetime,
    expires_at: datetime,
    answered_at: datetime | None = None,
) -> HITLRequest:
    return HITLRequest(
        id="hitl-1",
        request_type=HITLRequestType.CLARIFICATION,
        conversation_id="conversation-1",
        message_id="message-1",
        tenant_id="tenant-1",
        project_id="project-1",
        question="Continue?",
        status=status,
        created_at=created_at,
        expires_at=expires_at,
        answered_at=answered_at,
    )


@pytest.mark.unit
def test_answered_authority_uses_stable_reason_and_timestamps() -> None:
    created_at = datetime(2026, 7, 28, 1, 0, tzinfo=UTC)
    answered_at = created_at + timedelta(seconds=5)
    request = _request(
        status=HITLRequestStatus.ANSWERED,
        created_at=created_at,
        expires_at=created_at + timedelta(minutes=5),
        answered_at=answered_at,
    )

    conflict = classify_hitl_authority_conflict(
        request,
        observed_at=created_at + timedelta(seconds=10),
    )

    assert conflict.reason_code == "hitl_already_answered"
    assert conflict.status_code == 409
    assert conflict.payload() == {
        "detail": "HITL request is no longer pending",
        "reason_code": "hitl_already_answered",
        "authority_revision": 2,
        "authority_status": "answered",
        "created_at": created_at.isoformat(),
        "answered_at": answered_at.isoformat(),
        "expires_at": (created_at + timedelta(minutes=5)).isoformat(),
        "observed_at": (created_at + timedelta(seconds=10)).isoformat(),
    }


@pytest.mark.unit
def test_expired_pending_authority_is_settled_without_guessing_from_message_text() -> None:
    created_at = datetime(2026, 7, 28, 1, 0, tzinfo=UTC)
    expires_at = created_at + timedelta(seconds=5)
    request = _request(
        status=HITLRequestStatus.PENDING,
        created_at=created_at,
        expires_at=expires_at,
    )

    conflict = classify_hitl_authority_conflict(
        request,
        observed_at=expires_at + timedelta(microseconds=1),
    )

    assert conflict.reason_code == "hitl_request_expired"
    assert conflict.status_code == 410
    assert conflict.authority_revision == 2
    assert conflict.expires_at == expires_at


@pytest.mark.unit
def test_live_pending_conflict_is_not_misclassified_as_settled() -> None:
    created_at = datetime(2026, 7, 28, 1, 0, tzinfo=UTC)
    request = _request(
        status=HITLRequestStatus.PENDING,
        created_at=created_at,
        expires_at=created_at + timedelta(minutes=5),
    )

    conflict = classify_hitl_authority_conflict(
        request,
        observed_at=created_at + timedelta(seconds=1),
    )

    assert conflict.reason_code == "hitl_claim_conflict"
    assert conflict.status_code == 409
    assert conflict.authority_revision == 1


@pytest.mark.unit
def test_pending_projection_supports_only_the_five_explicit_hitl_kinds() -> None:
    for hitl_kind in (
        "clarification",
        "decision",
        "env_var",
        "permission",
        "a2ui_action",
    ):
        assert SqlConversationSessionProjectionReader._hitl_kind(hitl_kind, None) == hitl_kind

    assert SqlConversationSessionProjectionReader._hitl_kind("elicitation", None) is None
