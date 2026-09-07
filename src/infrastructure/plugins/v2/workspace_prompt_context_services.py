"""Generation-owned dynamic Workspace prompt-context service."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, cast, runtime_checkable

from src.application.services.workspace_goal_sensing_service import WorkspaceGoalSensingService
from src.application.services.workspace_task_experience_service import (
    build_workspace_task_experience_summary,
)
from src.domain.model.workspace.blackboard_post import BlackboardPost, BlackboardPostStatus
from src.domain.model.workspace.cyber_objective import CyberObjective, CyberObjectiveType
from src.domain.model.workspace.workspace import Workspace
from src.domain.model.workspace.workspace_agent import WorkspaceAgent
from src.domain.model.workspace.workspace_member import WorkspaceMember
from src.domain.model.workspace.workspace_message import MessageSenderType, WorkspaceMessage
from src.domain.model.workspace.workspace_role import WorkspaceRole
from src.domain.model.workspace.workspace_task import (
    WorkspaceTask,
    WorkspaceTaskPriority,
    WorkspaceTaskStatus,
)
from src.infrastructure.agent.workspace.workspace_context_builder import format_workspace_context
from src.infrastructure.agent.workspace.workspace_metadata_keys import (
    CURRENT_ATTEMPT_ID,
    LAST_WORKER_REPORT_SUMMARY,
    PENDING_LEADER_ADJUDICATION,
)
from src.infrastructure.workspace_core.client import (
    WorkspaceCoreAgent,
    WorkspaceCoreBlackboardPost,
    WorkspaceCoreClientError,
    WorkspaceCoreCyberObjective,
    WorkspaceCoreMember,
    WorkspaceCoreMessage,
    WorkspaceCoreNotFoundError,
    WorkspaceCoreProfile,
    WorkspaceCoreTask,
)

from .conversation_access_services import ConversationAccessResolverProtocolV2
from .runtime import (
    ContextV2,
    OperationContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)
from .workspace_core_runtime import WorkspaceCoreRuntimeServiceV2

WORKSPACE_PROMPT_CONTEXT_MODULE_V2 = "builtin://memstack/workspace-core/prompt-context"
WORKSPACE_PROMPT_CONTEXT_SERVICE_V2 = "service:agent.workspace-prompt-context"
WORKSPACE_PROMPT_CONTEXT_RUNTIME_INJECT_V2 = "runtime"
WORKSPACE_PROMPT_CONTEXT_CONVERSATIONS_INJECT_V2 = "conversations"
_OPERATION_IDENTITY_SERVICE_V2 = "service:operation.identity"

_MAX_RECENT_MESSAGES = 20
_MAX_BLACKBOARD_POSTS = 5
_MAX_MEMBERS = 50
_MAX_AGENTS = 20
_MAX_TASKS = 20
_MAX_OBJECTIVES = 10
_MAX_GOAL_CANDIDATES = 5


@runtime_checkable
class WorkspacePromptContextProtocolV2(Protocol):
    """Build dynamic prompt context from one pinned operation authority."""

    async def build(
        self,
        operation: OperationContextV2,
        *,
        project_id: str,
        tenant_id: str,
    ) -> str | None: ...


@dataclass(frozen=True, kw_only=True)
class WorkspacePromptContextServiceV2:
    """Join conversation scope with the generation-owned Workspace Core read model."""

    runtime: WorkspaceCoreRuntimeServiceV2
    conversations: ConversationAccessResolverProtocolV2

    async def build(
        self,
        operation: OperationContextV2,
        *,
        project_id: str,
        tenant_id: str,
    ) -> str | None:
        conversation_id, user_id = _operation_scope_v2(
            operation,
            project_id=project_id,
            tenant_id=tenant_id,
        )
        access = self.conversations.resolve(operation)
        conversation = await access.get_conversation(
            conversation_id=conversation_id,
            project_id=project_id,
            user_id=user_id,
        )
        if conversation is None:
            raise RuntimeV2Error(
                "workspace_prompt_context_conversation_missing",
                "Workspace prompt context requires the exact scoped conversation",
            )
        if conversation.tenant_id != tenant_id:
            raise RuntimeV2Error(
                "workspace_prompt_context_conversation_scope_mismatch",
                "Workspace prompt conversation tenant differs from its pinned operation",
            )
        workspace_id = (conversation.workspace_id or "").strip()
        if not workspace_id:
            raise RuntimeV2Error(
                "workspace_prompt_context_workspace_missing",
                "Workspace prompt conversation has no owning Workspace",
            )

        client = self.runtime.client
        try:
            profile = await client.read_workspace_profile(
                tenant_id=tenant_id,
                project_id=project_id,
                workspace_id=workspace_id,
                user_id=user_id,
            )
            members, agents, messages, posts, tasks, objectives = await asyncio.gather(
                client.list_workspace_members(
                    tenant_id=tenant_id,
                    project_id=project_id,
                    workspace_id=workspace_id,
                    user_id=user_id,
                ),
                client.list_workspace_agents(
                    tenant_id=tenant_id,
                    project_id=project_id,
                    workspace_id=workspace_id,
                    user_id=user_id,
                    active_only=True,
                ),
                client.list_workspace_messages(
                    tenant_id=tenant_id,
                    project_id=project_id,
                    workspace_id=workspace_id,
                    user_id=user_id,
                    limit=_MAX_RECENT_MESSAGES,
                ),
                client.list_workspace_blackboard_posts(
                    tenant_id=tenant_id,
                    project_id=project_id,
                    workspace_id=workspace_id,
                    user_id=user_id,
                    limit=_MAX_BLACKBOARD_POSTS,
                ),
                client.list_workspace_tasks(
                    workspace_id=workspace_id,
                    user_id=user_id,
                    limit=_MAX_TASKS,
                ),
                client.list_workspace_objectives(
                    tenant_id=tenant_id,
                    project_id=project_id,
                    workspace_id=workspace_id,
                    user_id=user_id,
                    limit=_MAX_OBJECTIVES,
                ),
            )
        except WorkspaceCoreNotFoundError as exc:
            raise RuntimeV2Error(
                "workspace_prompt_context_workspace_missing",
                "Workspace Core could not find the conversation's owning Workspace",
            ) from exc
        except WorkspaceCoreClientError as exc:
            raise RuntimeV2Error(
                "workspace_prompt_context_read_failed",
                "Workspace Core could not build the dynamic prompt context",
            ) from exc

        return _format_core_context_v2(
            workspace_id=workspace_id,
            profile=profile,
            members=members,
            agents=agents,
            messages=messages,
            posts=posts,
            tasks=tasks,
            objectives=objectives,
        )


def workspace_prompt_context_definition_v2() -> PluginDefinitionV2:
    """Provide prompt context from explicit Workspace and conversation aliases."""

    def apply(context: ContextV2, config: Mapping[str, Any]) -> None:
        if config.get("strategy") != "workspace-core-read-model":
            raise ValueError("Workspace prompt context requires strategy workspace-core-read-model")
        runtime = context.require(WORKSPACE_PROMPT_CONTEXT_RUNTIME_INJECT_V2)
        if not isinstance(runtime, WorkspaceCoreRuntimeServiceV2):
            raise RuntimeV2Error(
                "invalid_workspace_prompt_context_runtime",
                "Workspace prompt context received an invalid Workspace Core Provider",
            )
        conversations = context.require(WORKSPACE_PROMPT_CONTEXT_CONVERSATIONS_INJECT_V2)
        if not isinstance(conversations, ConversationAccessResolverProtocolV2):
            raise RuntimeV2Error(
                "invalid_workspace_prompt_context_conversations",
                "Workspace prompt context received an invalid conversation Provider",
            )
        _ = context.provide(
            WORKSPACE_PROMPT_CONTEXT_SERVICE_V2,
            WorkspacePromptContextServiceV2(
                runtime=runtime,
                conversations=conversations,
            ),
            label="workspace-prompt-context",
        )

    return PluginDefinitionV2(
        module_ref=WORKSPACE_PROMPT_CONTEXT_MODULE_V2,
        contract_digest=generated_contract_digest_v2(WORKSPACE_PROMPT_CONTEXT_MODULE_V2),
        apply=apply,
    )


def _operation_scope_v2(
    operation: OperationContextV2,
    *,
    project_id: str,
    tenant_id: str,
) -> tuple[str, str]:
    scope = operation.context.scope
    if scope.tenant_id != tenant_id or scope.project_id != project_id or not scope.session_id:
        raise RuntimeV2Error(
            "workspace_prompt_context_scope_mismatch",
            "Workspace prompt context request differs from its pinned session scope",
        )
    identity = operation.require(_OPERATION_IDENTITY_SERVICE_V2)
    if not isinstance(identity, Mapping):
        raise RuntimeV2Error(
            "invalid_workspace_prompt_context_identity",
            "Workspace prompt context requires structured operation identity",
        )
    values = cast("Mapping[str, object]", identity)
    identity_tenant_id = values.get("tenant_id")
    identity_project_id = values.get("project_id")
    user_id = values.get("user_id")
    if (
        identity_tenant_id != tenant_id
        or identity_project_id != project_id
        or not isinstance(user_id, str)
        or not user_id.strip()
    ):
        raise RuntimeV2Error(
            "workspace_prompt_context_identity_mismatch",
            "Workspace prompt identity differs from its pinned session scope",
        )
    return scope.session_id, user_id


def _format_core_context_v2(
    *,
    workspace_id: str,
    profile: WorkspaceCoreProfile,
    members: list[WorkspaceCoreMember],
    agents: list[WorkspaceCoreAgent],
    messages: list[WorkspaceCoreMessage],
    posts: list[WorkspaceCoreBlackboardPost],
    tasks: list[WorkspaceCoreTask],
    objectives: list[WorkspaceCoreCyberObjective],
) -> str:
    if profile.id != workspace_id:
        raise RuntimeV2Error(
            "workspace_prompt_context_workspace_scope_mismatch",
            "Workspace Core profile differs from the conversation Workspace",
        )
    try:
        workspace = Workspace(
            id=profile.id,
            tenant_id=profile.tenant_id,
            project_id=profile.project_id,
            name=profile.name,
            created_by=profile.created_by,
            is_archived=profile.is_archived,
            metadata=dict(profile.metadata),
        )
        domain_members = [_member_v2(item) for item in members]
        domain_agents = [_agent_v2(item) for item in agents]
        domain_messages = [_message_v2(item) for item in messages]
        domain_posts = [_post_v2(item) for item in posts]
        domain_tasks = [_task_v2(item) for item in tasks]
        domain_objectives = [_objective_v2(item) for item in objectives]
    except (TypeError, ValueError) as exc:
        raise RuntimeV2Error(
            "workspace_prompt_context_invalid_core_data",
            "Workspace Core returned data that violates the prompt-context domain contract",
        ) from exc

    experiences = {
        task.id: build_workspace_task_experience_summary(task, attempts=[]) for task in domain_tasks
    }
    goal_candidates = WorkspaceGoalSensingService().sense_candidates(
        tasks=domain_tasks,
        objectives=domain_objectives,
        posts=domain_posts,
        messages=domain_messages,
    )[:_MAX_GOAL_CANDIDATES]
    return format_workspace_context(
        workspace,
        domain_members,
        domain_agents,
        domain_messages,
        domain_posts,
        domain_tasks,
        domain_objectives,
        goal_candidates,
        experiences,
    )


def _member_v2(item: WorkspaceCoreMember) -> WorkspaceMember:
    return WorkspaceMember(
        workspace_id=item.workspace_id,
        user_id=item.user_id,
        role=WorkspaceRole(item.role),
    )


def _agent_v2(item: WorkspaceCoreAgent) -> WorkspaceAgent:
    return WorkspaceAgent(
        id=item.id,
        workspace_id=item.workspace_id,
        agent_id=item.agent_id,
        display_name=item.display_name,
        description=item.description,
        label=item.label,
        status=item.status,
        is_active=item.is_active,
    )


def _message_v2(item: WorkspaceCoreMessage) -> WorkspaceMessage:
    return WorkspaceMessage(
        id=item.id,
        workspace_id=item.workspace_id,
        sender_id=item.sender_id,
        sender_type=MessageSenderType(item.sender_type),
        content=item.content,
        mentions=list(item.mentions),
        parent_message_id=item.parent_message_id,
        metadata=dict(item.metadata),
        created_at=item.created_at,
    )


def _post_v2(item: WorkspaceCoreBlackboardPost) -> BlackboardPost:
    return BlackboardPost(
        id=item.id,
        workspace_id=item.workspace_id,
        author_id=item.author_id,
        title=item.title,
        content=item.content,
        status=BlackboardPostStatus(item.status),
        is_pinned=item.is_pinned,
        metadata=dict(item.metadata),
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _task_v2(item: WorkspaceCoreTask) -> WorkspaceTask:
    metadata = dict(item.metadata)
    _copy_metadata(metadata, "workspace_agent_binding_id", item.workspace_agent_id)
    _copy_metadata(metadata, CURRENT_ATTEMPT_ID, item.current_attempt_id)
    _copy_metadata(metadata, "current_attempt_number", item.current_attempt_number)
    _copy_metadata(
        metadata,
        "current_attempt_conversation_id",
        item.current_attempt_conversation_id,
    )
    _copy_metadata(
        metadata,
        "current_attempt_worker_binding_id",
        item.current_attempt_worker_binding_id,
    )
    _copy_metadata(
        metadata,
        "current_attempt_worker_agent_id",
        item.current_attempt_worker_agent_id,
    )
    _copy_metadata(metadata, "last_attempt_status", item.last_attempt_status)
    _copy_metadata(
        metadata,
        PENDING_LEADER_ADJUDICATION,
        True if item.pending_leader_adjudication else None,
    )
    _copy_metadata(metadata, "last_worker_report_type", item.last_worker_report_type)
    _copy_metadata(metadata, LAST_WORKER_REPORT_SUMMARY, item.last_worker_report_summary)
    _copy_metadata(
        metadata,
        "last_worker_report_artifacts",
        item.last_worker_report_artifacts or None,
    )
    _copy_metadata(
        metadata,
        "last_worker_report_verifications",
        item.last_worker_report_verifications or None,
    )
    if not item.created_by or item.created_at is None:
        raise ValueError("Workspace prompt task requires creator and creation timestamp")
    return WorkspaceTask(
        id=item.id,
        workspace_id=item.workspace_id,
        title=item.title,
        description=item.description,
        created_by=item.created_by,
        assignee_user_id=item.assignee_user_id,
        assignee_agent_id=item.assignee_agent_id,
        status=WorkspaceTaskStatus(item.status),
        priority=WorkspaceTaskPriority(item.priority or ""),
        estimated_effort=item.estimated_effort,
        blocker_reason=item.blocker_reason,
        metadata=metadata,
        created_at=item.created_at,
        updated_at=item.updated_at,
        completed_at=item.completed_at,
        archived_at=item.archived_at,
    )


def _objective_v2(item: WorkspaceCoreCyberObjective) -> CyberObjective:
    return CyberObjective(
        id=item.id,
        workspace_id=item.workspace_id,
        title=item.title,
        description=item.description,
        obj_type=CyberObjectiveType(item.obj_type),
        parent_id=item.parent_id,
        progress=item.progress,
        created_by=item.created_by,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _copy_metadata(metadata: dict[str, Any], key: str, value: object) -> None:
    if value is not None:
        metadata[key] = value


__all__ = [
    "WORKSPACE_PROMPT_CONTEXT_CONVERSATIONS_INJECT_V2",
    "WORKSPACE_PROMPT_CONTEXT_MODULE_V2",
    "WORKSPACE_PROMPT_CONTEXT_RUNTIME_INJECT_V2",
    "WORKSPACE_PROMPT_CONTEXT_SERVICE_V2",
    "WorkspacePromptContextProtocolV2",
    "WorkspacePromptContextServiceV2",
    "workspace_prompt_context_definition_v2",
]
