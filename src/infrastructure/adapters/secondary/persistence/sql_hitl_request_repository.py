"""
V2 SQLAlchemy implementation of HITLRequestRepository using BaseRepository.
"""

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent.hitl_request import (
    HITLRequest,
    HITLRequestStatus,
    HITLRequestType,
)
from src.domain.ports.repositories.hitl_request_repository import (
    HITLRequestRepositoryPort,
)
from src.infrastructure.adapters.secondary.common.base_repository import BaseRepository

logger = logging.getLogger(__name__)


class SqlHITLRequestRepository(BaseRepository[HITLRequest, object], HITLRequestRepositoryPort):
    """
    V2 SQLAlchemy implementation of HITLRequestRepository using BaseRepository.

    Provides CRUD operations for HITL requests with
    tenant and project-level isolation.
    """

    # This repository doesn't use a standard model for CRUD
    _model_class = None

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository."""
        super().__init__(session)
        self._session = session

    async def create(self, request: HITLRequest) -> HITLRequest:
        """Create a new HITL request."""
        from src.infrastructure.adapters.secondary.persistence.models import (
            HITLRequest as HITLRequestRecord,
        )

        db_record = HITLRequestRecord(
            id=request.id,
            request_type=request.request_type.value,
            conversation_id=request.conversation_id,
            message_id=request.message_id,
            tenant_id=request.tenant_id,
            project_id=request.project_id,
            user_id=request.user_id,
            question=request.question,
            options=request.options,
            context=request.context,
            request_metadata=request.metadata,
            status=request.status.value,
            response=request.response,
            response_metadata=request.response_metadata,
            created_at=request.created_at,
            expires_at=request.expires_at,
            answered_at=request.answered_at,
        )

        self._session.add(db_record)
        await self._session.flush()

        logger.info(
            f"Created HITL request: {request.id} type={request.request_type.value} "
            f"conversation={request.conversation_id}"
        )
        return request

    async def get_by_id(self, request_id: str) -> HITLRequest | None:
        """Get an HITL request by its ID."""
        from src.infrastructure.adapters.secondary.persistence.models import (
            HITLRequest as HITLRequestRecord,
        )

        result = await self._session.execute(
            select(HITLRequestRecord).where(HITLRequestRecord.id == request_id)
        )
        db_record = result.scalar_one_or_none()

        return self._to_domain(db_record) if db_record else None

    async def get_by_conversation(
        self,
        conversation_id: str,
    ) -> list[HITLRequest]:
        """Get all HITL requests for a conversation (regardless of status)."""
        from src.infrastructure.adapters.secondary.persistence.models import (
            HITLRequest as HITLRequestRecord,
        )

        result = await self._session.execute(
            select(HITLRequestRecord)
            .where(HITLRequestRecord.conversation_id == conversation_id)
            .order_by(HITLRequestRecord.created_at.desc())
        )

        return [self._to_domain(r) for r in result.scalars().all()]

    async def get_pending_by_conversation(
        self,
        conversation_id: str,
        tenant_id: str,
        project_id: str,
        exclude_expired: bool = True,
    ) -> list[HITLRequest]:
        """Get all pending HITL requests for a conversation.

        Args:
            conversation_id: The conversation ID
            tenant_id: The tenant ID
            project_id: The project ID
            exclude_expired: If True, exclude requests that have passed their expires_at
        """
        from datetime import datetime

        from src.infrastructure.adapters.secondary.persistence.models import (
            HITLRequest as HITLRequestRecord,
        )

        conditions = [
            HITLRequestRecord.conversation_id == conversation_id,
            HITLRequestRecord.tenant_id == tenant_id,
            HITLRequestRecord.project_id == project_id,
            HITLRequestRecord.status == HITLRequestStatus.PENDING.value,
        ]

        # Exclude expired requests if requested
        if exclude_expired:
            now = datetime.now(UTC)
            conditions.append(
                (HITLRequestRecord.expires_at.is_(None)) | (HITLRequestRecord.expires_at > now)
            )

        result = await self._session.execute(
            select(HITLRequestRecord)
            .where(*conditions)
            .order_by(HITLRequestRecord.created_at.desc())
        )

        return [self._to_domain(r) for r in result.scalars().all()]

    async def get_pending_by_project(
        self,
        tenant_id: str,
        project_id: str,
        limit: int = 50,
    ) -> list[HITLRequest]:
        """Get all pending HITL requests for a project."""
        from src.infrastructure.adapters.secondary.persistence.models import (
            HITLRequest as HITLRequestRecord,
        )

        result = await self._session.execute(
            select(HITLRequestRecord)
            .where(
                HITLRequestRecord.tenant_id == tenant_id,
                HITLRequestRecord.project_id == project_id,
                HITLRequestRecord.status == HITLRequestStatus.PENDING.value,
            )
            .order_by(HITLRequestRecord.created_at.desc())
            .limit(limit)
        )

        return [self._to_domain(r) for r in result.scalars().all()]

    async def update_response(
        self,
        request_id: str,
        response: str,
        response_metadata: dict | None = None,
    ) -> HITLRequest | None:
        """Update an HITL request with a response."""
        from src.infrastructure.adapters.secondary.persistence.models import (
            HITLRequest as HITLRequestRecord,
        )

        now = datetime.now(UTC)

        result = await self._session.execute(
            update(HITLRequestRecord)
            .where(
                HITLRequestRecord.id == request_id,
                HITLRequestRecord.status == HITLRequestStatus.PENDING.value,
            )
            .values(
                status=HITLRequestStatus.ANSWERED.value,
                response=response,
                response_metadata=response_metadata,
                answered_at=now,
            )
            .returning(HITLRequestRecord)
        )

        db_record = result.scalar_one_or_none()
        if db_record:
            logger.info(f"Updated HITL request response: {request_id}")
            return self._to_domain(db_record)

        return None

    async def mark_timeout(
        self,
        request_id: str,
        default_response: str | None = None,
    ) -> HITLRequest | None:
        """Mark an HITL request as timed out."""
        from src.infrastructure.adapters.secondary.persistence.models import (
            HITLRequest as HITLRequestRecord,
        )

        response_metadata = {"is_default": True} if default_response else None

        result = await self._session.execute(
            update(HITLRequestRecord)
            .where(
                HITLRequestRecord.id == request_id,
                HITLRequestRecord.status == HITLRequestStatus.PENDING.value,
            )
            .values(
                status=HITLRequestStatus.TIMEOUT.value,
                response=default_response,
                response_metadata=response_metadata,
            )
            .returning(HITLRequestRecord)
        )

        db_record = result.scalar_one_or_none()
        if db_record:
            logger.info(f"Marked HITL request as timeout: {request_id}")
            return self._to_domain(db_record)

        return None

    async def mark_cancelled(self, request_id: str) -> HITLRequest | None:
        """Mark an HITL request as cancelled."""
        from src.infrastructure.adapters.secondary.persistence.models import (
            HITLRequest as HITLRequestRecord,
        )

        result = await self._session.execute(
            update(HITLRequestRecord)
            .where(
                HITLRequestRecord.id == request_id,
                HITLRequestRecord.status == HITLRequestStatus.PENDING.value,
            )
            .values(status=HITLRequestStatus.CANCELLED.value)
            .returning(HITLRequestRecord)
        )

        db_record = result.scalar_one_or_none()
        if db_record:
            logger.info(f"Marked HITL request as cancelled: {request_id}")
            return self._to_domain(db_record)

        return None

    async def mark_completed(self, request_id: str) -> HITLRequest | None:
        """Mark an HITL request as completed (Agent finished processing)."""
        from src.infrastructure.adapters.secondary.persistence.models import (
            HITLRequest as HITLRequestRecord,
        )

        result = await self._session.execute(
            update(HITLRequestRecord)
            .where(
                HITLRequestRecord.id == request_id,
                HITLRequestRecord.status.in_(
                    [
                        HITLRequestStatus.ANSWERED.value,
                        HITLRequestStatus.PROCESSING.value,
                    ]
                ),
            )
            .values(status=HITLRequestStatus.COMPLETED.value)
            .returning(HITLRequestRecord)
        )

        db_record = result.scalar_one_or_none()
        if db_record:
            logger.info(f"Marked HITL request as completed: {request_id}")
            return self._to_domain(db_record)

        return None

    async def get_unprocessed_answered_requests(
        self,
        limit: int = 100,
    ) -> list[HITLRequest]:
        """
        Get HITL requests that have been answered but not yet processed by Agent.

        This is used for recovery after Worker restart:
        - Status is ANSWERED (user responded, but Agent crashed before processing)
        - Ordered by answered_at to process oldest first

        Args:
            limit: Maximum number of requests to return

        Returns:
            List of HITL requests needing recovery
        """
        from src.infrastructure.adapters.secondary.persistence.models import (
            HITLRequest as HITLRequestRecord,
        )

        result = await self._session.execute(
            select(HITLRequestRecord)
            .where(
                HITLRequestRecord.status == HITLRequestStatus.ANSWERED.value,
            )
            .order_by(HITLRequestRecord.answered_at.asc())
            .limit(limit)
        )

        requests = [self._to_domain(r) for r in result.scalars().all()]
        if requests:
            logger.info(f"Found {len(requests)} unprocessed answered HITL requests for recovery")
        return requests

    async def mark_expired_requests(self, before: datetime) -> int:
        """Mark all expired pending requests as timed out."""
        from src.infrastructure.adapters.secondary.persistence.models import (
            HITLRequest as HITLRequestRecord,
        )

        result = await self._session.execute(
            update(HITLRequestRecord)
            .where(
                HITLRequestRecord.status == HITLRequestStatus.PENDING.value,
                HITLRequestRecord.expires_at < before,
            )
            .values(status=HITLRequestStatus.TIMEOUT.value)
        )

        count = result.rowcount
        if count > 0:
            logger.info(f"Marked {count} HITL requests as expired")

        return count

    async def delete(self, request_id: str) -> bool:
        """Delete an HITL request."""
        from src.infrastructure.adapters.secondary.persistence.models import (
            HITLRequest as HITLRequestRecord,
        )

        result = await self._session.execute(
            select(HITLRequestRecord).where(HITLRequestRecord.id == request_id)
        )
        db_record = result.scalar_one_or_none()

        if db_record:
            await self._session.delete(db_record)
            await self._session.flush()
            logger.info(f"Deleted HITL request: {request_id}")
            return True

        return False

    def _to_domain(self, record: Any) -> HITLRequest:
        """Convert database record to domain entity."""
        return HITLRequest(
            id=record.id,
            request_type=HITLRequestType(record.request_type),
            conversation_id=record.conversation_id,
            message_id=record.message_id,
            tenant_id=record.tenant_id,
            project_id=record.project_id,
            user_id=record.user_id,
            question=record.question,
            options=record.options,
            context=record.context,
            metadata=record.request_metadata,
            status=HITLRequestStatus(record.status),
            response=record.response,
            response_metadata=record.response_metadata,
            created_at=record.created_at,
            expires_at=record.expires_at,
            answered_at=record.answered_at,
        )
