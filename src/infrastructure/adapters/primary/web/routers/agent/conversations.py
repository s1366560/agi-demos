"""Conversation management endpoints.

CRUD operations for Agent conversations.
"""

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import and_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.constants.error_ids import AGENT_CONVERSATION_CREATE_FAILED
from src.domain.model.agent import ConversationStatus
from src.domain.ports.services.workspace_authority_port import (
    WorkspaceAuthorityAccessDeniedError,
    WorkspaceAuthorityNotFoundError,
    WorkspaceAuthorityScope,
    WorkspaceAuthorityUnavailableError,
)
from src.infrastructure.adapters.primary.web.conversation_collection_http_application_authority_v2 import (
    ConversationCollectionHttpApplicationAuthorityV2,
    conversation_create_http_application_authority_dependency_v2,
    conversation_list_http_application_authority_dependency_v2,
)
from src.infrastructure.adapters.primary.web.conversation_config_http_application_authority_v2 import (
    ConversationConfigHttpApplicationAuthorityV2,
    conversation_config_http_application_authority_dependency_v2,
)
from src.infrastructure.adapters.primary.web.conversation_context_status_http_application_authority_v2 import (
    ConversationContextStatusHttpApplicationAuthorityV2,
    conversation_context_status_http_application_authority_dependency_v2,
)
from src.infrastructure.adapters.primary.web.conversation_generation_http_application_authority_v2 import (
    ConversationGenerationHttpApplicationAuthorityV2,
    conversation_generation_http_application_authority_dependency_v2,
)
from src.infrastructure.adapters.primary.web.conversation_http_application_authority_v2 import (
    ConversationHttpApplicationAuthorityV2,
    conversation_http_application_authority_dependency_v2,
)
from src.infrastructure.adapters.primary.web.conversation_revision_http_application_authority_v2 import (
    ConversationRevisionHttpApplicationAuthorityV2,
    conversation_revision_http_application_authority_dependency_v2,
)
from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user,
    get_current_user_tenant,
)
from src.infrastructure.adapters.primary.web.workspace_authority import (
    get_workspace_authority,
    workspace_core_unavailable_error,
)
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import (
    Project,
    User,
    UserProject,
)
from src.infrastructure.i18n import gettext as _
from src.infrastructure.plugins.v2.conversation_collection_services import (
    InvalidConversationAgentSelectionV2,
)
from src.infrastructure.plugins.v2.conversation_config_services import ConversationConfigPatchV2
from src.infrastructure.plugins.v2.conversation_generation_services import (
    ConversationGenerationSourceMissingV2,
)
from src.infrastructure.plugins.v2.conversation_revision_services import (
    ConversationRevisionAccessDeniedV2,
    ConversationRevisionConversationNotFoundV2,
    ConversationRevisionMessageNotFoundV2,
    ConversationRevisionToolExecutionNotFoundV2,
)
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error

from .schemas import (
    ConversationResponse,
    CreateConversationRequest,
    PaginatedConversationsResponse,
    UpdateConversationConfigRequest,
    UpdateConversationModeRequest,
    UpdateConversationTitleRequest,
)

if TYPE_CHECKING:
    from src.domain.model.agent.conversation.conversation import Conversation

router = APIRouter()
logger = logging.getLogger(__name__)

CONVERSATION_LIST_DEFAULT_LIMIT = 10
WORKSPACE_GROUP_EXPANSION_HARD_LIMIT = 25


def _workspace_group_expansion_limit(page_limit: int) -> int:
    return min(page_limit, WORKSPACE_GROUP_EXPANSION_HARD_LIMIT)


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


def _conversation_list_filters(
    workspace_id: str | None,
    *,
    unbound_only: bool,
) -> tuple[str | None, bool]:
    requested_workspace_id = workspace_id.strip() if workspace_id else None
    requested_unbound_only = unbound_only is True
    if requested_workspace_id and requested_unbound_only:
        raise HTTPException(
            status_code=422,
            detail=_("Workspace and unbound filters cannot be combined"),
        )
    return requested_workspace_id, requested_unbound_only


