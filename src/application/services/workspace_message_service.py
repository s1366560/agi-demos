from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any, Protocol, cast

from src.domain.model.workspace.workspace_message import (
    MessageSenderType,
    WorkspaceMessage,
)
from src.domain.ports.repositories.user_repository import UserRepository
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

# Supports: @word, @word-with.dots, @"Multi Word Name"
_MENTION_RE = re.compile(r'@"([^"]{1,64})"|@([\w][\w\-.]{0,62}[\w]|[\w])')


class _BulkUserRepository(Protocol):
    async def find_by_ids(self, entity_ids: list[str]) -> list[object]:
        """Find multiple users by id."""
        ...


class WorkspaceMessageService:
    def __init__(
        self,
        message_repo: WorkspaceMessageRepository,
        member_repo: WorkspaceMemberRepository,
        agent_repo: WorkspaceAgentRepository,
        workspace_event_publisher: Callable[[str, str, dict[str, Any]], Awaitable[None]]
        | None = None,
        user_repo: UserRepository | None = None,
        allow_legacy_text_mentions: bool = False,
    ) -> None:
        self._message_repo = message_repo
        self._member_repo = member_repo
        self._agent_repo = agent_repo
        self._workspace_event_publisher = workspace_event_publisher
        self._user_repo = user_repo
        self._allow_legacy_text_mentions = allow_legacy_text_mentions
        self._pending_events: list[tuple[str, str, dict[str, Any]]] = []

    def consume_pending_events(self) -> list[tuple[str, str, dict[str, Any]]]:
        pending_events = list(self._pending_events)
        self._pending_events.clear()
        return pending_events

    async def publish_pending_events(self) -> None:
        if self._workspace_event_publisher is None:
            self._pending_events.clear()
            return
        for workspace_id, event_name, payload in self._pending_events:
            await self._workspace_event_publisher(workspace_id, event_name, payload)
        self._pending_events.clear()

    def _queue_workspace_event(
        self,
        workspace_id: str,
        event_name: str,
        payload: dict[str, Any],
    ) -> None:
        self._pending_events.append((workspace_id, event_name, payload))

    async def send_message(
        self,
        workspace_id: str,
        sender_id: str,
        sender_type: MessageSenderType,
        sender_name: str,
        content: str,
        parent_message_id: str | None = None,
        mentions: list[str] | None = None,
    ) -> WorkspaceMessage:
        if mentions is not None:
            mention_ids = await self._resolve_structured_mentions(workspace_id, mentions)
        elif self._allow_legacy_text_mentions:
            mention_ids = await self._resolve_legacy_text_mentions(workspace_id, content)
        else:
            mention_ids = []

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

        self._queue_workspace_event(
            workspace_id,
            "workspace_message_created",
            {
                "message": {
                    "id": saved.id,
                    "workspace_id": workspace_id,
                    "sender_id": sender_id,
                    "sender_type": sender_type.value,
                    "content": content,
                    "mentions": mention_ids,
                    "parent_message_id": parent_message_id,
                    "metadata": saved.metadata,
                    "created_at": saved.created_at.isoformat(),
                }
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

    async def _resolve_structured_mentions(
        self,
        workspace_id: str,
        mention_ids: list[str],
    ) -> list[str]:
        requested = [mention.strip() for mention in mention_ids if mention.strip()]
        if not requested:
            return []

        agents = await self._agent_repo.find_by_workspace(workspace_id)
        if any(mention.lower() == "all" for mention in requested):
            return [agent.agent_id for agent in agents]

        members = await self._member_repo.find_by_workspace(workspace_id)
        valid_targets = {agent.agent_id for agent in agents}
        valid_targets.update(member.user_id for member in members)

        resolved: list[str] = []
        seen: set[str] = set()
        invalid: list[str] = []
        for mention_id in requested:
            if mention_id not in valid_targets:
                invalid.append(mention_id)
                continue
            if mention_id not in seen:
                resolved.append(mention_id)
                seen.add(mention_id)

        if invalid:
            raise ValueError(f"Unknown workspace mentions: {', '.join(sorted(set(invalid)))}")

        return resolved

    async def _resolve_legacy_text_mentions(self, workspace_id: str, content: str) -> list[str]:
        raw_matches = _MENTION_RE.findall(content)
        if not raw_matches:
            return []

        raw_names = [quoted or plain for quoted, plain in raw_matches]

        members = await self._member_repo.find_by_workspace(workspace_id)
        agents = await self._agent_repo.find_by_workspace(workspace_id)

        # @all broadcasts to every agent in the workspace
        if any(name.strip().lower() == "all" for name in raw_names):
            return [a.agent_id for a in agents]

        name_to_id: dict[str, str] = {}
        for agent in agents:
            name_to_id[agent.agent_id.lower()] = agent.agent_id
            if agent.display_name:
                name_to_id[agent.display_name.lower()] = agent.agent_id

        await self._populate_member_names(name_to_id, members)

        resolved: list[str] = []
        seen: set[str] = set()
        for raw in raw_names:
            key = raw.strip().lower()
            target_id = name_to_id.get(key)
            if target_id and target_id not in seen:
                resolved.append(target_id)
                seen.add(target_id)

        return resolved

    async def _populate_member_names(
        self,
        name_to_id: dict[str, str],
        members: list[Any],
    ) -> None:
        member_user_ids = self._member_user_ids(members)
        if self._user_repo and member_user_ids:
            bulk_find = getattr(self._user_repo, "find_by_ids", None)
            if callable(bulk_find):
                users = await cast(_BulkUserRepository, self._user_repo).find_by_ids(
                    member_user_ids
                )
                users_by_id: dict[str, object] = {}
                for user in users:
                    user_id = getattr(user, "id", None)
                    if isinstance(user_id, str) and user_id in member_user_ids:
                        users_by_id[user_id] = user
                for user_id in member_user_ids:
                    user = users_by_id.get(user_id)
                    if user is not None:
                        self._register_user_alias_values(name_to_id, user_id, user)
                return

            for user_id in member_user_ids:
                await self._register_user_aliases(name_to_id, user_id)
        else:
            for user_id in member_user_ids:
                name_to_id[user_id.lower()] = user_id

    @staticmethod
    def _member_user_ids(members: list[Any]) -> list[str]:
        user_ids: list[str] = []
        seen: set[str] = set()
        for member in members:
            user_id = getattr(member, "user_id", None)
            if not isinstance(user_id, str) or user_id in seen:
                continue
            user_ids.append(user_id)
            seen.add(user_id)
        return user_ids

    async def _register_user_aliases(
        self,
        name_to_id: dict[str, str],
        user_id: str,
    ) -> None:
        user = await self._user_repo.find_by_id(user_id)  # type: ignore[union-attr]
        if user is None:
            return
        self._register_user_alias_values(name_to_id, user_id, user)

    @staticmethod
    def _register_user_alias_values(
        name_to_id: dict[str, str],
        user_id: str,
        user: object,
    ) -> None:
        email = getattr(user, "email", None)
        if email:
            name_to_id[email.lower()] = user_id
            local_part = email.split("@")[0]
            if local_part and local_part.lower() not in name_to_id:
                name_to_id[local_part.lower()] = user_id
        display_name = getattr(user, "display_name", None) or getattr(user, "name", None)
        if display_name and display_name.lower() not in name_to_id:
            name_to_id[display_name.lower()] = user_id
