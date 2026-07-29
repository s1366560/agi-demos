"""
V2 SQLAlchemy implementation of HITLRequestRepository using BaseRepository.
"""

import logging
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent.hitl_request import (
    HITLRequest,
    HITLRequestStatus,
    HITLRequestType,
)
from src.domain.ports.repositories.hitl_request_repository import (
    HITLRequestRepositoryPort,
)
from src.infrastructure.adapters.secondary.common.base_repository import (
    BaseRepository,
    refresh_select_statement,
)

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
            refresh_select_statement(self._refresh_statement(
                select(HITLRequestRecord).where(HITLRequestRecord.id == request_id)
            ))
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
            refresh_select_statement(self._refresh_statement(
                select(HITLRequestRecord)
                .where(HITLRequestRecord.conversation_id == conversation_id)
                .order_by(HITLRequestRecord.created_at.desc())
            ))
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
            refresh_select_statement(self._refresh_statement(
                select(HITLRequestRecord)
                .where(*conditions)
                .order_by(HITLRequestRecord.created_at.desc())
            ))
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
            refresh_select_statement(self._refresh_statement(
                select(HITLRequestRecord)
                .where(
                    HITLRequestRecord.tenant_id == tenant_id,
                    HITLRequestRecord.project_id == project_id,
                    HITLRequestRecord.status == HITLRequestStatus.PENDING.value,
                )
                .order_by(HITLRequestRecord.created_at.desc())
                .limit(limit)
            ))
        )

        return [self._to_domain(r) for r in result.scalars().all()]

    async def get_pending_by_project_for_user(
        self,
        tenant_id: str,
        project_id: str,
        user_id: str,
        limit: int = 50,
    ) -> list[HITLRequest]:
        """Get pending project HITL requests visible to a specific user."""
        from src.infrastructure.adapters.secondary.persistence.models import (
            Conversation,
            HITLRequest as HITLRequestRecord,
        )

        result = await self._session.execute(
            refresh_select_statement(self._refresh_statement(
                select(HITLRequestRecord)
                .join(Conversation, Conversation.id == HITLRequestRecord.conversation_id)
                .where(
                    HITLRequestRecord.tenant_id == tenant_id,
                    HITLRequestRecord.project_id == project_id,
                    HITLRequestRecord.status == HITLRequestStatus.PENDING.value,
                    Conversation.tenant_id == tenant_id,
                    or_(
                        HITLRequestRecord.user_id == user_id,
                        and_(
                            HITLRequestRecord.user_id.is_(None),
                            Conversation.user_id == user_id,
                        ),
                    ),
                )
                .order_by(HITLRequestRecord.created_at.desc())
                .limit(limit)
            ))
        )

        return [self._to_domain(r) for r in result.scalars().all()]

    async def update_response(
        self,
        request_id: str,
        response: str,
        response_metadata: dict[str, Any] | None = None,
    ) -> HITLRequest | None:
        """Update an HITL request with a response."""
        from src.infrastructure.adapters.secondary.persistence.models import (
            HITLRequest as HITLRequestRecord,
        )

        now = datetime.now(UTC)

        result = await self._session.execute(
            refresh_select_statement(self._refresh_statement(
                update(HITLRequestRecord)
                .where(
                    HITLRequestRecord.id == request_id,
                    HITLRequestRecord.status == HITLRequestStatus.PENDING.value,
                    (HITLRequestRecord.expires_at.is_(None)) | (HITLRequestRecord.expires_at > now),
                )
                .values(
                    status=HITLRequestStatus.ANSWERED.value,
                    response=response,
                    response_metadata=response_metadata,
                    answered_at=now,
                )
                .returning(HITLRequestRecord)
            ))
        )

        db_record = result.scalar_one_or_none()
        if db_record:
            logger.info(f"Updated HITL request response: {request_id}")
            return self._to_domain(db_record)

        return None

    async def claim_response_v2(
        self,
        *,
        request_id: str,
        response: str,
        response_metadata: dict[str, Any] | None,
        expected_revision: int,
        idempotency_key: str,
        payload_digest: str,
    ) -> HITLRequest | None:
        """Atomically claim a pending request and persist its replay receipt."""
        from src.application.services.hitl_response_contract import (
            HITL_PENDING_AUTHORITY_REVISION,
            merge_hitl_response_contract_metadata,
        )
        from src.infrastructure.adapters.secondary.persistence.models import (
            HITLRequest as HITLRequestRecord,
        )

        if expected_revision != HITL_PENDING_AUTHORITY_REVISION:
            return None

        now = datetime.now(UTC)
        persisted_metadata = merge_hitl_response_contract_metadata(
            response_metadata,
            expected_revision=expected_revision,
            idempotency_key=idempotency_key,
            payload_digest=payload_digest,
        )
        result = await self._session.execute(
            refresh_select_statement(
                self._refresh_statement(
                    update(HITLRequestRecord)
                    .where(
                        HITLRequestRecord.id == request_id,
                        HITLRequestRecord.status == HITLRequestStatus.PENDING.value,
                        (HITLRequestRecord.expires_at.is_(None))
                        | (HITLRequestRecord.expires_at > now),
                    )
                    .values(
                        status=HITLRequestStatus.ANSWERED.value,
                        response=response,
                        response_metadata=persisted_metadata,
                        answered_at=now,
                    )
                    .returning(HITLRequestRecord)
                )
            )
        )
        db_record = result.scalar_one_or_none()
        if db_record is None:
            return None
        logger.info("Claimed revisioned HITL response: %s", request_id)
        return self._to_domain(db_record)

    async def reopen_pending(self, request_id: str) -> HITLRequest | None:
        """Reopen an answered HITL request after delivery failure."""
        from src.infrastructure.adapters.secondary.persistence.models import (
            HITLRequest as HITLRequestRecord,
        )

        result = await self._session.execute(
            refresh_select_statement(self._refresh_statement(
                update(HITLRequestRecord)
                .where(
                    HITLRequestRecord.id == request_id,
                    HITLRequestRecord.status == HITLRequestStatus.ANSWERED.value,
                )
                .values(
                    status=HITLRequestStatus.PENDING.value,
                    response=None,
                    response_metadata=None,
                    answered_at=None,
                )
                .returning(HITLRequestRecord)
            ))
        )

        db_record = result.scalar_one_or_none()
        if db_record:
            logger.info(f"Reopened HITL request as pending: {request_id}")
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
            refresh_select_statement(self._refresh_statement(
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
            ))
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
            refresh_select_statement(self._refresh_statement(
                update(HITLRequestRecord)
                .where(
                    HITLRequestRecord.id == request_id,
                    HITLRequestRecord.status == HITLRequestStatus.PENDING.value,
                )
                .values(status=HITLRequestStatus.CANCELLED.value)
                .returning(HITLRequestRecord)
            ))
        )

        db_record = result.scalar_one_or_none()
        if db_record:
            logger.info(f"Marked HITL request as cancelled: {request_id}")
            return self._to_domain(db_record)

        return None

    async def mark_completed(
        self,
        request_id: str,
        *,
        lease_owner: str | None = None,
    ) -> HITLRequest | None:
        """Mark an HITL request as completed (Agent finished processing)."""
        from src.infrastructure.adapters.secondary.persistence.models import (
            HITLRequest as HITLRequestRecord,
        )
        from src.infrastructure.agent.hitl.utils import clear_processing_lease_metadata

        owner_expr = HITLRequestRecord.response_metadata["processing_owner"].as_string()
        processing_condition = HITLRequestRecord.status == HITLRequestStatus.PROCESSING.value
        completion_condition = or_(
            HITLRequestRecord.status == HITLRequestStatus.ANSWERED.value,
            processing_condition,
        )
        if lease_owner is not None:
            completion_condition = and_(
                processing_condition,
                owner_expr == lease_owner,
            )

        result = await self._session.execute(
            refresh_select_statement(self._refresh_statement(
                update(HITLRequestRecord)
                .where(
                    HITLRequestRecord.id == request_id,
                    completion_condition,
                )
                .values(status=HITLRequestStatus.COMPLETED.value)
                .returning(HITLRequestRecord)
            ))
        )

        db_record = result.scalar_one_or_none()
        if db_record:
            cleared_metadata = clear_processing_lease_metadata(
                getattr(db_record, "response_metadata", None)
            )
            await self._session.execute(
                refresh_select_statement(self._refresh_statement(
                    update(HITLRequestRecord)
                    .where(HITLRequestRecord.id == request_id)
                    .values(response_metadata=cleared_metadata)
                ))
            )
            logger.info(f"Marked HITL request as completed: {request_id}")
            return self._to_domain(db_record)

        return None

    async def claim_for_processing(
        self,
        request_id: str,
        *,
        lease_owner: str | None = None,
    ) -> HITLRequest | None:
        """Atomically transition an answered HITL request into processing."""
        from src.infrastructure.adapters.secondary.persistence.models import (
            HITLRequest as HITLRequestRecord,
        )
        from src.infrastructure.agent.hitl.utils import merge_processing_lease_metadata

        now = datetime.now(UTC)
        result = await self._session.execute(
            refresh_select_statement(self._refresh_statement(
                update(HITLRequestRecord)
                .where(
                    HITLRequestRecord.id == request_id,
                    HITLRequestRecord.status == HITLRequestStatus.ANSWERED.value,
                )
                .values(status=HITLRequestStatus.PROCESSING.value)
                .returning(HITLRequestRecord)
            ))
        )

        db_record = result.scalar_one_or_none()
        if db_record:
            lease_metadata = merge_processing_lease_metadata(
                getattr(db_record, "response_metadata", None),
                lease_time=now,
                lease_owner=lease_owner,
            )
            await self._session.execute(
                refresh_select_statement(self._refresh_statement(
                    update(HITLRequestRecord)
                    .where(HITLRequestRecord.id == request_id)
                    .values(response_metadata=lease_metadata)
                ))
            )
            logger.info("Claimed HITL request for processing: %s", request_id)
            return self._to_domain(db_record)

        return None

    async def refresh_processing_lease(
        self,
        request_id: str,
        *,
        lease_owner: str | None = None,
    ) -> bool:
        """Refresh the persisted processing heartbeat for an active claim."""
        from src.infrastructure.adapters.secondary.persistence.models import (
            HITLRequest as HITLRequestRecord,
        )
        from src.infrastructure.agent.hitl.utils import merge_processing_lease_metadata

        result = await self._session.execute(
            refresh_select_statement(self._refresh_statement(
                select(HITLRequestRecord).where(
                    HITLRequestRecord.id == request_id,
                    HITLRequestRecord.status == HITLRequestStatus.PROCESSING.value,
                )
            ))
        )
        db_record = result.scalar_one_or_none()
        if db_record is None:
            return False
        current_owner_expr = getattr(db_record, "response_metadata", None)
        current_owner = None
        if isinstance(current_owner_expr, dict):
            owner_value = current_owner_expr.get("processing_owner")
            current_owner = owner_value if isinstance(owner_value, str) and owner_value else None
        if lease_owner is not None and current_owner not in {None, lease_owner}:
            return False

        db_record.response_metadata = merge_processing_lease_metadata(
            db_record.response_metadata,
            lease_time=datetime.now(UTC),
            lease_owner=lease_owner,
        )
        await self._session.flush()
        return True

    async def revert_to_answered(
        self,
        request_id: str,
        *,
        lease_before: datetime | None = None,
        lease_owner: str | None = None,
    ) -> HITLRequest | None:
        """Revert a processing HITL request back to answered so recovery can retry it."""
        from src.infrastructure.adapters.secondary.persistence.models import (
            HITLRequest as HITLRequestRecord,
        )
        from src.infrastructure.agent.hitl.utils import clear_processing_lease_metadata

        conditions: list[Any] = [
            HITLRequestRecord.id == request_id,
            HITLRequestRecord.status == HITLRequestStatus.PROCESSING.value,
        ]
        owner_expr = HITLRequestRecord.response_metadata["processing_owner"].as_string()
        if lease_owner is not None:
            conditions.append(
                or_(
                    HITLRequestRecord.response_metadata.is_(None),
                    owner_expr.is_(None),
                    owner_expr == lease_owner,
                )
            )
        if lease_before is not None:
            lease_before_iso = lease_before.astimezone(UTC).isoformat()
            heartbeat_expr = HITLRequestRecord.response_metadata[
                "processing_heartbeat_at"
            ].as_string()
            started_expr = HITLRequestRecord.response_metadata["processing_started_at"].as_string()
            lease_expr = func.coalesce(heartbeat_expr, started_expr)
            conditions.append(
                or_(
                    HITLRequestRecord.response_metadata.is_(None),
                    lease_expr.is_(None),
                    lease_expr < lease_before_iso,
                )
            )

        result = await self._session.execute(
            refresh_select_statement(self._refresh_statement(
                update(HITLRequestRecord)
                .where(*conditions)
                .values(status=HITLRequestStatus.ANSWERED.value)
                .returning(HITLRequestRecord)
            ))
        )

        db_record = result.scalar_one_or_none()
        if db_record:
            cleared_metadata = clear_processing_lease_metadata(
                getattr(db_record, "response_metadata", None)
            )
            await self._session.execute(
                refresh_select_statement(self._refresh_statement(
                    update(HITLRequestRecord)
                    .where(HITLRequestRecord.id == request_id)
                    .values(response_metadata=cleared_metadata)
                ))
            )
            logger.info("Reverted HITL request to answered: %s", request_id)
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
            refresh_select_statement(self._refresh_statement(
                select(HITLRequestRecord)
                .where(
                    HITLRequestRecord.status == HITLRequestStatus.ANSWERED.value,
                )
                .order_by(HITLRequestRecord.answered_at.asc())
                .limit(limit)
            ))
        )

        requests = [self._to_domain(r) for r in result.scalars().all()]
        if requests:
            logger.info(f"Found {len(requests)} unprocessed answered HITL requests for recovery")
        return requests

    async def get_stale_processing_requests(
        self,
        *,
        before: datetime,
        limit: int = 100,
    ) -> list[HITLRequest]:
        """Get PROCESSING requests whose claim age is old enough to recover safely."""
        from src.infrastructure.adapters.secondary.persistence.models import (
            HITLRequest as HITLRequestRecord,
        )
        from src.infrastructure.agent.hitl.utils import is_processing_lease_stale

        result = await self._session.execute(
            refresh_select_statement(self._refresh_statement(
                select(HITLRequestRecord)
                .where(
                    HITLRequestRecord.status == HITLRequestStatus.PROCESSING.value,
                )
                .order_by(HITLRequestRecord.answered_at.asc())
                .limit(limit)
            ))
        )

        requests = [
            self._to_domain(r)
            for r in result.scalars().all()
            if is_processing_lease_stale(self._to_domain(r), before=before)
        ]
        if requests:
            logger.info("Found %d stale processing HITL requests for recovery", len(requests))
        return requests

    async def mark_expired_requests(self, before: datetime) -> int:
        """Mark all expired pending requests as timed out."""
        from src.infrastructure.adapters.secondary.persistence.models import (
            HITLRequest as HITLRequestRecord,
        )

        result = await self._session.execute(
            refresh_select_statement(self._refresh_statement(
                update(HITLRequestRecord)
                .where(
                    HITLRequestRecord.status == HITLRequestStatus.PENDING.value,
                    HITLRequestRecord.expires_at < before,
                )
                .values(status=HITLRequestStatus.TIMEOUT.value)
            ))
        )

        count = cast(CursorResult[Any], result).rowcount
        if count > 0:
            logger.info(f"Marked {count} HITL requests as expired")

        return count or 0

    async def delete(self, request_id: str) -> bool:
        """Delete an HITL request."""
        from src.infrastructure.adapters.secondary.persistence.models import (
            HITLRequest as HITLRequestRecord,
        )

        result = await self._session.execute(
            refresh_select_statement(self._refresh_statement(
                select(HITLRequestRecord).where(HITLRequestRecord.id == request_id)
            ))
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
