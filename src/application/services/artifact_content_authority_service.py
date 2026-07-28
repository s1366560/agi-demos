"""Durable cloud ArtifactContentContractV2 orchestration."""

import logging
from dataclasses import dataclass

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
from src.domain.ports.services.storage_service_port import StorageServicePort

logger = logging.getLogger(__name__)


class ArtifactContentNotReadyError(Exception):
    """Raised when a scoped Artifact is not in the ready state."""

    reason_code = "artifact_content_not_ready"


@dataclass(frozen=True)
class ArtifactContentBytes:
    """Authenticated bytes and MIME from the durable metadata pointer."""

    scope: ArtifactContentScope
    mime_type: str
    content: bytes


@dataclass(frozen=True)
class ArtifactContentSaveOutcome:
    """Save receipt plus the object that remains provisional until DB commit."""

    scope: ArtifactContentScope
    receipt: ArtifactContentSaveReceipt
    uploaded_object_key: str | None


class ArtifactContentAuthorityService:
    """Coordinate SQL fencing with immutable object-version writes."""

    def __init__(
        self,
        *,
        repository: ArtifactContentAuthorityRepositoryPort,
        storage_service: StorageServicePort,
        bucket_prefix: str = "artifacts",
    ) -> None:
        super().__init__()
        self._repository = repository
        self._storage = storage_service
        self._bucket_prefix = bucket_prefix

    async def resolve_scope(self, artifact_id: str) -> ArtifactContentScope | None:
        """Resolve only a structurally consistent tenant/project/conversation scope."""
        return await self._repository.resolve_scope(artifact_id)

    async def get_bytes(self, scope: ArtifactContentScope) -> ArtifactContentBytes | None:
        """Read authenticated bytes from the exact durable metadata pointer."""
        authority = await self._repository.get_authority(scope)
        if authority is None:
            return None
        self._require_ready(authority)
        content = await self._storage.get_file(authority.object_key)
        if content is None:
            return None
        return ArtifactContentBytes(
            scope=scope,
            mime_type=normalize_mime_type(authority.mime_type),
            content=content,
        )

    async def get_content(self, scope: ArtifactContentScope) -> ArtifactContentContract | None:
        """Return editable UTF-8 content and initialize legacy hashes durably."""
        for _attempt in range(2):
            authority = await self._repository.get_authority(scope)
            if authority is None:
                return None
            self._require_ready(authority)
            mime_type = self._require_editable(authority)
            content_bytes = await self._storage.get_file(authority.object_key)
            if content_bytes is None:
                return None
            try:
                content = content_bytes.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ArtifactContentNotEditableError from exc
            computed_hash = artifact_content_hash(content_bytes)
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
            return ArtifactContentContract(
                contract_version=2,
                artifact_id=scope.artifact_id,
                revision=authority.revision,
                content_hash=computed_hash,
                mime_type=mime_type,
                content=content,
            )
        raise ArtifactContentIntegrityError

    async def save_content(
        self,
        scope: ArtifactContentScope,
        command: ArtifactContentSaveCommand,
    ) -> ArtifactContentSaveOutcome | None:
        """Conditionally publish one immutable object version and fenced DB pointer."""
        validate_artifact_content_command(command)
        content_bytes = command.content.encode("utf-8")
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
        _ = await self._storage.upload_file(
            file_content=content_bytes,
            object_key=version_key,
            content_type=mime_type,
            metadata={
                "artifact_id": scope.artifact_id,
                "project_id": scope.project_id,
                "tenant_id": scope.tenant_id,
                "content_revision": str(next_revision),
                "content_hash": command.content_hash,
            },
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
        except Exception:
            await self._discard_orphan(version_key)
            raise
        if not advanced:
            await self._discard_orphan(version_key)
            current = await self._repository.get_authority(scope)
            if current is None:
                return None
            raise ArtifactContentRevisionConflictError(
                server_revision=current.revision,
                server_content_hash=self._require_content_hash(current),
            )
        return ArtifactContentSaveOutcome(
            scope=scope,
            receipt=ArtifactContentSaveReceipt(
                artifact_id=scope.artifact_id,
                revision=next_revision,
                content_hash=command.content_hash,
                duplicate=False,
            ),
            uploaded_object_key=version_key,
        )

    async def discard_uncommitted(self, outcome: ArtifactContentSaveOutcome) -> None:
        """Reconcile an ambiguous DB commit before removing its version object."""
        if outcome.uploaded_object_key is None:
            return
        current = await self._repository.get_authority(outcome.scope)
        if (
            current is not None
            and current.object_key == outcome.uploaded_object_key
            and current.revision == outcome.receipt.revision
            and current.content_hash == outcome.receipt.content_hash
        ):
            return
        await self._discard_orphan(outcome.uploaded_object_key)

    async def _ensure_authority_hash(
        self,
        scope: ArtifactContentScope,
        authority: ArtifactContentAuthorityRecord,
    ) -> ArtifactContentAuthorityRecord:
        current_bytes = await self._storage.get_file(authority.object_key)
        if current_bytes is None:
            raise ArtifactContentIntegrityError
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

    async def _discard_orphan(self, object_key: str) -> None:
        try:
            deleted = await self._storage.delete_file(object_key)
            if not deleted:
                logger.warning(
                    "Artifact content orphan was not present during cleanup: %s",
                    object_key,
                )
        except Exception:
            logger.warning(
                "Failed to remove uncommitted Artifact content object: %s",
                object_key,
                exc_info=True,
            )

    def _versioned_object_key(
        self,
        *,
        scope: ArtifactContentScope,
        revision: int,
        content_hash: str,
    ) -> str:
        digest = content_hash.removeprefix("sha256:")
        return (
            f"{self._bucket_prefix}/{scope.tenant_id}/{scope.project_id}/{scope.artifact_id}/"
            f"versions/r{revision}-{digest}"
        )

    @staticmethod
    def _require_ready(authority: ArtifactContentAuthorityRecord) -> None:
        if authority.status != "ready":
            raise ArtifactContentNotReadyError

    @staticmethod
    def _require_editable(authority: ArtifactContentAuthorityRecord) -> str:
        mime_type = normalize_mime_type(authority.mime_type)
        if mime_type not in EDITABLE_ARTIFACT_MIME_TYPES:
            raise ArtifactContentNotEditableError
        return mime_type

    @staticmethod
    def _require_content_hash(authority: ArtifactContentAuthorityRecord) -> str:
        if authority.content_hash is None:
            raise ArtifactContentIntegrityError
        return authority.content_hash
