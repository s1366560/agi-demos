"""
Session management router.

Provides endpoints for session lifecycle management.
"""

import logging
import uuid
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.schemas.session import (
    SessionCreate,
    SessionResponse,
    SessionListResponse,
    SessionMessageCreate,
    SessionMessageResponse,
    SessionHistoryResponse,
    SendMessageRequest,
    SessionStatsResponse,
)
from src.domain.model.session.entities import SessionKind, SessionStatus
from src.domain.model.session.value_objects import SessionKey
from src.domain.ports.session_repository import (
    SessionAggregateRepository,
    SessionRepository,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User as DBUser
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.persistence.session_repository import (
    PostgresSessionAggregateRepository,
    PostgresSessionRepository,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Sessions"])


def get_session_repository(db: AsyncSession = Depends(get_db)) -> SessionRepository:
    """Get session repository."""
    return PostgresSessionRepository(db)


def get_session_aggregate_repository(
    db: AsyncSession = Depends(get_db),
) -> SessionAggregateRepository:
    """Get session aggregate repository."""
    return PostgresSessionAggregateRepository(db)


@router.post("/sessions", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
async def create_session(
    session_data: SessionCreate,
    current_user: DBUser = Depends(get_current_user),
    repo: SessionAggregateRepository = Depends(get_session_aggregate_repository),
):
    """
    Create a new session.

    - **agent_id**: Which agent handles this session
    - **kind**: Session type (main, sub_agent, background, one_shot)
    - **model**: Optional model override
    - **metadata**: Optional metadata (channel, user, etc.)
    """
    logger.info(f"Creating session for user {current_user.email} with agent {session_data.agent_id}")

    try:
        # Generate session key
        session_key = SessionKey.from_parts(
            "agent",
            session_data.agent_id,
            str(uuid.uuid4()),
        )

        # Convert kind string to enum
        kind = SessionKind(session_data.kind) if session_data.kind else SessionKind.MAIN

        # Create aggregate
        aggregate = await repo.create_aggregate(
            session_key=session_key,
            agent_id=session_data.agent_id,
            kind=kind,
            model=session_data.model,
            metadata=session_data.metadata,
        )

        logger.info(f"Session created: {aggregate.session.id}")

        return SessionResponse(
            id=aggregate.session.id,
            session_key=aggregate.session.session_key.value,
            agent_id=aggregate.session.agent_id,
            kind=aggregate.session.kind.value,
            model=aggregate.session.model,
            status=aggregate.session.status.value,
            metadata=aggregate.session.metadata,
            created_at=aggregate.session.created_at,
            last_active_at=aggregate.session.last_active_at,
            message_count=aggregate.message_count(),
        )
    except Exception as e:
        logger.error(f"Failed to create session: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create session: {str(e)}",
        )


@router.get("/sessions", response_model=SessionListResponse)
async def list_sessions(
    agent_id: Optional[str] = Query(None, description="Filter by agent ID"),
    kind: Optional[str] = Query(None, description="Filter by session kind"),
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=200, description="Maximum number of results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    active_minutes: Optional[int] = Query(
        None, ge=1, description="Only sessions active in the last N minutes"
    ),
    current_user: DBUser = Depends(get_current_user),
    repo: SessionRepository = Depends(get_session_repository),
):
    """
    List sessions with optional filters.
    """
    # Parse filters
    kind_enum = SessionKind(kind) if kind else None
    status_enum = SessionStatus(status) if status else None

    # List sessions
    sessions = await repo.list_sessions(
        agent_id=agent_id,
        kind=kind_enum,
        status=status_enum,
        limit=limit,
        offset=offset,
        active_minutes=active_minutes,
    )

    # Get total count
    total = await repo.count_sessions(
        agent_id=agent_id,
        kind=kind_enum,
        status=status_enum,
    )

    # Build response
    session_responses = []
    for session in sessions:
        # Get message count (we'll need a separate repo for this)
        # For now, return 0
        session_responses.append(
            SessionResponse(
                id=session.id,
                session_key=session.session_key.value,
                agent_id=session.agent_id,
                kind=session.kind.value,
                model=session.model,
                status=session.status.value,
                metadata=session.metadata,
                created_at=session.created_at,
                last_active_at=session.last_active_at,
                message_count=0,  # TODO: Get actual count
            )
        )

    return SessionListResponse(
        sessions=session_responses,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/sessions/{session_id}", response_model=SessionResponse)
async def get_session(
    session_id: str,
    current_user: DBUser = Depends(get_current_user),
    repo: SessionAggregateRepository = Depends(get_session_aggregate_repository),
):
    """Get a session by ID."""
    aggregate = await repo.get_aggregate(session_id)

    if not aggregate:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        )

    return SessionResponse(
        id=aggregate.session.id,
        session_key=aggregate.session.session_key.value,
        agent_id=aggregate.session.agent_id,
        kind=aggregate.session.kind.value,
        model=aggregate.session.model,
        status=aggregate.session.status.value,
        metadata=aggregate.session.metadata,
        created_at=aggregate.session.created_at,
        last_active_at=aggregate.session.last_active_at,
        message_count=aggregate.message_count(),
    )


@router.get("/sessions/by-key/{session_key}", response_model=SessionResponse)
async def get_session_by_key(
    session_key: str,
    current_user: DBUser = Depends(get_current_user),
    repo: SessionAggregateRepository = Depends(get_session_aggregate_repository),
):
    """Get a session by session key."""
    aggregate = await repo.get_aggregate_by_key(session_key)

    if not aggregate:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        )

    return SessionResponse(
        id=aggregate.session.id,
        session_key=aggregate.session.session_key.value,
        agent_id=aggregate.session.agent_id,
        kind=aggregate.session.kind.value,
        model=aggregate.session.model,
        status=aggregate.session.status.value,
        metadata=aggregate.session.metadata,
        created_at=aggregate.session.created_at,
        last_active_at=aggregate.session.last_active_at,
        message_count=aggregate.message_count(),
    )


@router.get("/sessions/{session_id}/history", response_model=SessionHistoryResponse)
async def get_session_history(
    session_id: str,
    limit: int = Query(50, ge=1, le=500, description="Maximum number of messages"),
    include_tools: bool = Query(False, description="Include tool messages"),
    current_user: DBUser = Depends(get_current_user),
    repo: SessionAggregateRepository = Depends(get_session_aggregate_repository),
):
    """
    Get message history for a session.
    """
    aggregate = await repo.get_aggregate(session_id)

    if not aggregate:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        )

    messages = aggregate.get_messages(limit=limit, include_tools=include_tools)

    message_responses = [
        SessionMessageResponse(
            id=msg.id,
            session_id=msg.session_id,
            role=msg.role.value,
            content=msg.content,
            metadata=msg.metadata,
            created_at=msg.created_at,
        )
        for msg in messages
    ]

    return SessionHistoryResponse(
        session_id=aggregate.session.id,
        session_key=aggregate.session.session_key.value,
        messages=message_responses,
        total=len(messages),
        limit=limit,
    )


