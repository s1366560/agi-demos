"""Persistence tests for the atomic HITL response V2 claim."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.hitl_response_contract import read_hitl_response_contract_metadata
from src.domain.model.agent.hitl_request import HITLRequest, HITLRequestStatus, HITLRequestType
from src.infrastructure.adapters.secondary.persistence.sql_hitl_request_repository import (
    SqlHITLRequestRepository,
)


def _request(request_id: str) -> HITLRequest:
    now = datetime.now(UTC)
    return HITLRequest(
        id=request_id,
        request_type=HITLRequestType.CLARIFICATION,
        conversation_id="conv-1",
        message_id="msg-1",
        tenant_id="tenant-1",
        project_id="project-1",
        user_id="user-1",
        question="Please clarify",
        status=HITLRequestStatus.PENDING,
        created_at=now,
        expires_at=now + timedelta(minutes=5),
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_claim_response_v2_is_atomic_and_persists_receipt(
    v2_db_session: AsyncSession,
) -> None:
    repo = SqlHITLRequestRepository(v2_db_session)
    await repo.create(_request("hitl-v2-1"))

    claimed = await repo.claim_response_v2(
        request_id="hitl-v2-1",
        response="answer",
        response_metadata=None,
        expected_revision=1,
        idempotency_key="desktop:hitl-v2-1:clarification",
        payload_digest="a" * 64,
    )
    second = await repo.claim_response_v2(
        request_id="hitl-v2-1",
        response="different",
        response_metadata=None,
        expected_revision=1,
        idempotency_key="desktop:hitl-v2-1:clarification",
        payload_digest="b" * 64,
    )

    assert claimed is not None
    assert claimed.status == HITLRequestStatus.ANSWERED
    assert second is None
    receipt = read_hitl_response_contract_metadata(claimed.response_metadata)
    assert receipt is not None
    assert receipt.idempotency_key == "desktop:hitl-v2-1:clarification"
    assert receipt.payload_digest == "a" * 64


@pytest.mark.unit
@pytest.mark.asyncio
async def test_claim_response_v2_rejects_non_pending_authority_revision(
    v2_db_session: AsyncSession,
) -> None:
    repo = SqlHITLRequestRepository(v2_db_session)
    await repo.create(_request("hitl-v2-2"))

    claimed = await repo.claim_response_v2(
        request_id="hitl-v2-2",
        response="answer",
        response_metadata=None,
        expected_revision=2,
        idempotency_key="desktop:hitl-v2-2:clarification",
        payload_digest="a" * 64,
    )
    persisted = await repo.get_by_id("hitl-v2-2")

    assert claimed is None
    assert persisted is not None
    assert persisted.status == HITLRequestStatus.PENDING
