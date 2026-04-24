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


class CoordinatorSetRequest(BaseModel):
    """Assign (or clear) the coordinator agent.

    The target agent MUST already be on the roster. Passing ``null`` clears
    the coordinator — valid only when the effective mode is *not*
    ``autonomous`` (autonomous conversations require a coordinator to pass
    ``assert_autonomous_invariants``).
    """

    agent_id: str | None = Field(
        default=None,
        min_length=1,
        description="Agent ID to promote to coordinator; null to clear.",
    )


class FocusedAgentSetRequest(BaseModel):
    """Assign (or clear) the focused agent for isolated conversations."""

    agent_id: str | None = Field(
        default=None,
        min_length=1,
        description="Agent ID to focus; null to clear the focused agent.",
    )


class RosterResponse(BaseModel):
    """Current roster + coordination state for a conversation."""

    conversation_id: str
    conversation_mode: str
    effective_mode: str
    participant_agents: list[str]
    participant_bindings: list[RosterParticipantResponse] = Field(default_factory=list)
    coordinator_agent_id: str | None
    focused_agent_id: str | None


class RosterParticipantResponse(BaseModel):
    """Binding-aware participant projection for a roster entry."""

    agent_id: str
    workspace_agent_id: str | None = None
    display_name: str | None = None
    label: str | None = None
    is_active: bool = True
    source: str  # "workspace" | "conversation"


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


async def _roster_response(
    conversation: Conversation,
    effective_mode: ConversationMode,
    request: Request | None = None,
    db: AsyncSession | None = None,
) -> RosterResponse:
    participant_bindings: list[RosterParticipantResponse] = []
    workspace_id = getattr(conversation, "workspace_id", None)
    workspace_agent_repo = None
    if request is not None and db is not None:
        workspace_agent_repo = get_container_with_db(
            request, db
        ).workspace_agent_repository()

    for agent_id in conversation.participant_agents:
        binding = None
        if workspace_id and workspace_agent_repo is not None:
            binding = await workspace_agent_repo.find_by_workspace_and_agent_id(
                workspace_id=workspace_id,
                agent_id=agent_id,
            )
        participant_bindings.append(
            RosterParticipantResponse(
                agent_id=agent_id,
                workspace_agent_id=binding.id if binding is not None else None,
                display_name=binding.display_name if binding is not None else None,
                label=binding.label if binding is not None else None,
                is_active=binding.is_active if binding is not None else True,
                source="workspace" if binding is not None else "conversation",
            )
        )

    return RosterResponse(
        conversation_id=conversation.id,
        conversation_mode=(
            conversation.conversation_mode.value
            if conversation.conversation_mode is not None
            else ""
        ),
        effective_mode=effective_mode.value,
        participant_agents=list(conversation.participant_agents),
        participant_bindings=participant_bindings,
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
    return await _roster_response(
        conversation,
        _resolve_effective_mode(conversation, project),
        request=request,
        db=db,
    )


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
    return await _roster_response(conversation, effective_mode, request=request, db=db)


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
    return await _roster_response(conversation, effective_mode, request=request, db=db)


@router.patch(
    "/conversations/{conversation_id}/participants/coordinator",
    response_model=RosterResponse,
)
async def set_coordinator(
    conversation_id: str,
    data: CoordinatorSetRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> RosterResponse:
    """Assign or clear the coordinator agent for a conversation.

    Required before switching an autonomous conversation into run state
    (``Conversation.assert_autonomous_invariants`` raises
    ``CoordinatorRequiredError`` when it is missing).
    """
    conv_repo, conversation, project = await _load_conversation_and_project(
        request, db, conversation_id
    )
    effective_mode = _resolve_effective_mode(conversation, project)
    _assert_write_permission(conversation, project, current_user, effective_mode)

    try:
        conversation.set_coordinator(data.agent_id)
    except ParticipantNotPresentError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    await conv_repo.save(conversation)
    await db.commit()
    return await _roster_response(conversation, effective_mode, request=request, db=db)


@router.patch(
    "/conversations/{conversation_id}/participants/focused",
    response_model=RosterResponse,
)
async def set_focused_agent(
    conversation_id: str,
    data: FocusedAgentSetRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> RosterResponse:
    """Assign or clear the focused agent for a conversation."""
    conv_repo, conversation, project = await _load_conversation_and_project(
        request, db, conversation_id
    )
    effective_mode = _resolve_effective_mode(conversation, project)
    _assert_write_permission(conversation, project, current_user, effective_mode)

    try:
        conversation.set_focused_agent(data.agent_id)
    except ParticipantNotPresentError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    await conv_repo.save(conversation)
    await db.commit()
    return await _roster_response(conversation, effective_mode, request=request, db=db)


# === Mention candidates (Phase-5 G7) ===


class MentionCandidateResponse(BaseModel):
    """One candidate agent returned by GET /mention-candidates."""

    agent_id: str
    workspace_agent_id: str | None = None
    display_name: str | None = None
    label: str | None = None
    status: str = "idle"
    is_active: bool = True
    source: str  # "workspace" | "conversation"


class MentionCandidatesResponse(BaseModel):
    """List of mention candidates + the source of truth used to build it."""

    conversation_id: str
    workspace_id: str | None = None
    source: str  # "workspace" | "conversation"
    candidates: list[MentionCandidateResponse]


@router.get(
    "/conversations/{conversation_id}/mention-candidates",
    response_model=MentionCandidatesResponse,
)
async def list_mention_candidates(
    conversation_id: str,
    request: Request,
    include_inactive: bool = False,
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> MentionCandidatesResponse:
    """Return mention candidates for the ``MentionPicker``.

    When the conversation is linked to a workspace (``workspace_id``
    set), candidates come from the workspace agent roster; otherwise
    they fall back to ``conversation.participant_agents``.  Agent-First:
    the result is a bounded set — the frontend filters by substring
    *over this set* and never parses free-form text to guess an agent.
    """
    from src.application.services.agent.workspace_mention_candidates import (
        WorkspaceMentionCandidatesResolver,
    )

    _conv_repo, conversation, project = await _load_conversation_and_project(
        request, db, conversation_id
    )
    if (
        conversation.user_id != current_user.id
        and getattr(project, "owner_id", None) != current_user.id
    ):
        raise HTTPException(status_code=403, detail="Forbidden")

    container = get_container_with_db(request, db)
    resolver = WorkspaceMentionCandidatesResolver(container.workspace_agent_repository())
    candidates = await resolver.resolve(conversation, include_inactive=include_inactive)

    workspace_id = getattr(conversation, "workspace_id", None)
    source = "workspace" if workspace_id else "conversation"
    return MentionCandidatesResponse(
        conversation_id=conversation.id,
        workspace_id=workspace_id,
        source=source,
        candidates=[
            MentionCandidateResponse(
                agent_id=c.agent_id,
                workspace_agent_id=c.workspace_agent_id,
                display_name=c.display_name,
                label=c.label,
                status=c.status,
                is_active=c.is_active,
                source=c.source,
            )
            for c in candidates
        ],
    )
