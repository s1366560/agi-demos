"""Contract tests for revisioned and idempotent HITL REST responses."""

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from src.application.services.hitl_response_contract import (
    build_hitl_response_digest,
    merge_hitl_response_contract_metadata,
)
from src.configuration.config import get_settings
from src.domain.model.agent.hitl_request import HITLRequest, HITLRequestStatus, HITLRequestType
from src.infrastructure.adapters.primary.web.routers.agent import hitl as hitl_router
from src.infrastructure.adapters.primary.web.routers.agent.schemas import HITLResponseRequest


def _hitl_request(*, status: HITLRequestStatus = HITLRequestStatus.PENDING) -> HITLRequest:
    now = datetime.now(UTC)
    return HITLRequest(
        id="req-1",
        request_type=HITLRequestType.CLARIFICATION,
        conversation_id="conv-1",
        message_id="msg-1",
        tenant_id="tenant-1",
        project_id="project-1",
        question="Need input",
        status=status,
        response="first answer" if status != HITLRequestStatus.PENDING else None,
        created_at=now,
        answered_at=now if status != HITLRequestStatus.PENDING else None,
        expires_at=now + timedelta(minutes=5),
    )


def _request(
    *,
    answer: str = "first answer",
    expected_revision: int = 1,
    idempotency_key: str = "desktop:req-1:clarification",
) -> HITLResponseRequest:
    return HITLResponseRequest(
        contract_version=2,
        request_id="req-1",
        hitl_type="clarification",
        response_data={"answer": answer},
        expected_revision=expected_revision,
        idempotency_key=idempotency_key,
    )


def _wire_router(
    monkeypatch: pytest.MonkeyPatch,
    repo: MagicMock,
) -> tuple[AsyncMock, SimpleNamespace]:
    publish = AsyncMock(return_value=True)
    db = SimpleNamespace(commit=AsyncMock())
    monkeypatch.setattr(hitl_router, "SqlHITLRequestRepository", lambda _db: repo)
    monkeypatch.setattr(hitl_router, "_publish_hitl_response_to_redis", publish)
    monkeypatch.setattr(hitl_router, "_user_has_hitl_access", AsyncMock(return_value=True))
    monkeypatch.setattr(
        "src.infrastructure.agent.hitl.coordinator.validate_hitl_response",
        lambda **_: (True, None),
    )
    return publish, db


