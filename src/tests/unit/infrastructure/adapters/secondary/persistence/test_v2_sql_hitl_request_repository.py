"""
Tests for V2 SqlHITLRequestRepository using BaseRepository.
"""

import pytest
from datetime import datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent.hitl_request import (
    HITLRequest,
    HITLRequestStatus,
    HITLRequestType,
)
from src.infrastructure.adapters.secondary.persistence.v2_sql_hitl_request_repository import (
    V2SqlHITLRequestRepository,
)


@pytest.fixture
async def v2_hitl_repo(v2_db_session: AsyncSession) -> V2SqlHITLRequestRepository:
    """Create a V2 HITL request repository for testing."""
    return V2SqlHITLRequestRepository(v2_db_session)


def make_hitl_request(
    request_id: str,
    conversation_id: str,
    request_type: HITLRequestType = HITLRequestType.DECISION,
) -> HITLRequest:
    """Factory for creating HITLRequest objects."""
    return HITLRequest(
        id=request_id,
        request_type=request_type,
        conversation_id=conversation_id,
        message_id="msg-1",
        tenant_id="tenant-1",
        project_id="project-1",
        user_id="user-1",
        question="Please confirm",
        options=["yes", "no"],
        context={},
        metadata={},
        status=HITLRequestStatus.PENDING,
        response=None,
        response_metadata=None,
        created_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        answered_at=None,
    )


class TestV2SqlHITLRequestRepositoryCreate:
    """Tests for creating HITL requests."""

    @pytest.mark.asyncio
    async def test_create_new_request(self, v2_hitl_repo: V2SqlHITLRequestRepository):
        """Test creating a new HITL request."""
        request = make_hitl_request("hitl-1", "conv-1")

        result = await v2_hitl_repo.create(request)

        assert result.id == "hitl-1"
        assert result.request_type == HITLRequestType.DECISION


class TestV2SqlHITLRequestRepositoryFind:
    """Tests for finding HITL requests."""

    @pytest.mark.asyncio
    async def test_get_by_id_existing(self, v2_hitl_repo: V2SqlHITLRequestRepository):
        """Test getting a HITL request by ID."""
        request = make_hitl_request("hitl-find-1", "conv-1")
        await v2_hitl_repo.create(request)

        result = await v2_hitl_repo.get_by_id("hitl-find-1")
        assert result is not None
        assert result.question == "Please confirm"

    @pytest.mark.asyncio
    async def test_get_by_id_not_found(self, v2_hitl_repo: V2SqlHITLRequestRepository):
        """Test getting a non-existent HITL request returns None."""
        result = await v2_hitl_repo.get_by_id("non-existent")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_pending_by_conversation(self, v2_hitl_repo: V2SqlHITLRequestRepository):
        """Test getting pending HITL requests by conversation."""
        request1 = make_hitl_request("hitl-pend-1", "conv-pend-1")
        request2 = make_hitl_request("hitl-pend-2", "conv-pend-1")
        await v2_hitl_repo.create(request1)
        await v2_hitl_repo.create(request2)

        results = await v2_hitl_repo.get_pending_by_conversation("conv-pend-1", "tenant-1", "project-1")
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_get_pending_by_conversation_exclude_expired(self, v2_hitl_repo: V2SqlHITLRequestRepository):
        """Test getting pending HITL requests excludes expired ones."""
        # Create expired request
        expired_request = make_hitl_request("hitl-exp-1", "conv-exp-1")
        expired_request.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        await v2_hitl_repo.create(expired_request)

        # Create valid request
        valid_request = make_hitl_request("hitl-valid-1", "conv-exp-1")
        await v2_hitl_repo.create(valid_request)

        results = await v2_hitl_repo.get_pending_by_conversation("conv-exp-1", "tenant-1", "project-1", exclude_expired=True)
        assert len(results) == 1
        assert results[0].id == "hitl-valid-1"

    @pytest.mark.asyncio
    async def test_get_pending_by_project(self, v2_hitl_repo: V2SqlHITLRequestRepository):
        """Test getting pending HITL requests by project."""
        for i in range(3):
            request = make_hitl_request(f"hitl-proj-{i}", "conv-proj-1")
            await v2_hitl_repo.create(request)

        results = await v2_hitl_repo.get_pending_by_project("tenant-1", "project-1")
        assert len(results) == 3


