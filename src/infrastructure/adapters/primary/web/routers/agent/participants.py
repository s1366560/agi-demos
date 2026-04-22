"""Multi-agent conversation participant endpoints (P2-3 phase-2, Track B).

POST   /conversations/{conversation_id}/participants           — add an agent
DELETE /conversations/{conversation_id}/participants/{agent_id}— remove an agent
GET    /conversations/{conversation_id}/participants           — list roster

The endpoints are thin shells over the domain ``Conversation`` aggregate:
mutations go through ``add_participant`` / ``remove_participant`` so the
Agent First invariants (roster uniqueness, mode caps, coordinator cleanup,
event emission) are enforced in one place.

Permissions (per ``files/p2-decisions.md``):

- ``single_agent`` mode: only the owner may touch the roster (and adding a
  second participant is rejected at the domain layer).
- ``multi_agent_isolated``: the owner, or the acting user if they already
  have an agent on the roster, may add themselves.
- ``multi_agent_shared`` / ``autonomous``: owner OR any existing participant
  may add/remove.

Removal: always allowed for the owner; non-owners may only remove the agent
they themselves added (recorded via ``actor_id`` on the join event — for
now we simply require owner). The removal ``reason`` is captured verbatim
onto the emitted ``ConversationParticipantLeftEvent`` (Agent First — the
reason is the auditable artefact, not a classification).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent.conversation.conversation import Conversation
from src.domain.model.agent.conversation.conversation_mode import ConversationMode
from src.domain.model.agent.conversation.errors import (
    CoordinatorRequiredError,
    ParticipantAlreadyPresentError,
    ParticipantLimitError,
    ParticipantNotPresentError,
    SenderNotInRosterError,
)
from src.domain.model.project.project import Project
from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user,
    get_current_user_tenant,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.adapters.secondary.persistence.sql_conversation_repository import (
    SqlConversationRepository,
)

from .utils import get_container_with_db

router = APIRouter()
logger = logging.getLogger(__name__)


# === Request / response schemas ===


class ParticipantAddRequest(BaseModel):
    """Add a participant to a conversation's roster."""

    agent_id: str = Field(..., min_length=1, description="Agent ID to add.")
    role: str | None = Field(
        default=None,
        max_length=64,
        description="Optional role label captured on the join event (e.g. 'reviewer').",
    )


class ParticipantRemoveRequest(BaseModel):
    """Optional body for DELETE — pass a human-readable removal reason."""

    reason: str | None = Field(default=None, max_length=1000)


class RosterResponse(BaseModel):
    """Current roster + coordination state for a conversation."""

    conversation_id: str
    conversation_mode: str
    effective_mode: str
    participant_agents: list[str]
    coordinator_agent_id: str | None
    focused_agent_id: str | None


# === Helpers ===


