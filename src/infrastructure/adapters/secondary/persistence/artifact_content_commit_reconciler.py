"""Fresh-session reconciliation for ambiguous Artifact content commits."""

import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.application.services.artifact_content_authority_service import (
    ArtifactContentSaveOutcome,
)
from src.domain.ports.repositories.artifact_content_authority_repository import (
    ArtifactContentAuthorityRecord,
    ArtifactContentReceiptRecord,
)
from src.domain.ports.services.storage_service_port import StorageServicePort
from src.infrastructure.adapters.secondary.persistence.sql_artifact_content_authority import (
    SqlArtifactContentAuthorityRepository,
)

logger = logging.getLogger(__name__)


class ArtifactContentCommitReconciler:
    """Inspect primary SQL authority before collecting a provisional object."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        storage_service: StorageServicePort,
    ) -> None:
        super().__init__()
        self._session_factory = session_factory
        self._storage = storage_service

    async def reconcile(self, outcome: ArtifactContentSaveOutcome) -> None:
        """Retain committed/ambiguous objects and collect only proven orphans."""
        object_key = outcome.uploaded_object_key
        if object_key is None:
            return
        try:
            should_delete = await self._inspect_and_stage(outcome)
        except Exception:
            logger.warning(
                "Artifact content commit reconciliation could not confirm authority",
                exc_info=True,
            )
            await self._record_pending_safely(
                outcome,
                reason_code="authority_check_failed",
                last_error_code="authority_check_failed",
            )
            return
        if not should_delete:
            return
        try:
            deleted = await self._storage.delete_file(object_key)
        except Exception:
            logger.warning(
                "Artifact content orphan cleanup failed after durable staging",
                exc_info=True,
            )
            await self._mark_safely(
                object_key,
                status="pending",
                last_error_code="storage_delete_failed",
            )
            return
        await self._mark_safely(
            object_key,
            status="deleted" if deleted else "missing",
        )

    async def _inspect_and_stage(self, outcome: ArtifactContentSaveOutcome) -> bool:
        async with self._session_factory() as session:
            repository = SqlArtifactContentAuthorityRepository(session)
            authority = await repository.get_authority(outcome.scope)
            receipt = await repository.get_receipt(
                outcome.scope,
                outcome.idempotency_key,
            )
            if self._authority_confirms_commit(authority, outcome):
                return False
            if self._receipt_confirms_commit(receipt, outcome):
                return False
            if receipt is not None:
                await self._record_orphan(
                    repository,
                    outcome,
                    reason_code="receipt_mismatch",
                    status="retained",
                )
                await session.commit()
                return False
            if await repository.is_object_key_referenced(
                outcome.scope,
                outcome.uploaded_object_key or "",
            ):
                await self._record_orphan(
                    repository,
                    outcome,
                    reason_code="object_still_referenced",
                    status="retained",
                )
                await session.commit()
                return False
            await self._record_orphan(
                repository,
                outcome,
                reason_code="commit_not_observed",
                status="pending",
            )
            await session.commit()
            return True

    async def _record_pending_safely(
        self,
        outcome: ArtifactContentSaveOutcome,
        *,
        reason_code: str,
        last_error_code: str,
    ) -> None:
        try:
            async with self._session_factory() as session:
                repository = SqlArtifactContentAuthorityRepository(session)
                await self._record_orphan(
                    repository,
                    outcome,
                    reason_code=reason_code,
                    status="pending",
                    last_error_code=last_error_code,
                )
                await session.commit()
        except Exception:
            logger.error(
                "Artifact content orphan candidate could not be persisted; object retained",
                exc_info=True,
            )

    async def _mark_safely(
        self,
        object_key: str,
        *,
        status: str,
        last_error_code: str | None = None,
    ) -> None:
        try:
            async with self._session_factory() as session:
                repository = SqlArtifactContentAuthorityRepository(session)
                await repository.mark_orphan_gc_result(
                    object_key,
                    status=status,
                    last_error_code=last_error_code,
                )
                await session.commit()
        except Exception:
            logger.warning(
                "Artifact content orphan audit update failed; staged record remains retryable",
                exc_info=True,
            )

    @staticmethod
    def _authority_confirms_commit(
        authority: ArtifactContentAuthorityRecord | None,
        outcome: ArtifactContentSaveOutcome,
    ) -> bool:
        return (
            authority is not None
            and authority.object_key == outcome.uploaded_object_key
            and authority.revision == outcome.receipt.revision
            and authority.content_hash == outcome.receipt.content_hash
        )

    @staticmethod
    def _receipt_confirms_commit(
        receipt: ArtifactContentReceiptRecord | None,
        outcome: ArtifactContentSaveOutcome,
    ) -> bool:
        return (
            receipt is not None
            and receipt.request_hash == outcome.request_hash
            and receipt.resulting_revision == outcome.receipt.revision
            and receipt.content_hash == outcome.receipt.content_hash
            and receipt.object_key == outcome.uploaded_object_key
        )

    @staticmethod
    async def _record_orphan(
        repository: SqlArtifactContentAuthorityRepository,
        outcome: ArtifactContentSaveOutcome,
        *,
        reason_code: str,
        status: str,
        last_error_code: str | None = None,
    ) -> None:
        object_key = outcome.uploaded_object_key
        if object_key is None:
            raise RuntimeError("Artifact orphan reconciliation requires an object key")
        await repository.record_orphan_gc(
            scope=outcome.scope,
            object_key=object_key,
            idempotency_key=outcome.idempotency_key,
            request_hash=outcome.request_hash,
            content_revision=outcome.receipt.revision,
            content_hash=outcome.receipt.content_hash,
            reason_code=reason_code,
            status=status,
            last_error_code=last_error_code,
        )
