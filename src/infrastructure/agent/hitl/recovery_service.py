"""
HITL Recovery Service - Recovers unprocessed HITL responses after Worker restart.

When Agent-worker is a stateless service and restarts:
1. In-memory futures are lost
2. HITL requests that were ANSWERED but not processed need recovery
3. This service scans for such requests and re-triggers Agent execution

Usage:
    Called during Worker startup to recover pending work.
"""

import asyncio
import logging
from typing import Optional

from src.domain.model.agent.hitl_request import HITLRequest

logger = logging.getLogger(__name__)


class HITLRecoveryService:
    """
    Service to recover unprocessed HITL responses after Worker restart.

    Recovery flow:
    1. Scan database for ANSWERED requests (user responded, Agent didn't process)
    2. For each request, trigger Agent to continue execution
    3. Agent reads response from database and continues workflow
    """

    def __init__(self):
        self._recovery_in_progress = False
        self._recovered_count = 0

    async def recover_unprocessed_requests(
        self,
        max_concurrent: int = 5,
    ) -> int:
        """
        Scan and recover all unprocessed HITL responses.

        Args:
            max_concurrent: Maximum concurrent recovery operations

        Returns:
            Number of requests recovered
        """
        if self._recovery_in_progress:
            logger.warning("HITL recovery already in progress, skipping")
            return 0

        self._recovery_in_progress = True
        self._recovered_count = 0

        try:
            from src.infrastructure.adapters.secondary.persistence.database import (
                async_session_factory,
            )
            from src.infrastructure.adapters.secondary.persistence.sql_hitl_request_repository import (
                SQLHITLRequestRepository,
            )

            async with async_session_factory() as session:
                repo = SQLHITLRequestRepository(session)
                requests = await repo.get_unprocessed_answered_requests(limit=100)

                if not requests:
                    logger.info("HITL Recovery: No unprocessed requests found")
                    return 0

                logger.info(
                    f"HITL Recovery: Found {len(requests)} unprocessed requests, "
                    f"starting recovery (max_concurrent={max_concurrent})"
                )

                # Use semaphore for concurrency control
                sem = asyncio.Semaphore(max_concurrent)

                async def recover_one(req: HITLRequest):
                    async with sem:
                        success = await self._recover_single_request(req)
                        if success:
                            self._recovered_count += 1

                # Run recovery for all requests
                await asyncio.gather(
                    *[recover_one(req) for req in requests],
                    return_exceptions=True,
                )

                logger.info(
                    f"HITL Recovery: Completed, recovered {self._recovered_count}/{len(requests)} requests"
                )

                return self._recovered_count

        except Exception as e:
            logger.error(f"HITL Recovery: Error during recovery: {e}", exc_info=True)
            return self._recovered_count
        finally:
            self._recovery_in_progress = False

    async def _recover_single_request(self, request: HITLRequest) -> bool:
        """
        Recover a single HITL request by triggering Agent continuation.

        Args:
            request: The HITL request to recover

        Returns:
            True if recovery was successful
        """
        try:
            logger.info(
                f"HITL Recovery: Recovering request {request.id} "
                f"(type={request.request_type.value}, conversation={request.conversation_id})"
            )

            # Publish the response to Redis Streams
            # The Agent listening for this conversation will pick it up
            await self._publish_recovery_response(request)

            logger.info(f"HITL Recovery: Published recovery for {request.id}")
            return True

        except Exception as e:
            logger.error(
                f"HITL Recovery: Failed to recover {request.id}: {e}",
                exc_info=True,
            )
            return False

    async def _publish_recovery_response(self, request: HITLRequest) -> None:
        """
        Publish the HITL response to Redis Streams for Agent to pick up.

        This mimics what happens when a user responds to HITL,
        but uses the already-stored response from the database.
        """
        # Get the appropriate manager based on request type
        from src.domain.model.agent.hitl_request import HITLRequestType
        from src.infrastructure.agent.hitl.clarification_manager import (
            ClarificationManager,
        )
        from src.infrastructure.agent.hitl.decision_manager import DecisionManager
        from src.infrastructure.agent.hitl.env_var_manager import EnvVarManager

        if request.request_type == HITLRequestType.CLARIFICATION:
            manager = ClarificationManager()
            response_key = "answer"
        elif request.request_type == HITLRequestType.DECISION:
            manager = DecisionManager()
            response_key = "decision"
        elif request.request_type == HITLRequestType.ENV_VAR:
            manager = EnvVarManager()
            response_key = "env_vars"
        else:
            logger.warning(f"Unknown request type: {request.request_type}")
            return

        # Get message bus and publish
        message_bus = await manager._get_message_bus()
        if message_bus and request.response:
            # Parse response for env_var type (stored as JSON string)
            response_value = request.response
            if request.request_type == HITLRequestType.ENV_VAR:
                import json

                try:
                    response_value = json.loads(request.response)
                except (json.JSONDecodeError, TypeError):
                    pass

            await message_bus.publish_response(
                request_id=request.id,
                response_key=response_key,
                response_value=response_value,
            )
            logger.debug(
                f"HITL Recovery: Published to stream for {request.id} (response_key={response_key})"
            )
        else:
            # Fallback to Pub/Sub
            import json

            import redis.asyncio as redis_lib

            from src.configuration.config import get_settings

            settings = get_settings()
            redis_client = redis_lib.from_url(
                settings.redis_url,
                encoding="utf-8",
                decode_responses=True,
            )

            try:
                channel = f"hitl:{request.request_type.value}:{request.id}"
                message = json.dumps(
                    {
                        "request_id": request.id,
                        response_key: request.response,
                    }
                )
                await redis_client.publish(channel, message)
                logger.debug(f"HITL Recovery: Published to Pub/Sub for {request.id}")
            finally:
                await redis_client.aclose()


# Global instance for use in worker startup
_recovery_service: Optional[HITLRecoveryService] = None


def get_hitl_recovery_service() -> HITLRecoveryService:
    """Get the global HITL recovery service instance."""
    global _recovery_service
    if _recovery_service is None:
        _recovery_service = HITLRecoveryService()
    return _recovery_service


async def recover_hitl_on_startup() -> int:
    """
    Convenience function to be called during Worker startup.

    Returns:
        Number of requests recovered
    """
    service = get_hitl_recovery_service()
    return await service.recover_unprocessed_requests()
