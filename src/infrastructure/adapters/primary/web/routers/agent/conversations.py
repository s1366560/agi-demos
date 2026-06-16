"""Conversation management endpoints.

CRUD operations for Agent conversations.
"""

import logging
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement, Select, Subquery

from src.application.constants.error_ids import AGENT_CONVERSATION_CREATE_FAILED
from src.application.services.conversation_events import publish_conversation_created
from src.configuration.factories import create_llm_client
from src.domain.model.agent import ConversationStatus
from src.domain.model.agent.conversation.agent_config import selected_agent_id_from_config
from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user,
    get_current_user_tenant,
)
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentExecutionEvent as AgentExecutionEventModel,
    Conversation as ConversationModel,
    Message as MessageModel,
    Project,
    ToolExecutionRecord,
    User,
    UserProject,
    WorkspaceMemberModel,
    WorkspaceModel,
)
from src.infrastructure.adapters.secondary.persistence.sql_conversation_repository import (
    SqlConversationRepository,
    conversation_activity_order,
)
from src.infrastructure.i18n import gettext as _

from .schemas import (
    ConversationResponse,
    CreateConversationRequest,
    PaginatedConversationsResponse,
    UpdateConversationConfigRequest,
    UpdateConversationModeRequest,
    UpdateConversationTitleRequest,
)
from .utils import get_container_with_db

if TYPE_CHECKING:
    from src.configuration.di_container import DIContainer
    from src.domain.model.agent.conversation.conversation import Conversation

router = APIRouter()
logger = logging.getLogger(__name__)


def _workspace_id_from_conversation_id(conversation_id: str) -> str | None:
    if not conversation_id.startswith("workspace-"):
        return None
    parts = conversation_id.split(":")
    if len(parts) < 2:
        return None
    workspace_id = parts[1].strip()
    return workspace_id or None


def _linked_workspace_task_id_from_conversation_id(conversation_id: str) -> str | None:
    if conversation_id.startswith("workspace-chat:"):
        return None
    if not conversation_id.startswith("workspace-"):
        return None
    parts = conversation_id.split(":")
    if len(parts) < 3:
        return None
    task_id = parts[2].strip()
    return task_id or None


def _workspace_id_for_response(conversation: "Conversation") -> str | None:
    return conversation.workspace_id or _workspace_id_from_conversation_id(conversation.id)


def _linked_workspace_task_id_for_response(conversation: "Conversation") -> str | None:
    return conversation.linked_workspace_task_id or _linked_workspace_task_id_from_conversation_id(
        conversation.id
    )


def _last_activity_subquery() -> Subquery:
    return (
        select(
            AgentExecutionEventModel.conversation_id,
            func.max(AgentExecutionEventModel.event_time_us).label("last_event_time_us"),
        )
        .group_by(AgentExecutionEventModel.conversation_id)
        .subquery("last_activity")
    )


def _ordered_conversation_query() -> Select[tuple[ConversationModel]]:
    last_activity_subq = _last_activity_subquery()
    return (
        select(ConversationModel)
        .outerjoin(
            last_activity_subq,
            ConversationModel.id == last_activity_subq.c.conversation_id,
        )
        .order_by(
            *conversation_activity_order(
                cast("ColumnElement[int]", last_activity_subq.c.last_event_time_us)
            )
        )
    )


def _workspace_link_filter(workspace_ids: set[str]) -> ColumnElement[bool]:
    conditions = [
        ConversationModel.workspace_id.in_(workspace_ids),
        ConversationModel.meta["workspace_id"].as_string().in_(workspace_ids),
    ]
    conditions.extend(
        ConversationModel.id.like(f"workspace-%:{workspace_id}:%") for workspace_id in workspace_ids
    )
    return or_(*conditions)


async def _ensure_project_access(
    db: AsyncSession,
    *,
    current_user: User,
    tenant_id: str,
    project_id: str,
) -> None:
    result = await db.execute(
        refresh_select_statement(
            select(UserProject.id)
            .join(Project, UserProject.project_id == Project.id)
            .where(
                and_(
                    UserProject.user_id == current_user.id,
                    UserProject.project_id == project_id,
                    Project.tenant_id == tenant_id,
                )
            )
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_("Access denied"),
        )


async def _ensure_selected_agent_access(
    agent_config: dict[str, Any] | None,
    *,
    container: "DIContainer",
    tenant_id: str,
    project_id: str,
) -> None:
    selected_agent_id = selected_agent_id_from_config(agent_config)
    if selected_agent_id is None:
        return

    registry = container.agent_registry()
    agent = await registry.get_by_id(
        selected_agent_id,
        tenant_id=tenant_id,
        project_id=project_id,
    )
    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_("Invalid agent selection"),
        )


