"""
HITL Recovery Service - Recovers unprocessed HITL responses after Worker restart.

NOTE: With Temporal-based HITL architecture, this service is largely obsolete.
Temporal Workflows automatically persist and recover state, so HITL requests
that are waiting for user response will resume automatically when the workflow
is replayed.

This service is kept for backward compatibility but performs minimal operations.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


class HITLRecoveryService:
    """
    Service to recover unprocessed HITL responses after Worker restart.

    NOTE: With Temporal-based architecture, most recovery is handled automatically
    by Temporal Workflow replay. This service now only handles edge cases where
    responses were stored in the database but the Temporal Signal wasn't processed.
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

        With Temporal architecture, this mainly marks any orphaned PENDING requests
        as EXPIRED so they don't block future operations.

        Args:
            max_concurrent: Maximum concurrent recovery operations

        Returns:
            Number of requests processed
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
                SqlHITLRequestRepository,
            )

            async with async_session_factory() as session:
                repo = SqlHITLRequestRepository(session)

                # Mark any old PENDING requests as expired
                # With Temporal, if a workflow is running, it will create new requests
                now = datetime.now(timezone.utc)
                expired_count = await repo.mark_expired_requests(before=now)
                if expired_count > 0:
                    await session.commit()
                    logger.info(f"HITL Recovery: Marked {expired_count} expired PENDING requests")
                    self._recovered_count = expired_count

                # Check for ANSWERED but unprocessed requests (edge case)
                requests = await repo.get_unprocessed_answered_requests(limit=100)
                if requests:
                    logger.info(
                        f"HITL Recovery: Found {len(requests)} ANSWERED but unprocessed requests. "
                        "These should be handled by Temporal Workflow replay. "
                        "No action needed - Temporal will process them when workflows resume."
                    )

                return self._recovered_count

        except Exception as e:
            logger.error(f"HITL Recovery: Error during recovery: {e}", exc_info=True)
            return self._recovered_count
        finally:
            self._recovery_in_progress = False


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
