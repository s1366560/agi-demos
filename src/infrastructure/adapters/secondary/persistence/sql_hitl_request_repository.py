"""
SQLAlchemy implementation of HITLRequestRepository.

Provides persistence for Human-in-the-Loop requests with tenant
and project-level isolation for multi-tenant support.
"""

import logging
from datetime import datetime
from typing import List, Optional

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

logger = logging.getLogger(__name__)


class SQLHITLRequestRepository(HITLRequestRepositoryPort):
    """
    SQLAlchemy implementation of HITLRequestRepository.

    Provides CRUD operations for HITL requests with
    tenant and project-level isolation.
    """

    def __init__(self, session: AsyncSession):
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

    async def get_by_id(self, request_id: str) -> Optional[HITLRequest]:
        """Get an HITL request by its ID."""
        from src.infrastructure.adapters.secondary.persistence.models import (
            HITLRequest as HITLRequestRecord,
        )

        result = await self._session.execute(
            select(HITLRequestRecord).where(HITLRequestRecord.id == request_id)
        )
        db_record = result.scalar_one_or_none()

        return self._to_domain(db_record) if db_record else None

    async def get_pending_by_conversation(
        self,
        conversation_id: str,
        tenant_id: str,
        project_id: str,
    ) -> List[HITLRequest]:
        """Get all pending HITL requests for a conversation."""
        from src.infrastructure.adapters.secondary.persistence.models import (
            HITLRequest as HITLRequestRecord,
        )

        result = await self._session.execute(
            select(HITLRequestRecord)
            .where(
                HITLRequestRecord.conversation_id == conversation_id,
                HITLRequestRecord.tenant_id == tenant_id,
                HITLRequestRecord.project_id == project_id,
                HITLRequestRecord.status == HITLRequestStatus.PENDING.value,
            )
            .order_by(HITLRequestRecord.created_at.desc())
        )

        return [self._to_domain(r) for r in result.scalars().all()]

    async def get_pending_by_project(
        self,
        tenant_id: str,
        project_id: str,
        limit: int = 50,
    ) -> List[HITLRequest]:
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
        response_metadata: Optional[dict] = None,
    ) -> Optional[HITLRequest]:
        """Update an HITL request with a response."""
        from src.infrastructure.adapters.secondary.persistence.models import (
            HITLRequest as HITLRequestRecord,
        )

        now = datetime.utcnow()

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
        default_response: Optional[str] = None,
    ) -> Optional[HITLRequest]:
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

    async def mark_cancelled(self, request_id: str) -> Optional[HITLRequest]:
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

    def _to_domain(self, record) -> HITLRequest:
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
