"""SQLAlchemy adapter for durable cloud ArtifactContentContractV2 state."""

from typing import override

from sqlalchemy import and_, exists, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement, Select

from src.domain.ports.repositories.artifact_content_authority_repository import (
    ArtifactContentAuthorityRecord,
    ArtifactContentAuthorityRepositoryPort,
    ArtifactContentReceiptRecord,
    ArtifactContentScope,
)
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.artifact_model import (
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
        statement = self._authority_statement(scope)
        if for_update:
            statement = statement.with_for_update()
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
        return statement.execution_options(populate_existing=True)

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
