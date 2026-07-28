"""Persistence port for the durable ArtifactContentContractV2 authority."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ArtifactContentScope:
    """Exact multi-tenant scope of one Artifact content authority."""

    artifact_id: str
    tenant_id: str
    project_id: str
    conversation_id: str | None


@dataclass(frozen=True)
class ArtifactContentAuthorityRecord:
    """Current versioned object pointer stored in PostgreSQL."""

    scope: ArtifactContentScope
    mime_type: str
    status: str
    object_key: str
    size_bytes: int
    revision: int
    content_hash: str | None


@dataclass(frozen=True)
class ArtifactContentReceiptRecord:
    """Durable idempotency receipt stored alongside the metadata pointer."""

    request_hash: str
    resulting_revision: int
    content_hash: str
    object_key: str


@dataclass(frozen=True)
class ArtifactContentOrphanGcRecord:
    """One durably leased provisional object awaiting authoritative cleanup."""

    scope: ArtifactContentScope
    object_key: str
    idempotency_key: str
    request_hash: str
    content_revision: int
    content_hash: str
    reason_code: str
    attempts: int


class ArtifactContentAuthorityRepositoryPort(ABC):
    """Repository operations needed by the cloud Artifact content service."""

    @abstractmethod
    async def resolve_scope(self, artifact_id: str) -> ArtifactContentScope | None:
        """Resolve a structurally consistent Artifact scope."""

    @abstractmethod
    async def get_authority(
        self,
        scope: ArtifactContentScope,
        *,
        for_update: bool = False,
    ) -> ArtifactContentAuthorityRecord | None:
        """Read the exact scoped pointer, optionally locking it for mutation."""

    @abstractmethod
    async def initialize_content_hash(
        self,
        scope: ArtifactContentScope,
        *,
        expected_revision: int,
        expected_object_key: str,
        content_hash: str,
    ) -> ArtifactContentAuthorityRecord | None:
        """Conditionally initialize a legacy pointer's canonical content hash."""

    @abstractmethod
    async def get_receipt(
        self,
        scope: ArtifactContentScope,
        idempotency_key: str,
    ) -> ArtifactContentReceiptRecord | None:
        """Read a durable receipt within the locked Artifact scope."""

    @abstractmethod
    async def advance_pointer(
        self,
        scope: ArtifactContentScope,
        *,
        expected_revision: int,
        idempotency_key: str,
        request_hash: str,
        resulting_revision: int,
        content_hash: str,
        object_key: str,
        size_bytes: int,
    ) -> bool:
        """Flush a fenced pointer update and its receipt in one DB transaction."""

    @abstractmethod
    async def is_object_key_referenced(
        self,
        scope: ArtifactContentScope,
        object_key: str,
    ) -> bool:
        """Return whether the scoped pointer or any receipt references an object."""

    @abstractmethod
    async def record_orphan_gc(
        self,
        *,
        scope: ArtifactContentScope,
        object_key: str,
        idempotency_key: str,
        request_hash: str,
        content_revision: int,
        content_hash: str,
        reason_code: str,
        status: str,
        last_error_code: str | None = None,
    ) -> None:
        """Persist or refresh an auditable provisional-object GC record."""

    @abstractmethod
    async def claim_orphan_gc(
        self,
        *,
        lease_owner: str,
        lease_token: str,
        now: datetime,
        lease_expires_at: datetime,
        limit: int,
    ) -> list[ArtifactContentOrphanGcRecord]:
        """Lease a bounded pending batch with database-level skip-locked semantics."""

    @abstractmethod
    async def lease_orphan_gc(
        self,
        object_key: str,
        *,
        lease_owner: str,
        lease_token: str,
        now: datetime,
        lease_expires_at: datetime,
    ) -> bool:
        """Lease one known pending object before an immediate cleanup attempt."""

    @abstractmethod
    async def complete_orphan_gc_lease(
        self,
        object_key: str,
        *,
        lease_owner: str,
        lease_token: str,
        status: str,
        last_error_code: str | None,
        next_attempt_at: datetime,
    ) -> bool:
        """Fenced completion that cannot mutate a lease reclaimed by another worker."""
