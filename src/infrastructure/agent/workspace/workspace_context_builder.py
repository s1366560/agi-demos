"""Build dynamic workspace context for agent system prompts.

Fetches live workspace data (members, agents, recent messages, blackboard posts)
from the database and formats it as an XML-structured text block for injection
into the agent's system prompt.

Unlike WorkspaceManager (which loads static persona files like SOUL.md),
this module provides DYNAMIC runtime context from the database.

Usage in ReActAgent._build_system_prompt:
    context_text = await build_workspace_context(project_id, tenant_id)
"""

from __future__ import annotations

import logging
from datetime import datetime

from src.domain.model.workspace.blackboard_post import BlackboardPost
from src.domain.model.workspace.workspace import Workspace
from src.domain.model.workspace.workspace_agent import WorkspaceAgent
from src.domain.model.workspace.workspace_member import WorkspaceMember
from src.domain.model.workspace.workspace_message import WorkspaceMessage
from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
from src.infrastructure.adapters.secondary.persistence.sql_blackboard_repository import (
    SqlBlackboardRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_workspace_agent_repository import (
    SqlWorkspaceAgentRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_workspace_member_repository import (
    SqlWorkspaceMemberRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_workspace_message_repository import (
    SqlWorkspaceMessageRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_workspace_repository import (
    SqlWorkspaceRepository,
)

logger = logging.getLogger(__name__)

_MAX_RECENT_MESSAGES = 20
_MAX_BLACKBOARD_POSTS = 5
_MAX_MEMBERS = 50
_MAX_AGENTS = 20


async def build_workspace_context(
    project_id: str,
    tenant_id: str,
) -> str | None:
    """Build a workspace context string for the agent system prompt.

    Fetches workspace data from the database using a fresh session,
    following the agent runtime DB access pattern (async_session_factory).

    Args:
        project_id: The project ID to find associated workspaces.
        tenant_id: The tenant ID for workspace lookup.

    Returns:
        Formatted XML text block with workspace context, or None if no
        workspace exists for the given project.
    """
    if not project_id or not tenant_id:
        return None

    try:
        async with async_session_factory() as db:
            workspace_repo = SqlWorkspaceRepository(db)
            workspaces = await workspace_repo.find_by_project(
                tenant_id=tenant_id,
                project_id=project_id,
                limit=1,
            )
            if not workspaces:
                return None

            workspace = workspaces[0]

            member_repo = SqlWorkspaceMemberRepository(db)
            agent_repo = SqlWorkspaceAgentRepository(db)
            message_repo = SqlWorkspaceMessageRepository(db)
            blackboard_repo = SqlBlackboardRepository(db)

            members = await member_repo.find_by_workspace(
                workspace.id,
                limit=_MAX_MEMBERS,
            )
            agents = await agent_repo.find_by_workspace(
                workspace.id,
                active_only=True,
                limit=_MAX_AGENTS,
            )
            messages = await message_repo.find_by_workspace(
                workspace.id,
                limit=_MAX_RECENT_MESSAGES,
            )
            posts = await blackboard_repo.list_posts_by_workspace(
                workspace.id,
                limit=_MAX_BLACKBOARD_POSTS,
            )

        return format_workspace_context(workspace, members, agents, messages, posts)
    except Exception:
        logger.warning(
            "Failed to build workspace context for project %s", project_id, exc_info=True
        )
        return None


def format_workspace_context(
    workspace: Workspace,
    members: list[WorkspaceMember],
    agents: list[WorkspaceAgent],
    messages: list[WorkspaceMessage],
    posts: list[BlackboardPost],
) -> str:
    """Format workspace data into an XML text block for prompt injection."""
    sections: list[str] = []
    sections.append(f'<cyber-workspace name="{workspace.name}" id="{workspace.id}">')

    if members:
        lines = ["  <members>"]
        for m in members:
            lines.append(f'    <member user_id="{m.user_id}" role="{m.role.value}" />')
        lines.append("  </members>")
        sections.append("\n".join(lines))

    if agents:
        lines = ["  <agents>"]
        for a in agents:
            name = a.display_name or a.agent_id
            desc = f' description="{a.description}"' if a.description else ""
            status = f' status="{a.status}"' if a.status != "idle" else ""
            lines.append(f'    <agent id="{a.agent_id}" name="{name}"{desc}{status} />')
        lines.append("  </agents>")
        sections.append("\n".join(lines))

    if messages:
        lines = ["  <recent-messages>"]
        for msg in messages:
            ts = format_timestamp(msg.created_at)
            sender_label = f"{msg.sender_type.value}:{msg.sender_id}"
            content = truncate(msg.content, 200)
            mentions_attr = ""
            if msg.mentions:
                mentions_attr = f' mentions="{",".join(msg.mentions)}"'
            lines.append(
                f'    <message from="{sender_label}" at="{ts}"{mentions_attr}>{content}</message>'
            )
        lines.append("  </recent-messages>")
        sections.append("\n".join(lines))

    if posts:
        lines = ["  <blackboard>"]
        for p in posts:
            pinned = ' pinned="true"' if p.is_pinned else ""
            ts = format_timestamp(p.created_at)
            content = truncate(p.content, 300)
            lines.append(
                f'    <post title="{p.title}" author="{p.author_id}" '
                + f'status="{p.status.value}" at="{ts}"{pinned}>{content}</post>'
            )
        lines.append("  </blackboard>")
        sections.append("\n".join(lines))

    sections.append("</cyber-workspace>")
    return "\n".join(sections)


def format_timestamp(dt: datetime) -> str:
    """Format datetime to a compact ISO-like string."""
    return dt.strftime("%Y-%m-%d %H:%M")


def truncate(text: str, max_len: int) -> str:
    """Truncate text to max_len, adding ellipsis if needed."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."
