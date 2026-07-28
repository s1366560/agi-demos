"""SQLAlchemy Artifact lifecycle repository."""

from collections.abc import Sequence
from typing import override

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql import Select

from src.domain.model.artifact.artifact import Artifact, ArtifactCategory, ArtifactStatus
from src.domain.ports.repositories.artifact_repository import ArtifactRepositoryPort
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.artifact_model import ArtifactModel
from src.infrastructure.adapters.secondary.persistence.models import Conversation, Project


class SqlArtifactRepository(ArtifactRepositoryPort):
    """Persist complete Artifact lifecycle state using fresh committed transactions."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        super().__init__()
        self._session_factory = session_factory

    @override
    async def save(self, artifact: Artifact) -> Artifact:
        async with self._session_factory() as session, session.begin():
            model = await session.get(ArtifactModel, artifact.id, with_for_update=True)
            if model is None:
                model = self._new_model(artifact)
                session.add(model)
            else:
                self._apply_entity(model, artifact)
        return artifact

    @override
    async def get(self, artifact_id: str) -> Artifact | None:
        statement = self._scoped_statement().where(ArtifactModel.id == artifact_id)
        rows = await self._read(statement)
        return None if not rows else self._to_entity(rows[0])

    @override
    async def get_by_project(
        self,
        project_id: str,
        category: ArtifactCategory | None = None,
        status: ArtifactStatus | None = None,
    ) -> list[Artifact]:
        statement = self._scoped_statement().where(ArtifactModel.project_id == project_id)
        if category is not None:
            statement = statement.where(ArtifactModel.category == category.value)
        if status is not None:
            statement = statement.where(ArtifactModel.status == status.value)
        return self._to_entities(await self._read(self._newest_first(statement)))

    @override
    async def get_by_conversation(
        self,
        conversation_id: str,
        status: ArtifactStatus | None = None,
    ) -> list[Artifact]:
        statement = self._scoped_statement().where(ArtifactModel.conversation_id == conversation_id)
        if status is not None:
            statement = statement.where(ArtifactModel.status == status.value)
        return self._to_entities(await self._read(self._newest_first(statement)))

    @override
    async def get_by_tool_execution(self, tool_execution_id: str) -> list[Artifact]:
        statement = self._scoped_statement().where(
            ArtifactModel.tool_execution_id == tool_execution_id
        )
        return self._to_entities(await self._read(self._newest_first(statement)))

    @override
    async def get_by_workspace(
        self,
        workspace_id: str,
        category: ArtifactCategory | None = None,
        status: ArtifactStatus | None = None,
    ) -> list[Artifact]:
        statement = self._scoped_statement().where(ArtifactModel.workspace_id == workspace_id)
        if category is not None:
            statement = statement.where(ArtifactModel.category == category.value)
        if status is not None:
            statement = statement.where(ArtifactModel.status == status.value)
        return self._to_entities(await self._read(self._newest_first(statement)))

    @override
    async def delete(self, artifact_id: str) -> bool:
        return await self.update_status(artifact_id, ArtifactStatus.DELETED)

    @override
    async def update_status(
        self,
        artifact_id: str,
        status: ArtifactStatus,
        error_message: str | None = None,
        url: str | None = None,
        preview_url: str | None = None,
    ) -> bool:
        async with self._session_factory() as session, session.begin():
            model = await session.get(ArtifactModel, artifact_id, with_for_update=True)
            if model is None:
                return False
            model.status = status.value
            model.error_message = error_message
            model.url = url
            model.preview_url = preview_url
        return True

    async def _read(self, statement: Select[tuple[ArtifactModel]]) -> Sequence[ArtifactModel]:
        async with self._session_factory() as session:
            result = await session.execute(refresh_select_statement(statement))
            return result.scalars().all()

    @staticmethod
    def _scoped_statement() -> Select[tuple[ArtifactModel]]:
        conversation_is_consistent = or_(
            ArtifactModel.conversation_id.is_(None),
            and_(
                Conversation.id == ArtifactModel.conversation_id,
                Conversation.tenant_id == ArtifactModel.tenant_id,
                Conversation.project_id == ArtifactModel.project_id,
            ),
        )
        return (
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

    @staticmethod
    def _newest_first(
        statement: Select[tuple[ArtifactModel]],
    ) -> Select[tuple[ArtifactModel]]:
        return statement.order_by(ArtifactModel.created_at.desc(), ArtifactModel.id)

    @staticmethod
    def _new_model(artifact: Artifact) -> ArtifactModel:
        model = ArtifactModel(
            id=artifact.id,
            project_id=artifact.project_id,
            tenant_id=artifact.tenant_id,
            sandbox_id=artifact.sandbox_id,
            tool_execution_id=artifact.tool_execution_id,
            conversation_id=artifact.conversation_id,
            filename=artifact.filename,
            mime_type=artifact.mime_type,
            category=artifact.category.value,
            size_bytes=artifact.size_bytes,
            object_key=artifact.object_key,
            status=artifact.status.value,
            source_tool=artifact.source_tool,
            source_path=artifact.source_path,
            created_at=artifact.created_at,
        )
        SqlArtifactRepository._apply_entity(model, artifact)
        return model

    @staticmethod
    def _apply_entity(model: ArtifactModel, artifact: Artifact) -> None:
        metadata = dict(artifact.metadata)
        revision = metadata.pop("content_revision", None)
        content_hash = metadata.pop("content_hash", None)
        model.project_id = artifact.project_id
        model.tenant_id = artifact.tenant_id
        model.sandbox_id = artifact.sandbox_id
        model.tool_execution_id = artifact.tool_execution_id
        model.conversation_id = artifact.conversation_id
        model.filename = artifact.filename
        model.mime_type = artifact.mime_type
        model.category = artifact.category.value
        model.size_bytes = artifact.size_bytes
        model.object_key = artifact.object_key
        model.url = artifact.url
        model.preview_url = artifact.preview_url
        model.status = artifact.status.value
        model.error_message = artifact.error_message
        model.source_tool = artifact.source_tool
        model.source_path = artifact.source_path
        model.artifact_metadata = metadata
        if revision is not None:
            model.content_revision = int(revision)
        if content_hash is not None:
            model.content_hash = str(content_hash)

    @staticmethod
    def _to_entities(models: Sequence[ArtifactModel]) -> list[Artifact]:
        return [SqlArtifactRepository._to_entity(model) for model in models]

    @staticmethod
    def _to_entity(model: ArtifactModel) -> Artifact:
        metadata = dict(model.artifact_metadata or {})
        metadata["content_revision"] = model.content_revision
        if model.content_hash is not None:
            metadata["content_hash"] = model.content_hash
        return Artifact(
            id=model.id,
            project_id=model.project_id,
            tenant_id=model.tenant_id,
            sandbox_id=model.sandbox_id,
            tool_execution_id=model.tool_execution_id,
            conversation_id=model.conversation_id,
            filename=model.filename,
            mime_type=model.mime_type,
            category=ArtifactCategory(model.category),
            size_bytes=model.size_bytes,
            object_key=model.object_key,
            url=model.url,
            preview_url=model.preview_url,
            status=ArtifactStatus(model.status),
            error_message=model.error_message,
            source_tool=model.source_tool,
            source_path=model.source_path,
            metadata=metadata,
            created_at=model.created_at,
        )
