"""Durable cloud ArtifactContentContractV2 orchestration."""

import asyncio
import hashlib
import logging
import os
import secrets
import tempfile
from collections.abc import AsyncIterator, Awaitable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from src.application.services.artifact_content_contract import (
    EDITABLE_ARTIFACT_MIME_TYPES,
    ArtifactContentContract,
    ArtifactContentHashMismatchError,
    ArtifactContentIdempotencyConflictError,
    ArtifactContentIntegrityError,
    ArtifactContentNotEditableError,
    ArtifactContentRevisionConflictError,
    ArtifactContentSaveCommand,
    ArtifactContentSaveReceipt,
    artifact_content_hash,
    artifact_save_request_hash,
    normalize_mime_type,
    validate_artifact_content_command,
)
from src.domain.ports.repositories.artifact_content_authority_repository import (
    ArtifactContentAuthorityRecord,
    ArtifactContentAuthorityRepositoryPort,
    ArtifactContentScope,
)
from src.domain.ports.services.storage_service_port import (
    StorageObjectIntegrityError,
    StorageObjectMetadata,
    StorageObjectTooLargeError,
    StorageServicePort,
)

logger = logging.getLogger(__name__)

MAX_EDITABLE_ARTIFACT_BYTES = 1_048_576
MAX_ARTIFACT_PREVIEW_BYTES = 25 * 1_048_576
MAX_ARTIFACT_DOWNLOAD_BYTES = 50 * 1_048_576


async def _run_shielded_to_completion(
    operation: Awaitable[None],
) -> asyncio.CancelledError | None:
    """Finish one cleanup operation while preserving caller cancellation."""
    task = asyncio.ensure_future(operation)
    caller_cancellation: asyncio.CancelledError | None = None
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError as exc:
            if task.cancelled():
                raise
            caller_cancellation = caller_cancellation or exc
    if task.cancelled():
        raise asyncio.CancelledError
    error = task.exception()
    if error is not None:
        raise error
    return caller_cancellation


class ArtifactContentNotReadyError(Exception):
    """Raised when a scoped Artifact is not in the ready state."""

    reason_code = "artifact_content_not_ready"


class ArtifactContentTooLargeError(Exception):
    """Raised before an object exceeds a bounded Artifact operation."""

    reason_code = "artifact_content_size_limit"

    def __init__(self, *, actual_bytes: int, max_bytes: int) -> None:
        super().__init__(self.reason_code)
        self.actual_bytes = actual_bytes
        self.max_bytes = max_bytes


@dataclass(frozen=True)
class ArtifactContentBytes:
    """Authenticated bytes and MIME from the durable metadata pointer."""

    scope: ArtifactContentScope
    mime_type: str
    revision: int
    content_hash: str
    content: bytes


@dataclass(frozen=True)
class ArtifactContentDownload:
    """Hash-verified, disk-backed download that never buffers the object in memory."""

    scope: ArtifactContentScope
    mime_type: str
    revision: int
    content_hash: str
    size_bytes: int
    staged_path: Path

    async def iter_chunks(self, *, chunk_size: int = 64 * 1024) -> AsyncIterator[bytes]:
        """Yield staged bytes and remove the private temporary file on completion."""
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        try:
            staged = await asyncio.to_thread(self.staged_path.open, "rb")
            try:
                while chunk := await asyncio.to_thread(staged.read, chunk_size):
                    yield chunk
            finally:
                await asyncio.to_thread(staged.close)
        finally:
            await self.discard()

    async def discard(self) -> None:
        """Idempotently remove the private staged file."""
        await asyncio.to_thread(self.staged_path.unlink, missing_ok=True)


@dataclass(frozen=True)
class ArtifactContentSaveOutcome:
    """Save receipt plus the object that remains provisional until DB commit."""

    scope: ArtifactContentScope
    receipt: ArtifactContentSaveReceipt
    uploaded_object_key: str | None
    idempotency_key: str
    request_hash: str


