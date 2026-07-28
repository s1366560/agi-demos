"""Bounded durable worker for provisional Artifact content objects."""

import asyncio
import logging
import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.ports.repositories.artifact_content_authority_repository import (
    ArtifactContentOrphanGcRecord,
)
from src.domain.ports.services.storage_service_port import StorageServicePort
from src.infrastructure.adapters.secondary.persistence.sql_artifact_content_authority import (
    SqlArtifactContentAuthorityRepository,
)

logger = logging.getLogger(__name__)

MAX_ARTIFACT_ORPHAN_GC_BATCH_SIZE = 100
MAX_ARTIFACT_ORPHAN_GC_RETRY_SECONDS = 300


class ArtifactContentOrphanGcWorker:
    """Lease, authority-check, and collect a bounded durable orphan batch."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        storage_service: StorageServicePort,
        owner_id: str | None = None,
        clock: Callable[[], datetime] | None = None,
        batch_size: int = 10,
        lease_seconds: int = 60,
        poll_interval_seconds: float = 5.0,
    ) -> None:
        super().__init__()
        if batch_size < 1 or batch_size > MAX_ARTIFACT_ORPHAN_GC_BATCH_SIZE:
            raise ValueError("invalid Artifact orphan GC batch size")
        if lease_seconds < 1:
            raise ValueError("invalid Artifact orphan GC lease duration")
        if poll_interval_seconds <= 0:
            raise ValueError("invalid Artifact orphan GC poll interval")
        resolved_owner_id = owner_id or f"artifact-gc-{secrets.token_hex(8)}"
        if len(resolved_owner_id) > 64:
            raise ValueError("invalid Artifact orphan GC owner id")

        self._session_factory = session_factory
        self._storage = storage_service
        self._owner_id = resolved_owner_id
        self._clock = clock or (lambda: datetime.now(UTC))
        self._batch_size = batch_size
        self._lease_seconds = lease_seconds
        self._poll_interval_seconds = poll_interval_seconds
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    @property
    def owner_id(self) -> str:
        """Return the stable process-local lease owner."""
        return self._owner_id

    @property
    def is_running(self) -> bool:
        """Return whether the background dispatch loop is active."""
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        """Start background polling without creating duplicate dispatch loops."""
        if self.is_running:
            return
        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(
            self._run(),
            name=f"artifact-content-orphan-gc:{self._owner_id}",
        )

    async def stop(self) -> None:
        """Stop background polling and await the current bounded dispatch."""
        task = self._task
        if task is None:
            return
        self._stop_event.set()
        try:
            await task
        finally:
            self._task = None

    async def run_once(self) -> int:
        """Claim and process at most one configured batch; safe for manual invocation."""
        now = self._utc_now()
        lease_token = secrets.token_hex(16)
        async with self._session_factory() as session:
            repository = SqlArtifactContentAuthorityRepository(session)
            records = await repository.claim_orphan_gc(
                lease_owner=self._owner_id,
                lease_token=lease_token,
                now=now,
                lease_expires_at=now + timedelta(seconds=self._lease_seconds),
                limit=self._batch_size,
            )
            await session.commit()

        for record in records:
            try:
                await self._process_record(record, lease_token=lease_token)
            except Exception:
                logger.warning(
                    "Artifact orphan GC record processing failed; lease will expire",
                    exc_info=True,
                    extra={
                        "event": "artifact_content_orphan_gc.process_failed",
                        "object_key": record.object_key,
                    },
                )
        return len(records)

    async def _process_record(
        self,
        record: ArtifactContentOrphanGcRecord,
        *,
        lease_token: str,
    ) -> None:
        now = self._utc_now()
        status = "retained"
        last_error_code: str | None = None
        next_attempt_at = now

        async with self._session_factory() as session:
            repository = SqlArtifactContentAuthorityRepository(session)
            _ = await repository.get_authority(record.scope, for_update=True)
            referenced = await repository.is_object_key_referenced(
                record.scope,
                record.object_key,
            )
            if not referenced:
                try:
                    deleted = await self._storage.delete_file(record.object_key)
                except Exception:
                    status = "pending"
                    last_error_code = "storage_delete_failed"
                    next_attempt_at = now + timedelta(
                        seconds=self._retry_delay_seconds(record.attempts)
                    )
                else:
                    status = "deleted" if deleted else "missing"

            completed = await repository.complete_orphan_gc_lease(
                record.object_key,
                lease_owner=self._owner_id,
                lease_token=lease_token,
                status=status,
                last_error_code=last_error_code,
                next_attempt_at=next_attempt_at,
            )
            await session.commit()
        if not completed:
            logger.info(
                "Artifact orphan GC completion lost its lease fence",
                extra={
                    "event": "artifact_content_orphan_gc.lease_lost",
                    "object_key": record.object_key,
                },
            )

    async def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                _ = await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning(
                    "Artifact orphan GC dispatch failed",
                    exc_info=True,
                    extra={"event": "artifact_content_orphan_gc.dispatch_failed"},
                )
            try:
                _ = await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self._poll_interval_seconds,
                )
            except TimeoutError:
                continue

    def _utc_now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None:
            return now.replace(tzinfo=UTC)
        return now.astimezone(UTC)

    @staticmethod
    def _retry_delay_seconds(attempts: int) -> int:
        bounded_attempts = max(0, min(attempts, 8))
        return min(1 << bounded_attempts, MAX_ARTIFACT_ORPHAN_GC_RETRY_SECONDS)
