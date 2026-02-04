"""
Temporal HITL Service - Implementation of HITLServicePort using Temporal.

This service provides a clean interface for HITL operations, using Temporal
workflows and signals for cross-process communication.

Usage:
    service = TemporalHITLService(
        tenant_id="tenant-123",
        project_id="project-456",
    )

    # Create and wait for response
    response = await service.create_and_wait(request)

    # Or create without waiting
    request_id = await service.create_request(request)
    # ... later ...
    response = await service.wait_for_response(request_id)
"""

import logging
from datetime import datetime
from typing import List, Optional

from src.domain.model.agent.hitl_types import (
    HITL_RESPONSE_SIGNAL,
    ClarificationResponse,
    DecisionResponse,
    HITLRequest,
    HITLResponse,
    HITLStatus,
    HITLType,
)
from src.domain.ports.services.hitl_service_port import (
    HITLCancelledError,
    HITLRequestNotFoundError,
    HITLServiceError,
    HITLServicePort,
    HITLTimeoutError,
)

logger = logging.getLogger(__name__)


class TemporalHITLService(HITLServicePort):
    """
    HITL service implementation using Temporal workflows.

    This service:
    1. Creates HITL requests and persists them
    2. Emits SSE events for frontend
    3. Sends/receives Temporal Signals for responses
    4. Supports recovery after page refresh
    """

    def __init__(
        self,
        tenant_id: str,
        project_id: str,
        conversation_id: Optional[str] = None,
    ):
        """
        Initialize the service.

        Args:
            tenant_id: Tenant ID for multi-tenancy
            project_id: Project ID for workflow lookup
            conversation_id: Optional conversation ID for scoping
        """
        self.tenant_id = tenant_id
        self.project_id = project_id
        self.conversation_id = conversation_id
        self._temporal_client = None

    async def _get_temporal_client(self):
        """Get or create Temporal client."""
        if self._temporal_client is None:
            from temporalio.client import Client

            from src.configuration.temporal_config import get_temporal_settings

            temporal_settings = get_temporal_settings()
            self._temporal_client = await Client.connect(
                temporal_settings.temporal_host,
                namespace=temporal_settings.temporal_namespace,
            )
        return self._temporal_client

    async def _get_workflow_handle(self):
        """Get the workflow handle for this project."""
        from src.infrastructure.adapters.secondary.temporal.workflows.project_agent_workflow import (
            get_project_agent_workflow_id,
        )

        client = await self._get_temporal_client()
        workflow_id = get_project_agent_workflow_id(
            tenant_id=self.tenant_id,
            project_id=self.project_id,
        )
        return client.get_workflow_handle(workflow_id)

    # =========================================================================
    # Request Creation
    # =========================================================================

    async def create_request(self, request: HITLRequest) -> str:
        """
        Create a new HITL request and emit SSE event.

        This method:
        1. Persists the request to database
        2. Emits SSE event to frontend
        3. Registers request with workflow

        Args:
            request: The HITL request to create

        Returns:
            request_id for tracking
        """
        try:
            # Persist to database
            await self._persist_request(request)

            # Emit SSE event
            await self._emit_sse_event(request)

            logger.info(
                f"[TemporalHITLService] Created request {request.request_id} "
                f"(type={request.hitl_type.value})"
            )

            return request.request_id

        except Exception as e:
            logger.error(f"[TemporalHITLService] Failed to create request: {e}")
            raise HITLServiceError(f"Failed to create HITL request: {e}")

    async def _persist_request(self, request: HITLRequest) -> None:
        """Persist HITL request to database."""
        from src.domain.model.agent.hitl_request import (
            HITLRequest as HITLRequestEntity,
        )
        from src.domain.model.agent.hitl_request import (
            HITLRequestType,
        )
        from src.infrastructure.adapters.secondary.persistence.database import (
            async_session_factory,
        )
        from src.infrastructure.adapters.secondary.persistence.sql_hitl_request_repository import (
            SqlHITLRequestRepository,
        )

        # Map HITLType to HITLRequestType
        type_mapping = {
            HITLType.CLARIFICATION: HITLRequestType.CLARIFICATION,
            HITLType.DECISION: HITLRequestType.DECISION,
            HITLType.ENV_VAR: HITLRequestType.ENV_VAR,
        }
        request_type = type_mapping.get(
            request.hitl_type, HITLRequestType.CLARIFICATION
        )

        entity = HITLRequestEntity(
            id=request.request_id,
            request_type=request_type,
            conversation_id=request.conversation_id,
            message_id=request.message_id,
            tenant_id=request.tenant_id or self.tenant_id,
            project_id=request.project_id or self.project_id,
            question=request.question,
            options=[],  # Simplified - options are in type_specific_data
            context=request.type_specific_data,
            metadata={"hitl_type": request.hitl_type.value},
            created_at=request.created_at,
            expires_at=request.expires_at,
        )

        async with async_session_factory() as session:
            repo = SqlHITLRequestRepository(session)
            await repo.create(entity)
            await session.commit()

    async def _emit_sse_event(self, request: HITLRequest) -> None:
        """Emit SSE event for frontend."""
        event_type_mapping = {
            HITLType.CLARIFICATION: "clarification_asked",
            HITLType.DECISION: "decision_asked",
            HITLType.ENV_VAR: "env_var_requested",
            HITLType.PERMISSION: "permission_asked",
        }
        event_type = event_type_mapping.get(
            request.hitl_type, "clarification_asked"
        )

        try:
            from src.infrastructure.adapters.secondary.messaging.redis_unified_event_bus import (
                RedisUnifiedEventBusAdapter,
            )
            from src.infrastructure.adapters.secondary.temporal.agent_worker_state import (
                get_redis_client,
            )

            redis_client = await get_redis_client()
            if redis_client:
                event_bus = RedisUnifiedEventBusAdapter(redis_client)
                await event_bus.publish(
                    conversation_id=request.conversation_id,
                    event_type=event_type,
                    data={
                        "request_id": request.request_id,
                        "timeout_seconds": request.timeout_seconds,
                        **request.type_specific_data,
                    },
                )

        except Exception as e:
            logger.warning(f"[TemporalHITLService] Failed to emit SSE event: {e}")

    # =========================================================================
    # Response Handling
    # =========================================================================

    async def submit_response(self, response: HITLResponse) -> bool:
        """
        Submit a user response to an HITL request.

        This sends a Temporal Signal to the workflow.

        Args:
            response: The user's response

        Returns:
            True if response was accepted
        """
        try:
            # Build signal payload
            payload = {
                "request_id": response.request_id,
                "hitl_type": response.hitl_type.value,
                "response_data": response.to_dict(),
                "user_id": response.user_id,
                "timestamp": response.responded_at.isoformat(),
            }

            # Send signal to workflow
            handle = await self._get_workflow_handle()
            await handle.signal(HITL_RESPONSE_SIGNAL, payload)

            # Update database
            await self._update_request_response(response)

            logger.info(
                f"[TemporalHITLService] Submitted response for {response.request_id}"
            )
            return True

        except Exception as e:
            logger.error(f"[TemporalHITLService] Failed to submit response: {e}")
            raise HITLServiceError(f"Failed to submit response: {e}")

    async def _update_request_response(self, response: HITLResponse) -> None:
        """Update database with response."""
        from src.infrastructure.adapters.secondary.persistence.database import (
            async_session_factory,
        )
        from src.infrastructure.adapters.secondary.persistence.sql_hitl_request_repository import (
            SqlHITLRequestRepository,
        )

        async with async_session_factory() as session:
            repo = SqlHITLRequestRepository(session)
            response_str = str(response.response_value)
            await repo.update_response(response.request_id, response_str)
            await repo.mark_completed(response.request_id)
            await session.commit()

    async def wait_for_response(
        self,
        request_id: str,
        timeout_seconds: Optional[float] = None,
    ) -> HITLResponse:
        """
        Wait for user response to an HITL request.

        This queries the workflow for the response.

        Args:
            request_id: The request to wait for
            timeout_seconds: Override default timeout

        Returns:
            The user's response

        Raises:
            HITLTimeoutError: If request times out
            HITLCancelledError: If request is cancelled
            HITLRequestNotFoundError: If request doesn't exist
        """
        import asyncio

        timeout = timeout_seconds or 300.0

        try:
            # For external callers, poll the database
            start_time = datetime.utcnow()
            poll_interval = 1.0

            while True:
                # Check if response exists in database
                response = await self._get_response_from_db(request_id)
                if response:
                    return response

                # Check timeout
                elapsed = (datetime.utcnow() - start_time).total_seconds()
                if elapsed >= timeout:
                    raise HITLTimeoutError(request_id, timeout)

                # Wait before next poll
                await asyncio.sleep(poll_interval)
                # Exponential backoff up to 5 seconds
                poll_interval = min(poll_interval * 1.5, 5.0)

        except HITLTimeoutError:
            raise
        except Exception as e:
            logger.error(f"[TemporalHITLService] Error waiting for response: {e}")
            raise HITLServiceError(f"Error waiting for response: {e}")

    async def _get_response_from_db(
        self, request_id: str
    ) -> Optional[HITLResponse]:
        """Get response from database if completed."""
        from src.domain.model.agent.hitl_request import HITLRequestStatus
        from src.infrastructure.adapters.secondary.persistence.database import (
            async_session_factory,
        )
        from src.infrastructure.adapters.secondary.persistence.sql_hitl_request_repository import (
            SqlHITLRequestRepository,
        )

        async with async_session_factory() as session:
            repo = SqlHITLRequestRepository(session)
            request = await repo.get_by_id(request_id)

            if not request:
                raise HITLRequestNotFoundError(request_id)

            if request.status == HITLRequestStatus.CANCELLED:
                raise HITLCancelledError(request_id)

            if request.status == HITLRequestStatus.COMPLETED and request.response:
                # Convert to HITLResponse
                hitl_type = HITLType(
                    request.metadata.get("hitl_type", "clarification")
                )

                return HITLResponse(
                    request_id=request_id,
                    hitl_type=hitl_type,
                    clarification_response=(
                        ClarificationResponse(answer=request.response)
                        if hitl_type == HITLType.CLARIFICATION
                        else None
                    ),
                    decision_response=(
                        DecisionResponse(decision=request.response)
                        if hitl_type == HITLType.DECISION
                        else None
                    ),
                    responded_at=request.answered_at or datetime.utcnow(),
                )

            return None

    # =========================================================================
    # Request Management
    # =========================================================================

    async def get_pending_requests(
        self,
        conversation_id: str,
    ) -> List[HITLRequest]:
        """
        Get all pending HITL requests for a conversation.

        Args:
            conversation_id: The conversation ID

        Returns:
            List of pending requests
        """
        from src.infrastructure.adapters.secondary.persistence.database import (
            async_session_factory,
        )
        from src.infrastructure.adapters.secondary.persistence.sql_hitl_request_repository import (
            SqlHITLRequestRepository,
        )

        async with async_session_factory() as session:
            repo = SqlHITLRequestRepository(session)
            pending = await repo.get_pending_by_conversation(
                conversation_id=conversation_id,
                tenant_id=self.tenant_id,
                project_id=self.project_id,
                exclude_expired=True,
            )

            return [self._entity_to_request(r) for r in pending]

    async def get_request(
        self,
        request_id: str,
    ) -> Optional[HITLRequest]:
        """
        Get an HITL request by ID.

        Args:
            request_id: The request ID

        Returns:
            The request, or None if not found
        """
        from src.infrastructure.adapters.secondary.persistence.database import (
            async_session_factory,
        )
        from src.infrastructure.adapters.secondary.persistence.sql_hitl_request_repository import (
            SqlHITLRequestRepository,
        )

        async with async_session_factory() as session:
            repo = SqlHITLRequestRepository(session)
            entity = await repo.get_by_id(request_id)

            if entity:
                return self._entity_to_request(entity)
            return None

    async def cancel_request(
        self,
        request_id: str,
        reason: Optional[str] = None,
    ) -> bool:
        """
        Cancel a pending HITL request.

        Args:
            request_id: The request to cancel
            reason: Optional cancellation reason

        Returns:
            True if request was cancelled
        """
        try:
            # Send cancel signal to workflow
            handle = await self._get_workflow_handle()
            await handle.signal("cancel_hitl_request", request_id, reason)

            # Update database
            from src.infrastructure.adapters.secondary.persistence.database import (
                async_session_factory,
            )
            from src.infrastructure.adapters.secondary.persistence.sql_hitl_request_repository import (
                SqlHITLRequestRepository,
            )

            async with async_session_factory() as session:
                repo = SqlHITLRequestRepository(session)
                result = await repo.mark_cancelled(request_id, reason)
                await session.commit()
                return result

        except Exception as e:
            logger.error(f"[TemporalHITLService] Failed to cancel request: {e}")
            return False

    def _entity_to_request(self, entity) -> HITLRequest:
        """Convert database entity to HITLRequest."""
        hitl_type = HITLType(entity.metadata.get("hitl_type", "clarification"))

        return HITLRequest(
            request_id=entity.id,
            hitl_type=hitl_type,
            conversation_id=entity.conversation_id,
            message_id=entity.message_id,
            status=HITLStatus(entity.status.value),
            timeout_seconds=300.0,  # Default
            created_at=entity.created_at,
            expires_at=entity.expires_at,
            tenant_id=entity.tenant_id,
            project_id=entity.project_id,
        )


# =============================================================================
# Factory Function
# =============================================================================


def create_temporal_hitl_service(
    tenant_id: str,
    project_id: str,
    conversation_id: Optional[str] = None,
) -> TemporalHITLService:
    """
    Create a TemporalHITLService instance.

    Args:
        tenant_id: Tenant ID
        project_id: Project ID
        conversation_id: Optional conversation ID

    Returns:
        Configured service instance
    """
    return TemporalHITLService(
        tenant_id=tenant_id,
        project_id=project_id,
        conversation_id=conversation_id,
    )
