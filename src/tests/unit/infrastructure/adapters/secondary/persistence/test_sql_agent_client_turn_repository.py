"""Persistence tests for client agent-turn idempotency."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.model.agent import (
    AgentClientTurnPayloadConflictError,
    AgentClientTurnStatus,
)
from src.infrastructure.adapters.primary.web.websocket.handlers.chat_handler import (
    stream_agent_to_websocket_with_fresh_session,
)
from src.infrastructure.adapters.secondary.persistence.sql_agent_client_turn_repository import (
    SqlAgentClientTurnRepository,
)

pytestmark = pytest.mark.unit


class _StreamContext:
    tenant_id = "tenant-1"

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    @asynccontextmanager
    async def fresh_db_context(self) -> AsyncIterator[_StreamContext]:
        yield self


async def test_first_claim_is_durable_and_exact_replay_is_not_created(
    test_engine: object,
) -> None:
    session_factory = async_sessionmaker(
        test_engine,  # type: ignore[arg-type]
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with session_factory() as first_session:
        first = await SqlAgentClientTurnRepository(first_session).claim_and_commit(
            conversation_id="conversation-1",
            client_message_id="desktop-message-1",
            payload_hash="a" * 64,
        )

    async with session_factory() as refreshed_session:
        replay = await SqlAgentClientTurnRepository(refreshed_session).claim_and_commit(
            conversation_id="conversation-1",
            client_message_id="desktop-message-1",
            payload_hash="a" * 64,
        )

    assert first.created is True
    assert first.turn.status is AgentClientTurnStatus.ACCEPTED
    assert first.turn.execution_message_id == SqlAgentClientTurnRepository.execution_message_id(
        "conversation-1",
        "desktop-message-1",
    )
    assert first.turn.execution_message_id != "desktop-message-1"
    assert first.turn.execution_message_id != SqlAgentClientTurnRepository.execution_message_id(
        "conversation-2",
        "desktop-message-1",
    )
    assert replay.created is False
    assert replay.turn == first.turn


async def test_reusing_client_message_id_with_different_payload_fails_closed(
    test_db: AsyncSession,
) -> None:
    repository = SqlAgentClientTurnRepository(test_db)
    await repository.claim_and_commit(
        conversation_id="conversation-1",
        client_message_id="desktop-message-1",
        payload_hash="a" * 64,
    )

    with pytest.raises(AgentClientTurnPayloadConflictError):
        await repository.claim_and_commit(
            conversation_id="conversation-1",
            client_message_id="desktop-message-1",
            payload_hash="b" * 64,
        )

    persisted = await repository.find("conversation-1", "desktop-message-1")
    assert persisted is not None
    assert persisted.payload_hash == "a" * 64


async def test_concurrent_claim_grants_single_execution_authority(
    test_engine: object,
) -> None:
    session_factory = async_sessionmaker(
        test_engine,  # type: ignore[arg-type]
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with session_factory() as left_session, session_factory() as right_session:
        claims = await asyncio.gather(
            SqlAgentClientTurnRepository(left_session).claim_and_commit(
                conversation_id="conversation-1",
                client_message_id="desktop-message-race",
                payload_hash="c" * 64,
            ),
            SqlAgentClientTurnRepository(right_session).claim_and_commit(
                conversation_id="conversation-1",
                client_message_id="desktop-message-race",
                payload_hash="c" * 64,
            ),
        )

    assert sorted(claim.created for claim in claims) == [False, True]

    async with session_factory() as first_start_session:
        started = await SqlAgentClientTurnRepository(first_start_session).try_start(
            conversation_id="conversation-1",
            client_message_id="desktop-message-race",
            payload_hash="c" * 64,
        )
        assert started is True
        await first_start_session.commit()

    async with session_factory() as replay_session:
        replay_started = await SqlAgentClientTurnRepository(replay_session).try_start(
            conversation_id="conversation-1",
            client_message_id="desktop-message-race",
            payload_hash="c" * 64,
        )

    assert replay_started is False


async def test_uncommitted_start_rolls_back_to_accepted_for_safe_retry(
    test_engine: object,
) -> None:
    session_factory = async_sessionmaker(
        test_engine,  # type: ignore[arg-type]
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with session_factory() as claim_session:
        await SqlAgentClientTurnRepository(claim_session).claim_and_commit(
            conversation_id="conversation-1",
            client_message_id="desktop-message-recover",
            payload_hash="d" * 64,
        )

    async with session_factory() as crashed_session:
        granted = await SqlAgentClientTurnRepository(crashed_session).try_start(
            conversation_id="conversation-1",
            client_message_id="desktop-message-recover",
            payload_hash="d" * 64,
        )
        assert granted is True
        await crashed_session.rollback()

    async with session_factory() as recovery_session:
        recovery_repository = SqlAgentClientTurnRepository(recovery_session)
        recovered = await recovery_repository.try_start(
            conversation_id="conversation-1",
            client_message_id="desktop-message-recover",
            payload_hash="d" * 64,
        )
        assert recovered is True
        await recovery_session.commit()

    async with session_factory() as refreshed_session:
        persisted = await SqlAgentClientTurnRepository(refreshed_session).find(
            "conversation-1",
            "desktop-message-recover",
        )

    assert persisted is not None
    assert persisted.status is AgentClientTurnStatus.STARTED


async def test_llm_setup_failure_rolls_back_execution_claim(
    test_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload_hash = "e" * 64
    repository = SqlAgentClientTurnRepository(test_db)
    await repository.claim_and_commit(
        conversation_id="conversation-1",
        client_message_id="desktop-message-llm-failure",
        payload_hash=payload_hash,
    )

    async def fail_create_llm_client(_tenant_id: str) -> Any:
        raise RuntimeError("provider unavailable")

    import src.configuration.factories as factories

    monkeypatch.setattr(factories, "create_llm_client", fail_create_llm_client)

    with pytest.raises(RuntimeError, match="provider unavailable"):
        await stream_agent_to_websocket_with_fresh_session(
            context=_StreamContext(test_db),  # type: ignore[arg-type]
            conversation_id="conversation-1",
            user_message="Plan the requested change",
            project_id="project-1",
            client_message_id="desktop-message-llm-failure",
            client_payload_hash=payload_hash,
            execution_message_id=SqlAgentClientTurnRepository.execution_message_id(
                "conversation-1",
                "desktop-message-llm-failure",
            ),
        )

    persisted = await repository.find("conversation-1", "desktop-message-llm-failure")
    assert persisted is not None
    assert persisted.status is AgentClientTurnStatus.ACCEPTED
