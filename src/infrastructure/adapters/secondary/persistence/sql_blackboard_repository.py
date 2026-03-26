"""SQLAlchemy repository for blackboard posts and replies."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.workspace.blackboard_post import BlackboardPost, BlackboardPostStatus
from src.domain.model.workspace.blackboard_reply import BlackboardReply
from src.domain.ports.repositories.workspace.blackboard_repository import BlackboardRepository
from src.infrastructure.adapters.secondary.common.base_repository import BaseRepository
from src.infrastructure.adapters.secondary.persistence.models import (
    BlackboardPostModel,
    BlackboardReplyModel,
)


class SqlBlackboardRepository(BaseRepository[BlackboardPost, BlackboardPostModel], BlackboardRepository):
    """SQLAlchemy implementation of BlackboardRepository."""

    _model_class = BlackboardPostModel

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def save_post(self, post: BlackboardPost) -> BlackboardPost:
        await self.save(post)
        return post

    async def find_post_by_id(self, post_id: str) -> BlackboardPost | None:
        return await self.find_by_id(post_id)

    async def list_posts_by_workspace(
        self,
        workspace_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[BlackboardPost]:
        query = (
            select(BlackboardPostModel)
            .where(BlackboardPostModel.workspace_id == workspace_id)
            .order_by(BlackboardPostModel.is_pinned.desc(), BlackboardPostModel.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self._session.execute(query)
        rows = result.scalars().all()
        return [p for row in rows if (p := self._to_domain(row)) is not None]

    async def save_reply(self, reply: BlackboardReply) -> BlackboardReply:
        existing = await self._session.get(BlackboardReplyModel, reply.id)
        if existing:
            existing.content = reply.content
            existing.metadata_json = reply.metadata
            existing.updated_at = reply.updated_at
        else:
            self._session.add(
                BlackboardReplyModel(
                    id=reply.id,
                    post_id=reply.post_id,
                    workspace_id=reply.workspace_id,
                    author_id=reply.author_id,
                    content=reply.content,
                    metadata_json=reply.metadata,
                    created_at=reply.created_at,
                    updated_at=reply.updated_at,
                )
            )
        await self._session.flush()
        return reply

    async def list_replies_by_post(
        self,
        post_id: str,
        limit: int = 200,
        offset: int = 0,
    ) -> list[BlackboardReply]:
        query = (
            select(BlackboardReplyModel)
            .where(BlackboardReplyModel.post_id == post_id)
            .order_by(BlackboardReplyModel.created_at.asc())
            .offset(offset)
            .limit(limit)
        )
        result = await self._session.execute(query)
        rows = result.scalars().all()
        return [self._reply_to_domain(row) for row in rows]

    async def delete_post(self, post_id: str) -> bool:
        return await self.delete(post_id)

    async def delete_reply(self, reply_id: str) -> bool:
        existing = await self._session.get(BlackboardReplyModel, reply_id)
        if existing is None:
            return False
        await self._session.delete(existing)
        await self._session.flush()
        return True

    def _to_domain(self, db_post: BlackboardPostModel | None) -> BlackboardPost | None:
        if db_post is None:
            return None

        return BlackboardPost(
            id=db_post.id,
            workspace_id=db_post.workspace_id,
            author_id=db_post.author_id,
            title=db_post.title,
            content=db_post.content,
            status=BlackboardPostStatus(db_post.status),
            is_pinned=db_post.is_pinned,
            metadata=db_post.metadata_json or {},
            created_at=db_post.created_at,
            updated_at=db_post.updated_at,
        )

    def _to_db(self, domain_entity: BlackboardPost) -> BlackboardPostModel:
        return BlackboardPostModel(
            id=domain_entity.id,
            workspace_id=domain_entity.workspace_id,
            author_id=domain_entity.author_id,
            title=domain_entity.title,
            content=domain_entity.content,
            status=domain_entity.status.value,
            is_pinned=domain_entity.is_pinned,
            metadata_json=domain_entity.metadata,
            created_at=domain_entity.created_at,
            updated_at=domain_entity.updated_at,
        )

    def _update_fields(self, db_model: BlackboardPostModel, domain_entity: BlackboardPost) -> None:
        db_model.title = domain_entity.title
        db_model.content = domain_entity.content
        db_model.status = domain_entity.status.value
        db_model.is_pinned = domain_entity.is_pinned
        db_model.metadata_json = domain_entity.metadata
        db_model.updated_at = domain_entity.updated_at

    @staticmethod
    def _reply_to_domain(db_reply: BlackboardReplyModel) -> BlackboardReply:
        return BlackboardReply(
            id=db_reply.id,
            post_id=db_reply.post_id,
            workspace_id=db_reply.workspace_id,
            author_id=db_reply.author_id,
            content=db_reply.content,
            metadata=db_reply.metadata_json or {},
            created_at=db_reply.created_at,
            updated_at=db_reply.updated_at,
        )