async def _ensure_project_access(
    db: AsyncSession,
    *,
    current_user: User,
    project_id: str,
    tenant_id: str | None = None,
) -> str:
    conditions = [
        UserProject.user_id == current_user.id,
        UserProject.project_id == project_id,
    ]
    if tenant_id is not None:
        conditions.append(Project.tenant_id == tenant_id)

    result = await db.execute(
        refresh_select_statement(
            select(Project.tenant_id)
            .select_from(UserProject)
            .join(Project, UserProject.project_id == Project.id)
            .where(and_(*conditions))
        )
    )
    project_tenant_id = result.scalar_one_or_none()
    if project_tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_("Access denied"),
        )
    return str(project_tenant_id)


async def _workspace_name_by_id(
    request: Request,
    *,
    current_user: User,
    project_id: str,
    tenant_id: str,
    workspace_ids: set[str],
) -> dict[str, str]:
    if not workspace_ids:
        return {}
    profiles = await get_workspace_authority(request).accessible_profiles(
        tenant_id=tenant_id,
        project_id=project_id,
        workspace_ids=workspace_ids,
        user_id=str(current_user.id),
        is_superuser=bool(getattr(current_user, "is_superuser", False)),
    )
    return {workspace_id: profile.name for workspace_id, profile in profiles.items()}


async def _ensure_workspace_access(
    db: AsyncSession,
    *,
    request: Request,
    current_user: User,
    tenant_id: str,
    project_id: str,
    workspace_id: str,
) -> None:
    authority = get_workspace_authority(request)
    try:
        await authority.get_profile(
            WorkspaceAuthorityScope(
                tenant_id=tenant_id,
                project_id=project_id,
                workspace_id=workspace_id,
                user_id=str(current_user.id),
                is_superuser=bool(getattr(current_user, "is_superuser", False)),
            )
        )
    except WorkspaceAuthorityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=_("Workspace not found")) from exc
    except WorkspaceAuthorityAccessDeniedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_("Workspace access required"),
        ) from exc
    except WorkspaceAuthorityUnavailableError as exc:
        raise workspace_core_unavailable_error() from exc


async def _ensure_workspace_task_linkage(
    request: Request,
    *,
    current_user: User,
    linked_workspace_task_id: str,
    workspace_id: str,
    project_id: str,
    tenant_id: str,
) -> None:
    authority = get_workspace_authority(request)
    try:
        valid = await authority.has_task(
            WorkspaceAuthorityScope(
                tenant_id=tenant_id,
                project_id=project_id,
                workspace_id=workspace_id,
                user_id=str(current_user.id),
                is_superuser=bool(getattr(current_user, "is_superuser", False)),
            ),
            linked_workspace_task_id,
        )
    except (WorkspaceAuthorityAccessDeniedError, WorkspaceAuthorityNotFoundError):
        valid = False
    except WorkspaceAuthorityUnavailableError as exc:
        raise workspace_core_unavailable_error() from exc
    if not valid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=_("Invalid workspace task linkage"),
        )


async def _ensure_workspace_linkage_access(
    db: AsyncSession,
    *,
    request: Request,
    conversation: "Conversation",
    data: UpdateConversationModeRequest,
    current_user: User,
    tenant_id: str,
    project_id: str,
) -> None:
    fields = data.model_fields_set
    workspace_id = data.workspace_id if "workspace_id" in fields else conversation.workspace_id
    linked_workspace_task_id = (
        data.linked_workspace_task_id
        if "linked_workspace_task_id" in fields
        else conversation.linked_workspace_task_id
    )

    if workspace_id:
        await _ensure_workspace_access(
            db,
            request=request,
            current_user=current_user,
            tenant_id=tenant_id,
            project_id=project_id,
            workspace_id=workspace_id,
        )
    if not linked_workspace_task_id:
        return
    if not workspace_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=_("Invalid workspace task linkage"),
        )
    await _ensure_workspace_task_linkage(
        request,
        current_user=current_user,
        linked_workspace_task_id=linked_workspace_task_id,
        workspace_id=workspace_id,
        project_id=project_id,
        tenant_id=tenant_id,
    )