async def _load_owned_conversation_row(
    db: AsyncSession,
    *,
    conversation_id: str,
    current_user: User,
    tenant_id: str,
) -> ConversationModel:
    conversation = await db.get(ConversationModel, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail=_("Conversation not found"))
    if conversation.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail=_("Conversation not found"))
    if conversation.user_id != current_user.id:
        raise HTTPException(status_code=403, detail=_("Access denied"))
    await _ensure_project_access(
        db,
        current_user=current_user,
        tenant_id=tenant_id,
        project_id=conversation.project_id,
    )
    return conversation


async def _workspace_name_by_id(
    db: AsyncSession,
    *,
    project_id: str,
    tenant_id: str,
    workspace_ids: set[str],
) -> dict[str, str]:
    if not workspace_ids:
        return {}
    result = await db.execute(
        refresh_select_statement(
            select(WorkspaceModel.id, WorkspaceModel.name).where(
                WorkspaceModel.project_id == project_id,
                WorkspaceModel.tenant_id == tenant_id,
                WorkspaceModel.id.in_(workspace_ids),
            )
        )
    )
    return {workspace_id: name for workspace_id, name in result.all()}


async def _ensure_workspace_access(
    db: AsyncSession,
    *,
    current_user: User,
    tenant_id: str,
    project_id: str,
    workspace_id: str,
) -> None:
    workspace_exists = (
        await db.execute(
            refresh_select_statement(
                select(WorkspaceModel.id).where(
                    WorkspaceModel.id == workspace_id,
                    WorkspaceModel.tenant_id == tenant_id,
                    WorkspaceModel.project_id == project_id,
                )
            )
        )
    ).scalar_one_or_none()
    if workspace_exists is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_("Workspace not found"))

    result = await db.execute(
        refresh_select_statement(
            select(WorkspaceMemberModel.id).where(
                WorkspaceMemberModel.workspace_id == workspace_id,
                WorkspaceMemberModel.user_id == current_user.id,
            )
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_("Workspace access required"),
        )


async def _accessible_workspace_ids(
    db: AsyncSession,
    *,
    current_user: User,
    tenant_id: str,
    project_id: str,
    workspace_ids: set[str],
) -> set[str]:
    if not workspace_ids:
        return set()

    result = await db.execute(
        refresh_select_statement(
            select(WorkspaceMemberModel.workspace_id)
            .join(WorkspaceModel, WorkspaceMemberModel.workspace_id == WorkspaceModel.id)
            .where(
                WorkspaceMemberModel.user_id == current_user.id,
                WorkspaceMemberModel.workspace_id.in_(workspace_ids),
                WorkspaceModel.tenant_id == tenant_id,
                WorkspaceModel.project_id == project_id,
            )
        )
    )
    return {str(workspace_id) for workspace_id in result.scalars().all()}


async def _list_workspace_conversations(
    db: AsyncSession,
    *,
    project_id: str,
    tenant_id: str,
    workspace_ids: set[str],
    status: ConversationStatus | None,
    limit: int | None = None,
    offset: int = 0,
) -> list["Conversation"]:
    if not workspace_ids:
        return []

    query = _ordered_conversation_query().where(
        ConversationModel.project_id == project_id,
        ConversationModel.tenant_id == tenant_id,
        _workspace_link_filter(workspace_ids),
    )
    if status is not None:
        query = query.where(ConversationModel.status == status.value)
    if limit is not None:
        query = query.offset(offset).limit(limit)

    result = await db.execute(refresh_select_statement(query))
    repo = SqlConversationRepository(db)
    return [d for c in result.scalars().all() if (d := repo._to_domain(c)) is not None]


async def _count_workspace_conversations(
    db: AsyncSession,
    *,
    project_id: str,
    tenant_id: str,
    workspace_id: str,
    status: ConversationStatus | None,
) -> int:
    query = (
        select(func.count())
        .select_from(ConversationModel)
        .where(
            ConversationModel.project_id == project_id,
            ConversationModel.tenant_id == tenant_id,
            _workspace_link_filter({workspace_id}),
        )
    )
    if status is not None:
        query = query.where(ConversationModel.status == status.value)
    result = await db.execute(refresh_select_statement(query))
    return result.scalar() or 0


def _merge_workspace_groups(
    base_conversations: list["Conversation"],
    workspace_conversations: list["Conversation"],
) -> list["Conversation"]:
    conversations_by_workspace: dict[str, list[Conversation]] = {}
    for conversation in workspace_conversations:
        workspace_id = _workspace_id_for_response(conversation)
        if workspace_id is None:
            continue
        conversations_by_workspace.setdefault(workspace_id, []).append(conversation)

    merged: list[Conversation] = []
    seen_conversation_ids: set[str] = set()
    expanded_workspace_ids: set[str] = set()

    def append_once(conversation: "Conversation") -> None:
        if conversation.id in seen_conversation_ids:
            return
        merged.append(conversation)
        seen_conversation_ids.add(conversation.id)

    for conversation in base_conversations:
        workspace_id = _workspace_id_for_response(conversation)
        if workspace_id is None:
            append_once(conversation)
            continue
        if workspace_id in expanded_workspace_ids:
            append_once(conversation)
            continue

        group = conversations_by_workspace.get(workspace_id, [])
        if not any(group_conversation.id == conversation.id for group_conversation in group):
            append_once(conversation)
        for group_conversation in group:
            append_once(group_conversation)
        expanded_workspace_ids.add(workspace_id)

    return merged


def _conversation_responses(
    conversations: list["Conversation"],
    *,
    workspace_names: dict[str, str],
) -> list[ConversationResponse]:
    return [
        ConversationResponse.from_domain(
            conversation,
            workspace_id=_workspace_id_for_response(conversation),
            linked_workspace_task_id=_linked_workspace_task_id_for_response(conversation),
            workspace_name=workspace_names.get(_workspace_id_for_response(conversation) or ""),
        )
        for conversation in conversations
    ]


async def _enforce_conversation_invariants(
    conversation: "Conversation",
    *,
    container: "DIContainer",
) -> None:
    """Run the post-mutation invariant checks for a Conversation.

    Raises :class:`HTTPException(422)` wrapping the underlying
    :class:`ConversationDomainError` / :class:`ParticipantNotPresentError`.

    Extracted from ``update_conversation_mode`` to keep the handler
    below the linter's complexity thresholds; ``POST /conversations``
    will share the same helper in G4-follow-up.
    """
    from src.application.services.agent.workspace_roster_validator import (
        WorkspaceRosterValidator,
    )
    from src.domain.model.agent.conversation.errors import (
        ConversationDomainError,
        ParticipantNotPresentError,
    )

    if conversation.conversation_mode is not None:
        try:
            conversation.assert_autonomous_invariants(conversation.conversation_mode)
        except ConversationDomainError as exc:
            raise HTTPException(status_code=422, detail=_("Invalid conversation state")) from exc

    if conversation.workspace_id and conversation.participant_agents:
        validator = WorkspaceRosterValidator(
            workspace_agent_repository=container.workspace_agent_repository()
        )
        try:
            await validator.assert_valid(conversation)
        except ParticipantNotPresentError as exc:
            raise HTTPException(status_code=422, detail=_("Invalid workspace roster")) from exc


@router.post("/conversations", response_model=ConversationResponse, status_code=201)
async def create_conversation(
    data: CreateConversationRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> ConversationResponse:
    """Create a new conversation."""
    try:
        assert request is not None
        await _ensure_project_access(
            db,
            current_user=current_user,
            tenant_id=tenant_id,
            project_id=data.project_id,
        )
        container = get_container_with_db(request, db)
        await _ensure_selected_agent_access(
            data.agent_config,
            container=container,
            tenant_id=tenant_id,
            project_id=data.project_id,
        )
        llm = await create_llm_client(tenant_id)
        use_case = container.create_conversation_use_case(llm)
        conversation = await use_case.execute(
            project_id=data.project_id,
            user_id=current_user.id,
            tenant_id=tenant_id,
            title=data.title,
            agent_config=data.agent_config,
        )
        await db.commit()
        try:
            redis_client = container.redis()
            if redis_client is not None:
                await publish_conversation_created(
                    redis_client=redis_client,
                    conversation=conversation,
                )
        except Exception:
            logger.exception(
                "Failed to publish conversation_created after conversation commit",
                extra={"conversation_id": conversation.id, "project_id": conversation.project_id},
            )
        return ConversationResponse.from_domain(conversation)

    except HTTPException:
        raise
    except (ValueError, AttributeError) as e:
        await db.rollback()
        logger.error(
            f"Validation error creating conversation: {e}",
            exc_info=True,
            extra={"error_id": AGENT_CONVERSATION_CREATE_FAILED},
        )
        raise HTTPException(status_code=400, detail=_("Invalid request")) from e
    except SQLAlchemyError as e:
        await db.rollback()
        logger.error(
            f"Database error creating conversation: {e}",
            exc_info=True,
            extra={"error_id": AGENT_CONVERSATION_CREATE_FAILED},
        )
        raise HTTPException(
            status_code=500,
            detail=_("A database error occurred while creating the conversation"),
        ) from e
    except Exception as e:
        await db.rollback()
        logger.error(
            f"Unexpected error creating conversation: {e}",
            exc_info=True,
            extra={"error_id": AGENT_CONVERSATION_CREATE_FAILED},
        )
        raise HTTPException(
            status_code=500,
            detail=_("An error occurred while creating the conversation"),
        ) from e


@router.get("/conversations", response_model=PaginatedConversationsResponse)
async def list_conversations(
    request: Request,
    project_id: str = Query(..., description="Project ID to filter by"),
    status: str | None = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=500, description="Maximum number to return"),
    offset: int = Query(0, ge=0, description="Number of results to skip"),
    workspace_id: str | None = Query(None, description="Filter by workspace ID"),
    group_by_workspace: bool = Query(
        False,
        description="Expand paged workspace entries so each returned workspace group is complete",
    ),
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> PaginatedConversationsResponse:
    """List conversations for a project with pagination."""
    try:
        assert request is not None
        await _ensure_project_access(
            db,
            current_user=current_user,
            tenant_id=tenant_id,
            project_id=project_id,
        )

        engine = db.get_bind()
        pool = engine.pool  # type: ignore[union-attr]
        pool_size = getattr(pool, "size", lambda: 0)()
        checked_out = getattr(pool, "checkedout", lambda: 0)()
        overflow = getattr(pool, "overflow", lambda: 0)()
        logger.debug(
            f"[Connection Pool] size={pool_size}, checked_out={checked_out}, "
            f"overflow={overflow}, queue_size={pool_size - checked_out}"
        )

        conv_status = ConversationStatus(status) if status else None
        requested_workspace_id = workspace_id.strip() if workspace_id else None

        if requested_workspace_id:
            await _ensure_workspace_access(
                db,
                current_user=current_user,
                tenant_id=tenant_id,
                project_id=project_id,
                workspace_id=requested_workspace_id,
            )
            conversations = await _list_workspace_conversations(
                db,
                project_id=project_id,
                tenant_id=tenant_id,
                workspace_ids={requested_workspace_id},
                status=conv_status,
                limit=limit,
                offset=offset,
            )
            total = await _count_workspace_conversations(
                db,
                project_id=project_id,
                tenant_id=tenant_id,
                workspace_id=requested_workspace_id,
                status=conv_status,
            )
        else:
            container = get_container_with_db(request, db)
            llm = await create_llm_client(tenant_id)
            use_case = container.list_conversations_use_case(llm)
            conversations = await use_case.execute(
                project_id=project_id,
                user_id=current_user.id,
                limit=limit,
                offset=offset,
                status=conv_status,
            )

            total = await use_case.count(
                project_id=project_id,
                user_id=current_user.id,
                status=conv_status,
            )

            workspace_ids: set[str] = set()
            for conversation in conversations:
                conversation_workspace_id = _workspace_id_for_response(conversation)
                if conversation_workspace_id is not None:
                    workspace_ids.add(conversation_workspace_id)
            if group_by_workspace and workspace_ids:
                workspace_ids = await _accessible_workspace_ids(
                    db,
                    current_user=current_user,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    workspace_ids=workspace_ids,
                )
                workspace_conversations = await _list_workspace_conversations(
                    db,
                    project_id=project_id,
                    tenant_id=tenant_id,
                    workspace_ids=workspace_ids,
                    status=conv_status,
                )
                conversations = _merge_workspace_groups(conversations, workspace_conversations)

        response_workspace_ids: set[str] = set()
        for conversation in conversations:
            conversation_workspace_id = _workspace_id_for_response(conversation)
            if conversation_workspace_id is not None:
                response_workspace_ids.add(conversation_workspace_id)
        workspace_names = await _workspace_name_by_id(
            db,
            project_id=project_id,
            tenant_id=tenant_id,
            workspace_ids=response_workspace_ids,
        )
        items = _conversation_responses(conversations, workspace_names=workspace_names)
        next_offset = min(offset + limit, total)
        unique_item_count = len({item.id for item in items})
        has_more = next_offset < total and unique_item_count < total

        return PaginatedConversationsResponse(
            items=items,
            total=total,
            has_more=has_more,
            offset=offset,
            limit=limit,
            next_offset=next_offset,
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error listing conversations")
        raise HTTPException(status_code=500, detail=_("Failed to list conversations")) from exc


@router.get("/conversations/{conversation_id}", response_model=ConversationResponse)
async def get_conversation(
    conversation_id: str,
    request: Request,
    project_id: str = Query(..., description="Project ID for authorization"),
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> ConversationResponse:
    """Get a conversation by ID."""
    try:
        assert request is not None
        await _ensure_project_access(
            db,
            current_user=current_user,
            tenant_id=tenant_id,
            project_id=project_id,
        )
        container = get_container_with_db(request, db)
        llm = await create_llm_client(tenant_id)
        use_case = container.get_conversation_use_case(llm)

        conversation = await use_case.execute(
            conversation_id=conversation_id,
            project_id=project_id,
            user_id=current_user.id,
        )

        if not conversation:
            raise HTTPException(status_code=404, detail=_("Conversation not found"))

        return ConversationResponse.from_domain(conversation)

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error getting conversation")
        raise HTTPException(status_code=500, detail=_("Failed to get conversation")) from exc


@router.get("/conversations/{conversation_id}/context-status")
async def get_context_status(
    conversation_id: str,
    request: Request,
    project_id: str = Query(..., description="Project ID for authorization"),
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get context window status for a conversation.

    Returns the cached context summary info (if any) and message count,
    so the frontend can restore the context status indicator after page
    refresh or conversation switch.
    """
    try:
        assert request is not None
        await _ensure_project_access(
            db,
            current_user=current_user,
            tenant_id=tenant_id,
            project_id=project_id,
        )
        container = get_container_with_db(request, db)
        llm = await create_llm_client(tenant_id)
        use_case = container.get_conversation_use_case(llm)

        conversation = await use_case.execute(
            conversation_id=conversation_id,
            project_id=project_id,
            user_id=current_user.id,
        )
        if not conversation:
            raise HTTPException(status_code=404, detail=_("Conversation not found"))

        # Load cached context summary from conversation meta
        adapter = container.context_summary_adapter()
        summary = await adapter.get_summary(conversation_id)

        result: dict[str, Any] = {
            "conversation_id": conversation_id,
            "message_count": conversation.message_count,
            "has_summary": summary is not None,
        }

        if summary:
            result.update(
                {
                    "summary_tokens": summary.summary_tokens,
                    "messages_in_summary": summary.messages_covered_count,
                    "compression_level": summary.compression_level,
                    "from_cache": True,
                }
            )
        else:
            result.update(
                {
                    "summary_tokens": 0,
                    "messages_in_summary": 0,
                    "compression_level": "none",
                    "from_cache": False,
                }
            )

        return result

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error getting context status")
        raise HTTPException(status_code=500, detail=_("Failed to get context status")) from exc


@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: str,
    request: Request,
    project_id: str = Query(..., description="Project ID for authorization"),
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a conversation and all its messages."""
    try:
        assert request is not None
        await _ensure_project_access(
            db,
            current_user=current_user,
            tenant_id=tenant_id,
            project_id=project_id,
        )
        container = get_container_with_db(request, db)
        llm = await create_llm_client(tenant_id)
        agent_service = container.agent_service(llm)

        conversation = await agent_service.get_conversation(
            conversation_id=conversation_id,
            project_id=project_id,
            user_id=current_user.id,
        )

        if not conversation:
            raise HTTPException(status_code=404, detail=_("Conversation not found"))

        await agent_service.delete_conversation(
            conversation_id=conversation_id,
            project_id=project_id,
            user_id=current_user.id,
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error deleting conversation")
        raise HTTPException(status_code=500, detail=_("Failed to delete conversation")) from exc


@router.patch("/conversations/{conversation_id}/title", response_model=ConversationResponse)
async def update_conversation_title(
    conversation_id: str,
    data: UpdateConversationTitleRequest,
    request: Request,
    project_id: str = Query(..., description="Project ID for authorization"),
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> ConversationResponse:
    """Update conversation title."""
    try:
        assert request is not None
        await _ensure_project_access(
            db,
            current_user=current_user,
            tenant_id=tenant_id,
            project_id=project_id,
        )
        container = get_container_with_db(request, db)
        llm = await create_llm_client(tenant_id)
        agent_service = container.agent_service(llm)

        conversation = await agent_service.get_conversation(
            conversation_id=conversation_id,
            project_id=project_id,
            user_id=current_user.id,
        )

        if not conversation:
            raise HTTPException(status_code=404, detail=_("Conversation not found"))

        updated_conversation = await agent_service.update_conversation_title(
            conversation_id=conversation_id,
            project_id=project_id,
            user_id=current_user.id,
            title=data.title,
        )

        assert updated_conversation is not None
        return ConversationResponse.from_domain(updated_conversation)

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error updating conversation title")
        raise HTTPException(
            status_code=500, detail=_("Failed to update conversation title")
        ) from exc


@router.patch("/conversations/{conversation_id}/config", response_model=ConversationResponse)
async def update_conversation_config(
    conversation_id: str,
    data: UpdateConversationConfigRequest,
    request: Request,
    project_id: str = Query(..., description="Project ID for authorization"),
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> ConversationResponse:
    """Update conversation-level LLM configuration (model override, LLM params)."""
    try:
        assert request is not None
        await _ensure_project_access(
            db,
            current_user=current_user,
            tenant_id=tenant_id,
            project_id=project_id,
        )
        container = get_container_with_db(request, db)
        llm = await create_llm_client(tenant_id)
        agent_service = container.agent_service(llm)

        conversation = await agent_service.get_conversation(
            conversation_id=conversation_id,
            project_id=project_id,
            user_id=current_user.id,
        )
        if not conversation:
            raise HTTPException(status_code=404, detail=_("Conversation not found"))

        config_patch: dict[str, Any] = {}
        if data.llm_model_override is not None:
            cleaned = data.llm_model_override.strip()
            config_patch["llm_model_override"] = cleaned or None
        if data.llm_overrides is not None:
            cleaned_overrides = {k: v for k, v in data.llm_overrides.items() if v is not None}
            config_patch["llm_overrides"] = cleaned_overrides or None

        conversation.update_agent_config(config_patch)
        await agent_service._conversation_repo.save(conversation)
        await db.commit()

        return ConversationResponse.from_domain(conversation)

    except HTTPException:
        raise
    except Exception as exc:
        await db.rollback()
        logger.exception("Error updating conversation config")
        raise HTTPException(
            status_code=500, detail=_("Failed to update conversation config")
        ) from exc


@router.patch("/conversations/{conversation_id}/mode", response_model=ConversationResponse)
async def update_conversation_mode(
    conversation_id: str,
    data: UpdateConversationModeRequest,
    request: Request,
    project_id: str = Query(..., description="Project ID for authorization"),
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> ConversationResponse:
    """Update a conversation's mode override.

    Allows switching between ``single_agent``, ``multi_agent_shared``,
    ``multi_agent_isolated`` and ``autonomous`` modes. Goal + budget
    constraints for autonomous mode are sourced from the linked
    Workspace / WorkspaceTask (Track G) — not from this payload.
    """
    from src.domain.model.agent.conversation.conversation_mode import ConversationMode

    try:
        assert request is not None
        await _ensure_project_access(
            db,
            current_user=current_user,
            tenant_id=tenant_id,
            project_id=project_id,
        )
        container = get_container_with_db(request, db)
        llm = await create_llm_client(tenant_id)
        agent_service = container.agent_service(llm)

        conversation = await agent_service.get_conversation(
            conversation_id=conversation_id,
            project_id=project_id,
            user_id=current_user.id,
        )
        if not conversation:
            raise HTTPException(status_code=404, detail=_("Conversation not found"))

        fields = data.model_fields_set

        if "conversation_mode" in fields:
            raw_mode = data.conversation_mode
            if raw_mode is None:
                conversation.conversation_mode = None
            else:
                try:
                    conversation.conversation_mode = ConversationMode(raw_mode)
                except ValueError as exc:
                    raise HTTPException(
                        status_code=422,
                        detail=_("Invalid conversation mode"),
                    ) from exc

        # Track G2 — workspace linkage fields. Both are explicitly-optional:
        # presence in ``model_fields_set`` means apply the value (including
        # clearing to ``None``); absence means leave untouched.
        if "workspace_id" in fields:
            conversation.workspace_id = data.workspace_id
        if "linked_workspace_task_id" in fields:
            conversation.linked_workspace_task_id = data.linked_workspace_task_id

        # Enforce post-mutation invariants (autonomous + workspace roster).
        await _enforce_conversation_invariants(conversation, container=container)

        conversation.updated_at = datetime.now(UTC)
        await agent_service._conversation_repo.save(conversation)
        await db.commit()

        return ConversationResponse.from_domain(conversation)

    except HTTPException:
        await db.rollback()
        raise
    except ValueError as e:
        await db.rollback()
        logger.warning(f"Invalid conversation mode update for {conversation_id}: {e}")
        raise HTTPException(status_code=422, detail=_("Invalid conversation mode update")) from e
    except Exception as exc:
        await db.rollback()
        logger.exception("Error updating conversation mode")
        raise HTTPException(
            status_code=500, detail=_("Failed to update conversation mode")
        ) from exc


@router.post(
    "/conversations/{conversation_id}/generate-title",
    response_model=ConversationResponse,
    deprecated=True,
)
async def generate_conversation_title(
    conversation_id: str,
    request: Request,
    project_id: str = Query(..., description="Project ID for authorization"),
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> ConversationResponse:
    """
    Generate and update a friendly conversation title based on the first user message.

    .. deprecated::
        Title generation is now handled automatically by the backend.
    """
    try:
        assert request is not None
        await _ensure_project_access(
            db,
            current_user=current_user,
            tenant_id=tenant_id,
            project_id=project_id,
        )
        container = get_container_with_db(request, db)
        llm = await create_llm_client(tenant_id)
        agent_service = container.agent_service(llm)

        conversation = await agent_service.get_conversation(
            conversation_id=conversation_id,
            project_id=project_id,
            user_id=current_user.id,
        )

        if not conversation:
            raise HTTPException(status_code=404, detail=_("Conversation not found"))

        message_events = await agent_service.get_conversation_messages(
            conversation_id=conversation_id,
            project_id=project_id,
            user_id=current_user.id,
            limit=10,
        )

        first_user_message = None
        for event in message_events:
            if event.event_type == "user_message":
                first_user_message = event.event_data.get("content", "")
                break

        if not first_user_message:
            raise HTTPException(
                status_code=400, detail=_("No user message found to generate title from")
            )

        # Use DB provider config (same as ReActAgent) for title generation
        title_llm = await agent_service.get_title_llm()
        generated_title = await agent_service.generate_conversation_title(
            first_message=first_user_message,
            llm=title_llm,
        )

        updated_conversation = await agent_service.update_conversation_title(
            conversation_id=conversation_id,
            project_id=project_id,
            user_id=current_user.id,
            title=generated_title,
        )

        if not updated_conversation:
            raise HTTPException(status_code=500, detail=_("Failed to update conversation title"))

        return ConversationResponse.from_domain(updated_conversation)

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error generating conversation title")
        raise HTTPException(
            status_code=500, detail=_("Failed to generate conversation title")
        ) from exc


@router.post(
    "/conversations/{conversation_id}/summary",
    response_model=ConversationResponse,
)
async def generate_summary(
    conversation_id: str,
    request: Request,
    project_id: str = Query(..., description="Project ID for authorization"),
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> ConversationResponse:
    """Generate an AI summary of the conversation."""
    try:
        assert request is not None
        await _ensure_project_access(
            db,
            current_user=current_user,
            tenant_id=tenant_id,
            project_id=project_id,
        )
        container = get_container_with_db(request, db)
        llm = await create_llm_client(tenant_id)
        agent_service = container.agent_service(llm)

        conversation = await agent_service.get_conversation(
            conversation_id=conversation_id,
            project_id=project_id,
            user_id=current_user.id,
        )
        if not conversation:
            raise HTTPException(status_code=404, detail=_("Conversation not found"))

        message_events = await agent_service.get_conversation_messages(
            conversation_id=conversation_id,
            project_id=project_id,
            user_id=current_user.id,
            limit=50,
        )

        messages_text = ""
        for event in message_events:
            role = event.event_type.replace("_message", "")
            content = event.event_data.get("content", "")
            if content:
                messages_text += f"{role}: {content[:500]}\n"

        if not messages_text.strip():
            raise HTTPException(
                status_code=400,
                detail=_("No messages found to generate summary from"),
            )

        title_llm = await agent_service.get_title_llm()
        from src.domain.llm_providers.llm_types import Message as LLMMessage

        prompt = (
            "Summarize this conversation in 1-2 concise sentences. "
            "Focus on the main topic and key outcomes.\n\n"
            f"Messages:\n{messages_text[:3000]}\n\nSummary:"
        )
        response = await title_llm.ainvoke(
            [
                LLMMessage.system(
                    "You are a helpful assistant that generates concise conversation summaries."
                ),
                LLMMessage.user(prompt),
            ]
        )
        summary = response.content.strip()
        if len(summary) > 500:
            summary = summary[:497] + "..."

        conversation.summary = summary
        from datetime import datetime

        conversation.updated_at = datetime.now(UTC)
        await agent_service._conversation_repo.save_and_commit(conversation)  # type: ignore[attr-defined]

        return ConversationResponse.from_domain(conversation)

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error generating conversation summary")
        raise HTTPException(
            status_code=500,
            detail=_("Failed to generate conversation summary"),
        ) from exc


@router.post("/conversations/{conversation_id}/fork")
async def fork_conversation(
    conversation_id: str,
    message_id: str = Query(..., description="Message ID to fork from"),
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Fork a conversation from a specific message point."""
    try:
        original = await _load_owned_conversation_row(
            db,
            conversation_id=conversation_id,
            current_user=current_user,
            tenant_id=tenant_id,
        )

        new_id = str(uuid.uuid4())
        new_conv = ConversationModel(
            id=new_id,
            project_id=original.project_id,
            tenant_id=original.tenant_id,
            user_id=current_user.id,
            title=f"{original.title} (fork)",
            status="active",
            parent_conversation_id=conversation_id,
            branch_point_message_id=message_id,
        )
        db.add(new_conv)

        query = (
            select(MessageModel)
            .where(MessageModel.conversation_id == conversation_id)
            .order_by(MessageModel.created_at)
        )
        result = await db.execute(refresh_select_statement(query))
        messages = result.scalars().all()

        copied = 0
        for msg in messages:
            new_msg = MessageModel(
                id=str(uuid.uuid4()),
                conversation_id=new_id,
                role=msg.role,
                content=msg.content,
                message_type=msg.message_type,
                created_at=msg.created_at,
            )
            db.add(new_msg)
            copied += 1
            if msg.id == message_id:
                break

        new_conv.message_count = copied
        await db.commit()

        return {
            "id": new_conv.id,
            "title": new_conv.title,
            "parent_id": conversation_id,
        }

    except HTTPException:
        raise
    except Exception as exc:
        await db.rollback()
        logger.exception("Error forking conversation")
        raise HTTPException(
            status_code=500,
            detail=_("Failed to fork conversation"),
        ) from exc


@router.put("/conversations/{conversation_id}/messages/{message_id}")
async def edit_message(
    conversation_id: str,
    message_id: str,
    data: dict[str, Any],
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Edit a message and increment version."""
    try:
        await _load_owned_conversation_row(
            db,
            conversation_id=conversation_id,
            current_user=current_user,
            tenant_id=tenant_id,
        )
        msg = await db.get(MessageModel, message_id)
        if not msg or msg.conversation_id != conversation_id:
            raise HTTPException(status_code=404, detail=_("Message not found"))

        if msg.original_content is None:
            msg.original_content = msg.content
        msg.content = data.get("content", msg.content)
        msg.version = (msg.version or 1) + 1
        msg.edited_at = datetime.now(UTC)

        await db.commit()
        return {
            "id": msg.id,
            "content": msg.content,
            "version": msg.version,
            "edited_at": str(msg.edited_at),
        }

    except HTTPException:
        raise
    except Exception as exc:
        await db.rollback()
        logger.exception("Error editing message")
        raise HTTPException(
            status_code=500,
            detail=_("Failed to edit message"),
        ) from exc


@router.post("/conversations/{conversation_id}/tools/{execution_id}/undo")
async def request_tool_undo(
    conversation_id: str,
    execution_id: str,
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Request undo of a tool execution.

    Creates a follow-up user message asking the agent to undo
    the specified tool execution.
    """
    try:
        await _load_owned_conversation_row(
            db,
            conversation_id=conversation_id,
            current_user=current_user,
            tenant_id=tenant_id,
        )
        exec_record = await db.get(ToolExecutionRecord, execution_id)
        if not exec_record:
            raise HTTPException(status_code=404, detail=_("Tool execution not found"))

        if exec_record.conversation_id != conversation_id:
            raise HTTPException(status_code=404, detail=_("Tool execution not found"))

        undo_msg = MessageModel(
            id=str(uuid.uuid4()),
            conversation_id=conversation_id,
            role="user",
            content=(
                f"Please undo the previous tool execution: {exec_record.tool_name}. "
                "Revert any changes made."
            ),
            created_at=datetime.now(UTC),
        )
        db.add(undo_msg)
        await db.commit()

        return {
            "status": "undo_requested",
            "message_id": undo_msg.id,
            "tool_name": exec_record.tool_name,
        }

    except HTTPException:
        raise
    except Exception as exc:
        await db.rollback()
        logger.exception("Error requesting tool undo")
        raise HTTPException(
            status_code=500,
            detail=_("Failed to request tool undo"),
        ) from exc
