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
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from src.application.schemas.workspace_agent_autonomy import GoalCandidateRecordModel
from src.application.services.workspace_goal_sensing_service import (
    WorkspaceGoalSensingService,
)
from src.application.services.workspace_task_experience_service import (
    build_workspace_task_experience_summary,
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
from src.infrastructure.adapters.secondary.persistence.sql_workspace_task_session_attempt_repository import (
    SqlWorkspaceTaskSessionAttemptRepository,
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
            attempt_repo = SqlWorkspaceTaskSessionAttemptRepository(db)
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
            task_experience_summaries: dict[str, dict[str, Any]] = {}
            attempts_by_task = await attempt_repo.find_by_workspace_task_ids(
                [task.id for task in tasks],
                limit_per_task=3,
            )
            for task in tasks:
                task_experience_summaries[task.id] = build_workspace_task_experience_summary(
                    task,
                    attempts=attempts_by_task.get(task.id, []),
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
            task_experience_summaries,
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
    task_experience_summaries: Mapping[str, Mapping[str, Any]] | None = None,
) -> str:
    """Format workspace data into an XML text block for prompt injection."""
    sections: list[str] = []
    sections.append(f'<cyber-workspace name="{workspace.name}" id="{workspace.id}">')

    _extend_section(sections, _format_members(members))
    _extend_section(sections, _format_agents(agents))
    _extend_section(sections, _format_messages(messages))
    _extend_section(sections, _format_posts(posts))
    _extend_section(sections, _format_objectives(objectives or []))
    _extend_section(sections, _format_tasks(tasks or [], task_experience_summaries or {}))
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


def _format_tasks(
    tasks: list[WorkspaceTask],
    task_experience_summaries: Mapping[str, Mapping[str, Any]] | None = None,
) -> str | None:
    if not tasks:
        return None
    lines = ["  <tasks>"]
    for task in tasks:
        lines.append(_format_task(task, task_experience_summaries or {}))
    lines.append("  </tasks>")
    return "\n".join(lines)


def _format_task(
    task: WorkspaceTask,
    task_experience_summaries: Mapping[str, Mapping[str, Any]],
) -> str:
    metadata = task.metadata
    role = str(metadata.get(TASK_ROLE, "task"))
    attrs = "".join(
        [
            _task_goal_attrs(task, metadata),
            _task_worker_attrs(metadata),
            _task_attempt_attrs(metadata),
            _task_experience_attrs(task, task_experience_summaries),
        ]
    )
    return (
        f'    <task id="{task.id}" status="{task.status.value}" role="{role}" '
        + f'priority="{task.priority.value}"{attrs}>{truncate(task.title, 120)}</task>'
    )


def _task_goal_attrs(task: WorkspaceTask, metadata: Mapping[str, Any]) -> str:
    goal_evidence = metadata.get("goal_evidence")
    evidence_grade = (
        goal_evidence.get("verification_grade")
        if isinstance(goal_evidence, dict)
        and isinstance(goal_evidence.get("verification_grade"), str)
        else None
    )
    return "".join(
        [
            _xml_attr("description", task.description, max_len=160),
            _xml_attr("goal_health", metadata.get("goal_health")),
            _xml_attr("workspace_agent_binding_id", task.get_workspace_agent_binding_id()),
            _xml_attr("remediation_status", metadata.get(REMEDIATION_STATUS)),
            _xml_attr("progress_summary", metadata.get("goal_progress_summary"), max_len=160),
            _xml_bool_attr(
                "pending_leader_adjudication",
                metadata.get(PENDING_LEADER_ADJUDICATION) is True,
            ),
            _xml_attr("evidence_grade", evidence_grade),
        ]
    )


def _task_worker_attrs(metadata: Mapping[str, Any]) -> str:
    return "".join(
        [
            _xml_attr("last_worker_report_type", metadata.get("last_worker_report_type")),
            _xml_attr(
                "last_worker_report_summary",
                metadata.get(LAST_WORKER_REPORT_SUMMARY),
                max_len=120,
            ),
            _xml_list_attr(
                "last_worker_report_artifacts",
                metadata.get("last_worker_report_artifacts"),
                max_len=120,
            ),
            _xml_list_attr(
                "last_worker_report_verifications",
                metadata.get("last_worker_report_verifications"),
                max_len=120,
            ),
            _xml_attr("last_worker_report_id", metadata.get("last_worker_report_id")),
            _xml_attr(
                "last_worker_report_fingerprint",
                metadata.get("last_worker_report_fingerprint"),
                max_len=24,
            ),
        ]
    )


def _task_attempt_attrs(metadata: Mapping[str, Any]) -> str:
    return "".join(
        [
            _xml_attr("current_attempt_id", metadata.get(CURRENT_ATTEMPT_ID)),
            _xml_attr("current_attempt_number", metadata.get("current_attempt_number")),
            _xml_attr(
                "current_attempt_worker_agent_id",
                metadata.get("current_attempt_worker_agent_id"),
            ),
            _xml_attr(
                "current_attempt_worker_binding_id",
                metadata.get("current_attempt_worker_binding_id"),
            ),
            _xml_attr("last_attempt_id", metadata.get("last_attempt_id")),
            _xml_attr("last_attempt_status", metadata.get("last_attempt_status")),
        ]
    )


def _task_experience_attrs(
    task: WorkspaceTask,
    task_experience_summaries: Mapping[str, Mapping[str, Any]],
) -> str:
    experience = task_experience_summaries.get(task.id)
    if not isinstance(experience, Mapping):
        experience = build_workspace_task_experience_summary(task)
    readiness = _mapping_from_mapping(experience, "readiness")
    execution = _mapping_from_mapping(experience, "execution")
    evidence = _mapping_from_mapping(experience, "evidence")
    diagnostics = _mapping_from_mapping(experience, "diagnostics")
    active_attempt = _mapping_from_mapping(execution, "active_attempt")
    return "".join(
        [
            _xml_list_attr("missing_evidence", readiness.get("missing_evidence"), max_len=120),
            _xml_list_attr(
                "blocked_requirements",
                readiness.get("blocked_requirements"),
                max_len=160,
            ),
            _xml_list_attr("evidence_refs", evidence.get("evidence_refs"), max_len=120),
            _xml_list_attr(
                "verification_summaries",
                evidence.get("verification_summaries"),
                max_len=120,
            ),
            _xml_attr("active_attempt_status", active_attempt.get("status")),
            _xml_bool_attr("missing_conversation", diagnostics.get("missing_conversation") is True),
        ]
    )


def _mapping_from_mapping(source: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = source.get(key)
    return value if isinstance(value, Mapping) else {}


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


def _xml_attr(name: str, value: object, *, max_len: int | None = None) -> str:
    if value is None:
        return ""
    if not isinstance(value, str | int):
        return ""
    text = str(value)
    if not text:
        return ""
    if max_len is not None:
        text = truncate(text, max_len)
    return f' {name}="{text}"'


def _xml_bool_attr(name: str, value: bool) -> str:
    return f' {name}="true"' if value else ""


def _xml_list_attr(name: str, value: object, *, max_len: int) -> str:
    if not isinstance(value, list):
        return ""
    text = ",".join(item for item in value if isinstance(item, str) and item)
    return _xml_attr(name, text, max_len=max_len)


def format_timestamp(dt: datetime) -> str:
    """Format datetime to a compact ISO-like string."""
    return dt.strftime("%Y-%m-%d %H:%M")


def truncate(text: str, max_len: int) -> str:
    """Truncate text to max_len, adding ellipsis if needed."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."
