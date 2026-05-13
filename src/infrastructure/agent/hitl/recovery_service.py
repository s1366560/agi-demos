"""
HITL Recovery Service - Recovers unprocessed HITL responses after Worker restart.

With Ray/Redis-based HITL, state recovery is primarily handled by Redis Streams
and Postgres snapshots. This service performs minimal maintenance, such as
expiring stale pending requests.
"""

import asyncio
import contextlib
import logging
import uuid
from datetime import UTC, datetime, timedelta

from src.domain.model.agent.hitl_request import HITLRequest, HITLRequestStatus

logger = logging.getLogger(__name__)


class HITLRecoveryService:
    """
    Service to recover unprocessed HITL responses after Worker restart.

    NOTE: With Ray/Redis-based architecture, most recovery is handled by
    stream replay and snapshot restore. This service handles edge cases where
    requests remain pending or were answered but not resumed.
    """

    STALE_PROCESSING_AGE_SECONDS = 300

    def __init__(self) -> None:
        self._recovery_in_progress = False
        self._recovered_count = 0
        self._lease_owner = f"startup-recovery:{uuid.uuid4()}"

    async def _revert_processing_request(
        self,
        request_id: str,
        *,
        lease_before: datetime | None = None,
        lease_owner: str | None = None,
    ) -> None:
        """Return a claimed request to ANSWERED so recovery can retry it later."""
        from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
        from src.infrastructure.adapters.secondary.persistence.sql_hitl_request_repository import (
            SqlHITLRequestRepository,
        )

        async with async_session_factory() as session:
            repo = SqlHITLRequestRepository(session)
            if lease_before is None:
                reverted_request = await repo.revert_to_answered(
                    request_id,
                    lease_owner=lease_owner,
                )
            else:
                reverted_request = await repo.revert_to_answered(
                    request_id,
                    lease_before=lease_before,
                    lease_owner=lease_owner,
                )
            if reverted_request is not None:
                await session.commit()

    async def _recover_answered_request(self, request: HITLRequest) -> bool:
        """Replay a persisted ANSWERED request when its response remains recoverable."""
        from src.configuration.config import get_settings
        from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
        from src.infrastructure.adapters.secondary.persistence.sql_hitl_request_repository import (
            SqlHITLRequestRepository,
        )
        from src.infrastructure.agent.actor.execution import continue_project_chat
        from src.infrastructure.agent.actor.state.snapshot_repo import load_hitl_snapshot_agent_mode
        from src.infrastructure.agent.core.project_react_agent import (
            ProjectAgentConfig,
            ProjectReActAgent,
        )
        from src.infrastructure.agent.hitl.utils import (
            is_permanent_hitl_resume_error,
            processing_lease_heartbeat,
            restore_persisted_hitl_response,
        )

        request_id = getattr(request, "id", "")
        recovered = False
        try:
            response_data = restore_persisted_hitl_response(request)
        except Exception:
            logger.warning(
                "HITL Recovery: Skipping %s because persisted response payload is unreadable",
                request_id,
                exc_info=True,
            )
            response_data = None
        if response_data is None:
            logger.warning(
                "HITL Recovery: Skipping %s because no recoverable response payload was stored",
                request_id,
            )
        else:
            async with async_session_factory() as session:
                repo = SqlHITLRequestRepository(session)
                claimed_request = await repo.claim_for_processing(
                    request_id,
                    lease_owner=self._lease_owner,
                )
                if claimed_request is None:
                    logger.info(
                        "HITL Recovery: Skipping %s because it is already being processed",
                        request_id,
                    )
                else:
                    await session.commit()

                    settings = get_settings()
                    agent_mode = await load_hitl_snapshot_agent_mode(request_id) or "default"
                    agent = ProjectReActAgent(
                        ProjectAgentConfig(
                            tenant_id=request.tenant_id,
                            project_id=request.project_id,
                            agent_mode=agent_mode,
                            model=None,
                            api_key=None,
                            base_url=None,
                            temperature=0.7,
                            max_tokens=settings.agent_max_tokens,
                            max_steps=settings.agent_max_steps,
                            persistent=False,
                            max_concurrent_chats=10,
                            mcp_tools_ttl_seconds=300,
                            enable_skills=True,
                            enable_subagents=True,
                        )
                    )
                    try:
                        await agent.initialize()
                        async with processing_lease_heartbeat(
                            request_id,
                            lease_owner=self._lease_owner,
                        ):
                            result = await continue_project_chat(
                                agent,
                                request_id,
                                response_data,
                                lease_owner=self._lease_owner,
                                tenant_id=request.tenant_id,
                                project_id=request.project_id,
                                conversation_id=request.conversation_id,
                                message_id=request.message_id,
                            )
                        if result.is_error:
                            if is_permanent_hitl_resume_error(result.error_message):
                                from src.infrastructure.agent.hitl.coordinator import (
                                    complete_hitl_request,
                                )

                                await complete_hitl_request(
                                    request_id,
                                    lease_owner=self._lease_owner,
                                )
                                logger.warning(
                                    "HITL Recovery: Permanently rejected %s: %s",
                                    request_id,
                                    result.error_message,
                                )
                            else:
                                logger.warning(
                                    "HITL Recovery: Failed to replay %s: %s",
                                    request_id,
                                    result.error_message,
                                )
                                await self._revert_processing_request(
                                    request_id,
                                    lease_owner=self._lease_owner,
                                )
                        else:
                            logger.info(
                                "HITL Recovery: Replayed %s successfully (%s events)",
                                request_id,
                                result.event_count,
                            )
                            recovered = True
                    except Exception as e:
                        logger.error(
                            "HITL Recovery: Replay failed for %s: %s",
                            request_id,
                            e,
                            exc_info=True,
                        )
                        await self._revert_processing_request(
                            request_id,
                            lease_owner=self._lease_owner,
                        )
                    finally:
                        with contextlib.suppress(Exception):
                            await agent.stop()

        return recovered

    async def _recover_stale_processing_request(
        self,
        request: HITLRequest,
        *,
        lease_before: datetime,
    ) -> bool:
        """Repair and replay a long-idle PROCESSING request after a crash."""
        from src.infrastructure.agent.hitl.utils import get_processing_owner

        request_id = getattr(request, "id", "")
        await self._revert_processing_request(
            request_id,
            lease_before=lease_before,
            lease_owner=get_processing_owner(request),
        )
        if hasattr(request, "status"):
            request.status = HITLRequestStatus.ANSWERED
        return await self._recover_answered_request(request)

    async def recover_unprocessed_requests(
        self,
        max_concurrent: int = 5,
    ) -> int:
        """
        Scan and recover all unprocessed HITL responses.

        This mainly marks any orphaned PENDING requests as EXPIRED so they don't
        block future operations.

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
                now = datetime.now(UTC)
                expired_count = await repo.mark_expired_requests(before=now)
                if expired_count > 0:
                    await session.commit()
                    logger.info(f"HITL Recovery: Marked {expired_count} expired PENDING requests")
                    self._recovered_count = expired_count

                semaphore = asyncio.Semaphore(max_concurrent)

                # Check for ANSWERED but unprocessed requests (edge case)
                requests = await repo.get_unprocessed_answered_requests(limit=100)
                if requests:
                    logger.info(
                        f"HITL Recovery: Found {len(requests)} ANSWERED but unprocessed requests. "
                        "Replaying recoverable responses from persisted state."
                    )

                    async def _recover_with_limit(request: object) -> bool:
                        async with semaphore:
                            return await self._recover_answered_request(request)

                    replay_results = await asyncio.gather(
                        *(_recover_with_limit(request) for request in requests),
                        return_exceptions=True,
                    )
                    self._recovered_count += sum(
                        1
                        for result in replay_results
                        if isinstance(result, bool) and result
                    )

                stale_processing_before = now - timedelta(seconds=self.STALE_PROCESSING_AGE_SECONDS)
                processing_requests = await repo.get_stale_processing_requests(
                    before=stale_processing_before,
                    limit=100,
                )
                if processing_requests:
                    logger.info(
                        "HITL Recovery: Found %d stale PROCESSING requests. "
                        "Reverting and replaying recoverable responses.",
                        len(processing_requests),
                    )

                    async def _recover_processing_with_limit(request: object) -> bool:
                        async with semaphore:
                            return await self._recover_stale_processing_request(
                                request,
                                lease_before=stale_processing_before,
                            )

                    processing_results = await asyncio.gather(
                        *(
                            _recover_processing_with_limit(request)
                            for request in processing_requests
                        ),
                        return_exceptions=True,
                    )
                    self._recovered_count += sum(
                        1
                        for result in processing_results
                        if isinstance(result, bool) and result
                    )

                return self._recovered_count

        except Exception as e:
            logger.error(f"HITL Recovery: Error during recovery: {e}", exc_info=True)
            return self._recovered_count
        finally:
            self._recovery_in_progress = False


# Global instance for use in worker startup
_recovery_service: HITLRecoveryService | None = None


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
