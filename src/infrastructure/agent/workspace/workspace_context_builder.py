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

from src.application.schemas.workspace_agent_autonomy import GoalCandidateRecordModel
from src.application.services.workspace_goal_sensing_service import (
    WorkspaceGoalSensingService,
)
from src.domain.model.workspace.blackboard_post import BlackboardPost
from src.domain.model.workspace.cyber_objective import CyberObjective
from src.domain.model.workspace.workspace import Workspace
from src.domain.model.workspace.workspace_agent import WorkspaceAgent
from src.domain.model.workspace.workspace_member import WorkspaceMember
from src.domain.model.workspace.workspace_message import WorkspaceMessage
from src.domain.model.workspace.workspace_task import WorkspaceTask
from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
from src.infrastructure.adapters.secondary.persistence.sql_blackboard_repository import (
    SqlBlackboardRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_cyber_objective_repository import (
    SqlCyberObjectiveRepository,
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
from src.infrastructure.adapters.secondary.persistence.sql_workspace_task_repository import (
    SqlWorkspaceTaskRepository,
)
from src.infrastructure.agent.workspace.workspace_metadata_keys import (
    CURRENT_ATTEMPT_ID,
    LAST_WORKER_REPORT_SUMMARY,
    PENDING_LEADER_ADJUDICATION,
    REMEDIATION_STATUS,
    TASK_ROLE,
)

logger = logging.getLogger(__name__)

_MAX_RECENT_MESSAGES = 20
_MAX_BLACKBOARD_POSTS = 5
_MAX_MEMBERS = 50
_MAX_AGENTS = 20
_MAX_TASKS = 20
_MAX_OBJECTIVES = 10
_MAX_GOAL_CANDIDATES = 5


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
            task_repo = SqlWorkspaceTaskRepository(db)
            objective_repo = SqlCyberObjectiveRepository(db)

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
            tasks = await task_repo.find_by_workspace(
                workspace.id,
                limit=_MAX_TASKS,
            )
            objectives = await objective_repo.find_by_workspace(
                workspace.id,
                limit=_MAX_OBJECTIVES,
            )
            goal_candidates = WorkspaceGoalSensingService().sense_candidates(
                tasks=tasks,
                objectives=objectives,
                posts=posts,
                messages=messages,
            )[:_MAX_GOAL_CANDIDATES]

        return format_workspace_context(
            workspace,
            members,
            agents,
            messages,
            posts,
            tasks,
            objectives,
            goal_candidates,
        )
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
    tasks: list[WorkspaceTask] | None = None,
    objectives: list[CyberObjective] | None = None,
    goal_candidates: list[GoalCandidateRecordModel] | None = None,
) -> str:
    """Format workspace data into an XML text block for prompt injection."""
    sections: list[str] = []
    sections.append(f'<cyber-workspace name="{workspace.name}" id="{workspace.id}">')

    _extend_section(sections, _format_members(members))
    _extend_section(sections, _format_agents(agents))
    _extend_section(sections, _format_messages(messages))
    _extend_section(sections, _format_posts(posts))
    _extend_section(sections, _format_objectives(objectives or []))
    _extend_section(sections, _format_tasks(tasks or []))
    _extend_section(sections, _format_goal_candidates(goal_candidates or []))

    sections.append("</cyber-workspace>")
    return "\n".join(sections)


def _extend_section(sections: list[str], block: str | None) -> None:
    if block:
        sections.append(block)


def _format_members(members: list[WorkspaceMember]) -> str | None:
    if not members:
        return None
    lines = ["  <members>"]
    for member in members:
        lines.append(f'    <member user_id="{member.user_id}" role="{member.role.value}" />')
    lines.append("  </members>")
    return "\n".join(lines)


def _format_agents(agents: list[WorkspaceAgent]) -> str | None:
    if not agents:
        return None
    lines = ["  <agents>"]
    for agent in agents:
        name = agent.display_name or agent.agent_id
        desc = f' description="{agent.description}"' if agent.description else ""
        status = f' status="{agent.status}"' if agent.status != "idle" else ""
        lines.append(f'    <agent id="{agent.agent_id}" name="{name}"{desc}{status} />')
    lines.append("  </agents>")
    return "\n".join(lines)


def _format_messages(messages: list[WorkspaceMessage]) -> str | None:
    if not messages:
        return None
    lines = ["  <recent-messages>"]
    for msg in messages:
        ts = format_timestamp(msg.created_at)
        sender_label = f"{msg.sender_type.value}:{msg.sender_id}"
        content = truncate(msg.content, 200)
        mentions_attr = f' mentions="{",".join(msg.mentions)}"' if msg.mentions else ""
        lines.append(
            f'    <message from="{sender_label}" at="{ts}"{mentions_attr}>{content}</message>'
        )
    lines.append("  </recent-messages>")
    return "\n".join(lines)


def _format_posts(posts: list[BlackboardPost]) -> str | None:
    if not posts:
        return None
    lines = ["  <blackboard>"]
    for post in posts:
        pinned = ' pinned="true"' if post.is_pinned else ""
        ts = format_timestamp(post.created_at)
        content = truncate(post.content, 300)
        lines.append(
            f'    <post title="{post.title}" author="{post.author_id}" '
            + f'status="{post.status.value}" at="{ts}"{pinned}>{content}</post>'
        )
    lines.append("  </blackboard>")
    return "\n".join(lines)


def _format_objectives(objectives: list[CyberObjective]) -> str | None:
    if not objectives:
        return None
    lines = ["  <objectives>"]
    for objective in objectives:
        description_attr = (
            f' description="{truncate(objective.description, 160)}"'
            if objective.description
            else ""
        )
        lines.append(
            f'    <objective id="{objective.id}" type="{objective.obj_type.value}" '
            + f'progress="{objective.progress:.2f}"{description_attr}>'
            + f"{truncate(objective.title, 120)}</objective>"
        )
    lines.append("  </objectives>")
    return "\n".join(lines)


def _format_tasks(tasks: list[WorkspaceTask]) -> str | None:
    if not tasks:
        return None
    lines = ["  <tasks>"]
    for task in tasks:
        metadata = task.metadata
        role = str(metadata.get(TASK_ROLE, "task"))
        goal_health = metadata.get("goal_health")
        remediation_status = metadata.get(REMEDIATION_STATUS)
        goal_progress_summary = metadata.get("goal_progress_summary")
        last_worker_report_type = metadata.get("last_worker_report_type")
        last_worker_report_summary = metadata.get(LAST_WORKER_REPORT_SUMMARY)
        last_worker_report_artifacts = metadata.get("last_worker_report_artifacts")
        last_worker_report_verifications = metadata.get("last_worker_report_verifications")
        last_worker_report_id = metadata.get("last_worker_report_id")
        last_worker_report_fingerprint = metadata.get("last_worker_report_fingerprint")
        current_attempt_id = metadata.get(CURRENT_ATTEMPT_ID)
        current_attempt_number = metadata.get("current_attempt_number")
        last_attempt_id = metadata.get("last_attempt_id")
        last_attempt_status = metadata.get("last_attempt_status")
        goal_evidence = metadata.get("goal_evidence")
        description_attr = (
            f' description="{truncate(task.description, 160)}"' if task.description else ""
        )
        goal_health_attr = f' goal_health="{goal_health}"' if isinstance(goal_health, str) else ""
        remediation_attr = (
            f' remediation_status="{remediation_status}"'
            if isinstance(remediation_status, str)
            else ""
        )
        progress_summary_attr = (
            f' progress_summary="{truncate(str(goal_progress_summary), 160)}"'
            if isinstance(goal_progress_summary, str)
            else ""
        )
        pending_adjudication_attr = (
            ' pending_leader_adjudication="true"'
            if metadata.get(PENDING_LEADER_ADJUDICATION) is True
            else ""
        )
        worker_report_attr = (
            f' last_worker_report_type="{last_worker_report_type}"'
            if isinstance(last_worker_report_type, str)
            else ""
        )
        worker_summary_attr = (
            f' last_worker_report_summary="{truncate(str(last_worker_report_summary), 120)}"'
            if isinstance(last_worker_report_summary, str)
            else ""
        )
        worker_artifacts_attr = (
            f' last_worker_report_artifacts="{truncate(",".join(last_worker_report_artifacts), 120)}"'
            if isinstance(last_worker_report_artifacts, list)
            else ""
        )
        worker_verifications_attr = (
            f' last_worker_report_verifications="{truncate(",".join(last_worker_report_verifications), 120)}"'
            if isinstance(last_worker_report_verifications, list)
            else ""
        )
        worker_report_id_attr = (
            f' last_worker_report_id="{last_worker_report_id}"'
            if isinstance(last_worker_report_id, str)
            else ""
        )
        worker_report_fingerprint_attr = (
            f' last_worker_report_fingerprint="{truncate(str(last_worker_report_fingerprint), 24)}"'
            if isinstance(last_worker_report_fingerprint, str)
            else ""
        )
        current_attempt_id_attr = (
            f' current_attempt_id="{current_attempt_id}"'
            if isinstance(current_attempt_id, str)
            else ""
        )
        current_attempt_number_attr = (
            f' current_attempt_number="{current_attempt_number}"'
            if isinstance(current_attempt_number, int)
            else ""
        )
        last_attempt_id_attr = (
            f' last_attempt_id="{last_attempt_id}"' if isinstance(last_attempt_id, str) else ""
        )
        last_attempt_status_attr = (
            f' last_attempt_status="{last_attempt_status}"'
            if isinstance(last_attempt_status, str)
            else ""
        )
        evidence_grade_attr = (
            f' evidence_grade="{goal_evidence.get("verification_grade")}"'
            if isinstance(goal_evidence, dict)
            and isinstance(goal_evidence.get("verification_grade"), str)
            else ""
        )
        lines.append(
            f'    <task id="{task.id}" status="{task.status.value}" role="{role}" '
            + f'priority="{task.priority.value}"{description_attr}{goal_health_attr}'
            + f"{remediation_attr}{progress_summary_attr}{pending_adjudication_attr}"
            + f"{worker_report_attr}{worker_summary_attr}{worker_artifacts_attr}"
            + f"{worker_verifications_attr}{worker_report_id_attr}{worker_report_fingerprint_attr}"
            + f"{current_attempt_id_attr}{current_attempt_number_attr}{last_attempt_id_attr}"
            + f"{last_attempt_status_attr}"
            + f"{evidence_grade_attr}>"
            + f"{truncate(task.title, 120)}</task>"
        )
    lines.append("  </tasks>")
    return "\n".join(lines)


def _format_goal_candidates(candidates: list[GoalCandidateRecordModel]) -> str | None:
    if not candidates:
        return None
    lines = ["  <goal-candidates>"]
    for candidate in candidates:
        refs = ",".join(candidate.source_refs)
        lines.append(
            f'    <goal-candidate id="{candidate.candidate_id}" '
            + f'kind="{candidate.candidate_kind}" decision="{candidate.decision}" '
            + f'evidence_strength="{candidate.evidence_strength:.2f}" '
            + f'urgency="{candidate.urgency:.2f}" refs="{refs}">'
            + f"{truncate(candidate.candidate_text, 160)}</goal-candidate>"
        )
    lines.append("  </goal-candidates>")
    return "\n".join(lines)


def format_timestamp(dt: datetime) -> str:
    """Format datetime to a compact ISO-like string."""
    return dt.strftime("%Y-%m-%d %H:%M")


def truncate(text: str, max_len: int) -> str:
    """Truncate text to max_len, adding ellipsis if needed."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."