def test_hitl_response_request_accepts_legacy_or_complete_v2_only() -> None:
    legacy = HITLResponseRequest(
        request_id="req-1",
        hitl_type="clarification",
        response_data={"answer": "ok"},
    )
    revisioned = _request()

    assert legacy.contract_version is None
    assert legacy.expected_revision is None
    assert legacy.idempotency_key is None
    assert revisioned.contract_version == 2
    assert revisioned.expected_revision == 1

    with pytest.raises(ValidationError):
        HITLResponseRequest(
            request_id="req-1",
            hitl_type="clarification",
            response_data={"answer": "ok"},
            expected_revision=1,
        )
    with pytest.raises(ValidationError):
        HITLResponseRequest(
            request_id="req-1",
            hitl_type="clarification",
            response_data={"answer": "ok"},
            expected_revision=0,
            idempotency_key="desktop:req-1:clarification",
        )
    with pytest.raises(ValidationError):
        HITLResponseRequest(
            request_id="req-1",
            hitl_type="clarification",
            response_data={"answer": "ok"},
            expected_revision=1,
            idempotency_key=" contains spaces ",
        )
    legacy_with_extra = HITLResponseRequest(
        request_id="req-1",
        hitl_type="clarification",
        response_data={"answer": "ok"},
        unknown_legacy_field=True,
    )
    assert not hasattr(legacy_with_extra, "unknown_legacy_field")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_v2_hitl_response_claims_revision_one_and_returns_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pending = _hitl_request()
    answered = _hitl_request(status=HITLRequestStatus.ANSWERED)
    repo = MagicMock()
    repo.get_by_id = AsyncMock(return_value=pending)
    repo.claim_response_v2 = AsyncMock(return_value=answered)
    repo.update_response = AsyncMock(side_effect=AssertionError("legacy claim must not run"))
    publish, db = _wire_router(monkeypatch, repo)

    response = await hitl_router.respond_to_hitl(
        request=_request(),
        current_user=SimpleNamespace(id="user-1"),
        tenant_id="tenant-1",
        db=db,
    )

    assert response.status_code == 200
    payload = json.loads(response.body)
    assert payload["success"] is True
    assert payload["status"] == "answered"
    assert payload["authority_revision"] == 2
    assert payload["duplicate"] is False
    repo.claim_response_v2.assert_awaited_once()
    claim = repo.claim_response_v2.await_args.kwargs
    assert claim["expected_revision"] == 1
    assert claim["idempotency_key"] == "desktop:req-1:clarification"
    assert claim["payload_digest"]
    publish.assert_awaited_once()
    db.commit.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_v2_hitl_response_replays_same_key_and_payload_without_republishing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    answered = _hitl_request(status=HITLRequestStatus.ANSWERED)
    digest = build_hitl_response_digest(
        secret=get_settings().secret_key,
        request_id="req-1",
        hitl_type="clarification",
        response_data={"answer": "first answer"},
    )
    answered.response_metadata = merge_hitl_response_contract_metadata(
        None,
        expected_revision=1,
        idempotency_key="desktop:req-1:clarification",
        payload_digest=digest,
    )
    repo = MagicMock()
    repo.get_by_id = AsyncMock(return_value=answered)
    repo.claim_response_v2 = AsyncMock()
    publish, db = _wire_router(monkeypatch, repo)

    response = await hitl_router.respond_to_hitl(
        request=_request(),
        current_user=SimpleNamespace(id="user-1"),
        tenant_id="tenant-1",
        db=db,
    )

    assert response.status_code == 200
    payload = json.loads(response.body)
    assert payload["duplicate"] is True
    assert payload["authority_revision"] == 2
    repo.claim_response_v2.assert_not_awaited()
    publish.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_v2_hitl_response_rejects_same_key_with_different_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    answered = _hitl_request(status=HITLRequestStatus.ANSWERED)
    digest = build_hitl_response_digest(
        secret=get_settings().secret_key,
        request_id="req-1",
        hitl_type="clarification",
        response_data={"answer": "first answer"},
    )
    answered.response_metadata = merge_hitl_response_contract_metadata(
        None,
        expected_revision=1,
        idempotency_key="desktop:req-1:clarification",
        payload_digest=digest,
    )
    repo = MagicMock()
    repo.get_by_id = AsyncMock(return_value=answered)
    publish, db = _wire_router(monkeypatch, repo)

    response = await hitl_router.respond_to_hitl(
        request=_request(answer="different answer"),
        current_user=SimpleNamespace(id="user-1"),
        tenant_id="tenant-1",
        db=db,
    )

    assert response.status_code == 409
    payload = json.loads(response.body)
    assert payload["reason_code"] == "hitl_idempotency_conflict"
    assert payload["authority_revision"] == 2
    assert "first answer" not in json.dumps(payload)
    publish.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_v2_hitl_response_rejects_stale_pending_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pending = _hitl_request()
    repo = MagicMock()
    repo.get_by_id = AsyncMock(return_value=pending)
    repo.claim_response_v2 = AsyncMock()
    publish, db = _wire_router(monkeypatch, repo)

    response = await hitl_router.respond_to_hitl(
        request=_request(expected_revision=2),
        current_user=SimpleNamespace(id="user-1"),
        tenant_id="tenant-1",
        db=db,
    )

    assert response.status_code == 409
    payload = json.loads(response.body)
    assert payload["reason_code"] == "hitl_revision_conflict"
    assert payload["expected_revision"] == 2
    assert payload["authority_revision"] == 1
    repo.claim_response_v2.assert_not_awaited()
    publish.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_v2_hitl_response_lost_claim_replays_winning_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pending = _hitl_request()
    answered = _hitl_request(status=HITLRequestStatus.ANSWERED)
    digest = build_hitl_response_digest(
        secret=get_settings().secret_key,
        request_id="req-1",
        hitl_type="clarification",
        response_data={"answer": "first answer"},
    )
    answered.response_metadata = merge_hitl_response_contract_metadata(
        None,
        expected_revision=1,
        idempotency_key="desktop:req-1:clarification",
        payload_digest=digest,
    )
    repo = MagicMock()
    repo.get_by_id = AsyncMock(side_effect=[pending, answered])
    repo.claim_response_v2 = AsyncMock(return_value=None)
    publish, db = _wire_router(monkeypatch, repo)

    response = await hitl_router.respond_to_hitl(
        request=_request(),
        current_user=SimpleNamespace(id="user-1"),
        tenant_id="tenant-1",
        db=db,
    )

    assert response.status_code == 200
    payload = json.loads(response.body)
    assert payload["duplicate"] is True
    assert payload["authority_revision"] == 2
    publish.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_v2_hitl_response_losing_client_gets_answered_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    answered = _hitl_request(status=HITLRequestStatus.ANSWERED)
    digest = build_hitl_response_digest(
        secret=get_settings().secret_key,
        request_id="req-1",
        hitl_type="clarification",
        response_data={"answer": "first answer"},
    )
    answered.response_metadata = merge_hitl_response_contract_metadata(
        None,
        expected_revision=1,
        idempotency_key="desktop:req-1:clarification",
        payload_digest=digest,
    )
    repo = MagicMock()
    repo.get_by_id = AsyncMock(return_value=answered)
    publish, db = _wire_router(monkeypatch, repo)

    response = await hitl_router.respond_to_hitl(
        request=_request(idempotency_key="web:req-1:clarification"),
        current_user=SimpleNamespace(id="user-2"),
        tenant_id="tenant-1",
        db=db,
    )

    assert response.status_code == 409
    payload = json.loads(response.body)
    assert payload["reason_code"] == "hitl_already_answered"
    assert payload["authority_revision"] == 2
    assert payload["authority_status"] == "answered"
    publish.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_v2_hitl_response_returns_structured_expiry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pending = _hitl_request()
    pending.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    timed_out = _hitl_request(status=HITLRequestStatus.TIMEOUT)
    timed_out.expires_at = pending.expires_at
    repo = MagicMock()
    repo.get_by_id = AsyncMock(side_effect=[pending, pending])
    repo.mark_timeout = AsyncMock(return_value=timed_out)
    publish, db = _wire_router(monkeypatch, repo)

    response = await hitl_router.respond_to_hitl(
        request=_request(),
        current_user=SimpleNamespace(id="user-1"),
        tenant_id="tenant-1",
        db=db,
    )

    assert response.status_code == 410
    payload = json.loads(response.body)
    assert payload["reason_code"] == "hitl_request_expired"
    assert payload["authority_revision"] == 2
    assert payload["authority_status"] == "timeout"
    publish.assert_not_awaited()
    db.commit.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_pending_hitl_response_exposes_hitl_authority_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pending = _hitl_request()
    conversation_repo = MagicMock()
    conversation_repo.find_by_id = AsyncMock(
        return_value=SimpleNamespace(
            id="conv-1",
            tenant_id="tenant-1",
            project_id="project-1",
        )
    )
    repo = MagicMock()
    repo.get_pending_by_conversation = AsyncMock(return_value=[pending])
    monkeypatch.setattr(hitl_router, "SqlConversationRepository", lambda _db: conversation_repo)
    monkeypatch.setattr(hitl_router, "SqlHITLRequestRepository", lambda _db: repo)
    monkeypatch.setattr(hitl_router, "_user_has_hitl_access", AsyncMock(return_value=True))

    response = await hitl_router.get_pending_hitl_requests(
        conversation_id="conv-1",
        current_user=SimpleNamespace(id="user-1"),
        tenant_id="tenant-1",
        db=MagicMock(),
    )

    assert response.requests[0].authority_revision == 1