async def _accessible_workspace_ids(
    request: Request,
    *,
    current_user: User,
    tenant_id: str,
    project_id: str,
    workspace_ids: set[str],
) -> set[str]:
    if not workspace_ids:
        return set()

    profiles = await get_workspace_authority(request).accessible_profiles(
        tenant_id=tenant_id,
        project_id=project_id,
        workspace_ids=workspace_ids,
        user_id=str(current_user.id),
        is_superuser=bool(getattr(current_user, "is_superuser", False)),
    )
    return set(profiles)


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
    request: Request,
    current_user: User,
) -> None:
    """Run the post-mutation invariant checks for a Conversation.

    Raises :class:`HTTPException(422)` wrapping the underlying
    :class:`ConversationDomainError` / :class:`ParticipantNotPresentError`.

    Extracted from ``update_conversation_mode`` to keep the handler
    below the linter's complexity thresholds; ``POST /conversations``
    will share the same helper in G4-follow-up.
    """
    from src.domain.model.agent.conversation.errors import (
        ConversationDomainError,
    )

    if conversation.conversation_mode is not None:
        try:
            conversation.assert_autonomous_invariants(conversation.conversation_mode)
        except ConversationDomainError as exc:
            raise HTTPException(status_code=422, detail=_("Invalid conversation state")) from exc

    if conversation.workspace_id and conversation.participant_agents:
        try:
            bindings = await get_workspace_authority(request).list_agents(
                WorkspaceAuthorityScope(
                    tenant_id=conversation.tenant_id,
                    project_id=conversation.project_id,
                    workspace_id=conversation.workspace_id,
                    user_id=str(current_user.id),
                    is_superuser=bool(getattr(current_user, "is_superuser", False)),
                ),
                active_only=True,
            )
        except (WorkspaceAuthorityAccessDeniedError, WorkspaceAuthorityNotFoundError) as exc:
            raise HTTPException(status_code=422, detail=_("Invalid workspace roster")) from exc
        except WorkspaceAuthorityUnavailableError as exc:
            raise workspace_core_unavailable_error() from exc
        workspace_agent_ids = {binding.agent_id for binding in bindings}
        if not set(conversation.participant_agents).issubset(workspace_agent_ids):
            raise HTTPException(status_code=422, detail=_("Invalid workspace roster"))


