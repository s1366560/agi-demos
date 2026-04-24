"""Application service for workspace blackboard posts and replies."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime

from src.application.services.workspace_surface_contract import BLACKBOARD_OWNERSHIP_METADATA
from src.domain.model.workspace.blackboard_post import BlackboardPost, BlackboardPostStatus
from src.domain.model.workspace.blackboard_reply import BlackboardReply
from src.domain.model.workspace.workspace import Workspace
from src.domain.model.workspace.workspace_member import WorkspaceMember
from src.domain.model.workspace.workspace_role import WorkspaceRole
from src.domain.ports.repositories.workspace.blackboard_repository import BlackboardRepository
from src.domain.ports.repositories.workspace.workspace_member_repository import (
    WorkspaceMemberRepository,
)
from src.domain.ports.repositories.workspace.workspace_repository import WorkspaceRepository


class BlackboardService:
    """Orchestrates blackboard behaviors with workspace permission checks."""

    def __init__(
        self,
        blackboard_repo: BlackboardRepository,
        workspace_repo: WorkspaceRepository,
        workspace_member_repo: WorkspaceMemberRepository,
    ) -> None:
        self._blackboard_repo = blackboard_repo
        self._workspace_repo = workspace_repo
        self._workspace_member_repo = workspace_member_repo

    async def create_post(
        self,
        tenant_id: str,
        project_id: str,
        workspace_id: str,
        actor_user_id: str,
        title: str,
        content: str,
        status: BlackboardPostStatus = BlackboardPostStatus.OPEN,
        is_pinned: bool = False,
        metadata: Mapping[str, object] | None = None,
    ) -> BlackboardPost:
        workspace = await self._require_workspace_scope(
            tenant_id=tenant_id,
            project_id=project_id,
            workspace_id=workspace_id,
        )
        await self._require_minimum_role(
            workspace_id=workspace.id,
            user_id=actor_user_id,
            minimum=WorkspaceRole.EDITOR,
            error_message="Insufficient permission to create blackboard post",
        )
        now = datetime.now(UTC)
        post = BlackboardPost(
            id=BlackboardPost.generate_id(),
            workspace_id=workspace.id,
            author_id=actor_user_id,
            title=title,
            content=content,
            status=status,
            is_pinned=is_pinned,
            metadata=self._merge_blackboard_metadata(metadata),
            created_at=now,
            updated_at=now,
        )
        return await self._blackboard_repo.save_post(post)

    async def list_posts(
        self,
        tenant_id: str,
        project_id: str,
        workspace_id: str,
        actor_user_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[BlackboardPost]:
        workspace = await self._require_workspace_scope(
            tenant_id=tenant_id,
            project_id=project_id,
            workspace_id=workspace_id,
        )
        await self._require_membership(workspace_id=workspace.id, user_id=actor_user_id)
        return await self._blackboard_repo.list_posts_by_workspace(
            workspace_id=workspace.id,
            limit=limit,
            offset=offset,
        )

    async def get_post(
        self,
        tenant_id: str,
        project_id: str,
        workspace_id: str,
        post_id: str,
        actor_user_id: str,
    ) -> BlackboardPost:
        workspace = await self._require_workspace_scope(
            tenant_id=tenant_id,
            project_id=project_id,
            workspace_id=workspace_id,
        )
        await self._require_membership(workspace_id=workspace.id, user_id=actor_user_id)
        return await self._require_post_in_workspace(post_id=post_id, workspace_id=workspace.id)

    async def update_post(
        self,
        tenant_id: str,
        project_id: str,
        workspace_id: str,
        post_id: str,
        actor_user_id: str,
        title: str | None = None,
        content: str | None = None,
        status: BlackboardPostStatus | None = None,
        is_pinned: bool | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> BlackboardPost:
        workspace = await self._require_workspace_scope(
            tenant_id=tenant_id,
            project_id=project_id,
            workspace_id=workspace_id,
        )
        await self._require_minimum_role(
            workspace_id=workspace.id,
            user_id=actor_user_id,
            minimum=WorkspaceRole.EDITOR,
            error_message="Insufficient permission to update blackboard post",
        )
        post = await self._require_post_in_workspace(post_id=post_id, workspace_id=workspace.id)
        if title is not None:
            post.title = title
        if content is not None:
            post.content = content
        if status is not None:
            post.status = status
        if is_pinned is not None:
            post.is_pinned = is_pinned
        if metadata is not None:
            post.metadata = self._merge_blackboard_metadata(metadata)
        post.updated_at = datetime.now(UTC)
        return await self._blackboard_repo.save_post(post)

    async def delete_post(
        self,
        tenant_id: str,
        project_id: str,
        workspace_id: str,
        post_id: str,
        actor_user_id: str,
    ) -> bool:
        workspace = await self._require_workspace_scope(
            tenant_id=tenant_id,
            project_id=project_id,
            workspace_id=workspace_id,
        )
        await self._require_minimum_role(
            workspace_id=workspace.id,
            user_id=actor_user_id,
            minimum=WorkspaceRole.EDITOR,
            error_message="Insufficient permission to delete blackboard post",
        )
        await self._require_post_in_workspace(post_id=post_id, workspace_id=workspace.id)
        return await self._blackboard_repo.delete_post(post_id)

    async def pin_post(
        self,
        tenant_id: str,
        project_id: str,
        workspace_id: str,
        post_id: str,
        actor_user_id: str,
    ) -> BlackboardPost:
        return await self.update_post(
            tenant_id=tenant_id,
            project_id=project_id,
            workspace_id=workspace_id,
            post_id=post_id,
            actor_user_id=actor_user_id,
            is_pinned=True,
        )

    async def unpin_post(
        self,
        tenant_id: str,
        project_id: str,
        workspace_id: str,
        post_id: str,
        actor_user_id: str,
    ) -> BlackboardPost:
        return await self.update_post(
            tenant_id=tenant_id,
            project_id=project_id,
            workspace_id=workspace_id,
            post_id=post_id,
            actor_user_id=actor_user_id,
            is_pinned=False,
        )

    async def create_reply(
        self,
        tenant_id: str,
        project_id: str,
        workspace_id: str,
        post_id: str,
        actor_user_id: str,
        content: str,
        metadata: Mapping[str, object] | None = None,
    ) -> BlackboardReply:
        workspace = await self._require_workspace_scope(
            tenant_id=tenant_id,
            project_id=project_id,
            workspace_id=workspace_id,
        )
        await self._require_minimum_role(
            workspace_id=workspace.id,
            user_id=actor_user_id,
            minimum=WorkspaceRole.EDITOR,
            error_message="Insufficient permission to create blackboard reply",
        )
        await self._require_post_in_workspace(post_id=post_id, workspace_id=workspace.id)
        now = datetime.now(UTC)
        reply = BlackboardReply(
            id=BlackboardReply.generate_id(),
            post_id=post_id,
            workspace_id=workspace.id,
            author_id=actor_user_id,
            content=content,
            metadata=self._merge_blackboard_metadata(metadata),
            created_at=now,
            updated_at=now,
        )
        return await self._blackboard_repo.save_reply(reply)

    async def list_replies(
        self,
        tenant_id: str,
        project_id: str,
        workspace_id: str,
        post_id: str,
        actor_user_id: str,
        limit: int = 200,
        offset: int = 0,
    ) -> list[BlackboardReply]:
        workspace = await self._require_workspace_scope(
            tenant_id=tenant_id,
            project_id=project_id,
            workspace_id=workspace_id,
        )
        await self._require_membership(workspace_id=workspace.id, user_id=actor_user_id)
        await self._require_post_in_workspace(post_id=post_id, workspace_id=workspace.id)
        return await self._blackboard_repo.list_replies_by_post(
            post_id=post_id,
            limit=limit,
            offset=offset,
        )

    async def update_reply(
        self,
        tenant_id: str,
        project_id: str,
        workspace_id: str,
        post_id: str,
        reply_id: str,
        actor_user_id: str,
        content: str,
        metadata: Mapping[str, object] | None = None,
    ) -> BlackboardReply:
        workspace = await self._require_workspace_scope(
            tenant_id=tenant_id,
            project_id=project_id,
            workspace_id=workspace_id,
        )
        await self._require_minimum_role(
            workspace_id=workspace.id,
            user_id=actor_user_id,
            minimum=WorkspaceRole.EDITOR,
            error_message="Insufficient permission to update blackboard reply",
        )
        await self._require_post_in_workspace(post_id=post_id, workspace_id=workspace.id)
        reply = await self._require_reply_in_post(post_id=post_id, reply_id=reply_id)
        if reply.workspace_id != workspace.id:
            raise ValueError("Blackboard reply does not belong to workspace")
        reply.content = content
        if metadata is not None:
            reply.metadata = self._merge_blackboard_metadata(metadata)
        reply.updated_at = datetime.now(UTC)
        return await self._blackboard_repo.save_reply(reply)

    async def delete_reply(
        self,
        tenant_id: str,
        project_id: str,
        workspace_id: str,
        post_id: str,
        reply_id: str,
        actor_user_id: str,
    ) -> bool:
        workspace = await self._require_workspace_scope(
            tenant_id=tenant_id,
            project_id=project_id,
            workspace_id=workspace_id,
        )
        await self._require_minimum_role(
            workspace_id=workspace.id,
            user_id=actor_user_id,
            minimum=WorkspaceRole.EDITOR,
            error_message="Insufficient permission to delete blackboard reply",
        )
        await self._require_post_in_workspace(post_id=post_id, workspace_id=workspace.id)
        reply = await self._require_reply_in_post(post_id=post_id, reply_id=reply_id)
        if reply.workspace_id != workspace.id:
            raise ValueError("Blackboard reply does not belong to workspace")
        return await self._blackboard_repo.delete_reply(reply_id)

    async def _require_workspace_scope(
        self,
        tenant_id: str,
        project_id: str,
        workspace_id: str,
    ) -> Workspace:
        workspace = await self._workspace_repo.find_by_id(workspace_id)
        if workspace is None:
            raise ValueError(f"Workspace {workspace_id} not found")
        if workspace.tenant_id != tenant_id or workspace.project_id != project_id:
            raise ValueError("Workspace does not belong to tenant/project scope")
        return workspace

    async def _require_post_in_workspace(self, post_id: str, workspace_id: str) -> BlackboardPost:
        post = await self._blackboard_repo.find_post_by_id(post_id)
        if post is None:
            raise ValueError(f"Blackboard post {post_id} not found")
        if post.workspace_id != workspace_id:
            raise ValueError("Blackboard post does not belong to workspace")
        return post

    async def _require_reply_in_post(self, post_id: str, reply_id: str) -> BlackboardReply:
        candidates = await self._blackboard_repo.list_replies_by_post(
            post_id=post_id,
            limit=1000,
            offset=0,
        )
        for candidate in candidates:
            if candidate.id == reply_id:
                return candidate
        raise ValueError(f"Blackboard reply {reply_id} not found")

    async def _require_membership(self, workspace_id: str, user_id: str) -> WorkspaceMember:
        member = await self._workspace_member_repo.find_by_workspace_and_user(
            workspace_id=workspace_id,
            user_id=user_id,
        )
        if member is None:
            raise PermissionError("User must be a workspace member")
        return member

    async def _require_minimum_role(
        self,
        workspace_id: str,
        user_id: str,
        minimum: WorkspaceRole,
        error_message: str,
    ) -> WorkspaceMember:
        member = await self._require_membership(workspace_id=workspace_id, user_id=user_id)
        if self._role_weight(member.role) < self._role_weight(minimum):
            raise PermissionError(error_message)
        return member

    @staticmethod
    def _role_weight(role: WorkspaceRole) -> int:
        if role == WorkspaceRole.OWNER:
            return 300
        if role == WorkspaceRole.EDITOR:
            return 200
        return 100

    @staticmethod
    def _merge_blackboard_metadata(metadata: Mapping[str, object] | None) -> dict[str, object]:
        merged = dict(metadata or {})
        for key, value in BLACKBOARD_OWNERSHIP_METADATA.items():
            merged[key] = value
        return merged
