from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any

from src.domain.model.workspace.workspace_message import (
    MessageSenderType,
    WorkspaceMessage,
)
from src.domain.ports.repositories.workspace.workspace_agent_repository import (
    WorkspaceAgentRepository,
)
from src.domain.ports.repositories.workspace.workspace_member_repository import (
    WorkspaceMemberRepository,
)
from src.domain.ports.repositories.workspace.workspace_message_repository import (
    WorkspaceMessageRepository,
)

logger = logging.getLogger(__name__)

_MENTION_RE = re.compile(r"@([\w][\w\-.]{0,62}[\w]|[\w])")


class WorkspaceMessageService:
    def __init__(
        self,
        message_repo: WorkspaceMessageRepository,
        member_repo: WorkspaceMemberRepository,
        agent_repo: WorkspaceAgentRepository,
        workspace_event_publisher: Callable[[str, str, dict[str, Any]], Awaitable[None]]
        | None = None,
    ) -> None:
        self._message_repo = message_repo
        self._member_repo = member_repo
        self._agent_repo = agent_repo
        self._workspace_event_publisher = workspace_event_publisher

    async def send_message(
        self,
        workspace_id: str,
        sender_id: str,
        sender_type: MessageSenderType,
        sender_name: str,
        content: str,
        parent_message_id: str | None = None,
    ) -> WorkspaceMessage:
        mention_ids = await self._resolve_mentions(workspace_id, content)

        message = WorkspaceMessage(
            workspace_id=workspace_id,
            sender_id=sender_id,
            sender_type=sender_type,
            content=content,
            mentions=mention_ids,
            parent_message_id=parent_message_id,
            metadata={"sender_name": sender_name},
        )
        saved = await self._message_repo.save(message)

        if self._workspace_event_publisher is not None:
            await self._workspace_event_publisher(
                workspace_id,
                "workspace_message_created",
                {
                    "workspace_id": workspace_id,
                    "message_id": saved.id,
                    "sender_id": sender_id,
                    "sender_type": sender_type.value,
                    "sender_name": sender_name,
                    "content": content,
                    "mentions": mention_ids,
                    "parent_message_id": parent_message_id,
                },
            )

        return saved

    async def list_messages(
        self,
        workspace_id: str,
        limit: int = 50,
        before: str | None = None,
    ) -> list[WorkspaceMessage]:
        return await self._message_repo.find_by_workspace(workspace_id, limit=limit, before=before)

    async def get_mentions(
        self,
        workspace_id: str,
        target_id: str,
        limit: int = 50,
    ) -> list[WorkspaceMessage]:
        all_messages = await self._message_repo.find_by_workspace(workspace_id, limit=500)
        return [m for m in all_messages if target_id in m.mentions][:limit]

    async def _resolve_mentions(self, workspace_id: str, content: str) -> list[str]:
        raw_names = _MENTION_RE.findall(content)
        if not raw_names:
            return []

        members = await self._member_repo.find_by_workspace(workspace_id)
        agents = await self._agent_repo.find_by_workspace(workspace_id)

        name_to_id: dict[str, str] = {}
        for agent in agents:
            if agent.display_name:
                name_to_id[agent.display_name.lower()] = agent.agent_id

        for member in members:
            name_to_id[member.user_id.lower()] = member.user_id

        resolved: list[str] = []
        seen: set[str] = set()
        for raw in raw_names:
            key = raw.strip().lower()
            target_id = name_to_id.get(key)
            if target_id and target_id not in seen:
                resolved.append(target_id)
                seen.add(target_id)

        return resolved