class ArtifactContentOrphanRecorder(Protocol):
    """Fresh-transaction persistence seam for failed immediate orphan cleanup."""

    async def __call__(
        self,
        outcome: ArtifactContentSaveOutcome,
        *,
        reason_code: str,
        last_error_code: str,
    ) -> None:
        """Persist one retryable orphan without reusing the save transaction."""


class ArtifactContentAuthorityService:
    """Coordinate SQL fencing with immutable object-version writes."""

    def __init__(
        self,
        *,
        repository: ArtifactContentAuthorityRepositoryPort,
        storage_service: StorageServicePort,
        bucket_prefix: str = "artifacts",
        orphan_recorder: ArtifactContentOrphanRecorder | None = None,
    ) -> None:
        super().__init__()
        self._repository = repository
        self._storage = storage_service
        self._bucket_prefix = bucket_prefix
        self._orphan_recorder = orphan_recorder

    async def resolve_scope(self, artifact_id: str) -> ArtifactContentScope | None:
        """Resolve only a structurally consistent tenant/project/conversation scope."""
        return await self._repository.resolve_scope(artifact_id)

    async def get_bytes(
        self,
        scope: ArtifactContentScope,
        *,
        max_bytes: int = MAX_ARTIFACT_DOWNLOAD_BYTES,
    ) -> ArtifactContentBytes | None:
        """Read bounded bytes and verify the durable revision/hash authority."""
        for _attempt in range(2):
            authority = await self._repository.get_authority(scope)
            if authority is None:
                return None
            self._require_ready(authority)
            content = await self._read_bounded_object(authority, max_bytes=max_bytes)
            computed_hash = artifact_content_hash(content)
            if authority.content_hash is None:
                initialized = await self._repository.initialize_content_hash(
                    scope,
                    expected_revision=authority.revision,
                    expected_object_key=authority.object_key,
                    content_hash=computed_hash,
                )
                if (
                    initialized is None
                    or initialized.revision != authority.revision
                    or initialized.object_key != authority.object_key
                ):
                    continue
                authority = initialized
            if authority.content_hash != computed_hash:
                raise ArtifactContentIntegrityError
            return ArtifactContentBytes(
                scope=scope,
                mime_type=normalize_mime_type(authority.mime_type),
                revision=authority.revision,
                content_hash=computed_hash,
                content=content,
            )
        raise ArtifactContentIntegrityError

    async def stage_download(
        self,
        scope: ArtifactContentScope,
        *,
        max_bytes: int = MAX_ARTIFACT_DOWNLOAD_BYTES,
    ) -> ArtifactContentDownload | None:
        """Hash-verify a bounded object into a private disk-backed download."""
        for _attempt in range(2):
            authority = await self._repository.get_authority(scope)
            if authority is None:
                return None
            self._require_ready(authority)
            _ = await self._require_object_metadata(authority, max_bytes=max_bytes)
            staged_path, computed_hash = await self._stage_object(
                authority,
                max_bytes=max_bytes,
            )
            if authority.content_hash is None:
                initialized = await self._repository.initialize_content_hash(
                    scope,
                    expected_revision=authority.revision,
                    expected_object_key=authority.object_key,
                    content_hash=computed_hash,
                )
                if (
                    initialized is None
                    or initialized.revision != authority.revision
                    or initialized.object_key != authority.object_key
                ):
                    await self._discard_staged_path(staged_path)
                    continue
                authority = initialized
            if authority.content_hash != computed_hash:
                await self._discard_staged_path(staged_path)
                raise ArtifactContentIntegrityError
            return ArtifactContentDownload(
                scope=scope,
                mime_type=normalize_mime_type(authority.mime_type),
                revision=authority.revision,
                content_hash=computed_hash,
                size_bytes=authority.size_bytes,
                staged_path=staged_path,
            )
        raise ArtifactContentIntegrityError

    async def get_content(self, scope: ArtifactContentScope) -> ArtifactContentContract | None:
        """Return editable UTF-8 content and initialize legacy hashes durably."""
        content_bytes = await self.get_bytes(scope, max_bytes=MAX_EDITABLE_ARTIFACT_BYTES)
        if content_bytes is None:
            return None
        mime_type = self._require_editable_mime(content_bytes.mime_type)
        try:
            content = content_bytes.content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ArtifactContentNotEditableError from exc
        return ArtifactContentContract(
            contract_version=2,
            artifact_id=scope.artifact_id,
            revision=content_bytes.revision,
            content_hash=content_bytes.content_hash,
            mime_type=mime_type,
            content=content,
        )

    async def save_content(
        self,
        scope: ArtifactContentScope,
        command: ArtifactContentSaveCommand,
    ) -> ArtifactContentSaveOutcome | None:
        """Conditionally publish one immutable object version and fenced DB pointer."""
        validate_artifact_content_command(command)
        content_bytes = command.content.encode("utf-8")
        self._require_size_within_limit(len(content_bytes), MAX_EDITABLE_ARTIFACT_BYTES)
        if artifact_content_hash(content_bytes) != command.content_hash:
            raise ArtifactContentHashMismatchError

        authority = await self._repository.get_authority(scope, for_update=True)
        if authority is None:
            return None
        self._require_ready(authority)
        mime_type = self._require_editable(authority)
        authority = await self._ensure_authority_hash(scope, authority)
        request_hash = artifact_save_request_hash(scope.artifact_id, command)
        existing = await self._repository.get_receipt(scope, command.idempotency_key)
        if existing is not None:
            if existing.request_hash != request_hash:
                raise ArtifactContentIdempotencyConflictError(
                    server_revision=authority.revision,
                    server_content_hash=self._require_content_hash(authority),
                )
            return ArtifactContentSaveOutcome(
                scope=scope,
                receipt=ArtifactContentSaveReceipt(
                    artifact_id=scope.artifact_id,
                    revision=existing.resulting_revision,
                    content_hash=existing.content_hash,
                    duplicate=True,
                ),
                uploaded_object_key=None,
                idempotency_key=command.idempotency_key,
                request_hash=request_hash,
            )
        if command.expected_revision != authority.revision:
            raise ArtifactContentRevisionConflictError(
                server_revision=authority.revision,
                server_content_hash=self._require_content_hash(authority),
            )

        next_revision = authority.revision + 1
        version_key = self._versioned_object_key(
            scope=scope,
            revision=next_revision,
            content_hash=command.content_hash,
        )
        outcome = ArtifactContentSaveOutcome(
            scope=scope,
            receipt=ArtifactContentSaveReceipt(
                artifact_id=scope.artifact_id,
                revision=next_revision,
                content_hash=command.content_hash,
                duplicate=False,
            ),
            uploaded_object_key=version_key,
            idempotency_key=command.idempotency_key,
            request_hash=request_hash,
        )
        await self._upload_version(
            content_bytes=content_bytes,
            mime_type=mime_type,
            outcome=outcome,
        )
        try:
            advanced = await self._repository.advance_pointer(
                scope,
                expected_revision=command.expected_revision,
                idempotency_key=command.idempotency_key,
                request_hash=request_hash,
                resulting_revision=next_revision,
                content_hash=command.content_hash,
                object_key=version_key,
                size_bytes=len(content_bytes),
            )
        except asyncio.CancelledError:
            await self._record_orphan_candidate(
                outcome,
                reason_code="advance_pointer_cancelled",
                last_error_code="operation_cancelled",
            )
            raise
        except Exception:
            await self._discard_orphan(outcome)
            raise
        if not advanced:
            await self._discard_orphan(outcome)
            current = await self._repository.get_authority(scope)
            if current is None:
                return None
            raise ArtifactContentRevisionConflictError(
                server_revision=current.revision,
                server_content_hash=self._require_content_hash(current),
            )
        return outcome

    async def _upload_version(
        self,
        *,
        content_bytes: bytes,
        mime_type: str,
        outcome: ArtifactContentSaveOutcome,
    ) -> None:
        object_key = outcome.uploaded_object_key
        if object_key is None:
            raise RuntimeError("Artifact version upload requires an object key")
        try:
            _ = await self._storage.upload_file(
                file_content=content_bytes,
                object_key=object_key,
                content_type=mime_type,
                metadata={
                    "artifact_id": outcome.scope.artifact_id,
                    "project_id": outcome.scope.project_id,
                    "tenant_id": outcome.scope.tenant_id,
                    "content_revision": str(outcome.receipt.revision),
                    "content_hash": outcome.receipt.content_hash,
                },
            )
        except asyncio.CancelledError as cancellation:
            delayed_cancellation = await _run_shielded_to_completion(self._discard_orphan(outcome))
            if delayed_cancellation is not None:
                raise delayed_cancellation from cancellation
            raise
        except Exception:
            await self._discard_orphan(outcome)
            raise

    async def _ensure_authority_hash(
        self,
        scope: ArtifactContentScope,
        authority: ArtifactContentAuthorityRecord,
    ) -> ArtifactContentAuthorityRecord:
        current_bytes = await self._read_bounded_object(
            authority,
            max_bytes=MAX_EDITABLE_ARTIFACT_BYTES,
        )
        computed_hash = artifact_content_hash(current_bytes)
        if authority.content_hash is None:
            initialized = await self._repository.initialize_content_hash(
                scope,
                expected_revision=authority.revision,
                expected_object_key=authority.object_key,
                content_hash=computed_hash,
            )
            if initialized is None:
                raise ArtifactContentIntegrityError
            authority = initialized
        if authority.content_hash != computed_hash:
            raise ArtifactContentIntegrityError
        return authority

    async def _read_bounded_object(
        self,
        authority: ArtifactContentAuthorityRecord,
        *,
        max_bytes: int,
    ) -> bytes:
        _ = await self._require_object_metadata(authority, max_bytes=max_bytes)
        try:
            content = await self._storage.get_file_bounded(
                authority.object_key,
                max_bytes=max_bytes,
            )
        except StorageObjectTooLargeError as exc:
            raise ArtifactContentTooLargeError(
                actual_bytes=exc.actual_bytes,
                max_bytes=exc.max_bytes,
            ) from exc
        except StorageObjectIntegrityError as exc:
            raise ArtifactContentIntegrityError from exc
        if content is None:
            raise ArtifactContentIntegrityError
        self._require_size_within_limit(len(content), max_bytes)
        if len(content) != authority.size_bytes:
            raise ArtifactContentIntegrityError
        return content

    async def _require_object_metadata(
        self,
        authority: ArtifactContentAuthorityRecord,
        *,
        max_bytes: int,
    ) -> StorageObjectMetadata:
        self._require_size_within_limit(authority.size_bytes, max_bytes)
        try:
            metadata = await self._storage.get_file_metadata(authority.object_key)
        except StorageObjectIntegrityError as exc:
            raise ArtifactContentIntegrityError from exc
        if metadata is None:
            raise ArtifactContentIntegrityError
        self._require_size_within_limit(metadata.size_bytes, max_bytes)
        if metadata.size_bytes != authority.size_bytes:
            raise ArtifactContentIntegrityError
        return metadata

    async def _stage_object(
        self,
        authority: ArtifactContentAuthorityRecord,
        *,
        max_bytes: int,
    ) -> tuple[Path, str]:
        descriptor, raw_path = tempfile.mkstemp(prefix="memstack-artifact-", suffix=".download")
        os.close(descriptor)
        staged_path = Path(raw_path)
        digest = hashlib.sha256()
        total = 0
        try:
            staged = await asyncio.to_thread(staged_path.open, "wb")
            try:
                async for chunk in self._storage.stream_file(
                    authority.object_key,
                    max_bytes=max_bytes,
                ):
                    total += len(chunk)
                    self._require_size_within_limit(total, max_bytes)
                    digest.update(chunk)
                    _ = await asyncio.to_thread(staged.write, chunk)
            finally:
                await asyncio.to_thread(staged.close)
            if total != authority.size_bytes:
                raise ArtifactContentIntegrityError
        except StorageObjectTooLargeError as exc:
            await self._discard_staged_path(staged_path)
            raise ArtifactContentTooLargeError(
                actual_bytes=exc.actual_bytes,
                max_bytes=exc.max_bytes,
            ) from exc
        except StorageObjectIntegrityError as exc:
            await self._discard_staged_path(staged_path)
            raise ArtifactContentIntegrityError from exc
        except Exception:
            await self._discard_staged_path(staged_path)
            raise
        return staged_path, f"sha256:{digest.hexdigest()}"

    @staticmethod
    async def _discard_staged_path(staged_path: Path) -> None:
        await asyncio.to_thread(staged_path.unlink, missing_ok=True)

    async def _discard_orphan(self, outcome: ArtifactContentSaveOutcome) -> None:
        object_key = outcome.uploaded_object_key
        if object_key is None:
            raise RuntimeError("Artifact orphan cleanup requires an object key")
        try:
            deleted = await self._storage.delete_file(object_key)
            if not deleted:
                logger.warning(
                    "Artifact content orphan was not present during cleanup: %s",
                    object_key,
                )
        except asyncio.CancelledError:
            logger.warning(
                "Artifact content orphan cleanup was cancelled: %s",
                object_key,
            )
            await self._record_orphan_candidate(
                outcome,
                reason_code="immediate_delete_cancelled",
                last_error_code="storage_delete_cancelled",
            )
            raise
        except Exception:
            logger.warning(
                "Failed to remove uncommitted Artifact content object: %s",
                object_key,
                exc_info=True,
            )
            await self._record_orphan_candidate(
                outcome,
                reason_code="immediate_delete_failed",
                last_error_code="storage_delete_failed",
            )

    async def _record_orphan_candidate(
        self,
        outcome: ArtifactContentSaveOutcome,
        *,
        reason_code: str,
        last_error_code: str,
    ) -> None:
        object_key = outcome.uploaded_object_key
        if object_key is None:
            raise RuntimeError("Artifact orphan recording requires an object key")
        if self._orphan_recorder is None:
            logger.error(
                "Artifact content orphan candidate has no durable recorder: %s",
                object_key,
            )
            return
        try:
            delayed_cancellation = await _run_shielded_to_completion(
                self._orphan_recorder(
                    outcome,
                    reason_code=reason_code,
                    last_error_code=last_error_code,
                )
            )
        except asyncio.CancelledError:
            logger.error(
                "Artifact content orphan recorder was cancelled: %s",
                object_key,
                exc_info=True,
            )
            raise
        except Exception:
            logger.error(
                "Failed to persist uncommitted Artifact content object: %s",
                object_key,
                exc_info=True,
            )
            return
        if delayed_cancellation is not None:
            raise delayed_cancellation

    def _versioned_object_key(
        self,
        *,
        scope: ArtifactContentScope,
        revision: int,
        content_hash: str,
    ) -> str:
        digest = content_hash.removeprefix("sha256:")
        nonce = secrets.token_hex(16)
        return (
            f"{self._bucket_prefix}/{scope.tenant_id}/{scope.project_id}/{scope.artifact_id}/"
            f"versions/r{revision}-{digest}-{nonce}"
        )

    @staticmethod
    def _require_ready(authority: ArtifactContentAuthorityRecord) -> None:
        if authority.status != "ready":
            raise ArtifactContentNotReadyError

    @staticmethod
    def _require_editable(authority: ArtifactContentAuthorityRecord) -> str:
        return ArtifactContentAuthorityService._require_editable_mime(authority.mime_type)

    @staticmethod
    def _require_editable_mime(value: str) -> str:
        mime_type = normalize_mime_type(value)
        if mime_type not in EDITABLE_ARTIFACT_MIME_TYPES:
            raise ArtifactContentNotEditableError
        return mime_type

    @staticmethod
    def _require_content_hash(authority: ArtifactContentAuthorityRecord) -> str:
        if authority.content_hash is None:
            raise ArtifactContentIntegrityError
        return authority.content_hash

    @staticmethod
    def _require_size_within_limit(actual_bytes: object, max_bytes: object) -> None:
        if isinstance(actual_bytes, bool) or not isinstance(actual_bytes, int) or actual_bytes < 0:
            raise ArtifactContentIntegrityError
        if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 0:
            raise ArtifactContentIntegrityError
        if actual_bytes > max_bytes:
            raise ArtifactContentTooLargeError(
                actual_bytes=actual_bytes,
                max_bytes=max_bytes,
            )