@router.post("/conversations", response_model=ConversationResponse, status_code=201)
async def create_conversation(
    data: CreateConversationRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
    conversation_collection: ConversationCollectionHttpApplicationAuthorityV2 = Depends(
        conversation_create_http_application_authority_dependency_v2
    ),
) -> ConversationResponse:
    """Create a new conversation."""
    try:
        assert request is not None
        tenant_id = await _ensure_project_access(
            db,
            current_user=current_user,
            project_id=data.project_id,
        )
        if data.workspace_id:
            await _ensure_workspace_access(
                db,
                request=request,
                current_user=current_user,
                tenant_id=tenant_id,
                project_id=data.project_id,
                workspace_id=data.workspace_id,
            )
        conversation = await conversation_collection.service.create_conversation(
            project_id=data.project_id,
            user_id=current_user.id,
            tenant_id=tenant_id,
            title=data.title,
            agent_config=data.agent_config,
            workspace_id=data.workspace_id,
        )
        await db.commit()
        try:
            await conversation_collection.service.after_create_committed(conversation)
        except Exception:
            logger.exception(
                "Failed to dispatch conversation.created after conversation commit",
                extra={"conversation_id": conversation.id, "project_id": conversation.project_id},
            )
        return ConversationResponse.from_domain(conversation)

    except InvalidConversationAgentSelectionV2 as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_("Invalid agent selection"),
        ) from exc
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
    limit: int = Query(
        CONVERSATION_LIST_DEFAULT_LIMIT,
        ge=1,
        le=500,
        description="Maximum number to return",
    ),
    offset: int = Query(0, ge=0, description="Number of results to skip"),
    workspace_id: str | None = Query(None, description="Filter by workspace ID"),
    unbound_only: bool = Query(
        False,
        description="Return only conversations without an effective workspace binding",
    ),
    group_by_workspace: bool = Query(
        False,
        description="Expand paged workspace entries so each returned workspace group is complete",
    ),
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
    conversation_collection: ConversationCollectionHttpApplicationAuthorityV2 = Depends(
        conversation_list_http_application_authority_dependency_v2
    ),
) -> PaginatedConversationsResponse:
    """List conversations for a project with pagination."""
    try:
        assert request is not None
        tenant_id = await _ensure_project_access(
            db,
            current_user=current_user,
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
        requested_workspace_id, requested_unbound_only = _conversation_list_filters(
            workspace_id,
            unbound_only=unbound_only,
        )

        if requested_unbound_only:
            conversations = await conversation_collection.service.list_unbound_conversations(
                project_id=project_id,
                tenant_id=tenant_id,
                user_id=current_user.id,
                status=conv_status,
                limit=limit,
                offset=offset,
            )
            total = await conversation_collection.service.count_unbound_conversations(
                project_id=project_id,
                tenant_id=tenant_id,
                user_id=current_user.id,
                status=conv_status,
            )
        elif requested_workspace_id:
            await _ensure_workspace_access(
                db,
                request=request,
                current_user=current_user,
                tenant_id=tenant_id,
                project_id=project_id,
                workspace_id=requested_workspace_id,
            )
            conversations = await conversation_collection.service.list_workspace_conversations(
                project_id=project_id,
                tenant_id=tenant_id,
                workspace_ids={requested_workspace_id},
                status=conv_status,
                limit=limit,
                offset=offset,
            )
            total = await conversation_collection.service.count_workspace_conversations(
                project_id=project_id,
                tenant_id=tenant_id,
                workspace_id=requested_workspace_id,
                status=conv_status,
            )
        else:
            conversations = await conversation_collection.service.list_conversations(
                project_id=project_id,
                tenant_id=tenant_id,
                limit=limit,
                offset=offset,
                status=conv_status,
            )

            total = await conversation_collection.service.count_conversations(
                project_id=project_id,
                tenant_id=tenant_id,
                status=conv_status,
            )

            workspace_ids: set[str] = set()
            for conversation in conversations:
                conversation_workspace_id = _workspace_id_for_response(conversation)
                if conversation_workspace_id is not None:
                    workspace_ids.add(conversation_workspace_id)
            if group_by_workspace and workspace_ids:
                workspace_ids = await _accessible_workspace_ids(
                    request,
                    current_user=current_user,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    workspace_ids=workspace_ids,
                )
                workspace_conversations = (
                    await conversation_collection.service.list_workspace_conversations(
                        project_id=project_id,
                        tenant_id=tenant_id,
                        workspace_ids=workspace_ids,
                        status=conv_status,
                        limit=_workspace_group_expansion_limit(limit),
                        offset=0,
                    )
                )
                conversations = _merge_workspace_groups(conversations, workspace_conversations)

        response_workspace_ids: set[str] = set()
        for conversation in conversations:
            conversation_workspace_id = _workspace_id_for_response(conversation)
            if conversation_workspace_id is not None:
                response_workspace_ids.add(conversation_workspace_id)
        workspace_names = await _workspace_name_by_id(
            request,
            current_user=current_user,
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
    conversation_http: ConversationHttpApplicationAuthorityV2 = Depends(
        conversation_http_application_authority_dependency_v2
    ),
) -> ConversationResponse:
    """Get a conversation by ID."""
    try:
        assert request is not None
        await _ensure_project_access(
            db,
            current_user=current_user,
            project_id=project_id,
        )
        conversation = await conversation_http.service.get_conversation(
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
    conversation_context_status: ConversationContextStatusHttpApplicationAuthorityV2 = Depends(
        conversation_context_status_http_application_authority_dependency_v2
    ),
) -> dict[str, Any]:
    """Get context window status for a conversation.

    Returns the cached context summary info (if any) and message count,
    so the frontend can restore the context status indicator after page
    refresh or conversation switch.
    """
    try:
        assert request is not None
        authorized_tenant_id = await _ensure_project_access(
            db,
            current_user=current_user,
            project_id=project_id,
            tenant_id=tenant_id,
        )
        if authorized_tenant_id != tenant_id:
            raise HTTPException(status_code=403, detail=_("Access denied"))
        context_status = await conversation_context_status.service.get_context_status(
            conversation_id=conversation_id,
            project_id=project_id,
            tenant_id=authorized_tenant_id,
            user_id=str(current_user.id),
        )
        if context_status is None:
            raise HTTPException(status_code=404, detail=_("Conversation not found"))
        return context_status.to_dict()

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
    conversation_http: ConversationHttpApplicationAuthorityV2 = Depends(
        conversation_http_application_authority_dependency_v2
    ),
) -> None:
    """Delete a conversation and all its messages."""
    try:
        assert request is not None
        await _ensure_project_access(
            db,
            current_user=current_user,
            project_id=project_id,
        )
        deleted = await conversation_http.service.delete_conversation(
            conversation_id=conversation_id,
            project_id=project_id,
            user_id=current_user.id,
        )
        if not deleted:
            raise HTTPException(status_code=404, detail=_("Conversation not found"))
        await conversation_http.db.commit()
        await conversation_http.service.cache.invalidate(project_id)

    except HTTPException:
        await conversation_http.db.rollback()
        raise
    except Exception as exc:
        await conversation_http.db.rollback()
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
    conversation_http: ConversationHttpApplicationAuthorityV2 = Depends(
        conversation_http_application_authority_dependency_v2
    ),
) -> ConversationResponse:
    """Update conversation title."""
    try:
        assert request is not None
        await _ensure_project_access(
            db,
            current_user=current_user,
            project_id=project_id,
        )
        updated_conversation = await conversation_http.service.update_conversation_title(
            conversation_id=conversation_id,
            project_id=project_id,
            user_id=current_user.id,
            title=data.title,
        )
        if updated_conversation is None:
            raise HTTPException(status_code=404, detail=_("Conversation not found"))
        await conversation_http.db.commit()
        await conversation_http.service.cache.invalidate(project_id)
        return ConversationResponse.from_domain(updated_conversation)

    except HTTPException:
        await conversation_http.db.rollback()
        raise
    except Exception as exc:
        await conversation_http.db.rollback()
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
    conversation_config: ConversationConfigHttpApplicationAuthorityV2 = Depends(
        conversation_config_http_application_authority_dependency_v2
    ),
) -> ConversationResponse:
    """Update conversation-level LLM configuration (model override, LLM params)."""
    try:
        assert request is not None
        authorized_tenant_id = await _ensure_project_access(
            db,
            current_user=current_user,
            project_id=project_id,
            tenant_id=tenant_id,
        )
        fields = data.model_fields_set
        conversation = await conversation_config.service.update_conversation_config(
            conversation_id=conversation_id,
            project_id=project_id,
            tenant_id=authorized_tenant_id,
            user_id=str(current_user.id),
            patch=ConversationConfigPatchV2(
                selected_agent_id_present="selected_agent_id" in fields,
                selected_agent_id=data.selected_agent_id,
                llm_model_override_present="llm_model_override" in fields,
                llm_model_override=data.llm_model_override,
                llm_overrides_present="llm_overrides" in fields,
                llm_overrides=data.llm_overrides,
            ),
        )
        if conversation is None:
            raise HTTPException(status_code=404, detail=_("Conversation not found"))
        await conversation_config.db.commit()
        await conversation_config.service.after_update_committed(project_id)

        return ConversationResponse.from_domain(conversation)

    except InvalidConversationAgentSelectionV2 as exc:
        await conversation_config.db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_("Invalid agent selection"),
        ) from exc
    except HTTPException:
        await conversation_config.db.rollback()
        raise
    except Exception as exc:
        await conversation_config.db.rollback()
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
    conversation_http: ConversationHttpApplicationAuthorityV2 = Depends(
        conversation_http_application_authority_dependency_v2
    ),
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
        tenant_id = await _ensure_project_access(
            db,
            current_user=current_user,
            project_id=project_id,
        )
        conversation = await conversation_http.service.get_conversation(
            conversation_id=conversation_id,
            project_id=project_id,
            user_id=current_user.id,
        )
        if not conversation:
            raise HTTPException(status_code=404, detail=_("Conversation not found"))

        fields = data.model_fields_set
        await _ensure_workspace_linkage_access(
            db,
            request=request,
            conversation=conversation,
            data=data,
            current_user=current_user,
            tenant_id=tenant_id,
            project_id=project_id,
        )

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
        await _enforce_conversation_invariants(
            conversation,
            request=request,
            current_user=current_user,
        )

        conversation.updated_at = datetime.now(UTC)
        updated_conversation = await conversation_http.service.save_scoped_conversation(
            conversation=conversation,
            project_id=project_id,
            tenant_id=tenant_id,
            user_id=current_user.id,
        )
        if updated_conversation is None:
            raise HTTPException(status_code=404, detail=_("Conversation not found"))
        await conversation_http.db.commit()
        await conversation_http.service.cache.invalidate(project_id)

        return ConversationResponse.from_domain(updated_conversation)

    except HTTPException:
        await conversation_http.db.rollback()
        raise
    except ValueError as e:
        await conversation_http.db.rollback()
        logger.warning(f"Invalid conversation mode update for {conversation_id}: {e}")
        raise HTTPException(status_code=422, detail=_("Invalid conversation mode update")) from e
    except Exception as exc:
        await conversation_http.db.rollback()
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
    conversation_generation: ConversationGenerationHttpApplicationAuthorityV2 = Depends(
        conversation_generation_http_application_authority_dependency_v2
    ),
) -> ConversationResponse:
    """
    Generate and update a friendly conversation title based on the first user message.

    .. deprecated::
        Title generation is now handled automatically by the backend.
    """
    try:
        assert request is not None
        authorized_tenant_id = await _ensure_project_access(
            db,
            current_user=current_user,
            project_id=project_id,
            tenant_id=tenant_id,
        )
        if authorized_tenant_id != tenant_id:
            raise HTTPException(status_code=403, detail=_("Access denied"))
        conversation = await conversation_generation.service.generate_title(
            conversation_id=conversation_id,
        )
        if conversation is None:
            raise HTTPException(status_code=404, detail=_("Conversation not found"))
        await conversation_generation.db.commit()
        await conversation_generation.service.after_update_committed()
        return ConversationResponse.from_domain(conversation)

    except ConversationGenerationSourceMissingV2 as exc:
        await conversation_generation.db.rollback()
        raise HTTPException(
            status_code=400,
            detail=_("No user message found to generate title from"),
        ) from exc
    except HTTPException:
        await conversation_generation.db.rollback()
        raise
    except Exception as exc:
        await conversation_generation.db.rollback()
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
    conversation_generation: ConversationGenerationHttpApplicationAuthorityV2 = Depends(
        conversation_generation_http_application_authority_dependency_v2
    ),
) -> ConversationResponse:
    """Generate an AI summary of the conversation."""
    try:
        assert request is not None
        authorized_tenant_id = await _ensure_project_access(
            db,
            current_user=current_user,
            project_id=project_id,
            tenant_id=tenant_id,
        )
        if authorized_tenant_id != tenant_id:
            raise HTTPException(status_code=403, detail=_("Access denied"))
        conversation = await conversation_generation.service.generate_summary(
            conversation_id=conversation_id,
        )
        if conversation is None:
            raise HTTPException(status_code=404, detail=_("Conversation not found"))
        await conversation_generation.db.commit()
        await conversation_generation.service.after_update_committed()
        return ConversationResponse.from_domain(conversation)

    except ConversationGenerationSourceMissingV2 as exc:
        await conversation_generation.db.rollback()
        raise HTTPException(
            status_code=400,
            detail=_("No messages found to generate summary from"),
        ) from exc
    except HTTPException:
        await conversation_generation.db.rollback()
        raise
    except Exception as exc:
        await conversation_generation.db.rollback()
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
    conversation_revision: ConversationRevisionHttpApplicationAuthorityV2 = Depends(
        conversation_revision_http_application_authority_dependency_v2
    ),
) -> dict[str, Any]:
    """Fork a conversation from a specific message point."""
    try:
        fork = await conversation_revision.service.fork_conversation(
            conversation_id=conversation_id,
            branch_message_id=message_id,
            tenant_id=tenant_id,
            user_id=str(current_user.id),
        )
        await conversation_revision.db.commit()
        await conversation_revision.service.after_mutation_committed(fork.project_id)
        return fork.to_dict()

    except ConversationRevisionConversationNotFoundV2 as exc:
        await conversation_revision.db.rollback()
        raise HTTPException(status_code=404, detail=_("Conversation not found")) from exc
    except ConversationRevisionAccessDeniedV2 as exc:
        await conversation_revision.db.rollback()
        raise HTTPException(status_code=403, detail=_("Access denied")) from exc
    except ConversationRevisionMessageNotFoundV2 as exc:
        await conversation_revision.db.rollback()
        raise HTTPException(status_code=404, detail=_("Message not found")) from exc
    except RuntimeV2Error as exc:
        await conversation_revision.db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": exc.code,
                "message": _("Conversation revision authority is unavailable"),
            },
        ) from exc
    except Exception as exc:
        await conversation_revision.db.rollback()
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
    conversation_revision: ConversationRevisionHttpApplicationAuthorityV2 = Depends(
        conversation_revision_http_application_authority_dependency_v2
    ),
) -> dict[str, Any]:
    """Edit a message and increment version."""
    try:
        content = data.get("content")
        if content is not None and not isinstance(content, str):
            raise HTTPException(status_code=422, detail=_("Invalid message content"))
        edited = await conversation_revision.service.edit_message(
            conversation_id=conversation_id,
            message_id=message_id,
            content=content,
            tenant_id=tenant_id,
            user_id=str(current_user.id),
        )
        await conversation_revision.db.commit()
        await conversation_revision.service.after_mutation_committed(edited.project_id)
        return edited.to_dict()

    except ConversationRevisionConversationNotFoundV2 as exc:
        await conversation_revision.db.rollback()
        raise HTTPException(status_code=404, detail=_("Conversation not found")) from exc
    except ConversationRevisionAccessDeniedV2 as exc:
        await conversation_revision.db.rollback()
        raise HTTPException(status_code=403, detail=_("Access denied")) from exc
    except ConversationRevisionMessageNotFoundV2 as exc:
        await conversation_revision.db.rollback()
        raise HTTPException(status_code=404, detail=_("Message not found")) from exc
    except RuntimeV2Error as exc:
        await conversation_revision.db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": exc.code,
                "message": _("Conversation revision authority is unavailable"),
            },
        ) from exc
    except HTTPException:
        await conversation_revision.db.rollback()
        raise
    except Exception as exc:
        await conversation_revision.db.rollback()
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
    conversation_revision: ConversationRevisionHttpApplicationAuthorityV2 = Depends(
        conversation_revision_http_application_authority_dependency_v2
    ),
) -> dict[str, Any]:
    """Request undo of a tool execution.

    Creates a follow-up user message asking the agent to undo
    the specified tool execution.
    """
    try:
        undo = await conversation_revision.service.request_tool_undo(
            conversation_id=conversation_id,
            execution_id=execution_id,
            tenant_id=tenant_id,
            user_id=str(current_user.id),
        )
        await conversation_revision.db.commit()
        await conversation_revision.service.after_mutation_committed(undo.project_id)
        return undo.to_dict()

    except ConversationRevisionConversationNotFoundV2 as exc:
        await conversation_revision.db.rollback()
        raise HTTPException(status_code=404, detail=_("Conversation not found")) from exc
    except ConversationRevisionAccessDeniedV2 as exc:
        await conversation_revision.db.rollback()
        raise HTTPException(status_code=403, detail=_("Access denied")) from exc
    except ConversationRevisionToolExecutionNotFoundV2 as exc:
        await conversation_revision.db.rollback()
        raise HTTPException(status_code=404, detail=_("Tool execution not found")) from exc
    except RuntimeV2Error as exc:
        await conversation_revision.db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": exc.code,
                "message": _("Conversation revision authority is unavailable"),
            },
        ) from exc
    except Exception as exc:
        await conversation_revision.db.rollback()
        logger.exception("Error requesting tool undo")
        raise HTTPException(
            status_code=500,
            detail=_("Failed to request tool undo"),
        ) from exc