class TestV2SqlHITLRequestRepositoryUpdate:
    """Tests for updating HITL requests."""

    @pytest.mark.asyncio
    async def test_update_response(self, v2_hitl_repo: V2SqlHITLRequestRepository):
        """Test updating a HITL request with a response."""
        request = make_hitl_request("hitl-update-1", "conv-1")
        await v2_hitl_repo.create(request)

        result = await v2_hitl_repo.update_response("hitl-update-1", "yes", {"selected": "yes"})
        assert result is not None
        assert result.status == HITLRequestStatus.ANSWERED
        assert result.response == "yes"

    @pytest.mark.asyncio
    async def test_update_response_nonexistent(self, v2_hitl_repo: V2SqlHITLRequestRepository):
        """Test updating response of non-existent request returns None."""
        result = await v2_hitl_repo.update_response("non-existent", "yes")
        assert result is None

    @pytest.mark.asyncio
    async def test_mark_timeout(self, v2_hitl_repo: V2SqlHITLRequestRepository):
        """Test marking a HITL request as timed out."""
        request = make_hitl_request("hitl-timeout-1", "conv-1")
        await v2_hitl_repo.create(request)

        result = await v2_hitl_repo.mark_timeout("hitl-timeout-1", "default_response")
        assert result is not None
        assert result.status == HITLRequestStatus.TIMEOUT

    @pytest.mark.asyncio
    async def test_mark_cancelled(self, v2_hitl_repo: V2SqlHITLRequestRepository):
        """Test marking a HITL request as cancelled."""
        request = make_hitl_request("hitl-cancel-1", "conv-1")
        await v2_hitl_repo.create(request)

        result = await v2_hitl_repo.mark_cancelled("hitl-cancel-1")
        assert result is not None
        assert result.status == HITLRequestStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_mark_completed(self, v2_hitl_repo: V2SqlHITLRequestRepository):
        """Test marking a HITL request as completed."""
        request = make_hitl_request("hitl-complete-1", "conv-1")
        await v2_hitl_repo.create(request)

        # First mark as answered
        await v2_hitl_repo.update_response("hitl-complete-1", "yes")

        # Then mark as completed
        result = await v2_hitl_repo.mark_completed("hitl-complete-1")
        assert result is not None
        assert result.status == HITLRequestStatus.COMPLETED


class TestV2SqlHITLRequestRepositoryUtility:
    """Tests for utility methods."""

    @pytest.mark.asyncio
    async def test_get_unprocessed_answered_requests(self, v2_hitl_repo: V2SqlHITLRequestRepository):
        """Test getting unprocessed answered requests."""
        request = make_hitl_request("hitl-unproc-1", "conv-1")
        await v2_hitl_repo.create(request)
        await v2_hitl_repo.update_response("hitl-unproc-1", "yes")

        results = await v2_hitl_repo.get_unprocessed_answered_requests()
        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_mark_expired_requests(self, v2_hitl_repo: V2SqlHITLRequestRepository):
        """Test marking expired requests."""
        # Create expired request
        request = make_hitl_request("hitl-mark-exp-1", "conv-1")
        request.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        await v2_hitl_repo.create(request)

        count = await v2_hitl_repo.mark_expired_requests(datetime.now(timezone.utc))
        assert count >= 1


class TestV2SqlHITLRequestRepositoryDelete:
    """Tests for deleting HITL requests."""

    @pytest.mark.asyncio
    async def test_delete_existing(self, v2_hitl_repo: V2SqlHITLRequestRepository):
        """Test deleting an existing HITL request."""
        request = make_hitl_request("hitl-delete-1", "conv-1")
        await v2_hitl_repo.create(request)

        result = await v2_hitl_repo.delete("hitl-delete-1")
        assert result is True

        retrieved = await v2_hitl_repo.get_by_id("hitl-delete-1")
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, v2_hitl_repo: V2SqlHITLRequestRepository):
        """Test deleting a non-existent HITL request returns False."""
        result = await v2_hitl_repo.delete("non-existent")
        assert result is False
