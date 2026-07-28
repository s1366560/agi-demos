"""SQLAlchemy adapter for durable cloud ArtifactContentContractV2 state."""

from datetime import UTC, datetime
from typing import override

from sqlalchemy import and_, exists, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement, Select

from src.domain.ports.repositories.artifact_content_authority_repository import (
    ArtifactContentAuthorityRecord,
    ArtifactContentAuthorityRepositoryPort,
    ArtifactContentOrphanGcRecord,
    ArtifactContentReceiptRecord,
    ArtifactContentScope,
)
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.artifact_model import (
    ArtifactContentOrphanGcModel,
    ArtifactContentReceiptModel,
    ArtifactModel,
)
from src.infrastructure.adapters.secondary.persistence.models import Conversation, Project


class SqlArtifactContentAuthorityRepository(ArtifactContentAuthorityRepositoryPort):
    """Persist the Artifact metadata pointer and idempotency receipts."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__()
        self._session = session

    @override
    async def resolve_scope(self, artifact_id: str) -> ArtifactContentScope | None:
        statement = self._authority_statement().where(ArtifactModel.id == artifact_id)
        artifact = (
            await self._session.execute(refresh_select_statement(statement))
        ).scalar_one_or_none()
        return None if artifact is None else self._scope_from_model(artifact)

    @override
    async def get_authority(
        self,
        scope: ArtifactContentScope,
        *,
        for_update: bool = False,
    ) -> ArtifactContentAuthorityRecord | None:
        statement = self._authority_statement(scope, for_update=for_update)
        artifact = (
            await self._session.execute(refresh_select_statement(statement))
        ).scalar_one_or_none()
        return None if artifact is None else self._authority_from_model(artifact)

    @override
    async def initialize_content_hash(
        self,
        scope: ArtifactContentScope,
        *,
        expected_revision: int,
        expected_object_key: str,
        content_hash: str,
    ) -> ArtifactContentAuthorityRecord | None:
        statement = (
            update(ArtifactModel)
            .where(
                *self._exact_scope_predicates(scope),
                ArtifactModel.content_revision == expected_revision,
                ArtifactModel.object_key == expected_object_key,
                ArtifactModel.content_hash.is_(None),
                ArtifactModel.status == "ready",
            )
            .values(content_hash=content_hash)
            .execution_options(synchronize_session=False)
        )
        _ = await self._session.execute(statement)
        await self._session.flush()
        return await self.get_authority(scope)

    @override
    async def get_receipt(
        self,
        scope: ArtifactContentScope,
        idempotency_key: str,
    ) -> ArtifactContentReceiptRecord | None:
        statement = select(ArtifactContentReceiptModel).where(
            ArtifactContentReceiptModel.artifact_id == scope.artifact_id,
            ArtifactContentReceiptModel.tenant_id == scope.tenant_id,
            ArtifactContentReceiptModel.project_id == scope.project_id,
            ArtifactContentReceiptModel.idempotency_key == idempotency_key,
        )
        receipt = (
            await self._session.execute(refresh_select_statement(statement))
        ).scalar_one_or_none()
        if receipt is None:
            return None
        return ArtifactContentReceiptRecord(
            request_hash=receipt.request_hash,
            resulting_revision=receipt.resulting_revision,
            content_hash=receipt.content_hash,
            object_key=receipt.object_key,
        )

    @override
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
        statement = (
            update(ArtifactModel)
            .where(
                *self._exact_scope_predicates(scope),
                ArtifactModel.content_revision == expected_revision,
                ArtifactModel.status == "ready",
            )
            .values(
                object_key=object_key,
                size_bytes=size_bytes,
                content_revision=resulting_revision,
                content_hash=content_hash,
                url=None,
                preview_url=None,
                error_message=None,
            )
            .returning(ArtifactModel.id)
            .execution_options(synchronize_session=False)
        )
        updated_id = (await self._session.execute(statement)).scalar_one_or_none()
        if updated_id is None:
            return False
        self._session.add(
            ArtifactContentReceiptModel(
                artifact_id=scope.artifact_id,
                idempotency_key=idempotency_key,
                project_id=scope.project_id,
                tenant_id=scope.tenant_id,
                request_hash=request_hash,
                expected_revision=expected_revision,
                resulting_revision=resulting_revision,
                content_hash=content_hash,
                object_key=object_key,
                size_bytes=size_bytes,
            )
        )
        await self._session.flush()
        return True

    @override
    async def is_object_key_referenced(
        self,
        scope: ArtifactContentScope,
        object_key: str,
    ) -> bool:
        pointer_statement = select(ArtifactModel.id).where(
            *self._exact_scope_predicates(scope),
            ArtifactModel.object_key == object_key,
        )
        pointer = (
            await self._session.execute(refresh_select_statement(pointer_statement))
        ).scalar_one_or_none()
        if pointer is not None:
            return True
        receipt_statement = select(ArtifactContentReceiptModel.artifact_id).where(
            ArtifactContentReceiptModel.artifact_id == scope.artifact_id,
            ArtifactContentReceiptModel.tenant_id == scope.tenant_id,
            ArtifactContentReceiptModel.project_id == scope.project_id,
            ArtifactContentReceiptModel.object_key == object_key,
        )
        receipt = (
            await self._session.execute(refresh_select_statement(receipt_statement))
        ).scalar_one_or_none()
        return receipt is not None

    @override
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
        statement = (
            select(ArtifactContentOrphanGcModel)
            .where(ArtifactContentOrphanGcModel.object_key == object_key)
            .with_for_update()
        )
        existing = (
            await self._session.execute(refresh_select_statement(statement))
        ).scalar_one_or_none()
        if existing is None:
            self._session.add(
                ArtifactContentOrphanGcModel(
                    object_key=object_key,
                    artifact_id=scope.artifact_id,
                    project_id=scope.project_id,
                    tenant_id=scope.tenant_id,
                    conversation_id=scope.conversation_id,
                    idempotency_key=idempotency_key,
                    request_hash=request_hash,
                    content_revision=content_revision,
                    content_hash=content_hash,
                    reason_code=reason_code,
                    status=status,
                    last_error_code=last_error_code,
                )
            )
        else:
            identity = (
                existing.artifact_id,
                existing.project_id,
                existing.tenant_id,
                existing.conversation_id,
                existing.idempotency_key,
                existing.request_hash,
                existing.content_revision,
                existing.content_hash,
            )
            expected_identity = (
                scope.artifact_id,
                scope.project_id,
                scope.tenant_id,
                scope.conversation_id,
                idempotency_key,
                request_hash,
                content_revision,
                content_hash,
            )
            if identity != expected_identity:
                raise RuntimeError("Artifact orphan GC identity conflict")
            if existing.status == "pending":
                existing.reason_code = reason_code
                existing.status = status
                existing.last_error_code = last_error_code
                existing.next_attempt_at = datetime.now(UTC)
                if status != "pending":
                    existing.lease_owner = None
                    existing.lease_token = None
                    existing.lease_expires_at = None
                existing.updated_at = func.now()
        await self._session.flush()

    @override
    async def claim_orphan_gc(
        self,
        *,
        lease_owner: str,
        lease_token: str,
        now: datetime,
        lease_expires_at: datetime,
        limit: int,
    ) -> list[ArtifactContentOrphanGcRecord]:
        self._validate_gc_lease(
            lease_owner=lease_owner,
            lease_token=lease_token,
            now=now,
            lease_expires_at=lease_expires_at,
            limit=limit,
        )
        rows = (
            (
                await self._session.execute(
                    refresh_select_statement(self._orphan_gc_claim_statement(now=now, limit=limit))
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            row.lease_owner = lease_owner
            row.lease_token = lease_token
            row.lease_expires_at = lease_expires_at
            row.updated_at = func.now()
        await self._session.flush()
        return [self._orphan_gc_record_from_model(row) for row in rows]

    @override
    async def lease_orphan_gc(
        self,
        object_key: str,
        *,
        lease_owner: str,
        lease_token: str,
        now: datetime,
        lease_expires_at: datetime,
    ) -> bool:
        self._validate_gc_lease(
            lease_owner=lease_owner,
            lease_token=lease_token,
            now=now,
            lease_expires_at=lease_expires_at,
            limit=1,
        )
        statement = (
            update(ArtifactContentOrphanGcModel)
            .where(
                ArtifactContentOrphanGcModel.object_key == object_key,
                ArtifactContentOrphanGcModel.status == "pending",
                ArtifactContentOrphanGcModel.next_attempt_at <= now,
                or_(
                    ArtifactContentOrphanGcModel.lease_expires_at.is_(None),
                    ArtifactContentOrphanGcModel.lease_expires_at <= now,
                ),
            )
            .values(
                lease_owner=lease_owner,
                lease_token=lease_token,
                lease_expires_at=lease_expires_at,
                updated_at=func.now(),
            )
            .returning(ArtifactContentOrphanGcModel.object_key)
            .execution_options(synchronize_session=False)
        )
        leased_key = (await self._session.execute(statement)).scalar_one_or_none()
        await self._session.flush()
        return leased_key is not None

    @override
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
        self._validate_gc_identity(
            object_key=object_key,
            lease_owner=lease_owner,
            lease_token=lease_token,
        )
        if status not in {"pending", "deleted", "missing", "retained"}:
            raise ValueError("invalid Artifact orphan GC status")
        if last_error_code is not None and len(last_error_code) > 64:
            raise ValueError("invalid Artifact orphan GC error code")
        self._require_timezone_aware(next_attempt_at, name="next attempt")
        statement = (
            update(ArtifactContentOrphanGcModel)
            .where(
                ArtifactContentOrphanGcModel.object_key == object_key,
                ArtifactContentOrphanGcModel.status == "pending",
                ArtifactContentOrphanGcModel.lease_owner == lease_owner,
                ArtifactContentOrphanGcModel.lease_token == lease_token,
            )
            .values(
                status=status,
                attempts=ArtifactContentOrphanGcModel.attempts + 1,
                last_error_code=last_error_code,
                next_attempt_at=next_attempt_at,
                lease_owner=None,
                lease_token=None,
                lease_expires_at=None,
                updated_at=func.now(),
            )
            .returning(ArtifactContentOrphanGcModel.object_key)
            .execution_options(synchronize_session=False)
        )
        completed_key = (await self._session.execute(statement)).scalar_one_or_none()
        await self._session.flush()
        return completed_key is not None

    @staticmethod
    def _authority_from_model(artifact: ArtifactModel) -> ArtifactContentAuthorityRecord:
        return ArtifactContentAuthorityRecord(
            scope=SqlArtifactContentAuthorityRepository._scope_from_model(artifact),
            mime_type=artifact.mime_type,
            status=artifact.status,
            object_key=artifact.object_key,
            size_bytes=artifact.size_bytes,
            revision=artifact.content_revision,
            content_hash=artifact.content_hash,
        )

    @staticmethod
    def _scope_from_model(artifact: ArtifactModel) -> ArtifactContentScope:
        return ArtifactContentScope(
            artifact_id=artifact.id,
            tenant_id=artifact.tenant_id,
            project_id=artifact.project_id,
            conversation_id=artifact.conversation_id,
        )

    @staticmethod
    def _authority_statement(
        scope: ArtifactContentScope | None = None,
        *,
        for_update: bool = False,
    ) -> Select[tuple[ArtifactModel]]:
        conversation_is_consistent = or_(
            ArtifactModel.conversation_id.is_(None),
            and_(
                Conversation.id == ArtifactModel.conversation_id,
                Conversation.tenant_id == ArtifactModel.tenant_id,
                Conversation.project_id == ArtifactModel.project_id,
            ),
        )
        statement = (
            select(ArtifactModel)
            .join(
                Project,
                and_(
                    Project.id == ArtifactModel.project_id,
                    Project.tenant_id == ArtifactModel.tenant_id,
                ),
            )
            .outerjoin(Conversation, Conversation.id == ArtifactModel.conversation_id)
            .where(conversation_is_consistent)
        )
        if scope is not None:
            statement = statement.where(
                *SqlArtifactContentAuthorityRepository._exact_scope_predicates(scope)
            )
        if for_update:
            statement = statement.with_for_update(of=ArtifactModel)
        return statement.execution_options(populate_existing=True)

    @staticmethod
    def _orphan_gc_claim_statement(
        *,
        now: datetime,
        limit: int,
    ) -> Select[tuple[ArtifactContentOrphanGcModel]]:
        return (
            select(ArtifactContentOrphanGcModel)
            .where(
                ArtifactContentOrphanGcModel.status == "pending",
                ArtifactContentOrphanGcModel.next_attempt_at <= now,
                or_(
                    ArtifactContentOrphanGcModel.lease_expires_at.is_(None),
                    ArtifactContentOrphanGcModel.lease_expires_at <= now,
                ),
            )
            .order_by(
                ArtifactContentOrphanGcModel.next_attempt_at,
                ArtifactContentOrphanGcModel.created_at,
                ArtifactContentOrphanGcModel.object_key,
            )
            .limit(limit)
            .with_for_update(of=ArtifactContentOrphanGcModel, skip_locked=True)
        )

    @staticmethod
    def _orphan_gc_record_from_model(
        row: ArtifactContentOrphanGcModel,
    ) -> ArtifactContentOrphanGcRecord:
        return ArtifactContentOrphanGcRecord(
            scope=ArtifactContentScope(
                artifact_id=row.artifact_id,
                tenant_id=row.tenant_id,
                project_id=row.project_id,
                conversation_id=row.conversation_id,
            ),
            object_key=row.object_key,
            idempotency_key=row.idempotency_key,
            request_hash=row.request_hash,
            content_revision=row.content_revision,
            content_hash=row.content_hash,
            reason_code=row.reason_code,
            attempts=row.attempts,
        )

    @staticmethod
    def _validate_gc_lease(
        *,
        lease_owner: str,
        lease_token: str,
        now: datetime,
        lease_expires_at: datetime,
        limit: int,
    ) -> None:
        SqlArtifactContentAuthorityRepository._validate_gc_identity(
            object_key="lease-validation",
            lease_owner=lease_owner,
            lease_token=lease_token,
        )
        if limit < 1 or limit > 100:
            raise ValueError("invalid Artifact orphan GC batch limit")
        SqlArtifactContentAuthorityRepository._require_timezone_aware(
            now,
            name="claim time",
        )
        SqlArtifactContentAuthorityRepository._require_timezone_aware(
            lease_expires_at,
            name="lease expiry",
        )
        if lease_expires_at <= now:
            raise ValueError("Artifact orphan GC lease must expire after claim time")

    @staticmethod
    def _validate_gc_identity(
        *,
        object_key: str,
        lease_owner: str,
        lease_token: str,
    ) -> None:
        if not object_key or len(object_key) > 500:
            raise ValueError("invalid Artifact orphan GC object key")
        if not lease_owner or len(lease_owner) > 64:
            raise ValueError("invalid Artifact orphan GC lease owner")
        if not lease_token or len(lease_token) > 64:
            raise ValueError("invalid Artifact orphan GC lease token")

    @staticmethod
    def _require_timezone_aware(value: datetime, *, name: str) -> None:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"Artifact orphan GC {name} must be timezone-aware")

    @staticmethod
    def _exact_scope_predicates(
        scope: ArtifactContentScope,
    ) -> tuple[ColumnElement[bool], ...]:
        project_is_consistent = exists(
            select(Project.id).where(
                Project.id == scope.project_id,
                Project.tenant_id == scope.tenant_id,
            )
        )
        conversation_matches: ColumnElement[bool]
        if scope.conversation_id is None:
            conversation_matches = ArtifactModel.conversation_id.is_(None)
        else:
            conversation_matches = and_(
                ArtifactModel.conversation_id == scope.conversation_id,
                exists(
                    select(Conversation.id).where(
                        Conversation.id == scope.conversation_id,
                        Conversation.tenant_id == scope.tenant_id,
                        Conversation.project_id == scope.project_id,
                    )
                ),
            )
        return (
            ArtifactModel.id == scope.artifact_id,
            ArtifactModel.tenant_id == scope.tenant_id,
            ArtifactModel.project_id == scope.project_id,
            project_is_consistent,
            conversation_matches,
        )