async def _load_conversation_and_project(
    request: Request,
    db: AsyncSession,
    conversation_id: str,
) -> tuple[SqlConversationRepository, Conversation, Project]:
    """Load the conversation + its project, or raise 404."""
    container = get_container_with_db(request, db)
    conv_repo = container.conversation_repository()
    project_repo = container.project_repository()

    conversation = await conv_repo.find_by_id(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    project = await project_repo.find_by_id(conversation.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return conv_repo, conversation, project


def _resolve_effective_mode(conversation: Conversation, project: Project) -> ConversationMode:
    """Pick the conversation override if present, else the project default."""
    if conversation.conversation_mode is not None:
        return conversation.conversation_mode
    raw = project.agent_conversation_mode or "single_agent"
    try:
        return ConversationMode(raw)
    except ValueError:
        # Defensive: unknown string in DB → treat as single_agent.
        return ConversationMode.SINGLE_AGENT


def _assert_write_permission(
    conversation: Conversation,
    project: Project,
    current_user: User,
    effective_mode: ConversationMode,
) -> None:
    """Raise 403 if ``current_user`` is not allowed to mutate the roster."""
    # Owner (conversation creator OR project owner) is always allowed.
    if conversation.user_id == current_user.id:
        return
    if getattr(project, "owner_id", None) == current_user.id:
        return

    # For shared / autonomous modes, existing participant agents run on behalf
    # of their owner — callers currently can only identify themselves by user
    # id at this endpoint, so we stay strict: non-owner humans are 403.
    # (Agent-initiated roster changes happen through the tool layer, not this
    # HTTP surface.)
    if effective_mode in (
        ConversationMode.MULTI_AGENT_SHARED,
        ConversationMode.AUTONOMOUS,
        ConversationMode.MULTI_AGENT_ISOLATED,
    ):
        raise HTTPException(
            status_code=403,
            detail="Only the conversation owner can modify the roster via this endpoint.",
        )

    raise HTTPException(status_code=403, detail="Forbidden")


def _roster_response(
    conversation: Conversation, effective_mode: ConversationMode
) -> RosterResponse:
    return RosterResponse(
        conversation_id=conversation.id,
        conversation_mode=(
            conversation.conversation_mode.value
            if conversation.conversation_mode is not None
            else ""
        ),
        effective_mode=effective_mode.value,
        participant_agents=list(conversation.participant_agents),
        coordinator_agent_id=conversation.coordinator_agent_id,
        focused_agent_id=conversation.focused_agent_id,
    )


# === Endpoints ===


@router.get(
    "/conversations/{conversation_id}/participants",
    response_model=RosterResponse,
)
async def list_participants(
    conversation_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> RosterResponse:
    """Return the current roster + coordination state."""
    _conv_repo, conversation, project = await _load_conversation_and_project(
        request, db, conversation_id
    )
    # Read access: must be owner OR an existing participant's user. For now
    # enforce owner-or-project-owner; tightening this is phase-2.2.
    if (
        conversation.user_id != current_user.id
        and getattr(project, "owner_id", None) != current_user.id
    ):
        raise HTTPException(status_code=403, detail="Forbidden")
    return _roster_response(conversation, _resolve_effective_mode(conversation, project))


@router.post(
    "/conversations/{conversation_id}/participants",
    response_model=RosterResponse,
    status_code=201,
)
async def add_participant(
    conversation_id: str,
    data: ParticipantAddRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> RosterResponse:
    """Add an agent to the roster."""
    conv_repo, conversation, project = await _load_conversation_and_project(
        request, db, conversation_id
    )
    effective_mode = _resolve_effective_mode(conversation, project)
    _assert_write_permission(conversation, project, current_user, effective_mode)

    try:
        conversation.add_participant(
            data.agent_id,
            effective_mode=effective_mode,
            actor_id=current_user.id,
            role=data.role,
        )
    except ParticipantAlreadyPresentError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except ParticipantLimitError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except SenderNotInRosterError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except CoordinatorRequiredError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except ParticipantNotPresentError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    await conv_repo.save(conversation)
    await db.commit()
    return _roster_response(conversation, effective_mode)


@router.delete(
    "/conversations/{conversation_id}/participants/{agent_id}",
    response_model=RosterResponse,
)
async def remove_participant(
    conversation_id: str,
    agent_id: str,
    request: Request,
    data: ParticipantRemoveRequest | None = None,
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> RosterResponse:
    """Remove an agent from the roster."""
    conv_repo, conversation, project = await _load_conversation_and_project(
        request, db, conversation_id
    )
    effective_mode = _resolve_effective_mode(conversation, project)
    _assert_write_permission(conversation, project, current_user, effective_mode)

    reason = data.reason if data is not None else None
    try:
        conversation.remove_participant(agent_id, actor_id=current_user.id, reason=reason)
    except ParticipantNotPresentError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except CoordinatorRequiredError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    await conv_repo.save(conversation)
    await db.commit()
    return _roster_response(conversation, effective_mode)