@router.post("/sessions/{session_id}/messages", response_model=SessionMessageResponse)
async def add_session_message(
    session_id: str,
    message_data: SessionMessageCreate,
    current_user: DBUser = Depends(get_current_user),
    repo: SessionAggregateRepository = Depends(get_session_aggregate_repository),
):
    """Add a message to a session."""
    aggregate = await repo.get_aggregate(session_id)

    if not aggregate:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        )

    # Convert role string to enum
    from src.domain.model.session.entities import MessageRole
    role = MessageRole(message_data.role)

    # Add message
    message = aggregate.add_message(
        message_id=str(uuid.uuid4()),
        role=role,
        content=message_data.content,
        metadata=message_data.metadata,
    )

    # Save aggregate
    await repo.save_aggregate(aggregate)

    return SessionMessageResponse(
        id=message.id,
        session_id=message.session_id,
        role=message.role.value,
        content=message.content,
        metadata=message.metadata,
        created_at=message.created_at,
    )


@router.post("/sessions/send", response_model=SessionMessageResponse)
async def send_message_to_session(
    request: SendMessageRequest,
    current_user: DBUser = Depends(get_current_user),
    repo: SessionAggregateRepository = Depends(get_session_aggregate_repository),
):
    """
    Send a message to another session.

    Can use either session_id or session_key to identify the target session.
    """
    from src.domain.model.session.entities import MessageRole, MessageRole

    # Find target session
    aggregate = None
    if request.session_id:
        aggregate = await repo.get_aggregate(request.session_id)
    elif request.session_key:
        aggregate = await repo.get_aggregate_by_key(request.session_key)

    if not aggregate:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Target session not found",
        )

    # Add message
    role = MessageRole(request.role) if request.role else MessageRole.ASSISTANT
    message = aggregate.add_message(
        message_id=str(uuid.uuid4()),
        role=role,
        content=request.message,
        metadata=request.metadata or {},
    )

    # Save aggregate
    await repo.save_aggregate(aggregate)

    logger.info(f"Message sent to session {aggregate.session.id}")

    return SessionMessageResponse(
        id=message.id,
        session_id=message.session_id,
        role=message.role.value,
        content=message.content,
        metadata=message.metadata,
        created_at=message.created_at,
    )


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: str,
    current_user: DBUser = Depends(get_current_user),
    repo: SessionRepository = Depends(get_session_repository),
):
    """Delete a session."""
    deleted = await repo.delete(session_id)

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        )

    logger.info(f"Session {session_id} deleted")


@router.get("/sessions/stats", response_model=SessionStatsResponse)
async def get_session_stats(
    agent_id: Optional[str] = Query(None, description="Filter by agent ID"),
    current_user: DBUser = Depends(get_current_user),
    repo: SessionRepository = Depends(get_session_repository),
):
    """
    Get session statistics.
    """
    # Get counts by status
    active_count = await repo.count_sessions(agent_id=agent_id, status=SessionStatus.ACTIVE)
    inactive_count = await repo.count_sessions(agent_id=agent_id, status=SessionStatus.INACTIVE)
    terminated_count = await repo.count_sessions(agent_id=agent_id, status=SessionStatus.TERMINATED)
    error_count = await repo.count_sessions(agent_id=agent_id, status=SessionStatus.ERROR)

    # Get counts by kind
    main_count = await repo.count_sessions(agent_id=agent_id, kind=SessionKind.MAIN)
    sub_agent_count = await repo.count_sessions(agent_id=agent_id, kind=SessionKind.SUB_AGENT)
    background_count = await repo.count_sessions(agent_id=agent_id, kind=SessionKind.BACKGROUND)
    one_shot_count = await repo.count_sessions(agent_id=agent_id, kind=SessionKind.ONE_SHOT)

    total = active_count + inactive_count + terminated_count + error_count

    return SessionStatsResponse(
        total=total,
        by_status={
            "active": active_count,
            "inactive": inactive_count,
            "terminated": terminated_count,
            "error": error_count,
        },
        by_kind={
            "main": main_count,
            "sub_agent": sub_agent_count,
            "background": background_count,
            "one_shot": one_shot_count,
        },
    )
