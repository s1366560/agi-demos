"""Atomic Workspace task-session creation for cloud clients."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any, Literal, Self

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.auth.user import User
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.routers.workspace_agent_policy import (
    CAPABILITY_VERSION,
    PermissionMode,
    ReasoningEffort,
    RouteTarget,
    _default_roles,
    _policy_response,
    _require_workspace_access,
    _validate_route,
)
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import (
    Conversation,
    Project,
    TaskSessionCreationReceiptModel,
    UserProject,
    WorkspaceAgentPolicyModel,
    WorkspaceMemberModel,
    WorkspaceMessageModel,
    WorkspaceModel,
)
from src.infrastructure.i18n import gettext as _

router = APIRouter(
    prefix="/api/v1/tenants/{tenant_id}/projects/{project_id}/task-sessions",
    tags=["task-sessions"],
)


class ExistingWorkspaceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["existing"]
    workspace_id: str


class CreateWorkspaceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["create"]
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    use_case: Literal["general", "programming", "conversation", "research", "operations"]
    collaboration_mode: Literal[
        "single_agent", "multi_agent_shared", "multi_agent_isolated", "autonomous"
    ]
    sandbox_code_root: str | None = None


class ConversationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=255)
    capability_mode: Literal["work", "code"]


class ComposerContextItemInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["attachment", "agent", "skill", "plugin", "command", "thread"]
    resource_id: str = Field(min_length=1, max_length=512)
    label: str = Field(min_length=1, max_length=255)
    metadata: dict[str, str | int | float | bool | None] | None = None

    @field_validator("resource_id", "label")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("context item text cannot be empty")
        return normalized

    @field_validator("metadata")
    @classmethod
    def validate_metadata_size(
        cls,
        value: dict[str, str | int | float | bool | None] | None,
    ) -> dict[str, str | int | float | bool | None] | None:
        if value is not None:
            encoded = json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode()
            if len(encoded) > 4 * 1024:
                raise ValueError("context item metadata is too large")
        return value


class InitialMessageInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=100_000)
    context_items: list[ComposerContextItemInput] = Field(
        default_factory=list[ComposerContextItemInput],
        max_length=32,
    )

    @model_validator(mode="after")
    def validate_unique_context_items(self) -> Self:
        identities = {(item.kind, item.resource_id) for item in self.context_items}
        if len(identities) != len(self.context_items):
            raise ValueError("context_items cannot contain duplicate resources")
        return self


class WorkspacePolicySelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=0)
    route: RouteTarget
    reasoning_effort: ReasoningEffort
    permission_mode: PermissionMode


class CreateTaskSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=1, max_length=255)
    workspace: ExistingWorkspaceInput | CreateWorkspaceInput = Field(discriminator="kind")
    conversation: ConversationInput
    initial_message: InitialMessageInput
    workspace_policy: WorkspacePolicySelection | None = None


@router.get("/capabilities")
async def task_session_capabilities() -> dict[str, Any]:
    return {
        "schema_version": 2,
        "atomic_creation": True,
        "initial_conversation_mode": "workspace",
        "initial_plan_mode": "plan",
        "workspace_agent_policy": True,
        "capability_version": CAPABILITY_VERSION,
    }


@router.post("", response_model=None)
async def create_task_session(
    tenant_id: str,
    project_id: str,
    body: CreateTaskSessionRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any] | JSONResponse:
    await _require_project_access(db, current_user, tenant_id, project_id)
    payload_hash = hashlib.sha256(
        json.dumps(body.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    receipt_result = await db.execute(
        refresh_select_statement(
            select(TaskSessionCreationReceiptModel).where(
                TaskSessionCreationReceiptModel.actor_user_id == current_user.id,
                TaskSessionCreationReceiptModel.tenant_id == tenant_id,
                TaskSessionCreationReceiptModel.project_id == project_id,
                TaskSessionCreationReceiptModel.idempotency_key == body.idempotency_key,
            )
        )
    )
    receipt = receipt_result.scalar_one_or_none()
    if receipt is not None:
        if receipt.payload_hash != payload_hash:
            return JSONResponse(
                status_code=status.HTTP_409_CONFLICT,
                content={
                    "code": "TASK_SESSION_IDEMPOTENCY_CONFLICT",
                    "detail": _("Task session idempotency conflict"),
                },
            )
        return {**receipt.response_json, "replayed": True}

    now = datetime.now(UTC)
    if body.workspace.kind == "existing":
        workspace = await _require_workspace_access(
            db,
            current_user,
            tenant_id,
            project_id,
            body.workspace.workspace_id,
            require_manager=body.workspace_policy is not None,
        )
    else:
        workspace = WorkspaceModel(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            project_id=project_id,
            name=body.workspace.name.strip(),
            description=body.workspace.description,
            created_by=current_user.id,
            is_archived=False,
            metadata_json={
                **body.workspace.metadata,
                "use_case": body.workspace.use_case,
                "collaboration_mode": body.workspace.collaboration_mode,
                **(
                    {"sandbox_code_root": body.workspace.sandbox_code_root}
                    if body.workspace.sandbox_code_root
                    else {}
                ),
            },
            office_status="inactive",
            created_at=now,
            updated_at=now,
        )
        db.add(workspace)
        db.add(
            WorkspaceMemberModel(
                id=str(uuid.uuid4()),
                workspace_id=workspace.id,
                user_id=current_user.id,
                role="owner",
                created_at=now,
            )
        )
        await db.flush()

    policy = await _apply_policy_selection(
        db,
        workspace,
        body.conversation.capability_mode,
        body.workspace_policy,
        current_user.id,
    )
    conversation = Conversation(
        id=str(uuid.uuid4()),
        project_id=project_id,
        tenant_id=tenant_id,
        user_id=current_user.id,
        title=body.conversation.title.strip(),
        status="active",
        agent_config={
            "selected_agent_id": "builtin:all-access",
            "capability_mode": body.conversation.capability_mode,
        },
        meta={"source": "task_session"},
        message_count=1,
        current_mode="plan",
        conversation_mode="workspace",
        workspace_id=workspace.id,
        created_at=now,
        updated_at=now,
    )
    message = WorkspaceMessageModel(
        id=str(uuid.uuid4()),
        workspace_id=workspace.id,
        sender_id=current_user.id,
        sender_type="human",
        content=body.initial_message.content.strip(),
        mentions_json=[],
        parent_message_id=None,
        metadata_json={
            "source": "task_session",
            "conversation_id": conversation.id,
            "runtime": "cloud",
            "context_items": [
                item.model_dump(mode="json", exclude_none=True)
                for item in body.initial_message.context_items
            ],
        },
        created_at=now,
    )
    db.add_all([conversation, message])
    await db.flush()
    policy_response = await _policy_response(db, workspace, policy)
    response = {
        "replayed": False,
        "workspace": _workspace_json(workspace),
        "conversation": _conversation_json(conversation),
        "initial_message": _message_json(message),
        "policy": policy_response.model_dump(mode="json"),
        "capability_version": CAPABILITY_VERSION,
    }
    db.add(
        TaskSessionCreationReceiptModel(
            id=str(uuid.uuid4()),
            actor_user_id=current_user.id,
            tenant_id=tenant_id,
            project_id=project_id,
            idempotency_key=body.idempotency_key,
            payload_hash=payload_hash,
            workspace_id=workspace.id,
            conversation_id=conversation.id,
            initial_message_id=message.id,
            response_json=response,
            created_at=now,
        )
    )
    await db.commit()
    return response


async def _require_project_access(
    db: AsyncSession,
    current_user: User,
    tenant_id: str,
    project_id: str,
) -> None:
    project_result = await db.execute(
        refresh_select_statement(
            select(Project.id).where(
                Project.id == project_id,
                Project.tenant_id == tenant_id,
            )
        )
    )
    if project_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail=_("Project not found"))
    membership_result = await db.execute(
        refresh_select_statement(
            select(UserProject.id).where(
                UserProject.project_id == project_id,
                UserProject.user_id == current_user.id,
            )
        )
    )
    if membership_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=403, detail=_("Access denied"))


async def _apply_policy_selection(
    db: AsyncSession,
    workspace: WorkspaceModel,
    capability_mode: Literal["work", "code"],
    selection: WorkspacePolicySelection | None,
    actor_id: str,
) -> WorkspaceAgentPolicyModel | None:
    result = await db.execute(
        refresh_select_statement(
            select(WorkspaceAgentPolicyModel)
            .where(WorkspaceAgentPolicyModel.workspace_id == workspace.id)
            .with_for_update()
        )
    )
    policy = result.scalar_one_or_none()
    if selection is None:
        return policy
    await _validate_route(db, workspace.tenant_id, selection.route)
    actual_revision = policy.revision if policy else 0
    if actual_revision != selection.expected_revision:
        raise HTTPException(status_code=409, detail=_("Workspace policy revision conflict"))
    roles = _default_roles() if policy is None else dict(policy.roles_json)
    if not roles.get("default"):
        roles["default"] = selection.route.model_dump()
    roles["default" if capability_mode == "work" else "coding"] = selection.route.model_dump()
    if policy is None:
        policy = WorkspaceAgentPolicyModel(
            workspace_id=workspace.id,
            tenant_id=workspace.tenant_id,
            project_id=workspace.project_id,
            revision=1,
            roles_json=roles,
            fallbacks_json=[],
            reasoning_effort=selection.reasoning_effort,
            permission_mode=selection.permission_mode,
            updated_by=actor_id,
        )
        db.add(policy)
    else:
        policy.revision += 1
        policy.roles_json = roles
        policy.reasoning_effort = selection.reasoning_effort
        policy.permission_mode = selection.permission_mode
        policy.updated_by = actor_id
    await db.flush()
    return policy


def _workspace_json(workspace: WorkspaceModel) -> dict[str, Any]:
    return {
        "id": workspace.id,
        "tenant_id": workspace.tenant_id,
        "project_id": workspace.project_id,
        "name": workspace.name,
        "description": workspace.description,
        "status": "open",
        "is_archived": workspace.is_archived,
        "created_at": workspace.created_at.isoformat(),
        "updated_at": (workspace.updated_at or workspace.created_at).isoformat(),
        "metadata": workspace.metadata_json,
    }


def _conversation_json(conversation: Conversation) -> dict[str, Any]:
    return {
        "id": conversation.id,
        "tenant_id": conversation.tenant_id,
        "project_id": conversation.project_id,
        "user_id": conversation.user_id,
        "title": conversation.title,
        "status": conversation.status,
        "message_count": conversation.message_count,
        "created_at": conversation.created_at.isoformat(),
        "updated_at": conversation.updated_at.isoformat() if conversation.updated_at else None,
        "summary": conversation.summary,
        "agent_config": conversation.agent_config,
        "metadata": conversation.meta,
        "conversation_mode": conversation.conversation_mode,
        "current_mode": conversation.current_mode,
        "workspace_id": conversation.workspace_id,
        "linked_workspace_task_id": conversation.linked_workspace_task_id,
        "participant_agents": conversation.participant_agents,
        "coordinator_agent_id": conversation.coordinator_agent_id,
        "focused_agent_id": conversation.focused_agent_id,
    }


def _message_json(message: WorkspaceMessageModel) -> dict[str, Any]:
    return {
        "id": message.id,
        "workspace_id": message.workspace_id,
        "sender_id": message.sender_id,
        "sender_type": message.sender_type,
        "content": message.content,
        "mentions": message.mentions_json,
        "parent_message_id": message.parent_message_id,
        "metadata": message.metadata_json,
        "created_at": message.created_at.isoformat(),
    }
